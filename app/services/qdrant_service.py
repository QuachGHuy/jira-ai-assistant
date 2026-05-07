import httpx
import asyncio
import uuid
import traceback
from typing import List, Dict, Any, Optional
from qdrant_client import QdrantClient, AsyncQdrantClient
from qdrant_client.http import models

from app.core.config import settings
from app.schemas.jira_models import JiraIssue
from app.services.text_processor import TextProcessor

class QdrantService:
    """
    Service responsible for vector database operations using Qdrant Cloud.
    Handles embedding generation via local Ollama and similarity searches.
    """

    def __init__(self) -> None:
        """
        Initializes the service with persistent HTTP clients and 
        sets up required Qdrant collections.
        """
        self.client: AsyncQdrantClient = AsyncQdrantClient(
            url=settings.QDRANT_ENDPOINT_URL,
            api_key=settings.QDRANT_API_TOKEN,
            check_compatibility=False
        )
        self.ollama_url = f"{settings.OLLAMA_BASE_URL}/api/embeddings"
        
        # Extended timeout (5 mins) to handle large payloads and slow local model inference
        self.http_client = httpx.AsyncClient(timeout=300.0)
        
        # Semaphore(1) limits concurrent embedding calls to prevent Ollama Out-Of-Memory (OOM)
        self.sem = asyncio.Semaphore(1) 
        
        # Execute collection setup synchronously on startup
        self._sync_setup_collections()
        self.processor = TextProcessor()

    async def close(self) -> None:
        """
        Gracefully closes persistent HTTP and Qdrant client connections.
        """
        await self.http_client.aclose()
        await self.client.close()

    def _sync_setup_collections(self) -> None:
        """
        Synchronously verifies and initializes required Qdrant collections.
        Creates Payload Indexes to optimize filtering during similarity search.
        """
        sync_client = QdrantClient(
            url=settings.QDRANT_ENDPOINT_URL, 
            api_key=settings.QDRANT_API_TOKEN,
            check_compatibility=False
        )
        try:
            existing_col_names = [c.name for c in sync_client.get_collections().collections]
            
            # 1. Main JIRA Knowledge Base Collection
            col_jira = settings.QDRANT_COLLECTION_JIRA
            if col_jira not in existing_col_names:
                print(f"🚀 Initializing JIRA collection: {col_jira}")
                sync_client.create_collection(
                    collection_name=col_jira,
                    vectors_config=models.VectorParams(
                        size=settings.QDRANT_VECTOR_SIZE, 
                        distance=models.Distance.COSINE
                    )
                )
                
                # Payload Index Schema Setup (Optimizes search filters)
                keyword_fields = [
                    "metadata.key", "metadata.project", "metadata.type", 
                    "metadata.status", "metadata.priority", "metadata.assignee_id", 
                    "metadata.assignee_email", "metadata.outward_issue_key", 
                    "metadata.inward_issue_key"
                ]
                text_fields = ["metadata.task_name", "metadata.assignee"]
                date_fields = ["metadata.created_at"]

                # Keyword indexes for exact matches (filtering)
                for field in keyword_fields:
                    sync_client.create_payload_index(
                        collection_name=col_jira,
                        field_name=field,
                        field_schema=models.PayloadSchemaType.KEYWORD,
                    )
                # Text indexes for partial matches
                for field in text_fields:
                    sync_client.create_payload_index(
                        collection_name=col_jira,
                        field_name=field,
                        field_schema=models.PayloadSchemaType.TEXT,
                    )
                # DateTime indexes for temporal queries
                for field in date_fields:
                    sync_client.create_payload_index(
                        collection_name=col_jira,
                        field_name=field,
                        field_schema=models.PayloadSchemaType.DATETIME,
                    )

            # 2. NOTIFIED Tracking Collection (Lightweight check for duplicates)
            col_notified = settings.QDRANT_COLLECTION_NOTIFIED
            if col_notified not in existing_col_names:
                print(f"🚀 Initializing NOTIFIED collection: {col_notified}")
                sync_client.create_collection(
                    collection_name=col_notified,
                    vectors_config=models.VectorParams(
                        size=1, # Minimal size as we only use ID lookups
                        distance=models.Distance.COSINE
                    )
                )

        except Exception as e:
            print(f"❌ Qdrant setup error: {str(e)}")

    async def get_embedding(self, text: str, retries: int = 3) -> List[float]:
        """
        Generates a vector embedding using the local Ollama API.
        Includes a retry mechanism with exponential backoff for resilience.
        
        Args:
            text (str): The raw text to vectorize.
            retries (int): Number of attempts if the API is busy.

        Returns:
            List[float]: The resulting embedding vector or an empty list on failure.
        """
        clean_text = text.strip()
        if not clean_text:
            return []

        # Lock thread to prevent Ollama from processing multiple large embeddings simultaneously
        async with self.sem:
            for attempt in range(retries):
                try:
                    response = await self.http_client.post(
                        self.ollama_url,
                        json={
                            "model": settings.OLLAMA_EMBEDDING_MODEL, 
                            "prompt": clean_text.replace("\n", " ")
                        }
                    )
                    
                    # Handle internal server errors (Commonly VRAM exhaustion)
                    if response.status_code == 500:
                        raise httpx.HTTPStatusError("Ollama Busy/OOM", request=response.request, response=response)
                    
                    response.raise_for_status()
                    embedding = response.json().get("embedding", [])
                    
                    if len(embedding) == settings.QDRANT_VECTOR_SIZE:
                        return embedding
                        
                except Exception as e:
                    # Exponential backoff: 5s, 10s, 15s
                    wait_time = (attempt + 1) * 5 
                    print(f"⚠️ Attempt {attempt+1}/{retries} - Ollama busy. Retrying in {wait_time}s...")
                    await asyncio.sleep(wait_time)
            
            return []

    async def upsert_batch_to_qdrant(self, issues: List[JiraIssue]) -> Dict[str, Any]:
        """
        Vectorizes and uploads a batch of Jira issues to Qdrant Cloud.
        Processes sequentially to ensure stability on limited hardware.
        
        Args:
            issues (List[JiraIssue]): Validated Jira issue objects.

        Returns:
            Dict[str, Any]: A report of successful and failed synchronizations.
        """
        print(f"🔍 Vectorizing {len(issues)} issues...")
        
        all_points = []
        failed_keys = []

        for i, issue in enumerate(issues):
            vector = await self.get_embedding(issue.vector_content)
            
            if vector:
                all_points.append(models.PointStruct(
                    id=issue.point_id, # Stable UUID v5 generated by processor
                    vector=vector,
                    payload=issue.metadata.model_dump(by_alias=True)
                ))
            else:
                print(f"❌ Failed to vectorize: {issue.metadata.key}")
                failed_keys.append(issue.metadata.key)
            
            if (i + 1) % 5 == 0:
                print(f"📊 Progress: {i + 1}/{len(issues)} issues processed.")
                await asyncio.sleep(1) # Rest period to stabilize CPU/GPU load

        # Split into smaller chunks for cloud transmission stability
        total_uploaded = 0
        if all_points:
            chunk_size = 20
            for i in range(0, len(all_points), chunk_size):
                chunk = all_points[i : i + chunk_size]
                try:
                    await self.client.upsert(
                        collection_name=settings.QDRANT_COLLECTION_JIRA,
                        points=chunk
                    )
                    total_uploaded += len(chunk)
                except Exception as e:
                    print(f"❌ Qdrant Cloud upload error: {str(e)}")

        return {
            "status": "success",
            "synced": total_uploaded,
            "failed_count": len(failed_keys),
            "failed_keys": failed_keys
        }
    
    async def search_similar_issues(
        self, 
        query_text: str, 
        limit: int = 20,
        score_threshold: float = 0.62
    ) -> List[Dict[str, Any]]:
        """
        Performs a semantic similarity search using the modern 'query_points' API.
        Filters out 'Unassigned' tickets to improve recommendation quality.
        
        Args:
            query_text (str): The search query (usually issue description).
            limit (int): Max number of neighbors to return.
            score_threshold (float): Similarity floor.

        Returns:
            List[Dict[str, Any]]: A list of similar historical issue metadata.
        """
        query_vector = await self.get_embedding(query_text)
        if not query_vector:
            return []

        try:
            # Filter logic: Exclude tickets where assignee_id is 'None'
            search_filter = models.Filter(
                must_not=[
                    models.FieldCondition(
                        key="metadata.assignee_id",
                        match=models.MatchValue(value="None"),
                    )
                ]
            )

            # Execution using the modern v1.10+ Qdrant interface
            search_results = await self.client.query_points(
                collection_name=settings.QDRANT_COLLECTION_JIRA,
                query=query_vector, 
                query_filter=search_filter,
                limit=limit,
                score_threshold=score_threshold
            )
            
            print(f"🔎 Qdrant returned {len(search_results.points)} neighbors.")

            suggestions = []
            for hit in search_results.points:
                payload = hit.payload
                if payload:
                    suggestions.append({
                        "key": payload.get("key"),
                        "assignee": payload.get("assignee"),
                        "assignee_email": payload.get("assignee_email"), 
                        "assignee_id": payload.get("assignee_id"),       
                        "score": round(hit.score, 4)
                    })
            
            return suggestions

        except Exception as e:
            print(f"❌ Query failed: {str(e)}")
            return []

    async def check_already_notified(self, issue_key: str) -> bool:
        """
        Checks if a notification has already been dispatched for a specific ticket.
        Utilizes fast ID-based retrieval.
        
        Args:
            issue_key (str): The Jira issue key (e.g., 'APG-136').

        Returns:
            bool: True if previously notified, False otherwise.
        """
        point_id = self.processor.generate_stable_id(issue_key)
        try:
            results = await self.client.retrieve(
                collection_name=settings.QDRANT_COLLECTION_NOTIFIED,
                ids=[point_id]
            )
            return len(results) > 0
        except Exception as e:
            print(f"⚠️ Notification check failed for {issue_key}: {str(e)}")
            return False

    async def mark_as_notified(self, issue_key: str) -> bool:
        """
        Records a ticket key in the tracking collection to prevent duplicate notifications.
        
        Args:
            issue_key (str): The Jira issue key.

        Returns:
            bool: Success status of the record operation.
        """
        point_id = self.processor.generate_stable_id(issue_key)
        try:
            await self.client.upsert(
                collection_name=settings.QDRANT_COLLECTION_NOTIFIED,
                points=[models.PointStruct(
                    id=point_id, 
                    vector=[0.0], # Placeholder vector for tracking collection
                    payload={"key": issue_key}
                )]
            )
            return True
        except Exception as e:
            print(f"❌ Mark notified failed for {issue_key}: {str(e)}")
            return False
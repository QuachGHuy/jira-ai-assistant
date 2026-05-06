import httpx
import asyncio
import uuid
from typing import List, Dict, Any, Optional
from qdrant_client import QdrantClient, AsyncQdrantClient
from qdrant_client.http import models
from app.core.config import settings
from app.schemas.jira_models import JiraIssue
from app.services.text_processor import TextProcessor

class QdrantService:
    """
    Service to handle vector database operations with Qdrant Cloud 
    and embedding generation via local Ollama.
    """

    def __init__(self) -> None:
        """
        Initialize the service with persistent HTTP clients and 
        setup necessary collections.
        """
        self.client: AsyncQdrantClient = AsyncQdrantClient(
            url=settings.QDRANT_ENDPOINT_URL,
            api_key=settings.QDRANT_API_TOKEN,
            check_compatibility=False
        )
        self.ollama_url = f"{settings.OLLAMA_BASE_URL}/api/embeddings"
        
        # Increased timeout to 5 minutes to handle very large Jira tickets
        self.http_client = httpx.AsyncClient(timeout=300.0)
        
        # Semaphore(1) ensures sequential processing to prevent Ollama from crashing (OOM)
        self.sem = asyncio.Semaphore(1) 
        
        # Initialize collections synchronously at startup
        self._sync_setup_collections()
        self.processor = TextProcessor()

    async def close(self) -> None:
        """Close persistent HTTP and Qdrant client connections."""
        await self.http_client.aclose()
        await self.client.close()

    def _sync_setup_collections(self) -> None:
        """
        Synchronously check and initialize required collections.
        """
        sync_client = QdrantClient(
            url=settings.QDRANT_ENDPOINT_URL, 
            api_key=settings.QDRANT_API_TOKEN,
            check_compatibility=False
        )
        try:
            existing_col_names = [c.name for c in sync_client.get_collections().collections]
            required_cols = [
                settings.QDRANT_COLLECTION_JIRA, 
                settings.QDRANT_COLLECTION_NOTIFIED
            ]

            for col in required_cols:
                if col not in existing_col_names:
                    print(f"🚀 Initializing collection: {col}")
                    sync_client.create_collection(
                        collection_name=col,
                        vectors_config=models.VectorParams(
                            size=settings.QDRANT_VECTOR_SIZE, 
                            distance=models.Distance.COSINE
                        )
                    )
        except Exception as e:
            print(f"❌ Qdrant setup error: {str(e)}")

    async def get_embedding(self, text: str, retries: int = 3) -> List[float]:
        """
        Generate a vector embedding using Ollama with exponential backoff retry.
        
        Args:
            text: Raw text content to embed.
            retries: Number of retry attempts on failure.
        Returns:
            A list of floats representing the embedding, or empty list on failure.
        """
        clean_text = text.strip()
        if not clean_text:
            return []

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
                    
                    # Check for 500 errors (often caused by VRAM/RAM exhaustion)
                    if response.status_code == 500:
                        raise httpx.HTTPStatusError("Ollama OOM/Internal Error", request=response.request, response=response)
                    
                    response.raise_for_status()
                    embedding = response.json().get("embedding", [])
                    
                    if len(embedding) == settings.QDRANT_VECTOR_SIZE:
                        return embedding
                        
                except Exception as e:
                    # Wait time increases with each attempt: 5s, 10s, 15s
                    wait_time = (attempt + 1) * 5 
                    print(f"⚠️ Attempt {attempt+1}/{retries} - Ollama busy/OOM. Retrying in {wait_time}s...")
                    await asyncio.sleep(wait_time)
            
            return []

    async def upsert_batch_to_qdrant(self, issues: List[JiraIssue]) -> Dict[str, Any]:
        """
        Process and upload multiple Jira issues in a stable, sequential manner.
        
        Args:
            issues: List of JiraIssue objects to vectorize and store.
        Returns:
            Status report including synced count and failed keys.
        """
        print(f"🔍 Vectorizing {len(issues)} issues with Full Context Mode...")
        
        all_points = []
        failed_keys = []

        # Sequential loop ensures stability on consumer-grade hardware
        for i, issue in enumerate(issues):
            vector = await self.get_embedding(issue.vector_content)
            
            if vector:
                all_points.append(models.PointStruct(
                    id=issue.point_id, # Uses stable UUID v5
                    vector=vector,
                    payload=issue.metadata.model_dump(by_alias=True)
                ))
            else:
                print(f"❌ Failed to vectorize: {issue.metadata.key}")
                failed_keys.append(issue.metadata.key)
            
            if (i + 1) % 5 == 0:
                print(f"📊 Progress: {i + 1}/{len(issues)} issues processed.")
                # Brief rest to prevent hardware overheating
                await asyncio.sleep(1)

        # Batch upload to Qdrant Cloud in smaller chunks for network stability
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
        limit: int = 15,
        score_threshold: float = 0.62
    ) -> List[Dict[str, Any]]:
        """
        Find similar issues using the modern query_points API.
        
        Args:
            query_text: The user query or issue description.
            limit: Maximum number of suggestions to return.
            score_threshold: Minimum similarity score.
        Returns:
            A list of similar issue metadata.
        """
        query_vector = await self.get_embedding(query_text)
        if not query_vector:
            return []

        try:
            # query_points is the modern API for Qdrant (v1.10+)
            search_results = await self.client.query_points(
                collection_name=settings.QDRANT_COLLECTION_JIRA,
                query=query_vector, 
                query_filter=None, # Filtering can be applied here if needed
                limit=limit,
                score_threshold=score_threshold
            )
            
            suggestions = []
            # Extract results from the .points attribute
            for hit in search_results.points:
                if hit.payload:
                    suggestions.append({
                        "key": hit.payload.get("key"),
                        "taskName": hit.payload.get("taskName"),
                        "assignee": hit.payload.get("assignee") or hit.payload.get("owner"),
                        "assigneeId": hit.payload.get("assigneeId") or hit.payload.get("ownerId"),
                        "score": round(hit.score, 4)
                    })
            
            print(f"🔎 Found {len(suggestions)} candidates above threshold {score_threshold}.")
            return suggestions

        except Exception as e:
            print(f"❌ Query failed: {str(e)}")
            return []

    async def check_already_notified(self, issue_key: str) -> bool:
        """
        Check if an issue has already triggered a notification.
        Uses UUID transformation to ensure stable lookup.
        """
        point_id = self.processor.generate_stable_id(issue_key)
        try:
            results = await self.client.retrieve(
                collection_name=settings.QDRANT_COLLECTION_NOTIFIED,
                ids=[point_id]
            )
            return len(results) > 0
        except Exception as e:
            print(f"⚠️ Check notified failed for {issue_key}: {str(e)}")
            return False

    async def mark_as_notified(self, issue_key: str) -> bool:
        """
        Mark an issue as notified by storing its UUID in a tracking collection.
        Uses a zero-vector placeholder as per Qdrant requirements.
        """
        point_id = self.processor.generate_stable_id(issue_key)
        try:
            await self.client.upsert(
                collection_name=settings.QDRANT_COLLECTION_NOTIFIED,
                points=[models.PointStruct(
                    id=point_id, 
                    vector=[0.0] * settings.QDRANT_VECTOR_SIZE, 
                    payload={"key": issue_key, "processed": True}
                )]
            )
            return True
        except Exception as e:
            print(f"❌ Notification marking failed for {issue_key}: {str(e)}")
            return False
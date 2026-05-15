import httpx
import asyncio
from typing import List, Dict, Any, Optional
from qdrant_client import QdrantClient, AsyncQdrantClient
from qdrant_client.http import models

from app.core.config import settings
from app.schemas.jira_models import JiraIssue
from app.services.text_processor import TextProcessor

class QdrantService:
    """
    Service responsible for managing Vector Database operations using Qdrant.
    
    This service handles the lifecycle of Qdrant collections, generates text embeddings 
    via a local Ollama instance, and performs hybrid similarity searches combining 
    vector proximity with strict metadata filtering.
    """

    def __init__(self) -> None:
        """
        Initializes persistent HTTP and Qdrant clients.
        
        Uses AsyncQdrantClient for non-blocking runtime operations and a temporary 
        synchronous QdrantClient to verify/initialize collections during startup, 
        as Python's __init__ method cannot be asynchronous.
        """
        # Primary asynchronous client for high-concurrency requests
        self.client: AsyncQdrantClient = AsyncQdrantClient(
            url=settings.QDRANT_ENDPOINT_URL,
            api_key=settings.QDRANT_API_TOKEN,
            check_compatibility=False
        )
        
        self.ollama_url = f"{settings.OLLAMA_BASE_URL}/api/embeddings"
        
        # Persistent HTTP client with a generous timeout for local LLM inference
        self.http_client = httpx.AsyncClient(timeout=300.0)
        
        # Semaphore(1) ensures only one embedding request is processed at a time.
        # This protects local hardware (GPU/VRAM) from Out-Of-Memory (OOM) errors.
        self.sem = asyncio.Semaphore(1) 
        
        self.processor = TextProcessor()
        
        # Trigger immediate synchronization of collection schemas
        self._sync_setup_collections()

    async def close(self) -> None:
        """
        Gracefully closes persistent HTTP and Qdrant client connections.
        
        This method ensures that all network resources are released properly 
        to prevent memory leaks or hung connections during application shutdown.
        """
        print("🔌 Closing Qdrant and HTTP client connections...")
        try:
            await self.http_client.aclose()
            await self.client.close()
            print("✅ All connections closed successfully.")
        except Exception as e:
            print(f"⚠️ Error while closing connections: {e}")

    def _sync_setup_collections(self) -> None:
        """
        Verifies, creates collections, and sets up advanced payload indexing.
        
        Configures:
        - Nested Metadata Indexes: For strict filtering on Jira fields inside the 'metadata' object.
        - Root Text Index: For full-text search capabilities on the 'content' field.
        - Datetime Index: To support temporal queries (e.g., tasks created after a certain date).
        """
        sync_client = QdrantClient(
            url=settings.QDRANT_ENDPOINT_URL, 
            api_key=settings.QDRANT_API_TOKEN,
            check_compatibility=False
        )
        
        try:
            existing_col_names = [c.name for c in sync_client.get_collections().collections]
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
                
                # Metadata fields nested inside the 'metadata' object (Keyword for exact matching)
                keyword_fields = [
                    "metadata.key", "metadata.project", "metadata.type", 
                    "metadata.status", "metadata.priority", "metadata.assignee_id", 
                    "metadata.assignee_email", "metadata.outward_issue_key", 
                    "metadata.inward_issue_key"
                ]
                
                # Fields supporting text matching/partial search
                text_fields = ["metadata.task_name", "metadata.assignee", "content"]

                print("📝 Creating payload indexes for optimized Jira filtering...")
                
                # 1. Create Keyword Indexes for strict filtering
                for field in keyword_fields:
                    sync_client.create_payload_index(
                        collection_name=col_jira,
                        field_name=field,
                        field_schema=models.PayloadSchemaType.KEYWORD,
                    )
                
                # 2. Create Text Indexes for keyword/description search
                for field in text_fields:
                    sync_client.create_payload_index(
                        collection_name=col_jira,
                        field_name=field,
                        field_schema=models.PayloadSchemaType.TEXT,
                    )
                
                # 3. Create Datetime Index for time-range queries
                sync_client.create_payload_index(
                    collection_name=col_jira,
                    field_name="metadata.created_at",
                    field_schema=models.PayloadSchemaType.DATETIME,
                )
                print("✅ All Jira indexes initialized.")

            # Setup dedicated collection for tracking sent notifications
            col_notified = settings.QDRANT_COLLECTION_NOTIFIED
            if col_notified not in existing_col_names:
                print(f"🚀 Initializing NOTIFIED collection: {col_notified}")
                sync_client.create_collection(
                    collection_name=col_notified,
                    vectors_config=models.VectorParams(size=1, distance=models.Distance.COSINE)
                )

        except Exception as e:
            print(f"❌ Qdrant setup error: {str(e)}")

    def _build_filters(self, filter_dict: Optional[Dict[str, Any]]) -> Optional[models.Filter]:
        """
        Translates LLM-generated JSON filters into Qdrant-native Filter objects.
        
        This function acts as a semantic bridge between the QueryAnalyzer's output 
        and the Qdrant SDK, ensuring type safety and schema validation for both 
        inclusive (must) and exclusive (must_not) logical conditions.

        Args:
            filter_dict: A dictionary containing 'must' and/or 'must_not' keys 
                        with nested match/range conditions.

        Returns:
            A qdrant_client.models.Filter object or None if no valid conditions are found.
        """
        # Early exit if the input is empty or malformed
        if not filter_dict or not isinstance(filter_dict, dict):
            return None
        
        # Define which fields are indexed as "text" in your Qdrant schema
        TEXT_FIELDS = ["metadata.task_name", "metadata.assignee", "content"]
        filter_params = {}
      
        # Define the logical operators we want to process
        for op in ["must", "must_not", "should"]:
            if op in filter_dict and isinstance(filter_dict[op], list):
                conditions = []
                for item in filter_dict[op]:
                    field_key = item.get("key")
                    if not field_key: continue

                    try:
                        if "match" in item:
                            match_val = item["match"].get("value")
                            if match_val is None: continue

                            # SMART LOGIC: Switch between MatchText and MatchValue
                            if field_key in TEXT_FIELDS:
                                # Use MatchText for partial string matching on 'text' indexes
                                match_obj = models.MatchText(text=str(match_val))
                            else:
                                # Use MatchValue for exact matching on 'keyword' indexes
                                match_obj = models.MatchValue(value=match_val)
                            
                            conditions.append(models.FieldCondition(key=field_key, match=match_obj))

                        elif "range" in item:
                            conditions.append(models.FieldCondition(key=field_key, range=item["range"]))
                    except Exception as e:
                        print(f"⚠️ Filtering error for {field_key}: {e}")
                
                if conditions:
                    filter_params[op] = conditions

        return models.Filter(**filter_params) if filter_params else None

    async def get_embedding(self, text: str) -> List[float]:
        """
        Generates a numerical vector embedding for the input text using local Ollama.

        Args:
            text (str): The raw text to be vectorized (e.g., ticket description).

        Returns:
            List[float]: A list of floats representing the text in vector space. 
                         Returns an empty list if generation fails.
        """
        clean_text = text.strip()
        if not clean_text:
            return []

        # Enforce sequential execution to ensure local VRAM stability
        async with self.sem:
            try:
                response = await self.http_client.post(
                    self.ollama_url,
                    json={
                        "model": settings.OLLAMA_EMBEDDING_MODEL, 
                        # Replace newlines with spaces as some embedding models prefer linear input
                        "prompt": clean_text.replace("\n", " ")
                    }
                )
                response.raise_for_status()
                return response.json().get("embedding", [])
            except Exception as e:
                print(f"⚠️ Embedding generation failed: {str(e)}")
                return []

    async def upsert_batch_to_qdrant(self, issues: List[JiraIssue]) -> Dict[str, Any]:
        """
        Vectorizes and uploads a batch of Jira issues to Qdrant.
        
        Data is structured to keep 'content' at the root for easy AI access,
        while nesting all technical Jira fields inside a 'metadata' object for 
        clean, scalable indexing.

        Args:
            issues (List[JiraIssue]): A list of validated Jira issue models.

        Returns:
            Dict[str, Any]: A summary of the operation (status and sync count).
        """
        print(f"📥 Processing batch: {len(issues)} issues...")
        
        all_points = []
        for issue in issues:
            vector = await self.get_embedding(issue.vector_content)
            
            if vector:
                # Payload Structure: Root 'content' + Nested 'metadata'
                payload = {
                    "content": issue.content,
                    "metadata": issue.metadata.model_dump(by_alias=True)
                }
                
                all_points.append(models.PointStruct(
                    id=issue.point_id,
                    vector=vector,
                    payload=payload
                ))
            else:
                print(f"❌ Skipping {issue.metadata.key}: Could not generate vector.")

        if all_points:
            try:
                # Use bulk upsert for optimal cloud transmission performance
                await self.client.upsert(
                    collection_name=settings.QDRANT_COLLECTION_JIRA,
                    points=all_points
                )
                print(f"✅ Successfully synced {len(all_points)} issues to Qdrant.")
                return {"status": "success", "synced": len(all_points)}
            except Exception as e:
                print(f"❌ Upsert failed: {str(e)}")
                return {"status": "error", "message": str(e)}
        
        return {"status": "warning", "message": "No issues were processed."}

    async def search_similar_issues(
        self, 
        query_text: str, 
        filter_obj: Optional[Dict[str, Any]] = None,
        limit: int = 10,
        score_threshold: float = 0.3
    ) -> List[Dict[str, Any]]:
        """
        Performs an advanced Hybrid Search on Jira tickets within Qdrant.
        
        The search follows a 'Double-Path' logic:
        1. Exact Match Path: Uses the 'Scroll' API if a specific Ticket ID is detected.
        This bypasses vector calculations for 100% precision and lower latency.
        2. Semantic Path: Uses Vector Similarity search for topic-based or intent-based 
        queries when no exact ID is found or matched.

        Args:
            query_text (str): The semantic keywords or Ticket ID extracted by the analyzer.
            filter_obj (Optional[Dict]): The raw JSON filter structure from the Agent.
            limit (int): Maximum number of results to retrieve.
            score_threshold (float): Minimum similarity score for semantic results (0.0 - 1.0).

        Returns:
            List[Dict[str, Any]]: A list of standardized ticket objects with metadata and scores.
        """
        
        # Step 1: Translate the raw JSON filter into Qdrant Model objects
        # This utility ensures type-safety for Keyword and Range conditions
        search_filter = self._build_filters(filter_obj)
        
        # Step 2: Check for high-precision lookup requirement (Ticket ID)
        # If the filter specifies a unique key, we prioritize metadata retrieval over vector search
        has_exact_id = False
        if filter_obj and "must" in filter_obj:
            has_exact_id = any(item.get("key") == "metadata.key" for item in filter_obj["must"])

        results_to_process = []

        # --- PATH A: EXACT ID SEARCH (SCROLL API) ---
        if has_exact_id:
            print(f"🎯 Exact ID detected in filter. Executing high-precision Scroll...")
            # Scroll is more efficient for filtering by unique keys (no distance calculation needed)
            scroll_results, _ = await self.client.scroll(
                collection_name=settings.QDRANT_COLLECTION_JIRA,
                scroll_filter=search_filter,
                limit=1,
                with_payload=True,
                with_vectors=False
            )
            if scroll_results:
                # Assign a perfect score (1.0) to exact metadata matches
                results_to_process = [(hit, 1.0) for hit in scroll_results]

        # --- PATH B: SEMANTIC SEARCH (VECTOR QUERY) ---
        # Triggered if no ID is provided or if the ID was not found in the initial scroll
        if not results_to_process:
            # Generate embedding for the semantic part of the query
            query_vector = await self.get_embedding(query_text)
            if not query_vector:
                return []

            print(f"🔍 Executing semantic search for: '{query_text}' with filters: {filter_obj}")
            try:
                # Performs a K-Nearest Neighbors (KNN) search filtered by metadata constraints
                search_res = await self.client.query_points(
                    collection_name=settings.QDRANT_COLLECTION_JIRA,
                    query=query_vector, 
                    query_filter=search_filter,
                    limit=limit,
                    score_threshold=score_threshold,
                    with_payload=True
                )
                results_to_process = [(hit, hit.score) for hit in search_res.points]
            except Exception as e:
                print(f"❌ Qdrant Vector search failed: {str(e)}")
                return []

        # Step 3: Standardize the output format for downstream AI processing
        print(f"🔎 Found {len(results_to_process)} matching candidates.")
        
        standardized_results = []
        for hit, score in results_to_process:
            payload = hit.payload
            if not payload:
                continue
                
            meta = payload.get("metadata", {})
            
            # Mapping raw metadata to a clean structure for the RAG engine
            standardized_results.append({
                "key": meta.get("key"),
                "task_name": meta.get("task_name"),
                "project": meta.get("project"),
                "status": meta.get("status"),
                "priority": meta.get("priority"),
                "assignee": meta.get("assignee"),
                "assignee_id": meta.get("assignee_id"),
                "assignee_email": meta.get("assignee_email"),
                "content": payload.get("content"), 
                "score": round(score, 4)
            })
            
        return standardized_results

    async def check_already_notified(self, issue_key: str) -> bool:
        """
        Determines if a specific Jira ticket has already been processed.
        Utilizes fast ID-based retrieval to prevent duplicate Slack notifications.

        Args:
            issue_key (str): The unique Jira key (e.g., 'AD-123').

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
            print(f"⚠️ Retrieve failed for key {issue_key}: {e}")
            return False

    async def mark_as_notified(self, issue_key: str) -> bool:
        """
        Persists a record of a notification event in the tracking collection.

        Args:
            issue_key (str): The Jira key that was successfully notified.

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
            print(f"❌ Failed to record notification for {issue_key}: {e}")
            return False
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
    
    Handles collection lifecycles, text embeddings generation via local Ollama,
    and hybrid similarity searches combining vector proximity with metadata filters.
    """

    def __init__(self) -> None:
        """
        Initializes persistent HTTP and Qdrant clients.
        
        Uses AsyncQdrantClient for non-blocking operations and a temporary 
        synchronous QdrantClient to verify/initialize collections during startup.
        """
        self.client: AsyncQdrantClient = AsyncQdrantClient(
            url=settings.QDRANT_ENDPOINT_URL,
            api_key=settings.QDRANT_API_TOKEN.get_secret_value(),
            check_compatibility=False
        )
        
        self.ollama_url = f"{settings.OLLAMA_BASE_URL}"
        self.http_client = httpx.AsyncClient(timeout=300.0)
        
        # Semaphore(1) safely serializes embedding calls to protect local GPU VRAM from OOM crashes.
        # Can be scaled up if OLLAMA_NUM_PARALLEL is configured or cloud APIs are adopted.
        self.sem = asyncio.Semaphore(5) 
        
        self.processor = TextProcessor()
        self._sync_setup_collections()

    async def close(self) -> None:
        """
        Gracefully releases persistent HTTP and Qdrant client connections during teardown.
        """
        try:
            await self.http_client.aclose()
            await self.client.close()
            print("🔌 Qdrant and HTTP client connections terminated safely.")
        except Exception as e:
            print(f"⚠️ Error closing storage connections: {e}")

    def _sync_setup_collections(self) -> None:
        """
        Verifies collection availability at startup and constructs optimized schema structural indexes.
        """
        sync_client = QdrantClient(
            url=settings.QDRANT_ENDPOINT_URL, 
            api_key=settings.QDRANT_API_TOKEN.get_secret_value(),
            check_compatibility=False
        )
        
        try:
            existing_col_names = [c.name for c in sync_client.get_collections().collections]
            col_jira = settings.QDRANT_COLLECTION_JIRA
            
            if col_jira not in existing_col_names:
                print(f"🚀 Initializing core JIRA tracking collection: '{col_jira}'")
                sync_client.create_collection(
                    collection_name=col_jira,
                    vectors_config=models.VectorParams(
                        size=settings.QDRANT_VECTOR_SIZE, 
                        distance=models.Distance.COSINE
                    )
                )
                
                keyword_fields = [
                    "metadata.key", "metadata.project", "metadata.type", 
                    "metadata.status", "metadata.priority", "metadata.assignee_id", 
                    "metadata.assignee_email", "metadata.outward_issue_key", 
                    "metadata.inward_issue_key"
                ]
                text_fields = ["metadata.task_name", "metadata.assignee", "content"]

                # 1. Keyword Indexes for strict, accelerated filtering
                for field in keyword_fields:
                    sync_client.create_payload_index(
                        collection_name=col_jira,
                        field_name=field,
                        field_schema=models.PayloadSchemaType.KEYWORD,
                    )
                
                # 2. Text Indexes for semantic keyword description lookups
                for field in text_fields:
                    sync_client.create_payload_index(
                        collection_name=col_jira,
                        field_name=field,
                        field_schema=models.PayloadSchemaType.TEXT,
                    )
                
                # 3. Datetime Index for quick temporal queries
                sync_client.create_payload_index(
                    collection_name=col_jira,
                    field_name="metadata.created_at",
                    field_schema=models.PayloadSchemaType.DATETIME,
                )
                print(f"📝 Payloads and indexing properties bound to collection: '{col_jira}'")

            # Tracking structures setups
            for col_name in [settings.QDRANT_COLLECTION_NOTIFIED, settings.QDRANT_COLLECTION_JOBS]:
                if col_name not in existing_col_names:
                    print(f"🚀 Initializing automation schema utility collection: '{col_name}'")
                    sync_client.create_collection(
                        collection_name=col_name,
                        vectors_config=models.VectorParams(size=1, distance=models.Distance.COSINE)
                    )

        except Exception as e:
            print(f"❌ Qdrant system initial configuration mapping failed: {str(e)}")

    def _build_filters(self, filter_dict: Optional[Dict[str, Any]]) -> Optional[models.Filter]:
        """
        Translates raw structural JSON criteria matrices into strict Qdrant Filter objects.
        """
        if not filter_dict or not isinstance(filter_dict, dict):
            return None
        
        TEXT_FIELDS = ["metadata.task_name", "metadata.assignee", "content"]
        filter_params = {}
      
        for op in ["must", "must_not", "should"]:
            if op in filter_dict and isinstance(filter_dict[op], list):
                conditions = []
                for item in filter_dict[op]:
                    field_key = item.get("key")
                    if not field_key: 
                        continue

                    try:
                        if "match" in item:
                            match_val = item["match"].get("value")
                            if match_val is None: 
                                continue

                            match_obj = (
                                models.MatchText(text=str(match_val))
                                if field_key in TEXT_FIELDS
                                else models.MatchValue(value=match_val)
                            )
                            conditions.append(models.FieldCondition(key=field_key, match=match_obj))

                        elif "range" in item:
                            conditions.append(models.FieldCondition(key=field_key, range=item["range"]))
                    except Exception as e:
                        print(f"⚠️ Parsing criteria dropped for key '{field_key}': {e}")
                
                if conditions:
                    filter_params[op] = conditions

        return models.Filter(**filter_params) if filter_params else None

    async def get_embedding(self, text: str) -> List[float]:
        """
        Requests high-dimensional numerical feature vectors from local Ollama endpoint models.
        """
        clean_text = text.strip()
        if not clean_text:
            return []

        async with self.sem:
            try:
                response = await self.http_client.post(
                    self.ollama_url,
                    json={
                        "model": settings.OLLAMA_EMBEDDING_MODEL, 
                        "prompt": clean_text.replace("\n", " ")
                    }
                )
                response.raise_for_status()
                return response.json().get("embedding", [])
            except Exception as e:
                print(f"⚠️ Model vectorization failed via internal server error: {str(e)}")
                return []

    async def get_all_points(self, collection_name: str, limit: int = 1000, **kwargs) -> List[Dict[str, Any]]:
        """
        Scrolls and fetches target entities out of standard collections.
        """
        try:
            # 🔥 FIXED BUG: Safely passing structural limits and criteria filters downstream via **kwargs
            response, _ = await self.client.scroll(
                collection_name=collection_name,
                limit=limit,
                with_payload=True,
                with_vectors=False,
                **kwargs
            )
            return [{"id": point.id, "payload": point.payload} for point in response]
        except Exception as e:
            print(f"❌ Failed streaming extraction protocols from collection '{collection_name}': {str(e)}")
            return []
        
    async def upsert_points(self, collection_name: str, points: List[models.PointStruct]) -> bool:
        """
        Pushes batch collections of point entities down into database partitions.
        """
        try:
            await self.client.upsert(collection_name=collection_name, points=points)
            return True
        except Exception as e:
            print(f"❌ Database pipeline write abort for collection '{collection_name}': {str(e)}")
            return False

    async def delete_point(self, collection_name: str, point_ids: list) -> bool:
        """
        Purges historical entries from database partitions using explicit identification mapping vectors.
        """
        try:
            await self.client.delete(
                collection_name=collection_name,
                points_selector=point_ids
            )
            print(f"🗑️ Purged record entry '{point_ids}' from partition collection: '{collection_name}'")
            return True
        except Exception as e:
            print(f"❌ Database deletion tracking error encountered on key metadata scope: {str(e)}")
            return False
        
    async def upsert_batch_to_qdrant(self, issues: List[JiraIssue]) -> Dict[str, Any]:
        """
        Serializes, indexes, and transitions structural Jira schemas into vectorized storage nodes.
        """
        all_points = []
        for issue in issues:
            vector = await self.get_embedding(issue.vector_content)
            if vector:
                all_points.append(models.PointStruct(
                    id=issue.point_id,
                    vector=vector,
                    payload={
                        "content": issue.content,
                        "metadata": issue.metadata.model_dump(by_alias=True)
                    }
                ))

        if all_points:
            # 🔥 CONSOLIDATED PRINT: Internal prints cleaned to avoid duplications
            success = await self.upsert_points(
                collection_name=settings.QDRANT_COLLECTION_JIRA,
                points=all_points
            )
            if success:
                print(f"✅ Vector database synchronization complete. Registered {len(all_points)} issue tracks.")
                return {"status": "success", "synced": len(all_points)}
            return {"status": "error", "message": "Batch pipeline transmission failed inside database driver layer."}
        
        return {"status": "warning", "message": "No actionable transformations parsed out of target payloads."}

    async def search_similar_issues(
        self, 
        query_text: str, 
        filter_obj: Optional[Dict[str, Any]] = None,
        limit: int = 50,
        score_threshold: float = 0.3
    ) -> List[Dict[str, Any]]:
        """
        Executes hybrid double-path querying vectors across indexed cluster documents.
        """
        search_filter = self._build_filters(filter_obj)
        
        # Check high-precision criteria matrix tracking
        has_exact_id = False
        if filter_obj and "must" in filter_obj:
            has_exact_id = any(item.get("key") == "metadata.key" for item in filter_obj["must"])

        results_to_process = []

        # --- PATH A: EXACT ID SEARCH (SCROLL API) ---
        if has_exact_id:
            # 🔥 FIXED: The scroll filter parameter is now safely channeled instead of swallowed
            scroll_results = await self.get_all_points(
                collection_name=settings.QDRANT_COLLECTION_JIRA,
                scroll_filter=search_filter,
                limit=1
            )
            if scroll_results:
                # Wrap dictionary components into mock structure types matching query interfaces
                class MockHit:
                    def __init__(self, d):
                        self.id = d["id"]
                        self.payload = d["payload"]
                results_to_process = [(MockHit(hit), 1.0) for hit in scroll_results]

        # --- PATH B: SEMANTIC SEARCH (VECTOR QUERY) ---
        if not results_to_process:
            query_vector = await self.get_embedding(query_text)
            if not query_vector:
                return []

            try:
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
                print(f"❌ Index search transaction failed inside vector clusters engine: {str(e)}")
                return []

        # Formatting outputs uniformly
        standardized_results = []
        for hit, score in results_to_process:
            payload = hit.payload
            if not payload: 
                continue
                
            meta = payload.get("metadata", {})
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
        Determines execution redundancy using accelerated direct primary memory key parsing.
        """
        point_id = self.processor.generate_stable_id(issue_key)
        try:
            results = await self.client.retrieve(
                collection_name=settings.QDRANT_COLLECTION_NOTIFIED,
                ids=[point_id]
            )
            return len(results) > 0
        except Exception as e:
            print(f"⚠️ Tracking memory extraction failed for token '{issue_key}': {e}")
            return False

    async def mark_as_notified(self, issue_key: str) -> bool:
        """
        Saves transaction state verification tokens into notification registries.
        """
        point_id = self.processor.generate_stable_id(issue_key)
        try:
            await self.client.upsert(
                collection_name=settings.QDRANT_COLLECTION_NOTIFIED,
                points=[models.PointStruct(
                    id=point_id, 
                    vector=[0.0], 
                    payload={"key": issue_key}
                )]
            )
            return True
        except Exception as e:
            print(f"❌ Tracking validation node mapping rejected for ticket token '{issue_key}': {e}")
            return False
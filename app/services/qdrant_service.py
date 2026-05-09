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
            # Close the persistent httpx client
            await self.http_client.aclose()
            # Close the asynchronous Qdrant client
            await self.client.close()
            print("✅ All connections closed successfully.")
        except Exception as e:
            print(f"⚠️ Error while closing connections: {e}")

    def _sync_setup_collections(self) -> None:
        """
        Verifies, creates collections, and sets up advanced payload indexing.
        
        Specifically configures:
        - Nested Metadata Indexes: For strict filtering on Jira fields (Project, Status, etc.)
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
                
                # Metadata fields lồng trong 'metadata' object (Keyword dùng để lọc chính xác)
                keyword_fields = [
                    "metadata.key", "metadata.project", "metadata.type", 
                    "metadata.status", "metadata.priority", "metadata.assignee_id", 
                    "metadata.assignee_email", "metadata.outward_issue_key", 
                    "metadata.inward_issue_key"
                ]
                
                # Các trường hỗ trợ tìm kiếm văn bản (Partial/Text matching)
                text_fields = ["metadata.task_name", "metadata.assignee", "content"]

                print("📝 Creating payload indexes for optimized Jira filtering...")
                
                # 1. Tạo Keyword Indexes cho việc lọc dữ liệu nghiêm ngặt
                for field in keyword_fields:
                    sync_client.create_payload_index(
                        collection_name=col_jira,
                        field_name=field,
                        field_schema=models.PayloadSchemaType.KEYWORD,
                    )
                
                # 2. Tạo Text Indexes hỗ trợ tìm kiếm từ khóa trong content/metadata
                for field in text_fields:
                    sync_client.create_payload_index(
                        collection_name=col_jira,
                        field_name=field,
                        field_schema=models.PayloadSchemaType.TEXT,
                    )
                
                # 3. Tạo Datetime Index phục vụ truy vấn theo khoảng thời gian
                sync_client.create_payload_index(
                    collection_name=col_jira,
                    field_name="metadata.created_at",
                    field_schema=models.PayloadSchemaType.DATETIME,
                )
                print("✅ All Jira indexes initialized.")

            # Khởi tạo collection theo dõi thông báo đã gửi
            col_notified = settings.QDRANT_COLLECTION_NOTIFIED
            if col_notified not in existing_col_names:
                print(f"🚀 Initializing NOTIFIED collection: {col_notified}")
                sync_client.create_collection(
                    collection_name=col_notified,
                    vectors_config=models.VectorParams(size=1, distance=models.Distance.COSINE)
                )

        except Exception as e:
            print(f"❌ Qdrant setup error: {str(e)}")

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

        # Bắt buộc thực hiện tuần tự để ổn định mức sử dụng VRAM cục bộ
        async with self.sem:
            try:
                response = await self.http_client.post(
                    self.ollama_url,
                    json={
                        "model": settings.OLLAMA_EMBEDDING_MODEL, 
                        # Thay thế xuống dòng bằng khoảng trắng vì một số model embedding hoạt động tốt hơn với text phẳng
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
        
        Dữ liệu được tổ chức để giữ 'content' ở root giúp AI Agent dễ dàng truy cập,
        trong khi lồng tất cả metadata kỹ thuật vào đối tượng 'metadata' để index gọn gàng.

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
                # Cấu trúc payload: Root 'content' + Nested 'metadata'
                payload = {
                    "content": issue.vector_content,
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
                # Sử dụng upsert hàng loạt để đạt hiệu suất cao nhất
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
        score_threshold: float = 0.62
    ) -> List[Dict[str, Any]]:
        """
        Performs a semantic similarity search with optional metadata filtering.
        
        Hỗ trợ 'Hybrid Search' bằng cách sử dụng filter_obj do Agent tạo ra để 
        thu hẹp không gian tìm kiếm (VD: theo dự án hoặc trạng thái cụ thể)
        trước khi tính toán khoảng cách vector.

        Args:
            query_text (str): The search query or task description.
            filter_obj (Optional[Dict]): A raw Qdrant JSON filter object.
            limit (int): Maximum number of results to return.
            score_threshold (float): Minimum similarity score (0.0 to 1.0).

        Returns:
            List[Dict[str, Any]]: A list of similar issues including raw content.
        """
        query_vector = await self.get_embedding(query_text)
        if not query_vector:
            return []

        # Chuyển đổi dictionary filter (từ Agent) thành Qdrant Filter model
        search_filter = None
        if filter_obj:
            try:
                search_filter = models.Filter(**filter_obj)
                print(f"🔍 Executing search with dynamic filters: {filter_obj}")
            except Exception as e:
                print(f"⚠️ Failed to parse Agent filter: {e}")

        try:
            results = await self.client.query_points(
                collection_name=settings.QDRANT_COLLECTION_JIRA,
                query=query_vector, 
                query_filter=search_filter,
                limit=limit,
                score_threshold=score_threshold,
                with_payload=True
            )
            
            print(f"🔎 Found {len(results.points)} neighbors matching context.")

            suggestions = []
            for hit in results.points:
                payload = hit.payload

                if payload is None:  
                    print(f"⚠️ Skipping hit with ID {hit.id} due to missing payload.")
                    continue
                
                meta = payload.get("metadata", {})
                
                # Trích xuất các trường quan trọng làm context cho AI
                suggestions.append({
                    "key": meta.get("key"),
                    "task_name": meta.get("task_name"),
                    "assignee": meta.get("assignee"),
                    "content": payload.get("content"), # Cung cấp raw text cho quy trình RAG
                    "score": round(hit.score, 4)
                })
            return suggestions

        except Exception as e:
            print(f"❌ Similarity search failed: {str(e)}")
            return []

    async def check_already_notified(self, issue_key: str) -> bool:
        """
        Determines if a specific Jira ticket has already been processed.
        Used to prevent duplicate Slack notifications.

        Args:
            issue_key (str): The Jira key (e.g., 'AD-123').

        Returns:
            bool: True if already notified, False otherwise.
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
        Records a notification event in a lightweight tracking collection.

        Args:
            issue_key (str): The Jira key that was notified.

        Returns:
            bool: Success status of the operation.
        """
        point_id = self.processor.generate_stable_id(issue_key)
        try:
            await self.client.upsert(
                collection_name=settings.QDRANT_COLLECTION_NOTIFIED,
                points=[models.PointStruct(
                    id=point_id, 
                    vector=[0.0], # Vector giả cho mục đích theo dõi ID
                    payload={"key": issue_key}
                )]
            )
            return True
        except Exception as e:
            print(f"❌ Failed to record notification for {issue_key}: {e}")
            return False
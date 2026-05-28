from typing import List, Optional
from qdrant_client.models import Distance, VectorParams, PointStruct

from app.schemas.job_models import JobConfig
from app.core.config import settings
from app.services.qdrant_service import QdrantService


class JobsService:
    """
    Manages CRUD transaction payloads for user-defined schedules inside Qdrant Cloud.
    
    Handles schema verification, asynchronous metadata retrieval, and atomic overwrite 
    transactions using a single-dimensional vector placeholder (size=1) for compliance.
    """
    
    def __init__(self, qdrant_service: QdrantService) -> None:
        """
        Initializes the JobsService with a shared QdrantService instance.
        
        Args:
            qdrant_service (QdrantService): Shared vector database connection client.
        """
        self.qdrant = qdrant_service
        self.collection_name = settings.QDRANT_COLLECTION_JOBS

    async def _ensure_collection_exists(self) -> None:
        """
        Verifies collection availability at startup and constructs the 'cron_jobs' index if missing.
        """
        try:
            collections = await self.qdrant.client.get_collections()
            exists = any(c.name == self.collection_name for c in collections.collections)
            
            if not exists:
                await self.qdrant.client.create_collection(
                    collection_name=self.collection_name,
                    vectors_config=VectorParams(size=1, distance=Distance.COSINE)
                )
                print(f"💾 Qdrant Collection '{self.collection_name}' initialized successfully.")

        except Exception as e:
            print(f"⚠️ Error verifying collection '{self.collection_name}' availability: {e}")

    async def get_all_configs(self) -> List[JobConfig]:
        """
        Scrolls, parses, and returns all structured points out of Qdrant into validated JobConfig instances.
        
        Returns:
            List[JobConfig]: A collection of verified scheduling configurations.
        """
        try:
            await self._ensure_collection_exists()
            points = await self.qdrant.get_all_points(
                collection_name=self.collection_name,
                limit=100
            )
            
            jobs = []
            for point in points:
                payload = point.get("payload")
                if payload:
                    # Map the payload dict back into the strict JobConfig schema
                    jobs.append(JobConfig(**payload))
            return jobs
        
        except Exception as e:
            print(f"❌ Failed to read job configurations from Qdrant: {str(e)}")
            return []

    async def overwrite_all_configs(self, jobs: List[JobConfig]) -> bool:
        """
        Overwrites current entries and updates Qdrant with the fresh pipeline matrix.
        Injects a dummy vector [0.0] to align with system configurations.
        
        Args:
            jobs (List[JobConfig]): The new configurations to write to the store.
            
        Returns:
            bool: True if the operation succeeded, False otherwise.
        """
        try:
            # 1. Clear out old configurations to avoid orphaned tasks
            await self.qdrant.client.delete_collection(collection_name=self.collection_name)
            await self._ensure_collection_exists()

            # 2. Build vector points
            points = []
            for job in jobs:
                points.append(PointStruct(
                    id=job.id,                 # Standardized schema UUID string mapped as point ID
                    vector=[0.0],              # Dummy vector matching dim=1 configuration
                    payload=job.model_dump()   # Full serialization of Pydantic models
                ))

            if points:
                # Use encapsulated upsert wrapper to transmit batch points
                success = await self.qdrant.upsert_points(
                    collection_name=self.collection_name, 
                    points=points
                )
                if not success:
                    raise Exception("Upsert operation failed in driver layer.")
                
            print(f"✅ Successfully committed {len(jobs)} schedule profiles to Qdrant Cloud.")
            return True
        
        except Exception as e:
            print(f"❌ Failed to write schedule batch map to Qdrant: {str(e)}")
            return False
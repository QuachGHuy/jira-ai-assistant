from fastapi import APIRouter, Request, BackgroundTasks, HTTPException, status
from typing import List
import logging

from app.schemas.job_models import JobConfig

# Initialize router with standard grouping tags
router = APIRouter(prefix="/scheduler", tags=["Scheduler Management"])


@router.get("/jobs", response_model=List[JobConfig], status_code=status.HTTP_200_OK)
async def get_all_schedules(request: Request):
    """
    Retrieves all configured job profiles from Qdrant Cloud.

    Queries the Qdrant service via the shared request state and returns
    a validated list of JobConfig schemas.
    """
    try:
        # Retrieve injected Scheduler and JobsService from application context state
        scheduler = request.app.state.scheduler
        jobs_service = scheduler.jobs_service

        configs = await jobs_service.get_all_configs()
        return configs
    except Exception as e:
        print(f"❌ API Error: Failed fetching scheduled jobs: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to retrieve jobs from vector database: {str(e)}"
        )


@router.post("/jobs", status_code=status.HTTP_200_OK)
async def save_and_reload_schedules(
    request: Request,
    jobs: List[JobConfig],
    background_tasks: BackgroundTasks
):
    """
    Bulk overwrites current scheduling configurations and triggers a hot-reload.

    Accepts the complete temporary queue from the Streamlit UI, serializes and
    persists it into Qdrant Cloud, and executes an asynchronous scheduler reload.
    """
    try:
        scheduler = request.app.state.scheduler
        jobs_service = scheduler.jobs_service

        # 1. Commit all validated configurations atomically to Qdrant Cloud
        success = await jobs_service.overwrite_all_configs(jobs)
        if not success:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Qdrant database update rejected. Check server logs."
            )

        # 2. Asynchronously reload scheduler jobs in background to maintain instant response times
        background_tasks.add_task(scheduler.reload_jobs_from_qdrant)
        
        print(f"🔌 API: Batch overwrite successfully registered {len(jobs)} jobs. Scheduling reload...")
        return {"status": "success", "message": f"Committed and reloaded {len(jobs)} configurations successfully."}
    except HTTPException:
        raise
    except Exception as e:
        print(f"❌ API Error: Failed bulk saving scheduled configurations: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to persist configuration payload: {str(e)}"
        )


@router.post("/reload", status_code=status.HTTP_200_OK)
async def trigger_manual_reload(request: Request, background_tasks: BackgroundTasks):
    """
    Forces an immediate in-memory reload of active scheduled jobs.

    Dispatches a task background signal to rebuild current memory cron triggers 
    using whatever data is currently stored inside Qdrant Cloud.
    """
    try:
        scheduler = request.app.state.scheduler
        background_tasks.add_task(scheduler.reload_jobs_from_qdrant)
        return {"status": "success", "message": "Hot-reload action dispatched."}
    except Exception as e:
        print(f"❌ API Error: Hot-reload trigger crashed: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed dispatching dynamic reload context: {str(e)}"
        )
import uvicorn
from fastapi import FastAPI
from contextlib import asynccontextmanager

from app.core.config import settings
from app.core.scheduler import WorkflowScheduler
from app.api.v1 import slack, chat, workflow, scheduler 
from app.services.jira_service import JiraService
from app.services.slack_service import SlackService
from app.services.qdrant_service import QdrantService
from app.services.voting_service import VotingService
from app.services.googlesheet_service import GoogleSheetService
from app.services.workflow_service import WorkflowService
from app.services.jobs_service import JobsService 
from app.ai_engine.agents.jira_agent import JiraAgent


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Manages the startup and shutdown lifecycle of the FastAPI application.
    
    Handles persistent connection pooling initialization, dependency assembly,
    database schema synchronization, and memory trigger hot-reloading.
    """
    # 1. Initialize core infrastructure connections (Qdrant Database Client)
    qdrant_svc = QdrantService()
    
    # 2. Initialize enterprise dynamic jobs service configuration abstraction layer
    jobs_svc = JobsService(qdrant_service=qdrant_svc)
    
    # 3. Assemble unified Workflow Orchestration layer
    workflow_svc = WorkflowService(
        jira=JiraService(), 
        slack=SlackService(), 
        qdrant=qdrant_svc, 
        gsheet=GoogleSheetService(), 
        voting=VotingService()
    )
    
    # 4. Mount active state objects to Application Context
    app.state.workflow_service = workflow_svc
    app.state.agent = JiraAgent(workflow_service=workflow_svc)
    app.state.qdrant_service = qdrant_svc
    app.state.jobs_service = jobs_svc
    
    # 5. Initialize, Bootstrap, and Hot-Reload background scheduling engine ⏰
    scheduler_engine = WorkflowScheduler(
        workflow_service=app.state.workflow_service,
        jira_agent=app.state.agent,
        jobs_service=jobs_svc # Injected newly developed jobs management cluster
    )
    
    # Fire up the background daemon threads pool
    scheduler_engine.start()
    
    # Automatically pull configuration frames from Qdrant Cloud to populate memory layout on startup
    await scheduler_engine.reload_jobs_from_qdrant()
    
    # Retain safe reference inside application state space for clean shutdown procedures
    app.state.scheduler = scheduler_engine 
    
    yield

    # 6. Teardown Lifespan Context - Safely release network locks and volatile state memories
    print("🔌 Initiating lifespan application teardown sequence...")
    
    if hasattr(app.state, "scheduler") and app.state.scheduler:
        app.state.scheduler.shutdown()
        
    await app.state.qdrant_service.close()


# --- APP INITIALIZATION ---
app = FastAPI(
    title="Jira AI Assistant API", 
    version="1.6.0", 
    lifespan=lifespan
)

# --- ROUTER REGISTRY ---
app.include_router(chat.router, prefix="/api/v1/chat", tags=["AI Agent"])
app.include_router(slack.router, prefix="/api/v1/slack", tags=["Slack"])
app.include_router(workflow.router, prefix="/api/v1/workflow", tags=["Workflows"])
app.include_router(scheduler.router, prefix="/api/v1", tags=["Scheduler Management"])


@app.get("/health", tags=["Infrastructure Check"])
async def health_check():
    """
    Performs a lightweight sanity check to verify application runtime responsiveness.
    """
    return {"status": "online", "timezone": settings.TIMEZONE}


if __name__ == "__main__":
    # Run server via highly concurrent ASGI runner framework
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)
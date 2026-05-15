import uvicorn
from fastapi import FastAPI, HTTPException, Depends, Query, Request
from contextlib import asynccontextmanager
from typing import List, Optional

from app.core.config import settings
from app.services.jira_service import JiraService
from app.services.slack_service import SlackService
from app.services.qdrant_service import QdrantService
from app.services.voting_service import VotingService
from app.services.googlesheet_service import GoogleSheetService
from app.services.workflow_service import WorkflowService
from app.ai_engine.agents.jira_agent import JiraAgent
from app.api.v1 import slack
from app.schemas.chat_models import ChatRequest, ChatResponse

# --- 1. LIFESPAN MANAGEMENT ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    print("🚀 [STARTUP] Jira AI Assistant is waking up...")
    qdrant_svc = QdrantService()
    try:
        jira_svc = JiraService()
        slack_svc = SlackService()
        gsheet_svc = GoogleSheetService()
        voting_svc = VotingService()
        
        workflow_svc = WorkflowService(
            jira=jira_svc,
            slack=slack_svc,
            qdrant=qdrant_svc,
            gsheet=gsheet_svc,
            voting=voting_svc
        )
        
        agent = JiraAgent(workflow_service=workflow_svc)
        
        # State Storage
        app.state.workflow_service = workflow_svc
        app.state.agent = agent
        app.state.qdrant_service = qdrant_svc
        
        print("✅ [STARTUP] Services and Agent (with Memory) initialized.")
    except Exception as e:
        print(f"❌ [STARTUP] Critical Error: {str(e)}")
        raise e
    
    yield
    print("🛑 [SHUTDOWN] Jira AI Assistant is going to sleep...")
    if hasattr(app.state, 'qdrant_service'):
        await app.state.qdrant_service.close()

# --- 2. APP INITIALIZATION ---
app = FastAPI(title="Jira AI Assistant API", version="1.0.0", lifespan=lifespan)

# --- 3. DEPENDENCIES ---
def get_workflow_svc(request: Request) -> WorkflowService:
    return request.app.state.workflow_service

def get_agent(request: Request) -> JiraAgent:
    return request.app.state.agent

# --- 4. REGISTER ROUTERS ---
app.include_router(slack.router, prefix="/api/v1/slack", tags=["Slack"])

# --- 5. ENDPOINTS ---

@app.get("/health")
async def health_check():
    return {"status": "online", "integrations": {"jira": settings.JIRA_DOMAIN_URL}}

@app.post("/chat", response_model=ChatResponse)
async def chat_endpoint(request_data: ChatRequest, agent: JiraAgent = Depends(get_agent)):
    # Lấy session_id từ request hoặc mặc định
    session_id = getattr(request_data, 'session_id', "default_user")
    
    reply = await agent.run(
        user_input=request_data.message,
        thread_id=session_id
    )
    return {"reply": reply}

# --- WORKFLOW ENDPOINTS (Phục vụ Streamlit Buttons) ---

@app.post("/api/v1/sync/knowledge-base")
async def sync_knowledge_base(
    workflow: WorkflowService = Depends(get_workflow_svc)
):
    """Nút: Sync Knowledge Base"""
    return await workflow.sync_jira_to_qdrant()

@app.post("/api/v1/workflow/gsheet-report")
async def generate_gsheet_report(
    workflow: WorkflowService = Depends(get_workflow_svc)
):
    """Nút: Sync Report (Xuất Google Sheet)"""
    # Huy đảm bảo trong workflow_service có hàm này nhé
    result = await workflow.sync_gsheet_report()
    return {"status": "success", "data": result}

@app.post("/api/v1/workflow/sync-status")
async def sync_ticket_status(
    workflow: WorkflowService = Depends(get_workflow_svc)
):
    """Nút: Sync Status"""
    # Logic cập nhật status từ Jira về các hệ thống khác nếu cần
    await workflow.sync_apg_status_from_ad()
    return {"status": "success", "message": "Statuses synchronized with Jira"}

@app.post("/api/v1/workflow/auto-assign")
async def run_auto_assignment(
    workflow: WorkflowService = Depends(get_workflow_svc)
):
    return await workflow.auto_issue_assignment()

if __name__ == "__main__":
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)
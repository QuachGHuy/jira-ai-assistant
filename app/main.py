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
    
    # Khởi tạo Qdrant trước để đảm bảo kết nối
    qdrant_svc = QdrantService()
    
    try:
        # Khởi tạo các service vệ tinh
        jira_svc = JiraService()
        slack_svc = SlackService()
        gsheet_svc = GoogleSheetService()
        voting_svc = VotingService()
        
        # Khởi tạo Workflow Service
        workflow_svc = WorkflowService(
            jira=jira_svc,
            slack=slack_svc,
            qdrant=qdrant_svc,
            gsheet=gsheet_svc,
            voting=voting_svc
        )
        
        # Khởi tạo Agent với bộ nhớ RAM Checkpoint
        agent = JiraAgent(workflow_service=workflow_svc)
        
        # Lưu vào state của app để dùng chung ở các endpoint
        app.state.workflow_service = workflow_svc
        app.state.agent = agent
        app.state.qdrant_service = qdrant_svc # Lưu để đóng kết nối sau này
        
        print("✅ [STARTUP] Services and Agent (with Memory) initialized.")
    except Exception as e:
        print(f"❌ [STARTUP] Critical Error: {str(e)}")
        raise e # Dừng app nếu khởi tạo thất bại
    
    yield
    
    print("🛑 [SHUTDOWN] Jira AI Assistant is going to sleep...")
    # Lấy qdrant service từ state để close
    if hasattr(app.state, 'qdrant_service'):
        await app.state.qdrant_service.close()

# --- 2. APP INITIALIZATION ---
app = FastAPI(
    title="Jira AI Assistant API",
    version="1.0.0",
    lifespan=lifespan
)

# --- 3. DEPENDENCIES (Lấy từ App State) ---
def get_workflow_svc(request: Request) -> WorkflowService:
    return request.app.state.workflow_service

def get_agent(request: Request) -> JiraAgent:
    return request.app.state.agent

# --- 4. REGISTER ROUTERS ---
app.include_router(slack.router, prefix="/api/v1/slack", tags=["Slack"])

# --- 5. ENDPOINTS ---

@app.get("/health")
async def health_check():
    return {
        "status": "online",
        "integrations": {
            "jira": settings.JIRA_DOMAIN_URL,
            "qdrant": settings.QDRANT_ENDPOINT_URL
        }
    }

@app.post("/chat", response_model=ChatResponse)
async def chat_endpoint(
    request_data: ChatRequest, 
    agent: JiraAgent = Depends(get_agent)
):
    """
    Endpoint xử lý chat chính.
    Sử dụng thread_id từ request để truy xuất lịch sử hội thoại từ RAM.
    """
    # Dùng session_id từ client làm thread_id cho LangGraph
    session_id = request_data.session_id if hasattr(request_data, 'session_id') else "default_user"
    
    # Agent.run giờ đây chỉ cần input và thread_id
    reply = await agent.run(
        user_input=request_data.message,
        thread_id=session_id
    )
    
    return {"reply": reply}

# --- WORKFLOW & DEBUG ENDPOINTS ---

@app.post("/api/v1/sync/knowledge-base")
async def sync_knowledge_base(
    project: str = "AIO Development",
    workflow: WorkflowService = Depends(get_workflow_svc)
):
    return await workflow.sync_jira_to_qdrant(project_key=project)

@app.post("/api/v1/workflow/auto-assign")
async def run_auto_assignment(
    jql: Optional[str] = Query(None),
    workflow: WorkflowService = Depends(get_workflow_svc)
):
    return await workflow.auto_issue_assignment(custom_jql=jql)

@app.get("/api/v1/ai/search")
async def search_similar_tasks(
    query: str,
    workflow: WorkflowService = Depends(get_workflow_svc)
):
    # Trỏ thẳng vào qdrant service bên trong workflow
    return await workflow.qdrant.search_similar_issues(query_text=query)

if __name__ == "__main__":
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)
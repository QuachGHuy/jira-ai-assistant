from urllib import request

import uvicorn
from fastapi import FastAPI, HTTPException, Depends, Query
from contextlib import asynccontextmanager
from typing import List, Optional
from pydantic import BaseModel

from app.core.config import settings
from app.services.jira_service import JiraService
from app.services.slack_service import SlackService
from app.services.qdrant_service import QdrantService
from app.services.voting_service import VotingService
from app.services.googlesheet_service import GoogleSheetService
from app.services.workflow_service import WorkflowService
from app.ai_engine.agents.jira_agent import JiraAgent  # <-- Đừng quên import Agent

# Import router xử lý tương tác từ Slack
from app.api.v1 import slack

# --- 1. SCHEMAS (Phải định nghĩa trước khi dùng trong Routes) ---
class ChatRequest(BaseModel):
    message: str
    chat_history: Optional[List[dict]] = []

class ChatResponse(BaseModel):
    reply: str

# --- 2. DEPENDENCY PROVIDER ---
def get_workflow_service() -> WorkflowService:
    """Khởi tạo WorkflowService cho các endpoint thủ công."""
    return WorkflowService(
        jira=JiraService(),
        slack=SlackService(),
        qdrant=QdrantService(),
        gsheet=GoogleSheetService(),
        voting=VotingService()
    )

# --- 3. LIFESPAN MANAGEMENT ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Quản lý khởi tạo và giải phóng tài nguyên."""
    print("🚀 [STARTUP] Jira AI Assistant is waking up...")
    
    # Khởi tạo QdrantService ở scope rộng hơn để đóng kết nối lúc shutdown
    q_svc = None
    
    try:
        q_svc = QdrantService()
        # Khởi tạo Workflow và Agent một lần duy nhất
        # (Dùng chung các instance service để tối ưu bộ nhớ)
        workflow_svc = get_workflow_service()
        agent = JiraAgent(workflow_service=workflow_svc)
        
        # Lưu vào state để các route có thể truy cập
        app.state.workflow_service = workflow_svc
        app.state.agent = agent
        
        print("✅ [STARTUP] Services and Agent initialized.")
    except Exception as e:
        print(f"❌ [STARTUP] Critical Error: {str(e)}")
    
    yield
    
    print("🛑 [SHUTDOWN] Jira AI Assistant is going to sleep...")
    await q_svc.close()  # Đóng kết nối an toàn

# --- 4. APP INITIALIZATION ---
app = FastAPI(
    title="Jira AI Assistant API",
    version="1.0.0",
    lifespan=lifespan
)

# --- 5. REGISTER ROUTERS ---
app.include_router(slack.router, prefix="/api/v1/slack", tags=["Slack"])

# --- 6. ENDPOINTS ---

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
async def chat(request: ChatRequest):
    # Kiểm tra an toàn
    if not hasattr(app.state, "agent"):
        raise HTTPException(status_code=503, detail="Agent not ready.")
    
    agent: JiraAgent = app.state.agent
    try:
        # Gọi run chỉ với user_input
        response = await agent.run(user_input=request.message)
        
        # Trích xuất nội dung trả về
        reply_content = response["messages"][-1].content
        
        return ChatResponse(reply=reply_content)
    except Exception as e:
        print(f"❌ Agent Error: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))
# --- WORKFLOW ENDPOINTS ---

@app.post("/api/v1/sync/knowledge-base")
async def sync_knowledge_base(
    project: str = "AIO Development",
    workflow: WorkflowService = Depends(get_workflow_service)
):
    return await workflow.sync_jira_to_qdrant(project_key=project)

@app.post("/api/v1/workflow/auto-assign")
async def run_auto_assignment(
    jql: Optional[str] = Query(None),
    workflow: WorkflowService = Depends(get_workflow_service)
):
    return await workflow.auto_issue_assignment(custom_jql=jql)

@app.get("/api/v1/ai/search")
async def search_similar_tasks(
    query: str,
    workflow: WorkflowService = Depends(get_workflow_service)
):
    return await workflow.qdrant.search_similar_issues(query_text=query)

# --- ENTRY POINT ---
if __name__ == "__main__":
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)
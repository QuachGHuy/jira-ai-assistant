import uvicorn
from fastapi import FastAPI, HTTPException, Depends, Query, BackgroundTasks
from contextlib import asynccontextmanager
from typing import Dict, Any, Optional

from app.core.config import settings
from app.services.jira_service import JiraService
from app.services.slack_service import SlackService
from app.services.qdrant_service import QdrantService
from app.services.voting_service import VotingService
from app.services.googlesheet_service import GoogleSheetService
from app.services.workflow_service import WorkflowService

# Import router xử lý tương tác từ Slack
from app.api.v1 import slack

# --- Dependency Provider ---
def get_workflow_service() -> WorkflowService:
    """
    Nhà máy sản xuất WorkflowService. 
    Tất cả các Service đơn lẻ được khởi tạo một lần và 'tiêm' vào Workflow.
    """
    return WorkflowService(
        jira=JiraService(),
        slack=SlackService(),
        qdrant=QdrantService(),
        gsheet=GoogleSheetService(),
        voting=VotingService()
    )

@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Quản lý vòng đời ứng dụng.
    Kiểm tra kết nối Qdrant ngay khi khởi động.
    """
    print("🚀 [STARTUP] Jira AI Assistant is waking up...")
    try:
        # Kiểm tra Qdrant
        q_svc = QdrantService()
        print("✅ [STARTUP] Qdrant Collections verified.")
    except Exception as e:
        print(f"❌ [STARTUP] Critical Error: {str(e)}")
    
    yield
    print("🛑 [SHUTDOWN] Jira AI Assistant is going to sleep...")
    await q_svc.close()  # Đóng kết nối Qdrant khi tắt ứng dụng

app = FastAPI(
    title="Jira AI Assistant API",
    version="1.0.0",
    lifespan=lifespan
)

# --- REGISTER ROUTERS ---
# Gắn router xử lý Slack Interactive (/api/v1/slack/interactive)
app.include_router(slack.router, prefix="/api/v1/slack", tags=["Slack"])

# --- BASIC ENDPOINTS ---

@app.get("/health")
async def health_check():
    return {
        "status": "online",
        "environment": "development",
        "integrations": {
            "jira": settings.JIRA_DOMAIN_URL,
            "qdrant": settings.QDRANT_ENDPOINT_URL,
            "gsheet": "Connected"
        }
    }

# --- WORKFLOW ENDPOINTS (Sử dụng WorkflowService làm cốt lõi) ---

@app.post("/api/v1/sync/knowledge-base")
async def sync_knowledge_base(
    project: str = "AIO Development",
    workflow: WorkflowService = Depends(get_workflow_service)
):
    """Đồng bộ Jira sang Qdrant để AI có dữ liệu học."""
    return await workflow.sync_jira_to_qdrant(project_key=project)

@app.post("/api/v1/sync/dashboard")
async def sync_dashboard(
    workflow: WorkflowService = Depends(get_workflow_service)
):
    """Đồng bộ ticket Sprint hiện tại lên Google Sheets Dashboard."""
    return await workflow.sync_gsheet_report()

@app.post("/api/v1/workflow/auto-assign")
async def run_auto_assignment(
    jql: Optional[str] = Query(None, description="Custom JQL for filtering issues"),
    workflow: WorkflowService = Depends(get_workflow_service)
):
    """Kích hoạt luồng AI gợi ý Assignee và gửi thông báo Slack."""
    return await workflow.auto_issue_assignment(custom_jql=jql)

@app.post("/api/v1/workflow/status-sync")
async def run_status_sync(
    workflow: WorkflowService = Depends(get_workflow_service)
):
    """Đồng bộ trạng thái từ ticket AD sang APG."""
    return await workflow.sync_apg_status_from_ad()

# --- SEARCH & DEBUG ENDPOINTS ---

@app.get("/api/v1/ai/search")
async def search_similar_tasks(
    query: str,
    workflow: WorkflowService = Depends(get_workflow_service)
):
    """Tìm kiếm các task tương tự trong quá khứ (Dành cho LangChain Tool sau này)."""
    return await workflow.qdrant.search_similar_issues(query_text=query)

if __name__ == "__main__":
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)
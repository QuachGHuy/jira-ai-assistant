import uvicorn
from fastapi import FastAPI
from app.core.config import settings
from app.services.jira_service import JiraService

app = FastAPI(title="Jira AI Assistant Backend")

@app.get("/health")
async def health_check():
    return {
        "status": "healthy",
        "embedding_model": settings.EMBEDDING_MODEL,
        "jira_url": settings.JIRA_DOMAIN_URL,
        "qdrant_url": settings.QDRANT_ENDPOINT_URL,
        "ollama_url": settings.OLLAMA_BASE_URL,
    }

@app.get("/test-jira")
async def test_jira():
    service = JiraService()
    jql = 'project = "AIO Development"'
    issues = service.get_issues_by_jql(jql)
    return {
        "count": len(issues),
        "all_issues": issues  
    }

@app.post("/test-update-status/{issue_key}")
async def test_update_status(issue_key: str, status: str):
    """
    Test logic của node 'Sync APG Issue's Status'.
    Ví dụ: status='Done' hoặc '31'
    """
    service = JiraService()
    result = service.update_issue_status(issue_key, status)
    return {"message": f"Ticket {issue_key} updated", "raw_response": result}

@app.post("/test-update-assignee/{issue_key}")
async def test_update_assignee(issue_key: str, assignee_id: str):
    """
    Test logic của node 'Update AD Issue's ASSIGNEE'.
    """
    service = JiraService()
    result = service.update_issue_assignee(issue_key, assignee_id)
    return {"message": f"Ticket {issue_key} assigned to {assignee_id}", "raw_response": result}

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000, reload=True)
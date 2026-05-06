import uvicorn
from fastapi import FastAPI, Query, HTTPException
from contextlib import asynccontextmanager
from typing import Dict, Any

from app.core.config import settings
from app.services.googlesheet_service import GoogleSheetService
from app.services.jira_service import JiraService
from app.services.qdrant_service import QdrantService
from app.services.voting_service import VotingService

@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Lifecycle management for the FastAPI application.
    Ensures Qdrant collections are initialized and services are ready.
    """
    print("🚀 Initializing Jira AI Assistant Backend...")
    # Triggering QdrantService setup (checks/creates collections)
    try:
        QdrantService()
        print("✅ Qdrant collections verified and ready.")
    except Exception as e:
        print(f"❌ Startup Error: Could not initialize Qdrant: {str(e)}")
    
    yield

    print("🛑 Shutting down Jira AI Assistant Backend...")

app = FastAPI(
    title="Jira AI Assistant Backend",
    lifespan=lifespan
)

@app.get("/health")
async def health_check() -> Dict[str, Any]:
    """Check connectivity and model configuration."""
    return {
        "status": "healthy",
        "embedding_model": settings.OLLAMA_EMBEDDING_MODEL,
        "jira_url": settings.JIRA_DOMAIN_URL,
        "qdrant_url": settings.QDRANT_ENDPOINT_URL,
    }

# --- JIRA INTEGRATION ENDPOINTS ---

@app.get("/test-jira")
async def test_jira():
    """Fetch issues directly from Jira to verify connection."""
    service = JiraService()
    jql = 'project = "AIO Development"'
    issues = await service.get_issues_by_jql(jql)
    return {
        "count": len(issues),
        "all_issues": issues  
    }

@app.post("/sync-jira-qdrant")
async def sync_jira_to_qdrant():
    """
    Triggers the full pipeline: Fetch from Jira -> Embed via Ollama -> Store in Qdrant.
    This implements the batch upsert logic for efficiency.
    """
    jira_service = JiraService()
    qdrant_service = QdrantService()
    
    # 1. Fetch data from Jira
    jql = 'project = "AIO Development"'
    issues = await jira_service.get_issues_by_jql(jql)
    
    if not issues:
        return {"status": "error", "message": "No issues found to synchronize."}

    # 2. Vectorize and Upsert
    sync_result = await qdrant_service.upsert_batch_to_qdrant(issues)
    return {
        "status": "success",
        "details": sync_result
    }

# --- QDRANT & AI SEARCH ENDPOINTS ---

@app.get("/test-search")
async def test_search(
    query: str, 
    threshold: float = 0.62
):
    """
    Tests the 'smart' similarity search with score threshold and filtered payloads.
    """
    qdrant_service = QdrantService()
    # Uses the optimized search logic with assignee extraction
    results = await qdrant_service.search_similar_issues(
        query_text=query,
        score_threshold=threshold
    )
    return {
        "query": query,
        "threshold_applied": threshold,
        "result_count": len(results),
        "suggestions": results
    }

@app.get("/check-notified/{issue_key}")
async def check_notified(issue_key: str):
    """Verify if a ticket has already been notified using the secondary collection."""
    qdrant_service = QdrantService()
    is_notified = await qdrant_service.check_already_notified(issue_key)
    return {"point_id": issue_key, "already_notified": is_notified}

# --- JIRA ACTION ENDPOINTS ---

@app.post("/test-update-status/{issue_key}")
async def test_update_status(issue_key: str, status: str):
    """Update issue status in Jira."""
    service = JiraService()
    result = await service.update_issue_status(issue_key, status)
    return result

@app.post("/test-update-assignee/{issue_key}")
async def test_update_assignee(issue_key: str, assignee_id: str):
    """Assign issue to a specific accountId in Jira."""
    service = JiraService()
    result = await service.update_issue_assignee(issue_key, assignee_id)
    return result

# Khởi tạo service bên ngoài để reuse connection pool
jira_service = JiraService()
gsheet_service = GoogleSheetService()

@app.post("/api/v1/full-sync-test")
async def full_sync_test():
    try:
        # 1. Lấy data từ Jira (Dạng list of objects hoặc list of dicts đều được)
        jql_query = "project = 'AIO Development' AND sprint in openSprints()"
        raw_issues = await jira_service.get_issues_by_jql(jql_query)

        # 2. Thông tin Sprint
        sprint_info = {
            "name": "ARD2026 (04.03 - 04.16)",
            "start_date": "2026-04-16",
            "end_date": "2026-04-29"
        }
        
        # 3. Đẩy thẳng sang Service, Service sẽ tự map mọi thứ
        await gsheet_service.sync_dashboard_upsert(
            sprint_metadata=sprint_info,
            issues=raw_issues
        )

        return {"status": "success", "synced_count": len(raw_issues)}

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))




if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
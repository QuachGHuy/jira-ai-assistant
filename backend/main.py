import uvicorn
from fastapi import FastAPI
from contextlib import asynccontextmanager
from app.api.v1 import slack, chat, workflow 
from app.services.jira_service import JiraService
from app.services.slack_service import SlackService
from app.services.qdrant_service import QdrantService
from app.services.voting_service import VotingService
from app.services.googlesheet_service import GoogleSheetService
from app.services.workflow_service import WorkflowService
from app.ai_engine.agents.jira_agent import JiraAgent

@asynccontextmanager
async def lifespan(app: FastAPI):
    qdrant_svc = QdrantService()
    workflow_svc = WorkflowService(
        jira=JiraService(), slack=SlackService(), 
        qdrant=qdrant_svc, gsheet=GoogleSheetService(), 
        voting=VotingService()
    )
    app.state.workflow_service = workflow_svc
    app.state.agent = JiraAgent(workflow_service=workflow_svc)
    app.state.qdrant_service = qdrant_svc
    yield
    await app.state.qdrant_service.close()

app = FastAPI(title="Jira AI Assistant API", version="1.0.0", lifespan=lifespan)

app.include_router(chat.router, prefix="/api/v1/chat", tags=["AI Agent"])
app.include_router(slack.router, prefix="/api/v1/slack", tags=["Slack"])
app.include_router(workflow.router, prefix="/api/v1/workflow", tags=["Workflows"])

@app.get("/health")
async def health_check():
    return {"status": "online"}

if __name__ == "__main__":
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)
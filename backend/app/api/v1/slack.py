# app/api/v1/slack.py
import json
from fastapi import APIRouter, Form, BackgroundTasks, Response, Depends
from app.services.workflow_service import WorkflowService
from app.services.jira_service import JiraService
from app.services.slack_service import SlackService
from app.services.qdrant_service import QdrantService
from app.services.voting_service import VotingService
from app.services.googlesheet_service import GoogleSheetService

router = APIRouter()

def get_workflow_service() -> WorkflowService:
    """
    Dependency provider for WorkflowService.
    Initializes all downstream services required for the orchestrator.
    
    Returns:
        WorkflowService: An instance of the central orchestrator.
    """
    return WorkflowService(
        jira=JiraService(),
        slack=SlackService(),
        qdrant=QdrantService(),
        gsheet=GoogleSheetService(),
        voting=VotingService()
    )

@router.post("/interactive")
async def handle_slack_interactive(
    background_tasks: BackgroundTasks,
    payload: str = Form(...),
    workflow: WorkflowService = Depends(get_workflow_service)
):
    """
    Receives and processes interactive component actions from Slack (e.g., button clicks).
    
    This endpoint follows Slack's 3-second acknowledgement rule by offloading
    the business logic (Jira updates, Slack UI refreshes) to a background task.
    
    Args:
        background_tasks: FastAPI utility to run logic after returning the response.
        payload: The JSON-encoded string sent by Slack in x-www-form-urlencoded format.
        workflow: The injected orchestrator service.
        
    Returns:
        Response: HTTP 200 OK to acknowledge receipt of the interaction.
    """
    try:
        # Slack sends the interactive data as a JSON string within a 'payload' form field
        data = json.loads(payload)
        
        # Offload the heavy lifting (Jira transitions/assignments) to avoid Slack timeout
        # handle_slack_interaction will update the original message once finished
        background_tasks.add_task(workflow.handle_slack_interaction, data)
        
        # Acknowledge the request immediately within the 3000ms window
        return Response(status_code=200)
        
    except json.JSONDecodeError as e:
        print(f"Failed to parse Slack interactive payload: {str(e)}")
        return Response(status_code=400, content="Invalid JSON payload")
    except Exception as e:
        # logger.error(f"Unexpected error in Slack interactive endpoint: {str(e)}")
        print(f"Unexpected error in Slack interactive endpoint: {str(e)}")
        return Response(status_code=500, content="Internal server error")
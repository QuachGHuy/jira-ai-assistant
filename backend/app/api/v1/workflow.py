from fastapi import APIRouter, Depends, Request
from app.services.workflow_service import WorkflowService

router = APIRouter()

def get_workflow_svc(request: Request) -> WorkflowService:
    return request.app.state.workflow_service

@router.post("/sync-knowledge-base")
async def sync_knowledge_base(workflow: WorkflowService = Depends(get_workflow_svc)):
    return await workflow.sync_jira_to_qdrant()

@router.post("/gsheet-report")
async def generate_gsheet_report(workflow: WorkflowService = Depends(get_workflow_svc)):
    result = await workflow.sync_gsheet_report()
    return result

@router.post("/sync-status")
async def sync_ticket_status(workflow: WorkflowService = Depends(get_workflow_svc)):
    result = await workflow.sync_apg_status_from_ad()
    return result

@router.post("/auto-assign")
async def run_auto_assignment(workflow: WorkflowService = Depends(get_workflow_svc)):
    result =  await workflow.auto_issue_assignment()
    return result
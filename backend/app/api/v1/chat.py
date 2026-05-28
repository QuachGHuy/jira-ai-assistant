from fastapi import APIRouter, Depends, Request
from app.ai_engine.agents.jira_agent import JiraAgent
from app.schemas.chat_models import ChatRequest, ChatResponse

router = APIRouter()

def get_agent(request: Request) -> JiraAgent:
    return request.app.state.agent

@router.post("", response_model=ChatResponse)
async def chat_endpoint(request_data: ChatRequest, agent: JiraAgent = Depends(get_agent)):
    session_id = getattr(request_data, 'session_id', "default_user")
    reply = await agent.run(user_input=request_data.message, thread_id=session_id)
    return {"reply": reply}
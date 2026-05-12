from langchain.agents import create_agent
from langchain_openai import ChatOpenAI

from app.core.config import settings
from app.ai_engine.tools.workflow_tools import WorkflowToolkit
from app.services.workflow_service import WorkflowService


class JiraAgent:

    def __init__(self, workflow_service: WorkflowService):
        # 1. Khởi tạo LLM trước (Bộ não)
        self.llm = ChatOpenAI(
            model=settings.ROUTER_CHAT_MODEL,
            base_url=settings.ROUTER_BASE_URL,
            api_key=settings.ROUTER_API_KEY,
            temperature=0,
        )

        # 2. Truyền llm trực tiếp vào Toolkit để QueryAnalyzer sử dụng
        self.toolkit = WorkflowToolkit(workflow_service, llm=self.llm)
        self.tools = self.toolkit.get_tools()

        self.agent = self._create_agent()

    def _create_agent(self):
        system_prompt = """
You are a Senior Jira Automation Expert.
Rules:
- Use tools whenever needed.
- Never hallucinate Jira data.
- Respond in Vietnamese if user uses Vietnamese.
"""
        return create_agent(
            model=self.llm,
            tools=self.tools,
            system_prompt=system_prompt,
        )

    async def run(self, user_input: str):
        """
        Bản stateless: Không giữ chat history.
        """
        return await self.agent.ainvoke({
            "messages": [
                {
                    "role": "user",
                    "content": user_input
                }
            ]
        })
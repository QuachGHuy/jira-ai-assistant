from datetime import datetime

from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage
from langgraph.prebuilt import create_react_agent
from langgraph.checkpoint.memory import MemorySaver

from app.core.config import settings
from app.ai_engine.tools.workflow_tools import WorkflowToolkit
from app.services.workflow_service import WorkflowService


class JiraAgent:
    def __init__(self, workflow_service: WorkflowService):

        self.llm = ChatOpenAI(
            model=settings.ROUTER_CHAT_MODEL,
            base_url=settings.ROUTER_BASE_URL,
            api_key=settings.ROUTER_API_KEY,
            temperature=0,
        )

        self.toolkit = WorkflowToolkit(
            workflow_service,
            llm=self.llm
        )

        self.tools = self.toolkit.get_tools()

        # Memory checkpoint
        self.memory = MemorySaver()

        self.agent = self._create_agent()

    def _create_agent(self):

        now = datetime.now().strftime("%A, %B %d, %Y")

        system_prompt = f"""
            You are an Intelligence Assistant.

            Your role is to assist users in managing,
            analyzing, and reporting Jira tickets.

            # TEMPORAL CONTEXT
            - Today is: {now}

            # SESSION START
            - If this is the FIRST message: Greet user warmly and list available tools

            # TOOL USAGE POLICY
            - SEARCH FIRST: Always search in Knowledge Base.
            - EXPLICIT ONLY: Use tools ONLY when the user asks for data.
            - ERROR REPORTING: Never hallucinate ticket IDs.

            # RESPONSE GUIDELINES
            - STRICT OBEDIENCE: Execute exactly what is asked. 
            - NO CHATTER: Do not ask irrelevant follow-up questions.
            - FORMAT: Use Markdown tables for data.
            - LANGUAGE: Vietnamese if input is Vietnamese.
            """

        return create_react_agent(
            model=self.llm,
            tools=self.tools,
            prompt=system_prompt,
            checkpointer=self.memory,
        )

    async def run(
        self,
        user_input: str,
        thread_id: str = "default_session"
    ):

        config = {
            "configurable": {
                "thread_id": thread_id
            }
        }

        result = await self.agent.ainvoke(
            {
                "messages": [
                    HumanMessage(content=user_input)
                ]
            },
            config=config
        )

        return result["messages"][-1].content
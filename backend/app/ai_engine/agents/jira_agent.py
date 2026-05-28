import inspect
from datetime import datetime
from typing import Any, Dict

from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage
from langchain.agents import create_agent
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.memory import MemorySaver

from app.core.config import settings
from app.ai_engine.tools.workflow_tools import WorkflowToolkit
from app.services.workflow_service import WorkflowService


class JiraAgent:
    """
    Core AI Agent orchestrator for the Jira Intelligence Platform.
    
    Integrates LangChain's conversational agent scaffolding with custom operational 
    toolkits, maintaining transactional state history using local MemorySaver checkpointers.
    Optimized for extended context operations with local Qwen2.5 architectures.
    """

    def __init__(self, workflow_service: WorkflowService) -> None:
        """
        Initializes the intelligence agent with an optimized OpenAI-compatible LLM instance,
        registers system tools, and configures memory state persistent storage.

        Args:
            workflow_service (WorkflowService): Unified service container orchestration.
        """
        # Configure Chat Client with expanded 16K context parameters to accommodate large RAG tables
        self.llm = ChatOpenAI(
            model=settings.LLM_CHAT_MODEL,
            base_url=settings.LLM_BASE_URL,
            api_key=settings.LLM_API_KEY, # Resolved SecretStr type compilation safe
            temperature=0.3,
        )

        # Initialize technical capabilities via the toolkit assembler
        self.toolkit = WorkflowToolkit(
            workflow_service,
            llm=self.llm
        )
        self.tools = self.toolkit.get_tools()

        # Ephemeral memory layer tracking session thread states
        self.memory = MemorySaver()
        self.agent = self._create_agent()

    def _create_agent(self) -> Any:
        """
        Constructs the strict system operational instructions prompt and binds the agent runner.

        Returns:
            Any: Compiled LangChain agent executor instance.
        """
        now = datetime.now().strftime("%A, %B %d, %Y")

        system_prompt = inspect.cleandoc(f"""
            You are an elite Intelligence Assistant specialized in Jira Operations.
            Your role is to assist engineering leads in managing, analyzing, and reporting Jira issues.

            # TEMPORAL CONTEXT
            - Current Date: {now}

            # CONVERSATIONAL LIFECYCLE
            - First Message Only: Warmly greet the user and immediately list out available tools.

            # TOOL USAGE POLICY
            - SEARCH CRITERIA: Prioritize querying the vector store database for semantic info.
            - EXPLICIT CALLS: Invoke system tools ONLY when data extraction is explicitly requested.
            - SYNC REGULATION: Never perform automated hot-sync operations on the Knowledge Base unless commanded.
            - INTEGRITY ENFORCEMENT: Never guess, fake, or hallucinate Ticket IDs or metadata statistics under any condition.

            # CRITICAL RESPONDING MANDATES (VIOLATION IS STRICTLY FORBIDDEN)
            - ZERO CHATTER: Output direct answers immediately. Do NOT include polite fillers, conversational small talk, or concluding questions like "Let me know if you need anything else".
            - ABSOLUTE FORMATTING LAW: You MUST present all structured data, lists of tickets, logs, or metrics using highly readable Markdown TABLES. Do NOT use bullet points or numbered lists for metrics or multiple items.
            - LOCALIZATION: Respond natively in Vietnamese if the prompt or user input is processed in Vietnamese.
            """)

        return create_agent(
            model=self.llm,
            tools=self.tools,
            system_prompt=system_prompt,
            checkpointer=self.memory,
        )

    async def run(self, user_input: str, thread_id: str = "default_session") -> str:
        """
        Executes a single conversational thread turn against the reactive agent executor.

        Args:
            user_input (str): Raw incoming instruction text prompt string.
            thread_id (str): Unique tracking identifier for runtime execution memory state isolation.

        Returns:
            str: Normalized response string extracted cleanly from the final message sequence node.
        """
        config = RunnableConfig(
            configurable={
                "thread_id": thread_id
            }
        )

        # Dispatch execution signal to LangGraph agent engine
        result = await self.agent.ainvoke(
            {
                "messages": [
                    HumanMessage(content=user_input)
                ]
            },
            config=config
        )

        # Safely extract and return the textual response out of the final message object
        final_message = result["messages"][-1]
        return str(final_message.content)
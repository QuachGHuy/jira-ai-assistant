from langchain_core.tools import tool
from app.services.workflow_service import WorkflowService
from typing import Optional, List, Dict, Any
from app.schemas.tool_models import SearchInput, JQLInput, ProjectInput
from app.ai_engine.agents.query_analyzer import QueryAnalyzer



# --- 2. The Toolkit Orchestrator ---

class WorkflowToolkit:
    """
    Standardized toolkit providing AI Agents access to Jira workflows, 
    Knowledge Base (Qdrant), and Dashboard (Google Sheets).
    """
    def __init__(self, workflow_service: WorkflowService, llm):
        self.workflow_service = workflow_service
        self.analyzer = QueryAnalyzer(llm=llm)

    def get_tools(self) -> List:
        """Returns a list of tools ready for the LangChain Agent."""
        
        @tool
        async def search_knowledge_base(query: str, **kwargs) -> str:
            """
            Search for historical issues, solutions, or experts in the Knowledge Base.
            Input: ONLY a natural language question (e.g., 'Find login bugs in project AIO').
            The tool will automatically handle filtering and semantic search.
            """

            structured_data = await self.analyzer.analyze(query)

            results = await self.workflow_service.qdrant.search_similar_issues(
                query_text=structured_data.input,
                filter_obj=structured_data.filter
            )
            
            return f"Found results for '{query}': {str(results)}"

        @tool(args_schema=JQLInput)
        async def automate_assignment() -> str:
            """
            Identify high-priority tickets, recommend assignees via AI, and notify via Slack.
            Can be filtered by a specific JQL.
            """
            stats = await self.workflow_service.auto_issue_assignment(custom_jql=jql)
            return f"Process Finished: {stats.get('notified', 0)} devs notified, {stats.get('skipped', 0)} skipped."
        
        @tool
        async def sync_dashboard() -> str:
            """Updates the Google Sheets project dashboard with latest sprint data."""
            result = await self.workflow_service.sync_gsheet_report()
            return f"Dashboard Sync: {result.get('status', 'success')} (Count: {result.get('synced_count', 0)})"
        
        @tool
        async def sync_knowledge_base() -> str:
            """Syncs Jira issues to Qdrant. Use this to 'train' or 'update' the AI memory."""
            result = await self.workflow_service.sync_jira_to_qdrant(project_key=project_key)
            return f"KB Sync: {result.get('status', 'success')} for project {project_key}."
        
        @tool
        async def sync_status() -> str:
            """Syncs status from Dev tickets (AD) to Management tickets (APG)."""
            result = await self.workflow_service.sync_apg_status_from_ad()
            return f"Status Mirrored: {result.get('synced_count', 0)} tickets updated."

        return [
            search_knowledge_base, 
            automate_assignment, 
            sync_dashboard, 
            sync_knowledge_base, 
            sync_status
        ]
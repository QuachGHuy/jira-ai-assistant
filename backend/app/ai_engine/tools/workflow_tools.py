from langchain_core.tools import tool
from app.services.workflow_service import WorkflowService
from typing import List
from app.ai_engine.agents.query_analyzer import QueryAnalyzer

class WorkflowToolkit:
    """
    Orchestrator class that provides the AI Agent with a set of tools to interact with 
    Jira workflows, Knowledge Base (Qdrant), and Project Dashboards (Google Sheets).
    """
    
    def __init__(self, workflow_service: WorkflowService, llm):
        """
        Initialize the toolkit with required services.
        
        Args:
            workflow_service (WorkflowService): The core service handling business logic.
            llm: The Language Model instance used for query analysis.
        """
        self.workflow_service = workflow_service
        self.analyzer = QueryAnalyzer(llm=llm)

    def get_tools(self) -> List:
        """
        Constructs and returns a list of LangChain-compatible tools.
        
        Returns:
            List: A collection of decorated tool functions.
        """
        
        @tool
        async def search_knowledge_base(query: str) -> str:
            """
            Search the Knowledge Base for historical issues, solutions, or technical experts.
            
            Args:
                query (str): The natural language question or search term.
                
            Returns:
                str: A summary of matching results or an error message.
            """
            try:
                # Extract semantic intent and metadata filters from the raw query
                structured_data = await self.analyzer.analyze(query)
                
                # Perform vector search using the analyzed components
                results = await self.workflow_service.qdrant.search_similar_issues(
                    query_text=structured_data.input,
                    filter_obj=structured_data.filter
                )
                
                if not results:
                    return f"No relevant information found in the Knowledge Base for: '{query}'."
                
                return f"Search results for '{query}': {str(results)}"
            except Exception as e:
                return f"Error during Knowledge Base search: {str(e)}"

        @tool
        async def automate_assignment() -> str:
            """
            Analyze high-priority tickets and recommend/assign developers via AI notifications.
            
            Returns:
                str: Execution summary including notification and skip counts.
            """
            try:
                # Trigger the auto-assignment workflow (uses default JQL settings)
                stats = await self.workflow_service.auto_issue_assignment()
                return (f"Workflow completed: {stats.get('notified', 0)} developers notified, "
                        f"{stats.get('skipped', 0)} tickets skipped.")
            except Exception as e:
                return f"Error during automated assignment: {str(e)}"
        
        @tool
        async def sync_dashboard() -> str:
            """
            Synchronize the Google Sheets dashboard with the latest Jira project data.
            
            Returns:
                str: Status of the synchronization process.
            """
            try:
                result = await self.workflow_service.sync_gsheet_report()
                return f"Dashboard Sync: {result.get('status', 'success')} ({result.get('synced_count', 0)} issues updated)."
            except Exception as e:
                return f"Error during Dashboard synchronization: {str(e)}"
        
        @tool
        async def sync_knowledge_base() -> str:
            """
            Manually trigger a data synchronization from Jira to the Vector Database (Qdrant).
            Only use this when a data refresh is explicitly requested.
            
            Returns:
                str: Confirmation of the sync process.
            """
            try:
                # Performs sync for the default project defined in settings
                result = await self.workflow_service.sync_jira_to_qdrant()
                return f"KB Sync Status: {result.get('status', 'success')}."
            except Exception as e:
                return f"Error during Knowledge Base synchronization: {str(e)}"
        
        @tool
        async def sync_status() -> str:
            """
            Mirror statuses from development tickets (AD) to corresponding management tickets (APG).
            
            Returns:
                str: Count of tickets updated during the mirroring process.
            """
            try:
                result = await self.workflow_service.sync_apg_status_from_ad()
                return f"Status Mirroring: Successfully updated {result.get('synced_count', 0)} management tickets."
            except Exception as e:
                return f"Error during status synchronization: {str(e)}"

        return [
            search_knowledge_base, 
            automate_assignment, 
            sync_dashboard, 
            sync_knowledge_base, 
            sync_status
        ]
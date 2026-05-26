from typing import List, Dict, Any, Optional, Tuple
from atlassian import Jira

from app.core.config import settings
from app.schemas.jira_models import JiraIssue, JiraMetadata
from app.services.text_processor import TextProcessor

class JiraService:
    """
    Service responsible for interacting with Jira Cloud API.
    Handles issue retrieval, data normalization, status transitions, and assignments.
    """

    def __init__(self) -> None:
        """
        Initializes the Jira Cloud client using environment configurations.
        
        Raises:
            Exception: If the connection to Jira Cloud cannot be established.
        """
        try:
            self.jira = Jira(
                url=settings.JIRA_DOMAIN_URL,
                username=settings.JIRA_EMAIL,
                password=settings.JIRA_API_TOKEN.get_secret_value(),
                cloud=True
            )
            self.processor = TextProcessor()
        except Exception as e:
            print(f"❌ Jira connection failed: {str(e)}")
            raise

    def _get_project_name(self, fields: Dict[str, Any]) -> str:
        """
        Extracts the project name based on the parent issue's summary.
        Filters out generic 'Customer Support' labels to return 'Others'.
        
        Args:
            fields (Dict[str, Any]): The fields dictionary from a Jira issue response.

        Returns:
            str: The determined project name or 'Others'.
        """
        parent_summary = fields.get("parent", {}).get("fields", {}).get("summary")
        if parent_summary and parent_summary != "Customer Support":
            return parent_summary
        return "Others"

    def _get_issue_links(self, fields: Dict[str, Any]) -> Tuple[str, str]:
        """
        Parses the outward and inward issue keys from the Jira issue links field.
        
        Args:
            fields (Dict[str, Any]): The fields dictionary from a Jira issue response.

        Returns:
            Tuple[str, str]: A tuple containing (outwardIssueKey, inwardIssueKey).
        """
        links = fields.get("issuelinks", [])
        outward_key = "None"
        inward_key = "None"
        
        if links:
            # Logic: Extract keys from the first available link in the array
            outward_key = links[0].get("outwardIssue", {}).get("key", "None")
            inward_key = links[0].get("inwardIssue", {}).get("key", "None")
            
        return outward_key, inward_key

    async def get_issues_by_jql(self, jql: str) -> List[JiraIssue]:
        """
        Retrieves issues matching a JQL query with full pagination support.
        Processes raw API data into structured JiraIssue objects.
        
        Args:
            jql (str): The Jira Query Language string to execute.

        Returns:
            List[JiraIssue]: A list of cleaned and validated JiraIssue objects.
        """
        all_issues: List[JiraIssue] = []
        next_token: Optional[str] = None
        limit: int = 50

        print(f"🔍 Executing JQL query: {jql}")
        
        try:
            while True:
                # Jira Cloud 'enhanced_jql' supports modern Cursor-based pagination
                response: Optional[Dict[str, Any]] = self.jira.enhanced_jql(
                    jql=jql,
                    limit=limit,
                    nextPageToken=next_token
                )

                if not response:
                    break
                
                issues_batch = response.get("issues", [])
                if not issues_batch:
                    break
                
                print(f"📦 Fetched {len(issues_batch)} items...")
                
                for issue in issues_batch:
                    key = issue.get("key", "")
                    try:
                        fields = issue.get("fields", {})
                        
                        # Extract project and linking metadata
                        project_name = self._get_project_name(fields)
                        outward_key, inward_key = self._get_issue_links(fields)

                        # Construct JiraMetadata using the normalized fields
                        metadata = JiraMetadata(
                            key_link=f"{settings.JIRA_DOMAIN_URL}/browse/{key}",
                            key=key,
                            task_name=fields.get("summary", ""),
                            project=project_name,
                            type=fields.get("issuetype", {}).get("name", ""),
                            assignee=fields.get("assignee", {}).get("displayName", "Unassigned") 
                                     if fields.get("assignee") else "Unassigned",
                            assignee_id=fields.get("assignee", {}).get("accountId") 
                                        if fields.get("assignee") else "None",
                            assignee_email=fields.get("assignee", {}).get("emailAddress") 
                                          if fields.get("assignee") else "None",
                            status=fields.get("status", {}).get("name", ""),
                            priority=fields.get("priority", {}).get("name", ""),
                            created_at=self.processor.format_jira_date(fields.get("created")),
                            outward_issue_key=outward_key,
                            inward_issue_key=inward_key
                        )
                        
                        # Handle potential empty descriptions
                        raw_desc = fields.get("description")
                        if not raw_desc or not str(raw_desc).strip():
                            raw_desc = "No description provided"
                            
                        # Clean text for Vector DB embedding
                        cleaned_desc = self.processor.clean_jira_text(raw_desc)
                        
                        # Aggregate into the final list
                        all_issues.append(JiraIssue(
                            point_id=self.processor.generate_stable_id(key),
                            metadata=metadata,
                            desc=cleaned_desc,
                            content=(
                                f"Project: {metadata.project}\n"
                                f"Task: {metadata.task_name}\n"
                                f"Type: {metadata.type}\n"
                                f"Status: {metadata.status}\n"
                                f"Priority: {metadata.priority}\n"
                                f"Description: {cleaned_desc}\n"
                                f"Assignee: {metadata.assignee}"
                            ),
                            vector_content=(
                                f"Project: {metadata.project}\n"
                                f"Task: {metadata.task_name}\n"
                                f"Description: {cleaned_desc}"
                            ),
                            slack_desc=self.processor.format_for_slack(raw_desc)
                        ))
                    except Exception as item_err:
                        print(f"⚠️ Failed to process issue {key}: {str(item_err)}")
                        continue

                # Pagination: Determine if there is a next page
                next_token = response.get("nextPageToken")
                if not next_token:
                    break
                    
            print(f"✅ Success: Retrieved {len(all_issues)} tickets total.")
            
        except Exception as e:
            print(f"❌ Critical error during Jira API call: {str(e)}")
        
        return all_issues

    async def update_issue_status(self, issue_key: str, status_name_or_id: str) -> Dict[str, Any]:
        """
        Transitions a Jira issue to a new status (e.g., 'READY FOR DEV').
        
        Args:
            issue_key (str): The unique identifier of the issue (e.g., 'APG-123').
            status_name_or_id (str): The name or ID of the destination status.

        Returns:
            Dict[str, Any]: A dictionary containing the operation status and result message.
        """
        try:
            print(f"🔄 Transitioning {issue_key} to status: {status_name_or_id}")
            self.jira.issue_transition(issue_key, status_name_or_id)
            return {
                "status": "success",
                "message": f"Issue {issue_key} transitioned to {status_name_or_id}",
            }
        except Exception as e:
            error_msg = f"Failed to update status for {issue_key}: {str(e)}"
            print(f"❌ {error_msg}")
            return {"status": "error", "message": error_msg}

    async def update_issue_assignee(self, issue_key: str, assignee_id: str) -> Dict[str, Any]:
        """
        Updates the assignee of an issue using their Jira accountId.
        
        Args:
            issue_key (str): The unique identifier of the issue.
            assignee_id (str): The Jira accountId of the user.

        Returns:
            Dict[str, Any]: A confirmation message of the assignment.
        """
        try:
            print(f"👤 Assigning {issue_key} to User ID: {assignee_id}")
            self.jira.assign_issue(issue_key, assignee_id)
            return {
                "status": "success",
                "message": f"Issue {issue_key} successfully assigned",
                "assignee_id": assignee_id
            }
        except Exception as e:
            error_msg = f"Failed to assign user to {issue_key}: {str(e)}"
            print(f"❌ {error_msg}")
            return {"status": "error", "message": error_msg}
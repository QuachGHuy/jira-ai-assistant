from typing import List, Dict, Any, Optional, Tuple
from atlassian import Jira
from app.core.config import settings
from app.schemas.jira_models import JiraIssue, JiraMetadata
from app.services.text_processor import TextProcessor

class JiraService:
    def __init__(self) -> None:
        """
        Initialize the Jira Cloud connection using configuration settings.
        Raises an exception if the connection cannot be established.
        """
        try:
            self.jira = Jira(
                url=settings.JIRA_DOMAIN_URL,
                username=settings.JIRA_EMAIL,
                password=settings.JIRA_API_TOKEN,
                cloud=True
            )
            self.processor = TextProcessor()
        except Exception as e:
            print(f"❌ Jira connection failed: {str(e)}")
            raise

    def _get_project_name(self, fields: Dict[str, Any]) -> str:
        """
        Extract the project name based on the parent issue's summary.
        Filters out 'Customer Support' projects to return 'Others'.
        
        Args:
            fields (Dict): The fields dictionary from a Jira issue.
        Returns:
            str: The project name or 'Others'.
        """
        parent_summary = fields.get("parent", {}).get("fields", {}).get("summary")
        if parent_summary and parent_summary != "Customer Support":
            return parent_summary
        return "Others"

    def _get_issue_links(self, fields: Dict[str, Any]) -> Tuple[str, str]:
        """
        Extract outward and inward issue keys from issue links.
        
        Args:
            fields (Dict): The fields dictionary from a Jira issue.
        Returns:
            Tuple[str, str]: A tuple containing (outwardIssueKey, inwardIssueKey).
        """
        links = fields.get("issuelinks", [])
        outward_key = "None"
        inward_key = "None"
        
        if links:
            # Extract keys from the first link in the list
            outward_key = links[0].get("outwardIssue", {}).get("key", "None")
            inward_key = links[0].get("inwardIssue", {}).get("key", "None")
            
        return outward_key, inward_key

    async def get_issues_by_jql(self, jql: str) -> List[JiraIssue]:
        """
        Fetch all Jira issues matching a JQL query with pagination support.
        Processes and cleans issue data into a structured JiraIssue format.
        
        Args:
            jql (str): The Jira Query Language string.
        Returns:
            List[JiraIssue]: A list of validated JiraIssue objects.
        """
        all_issues: List[JiraIssue] = []
        next_token: Optional[str] = None
        limit: int = 50

        print(f"🔍 Executing JQL query: {jql}")
        
        try:
            while True:
                # Use enhanced_jql for better performance and Cursor-based pagination
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
                        
                        # Use private methods to extract project and linked issues
                        project_name = self._get_project_name(fields)
                        outward_key, inward_key = self._get_issue_links(fields)

                        # Map Jira fields to JiraMetadata schema using aliases
                        metadata = JiraMetadata(
                            keyLink=f"{settings.JIRA_DOMAIN_URL}/browse/{key}",
                            key=key,
                            taskName=fields.get("summary", ""),
                            project=project_name,
                            type=fields.get("issuetype", {}).get("name", ""),
                            assignee=fields.get("assignee", {}).get("emailAddress", "Unassigned") if fields.get("assignee") else "Unassigned",
                            assigneeId=fields.get("assignee", {}).get("accountId") if fields.get("assignee") else "None",
                            status=fields.get("status", {}).get("name", ""),
                            priority=fields.get("priority", {}).get("name", ""),
                            createdAt=fields.get("created"),
                            outwardIssueKey=outward_key,
                            inwardIssueKey=inward_key
                        )
                        
                        raw_desc = fields.get("description")
                        if not raw_desc or not str(raw_desc).strip():
                            raw_desc = "No description provided"
                            
                        # Prepare content for Vector DB and Slack notifications
                        raw_desc = fields.get("description", "")
                        all_issues.append(JiraIssue(
                            pointId=self.processor.generate_stable_id(key),
                            metadata=metadata,
                            vectorContent=f"Project: {metadata.project}\nTask: {metadata.task_name}\nDescription: {self.processor.clean_jira_text(raw_desc)}",
                            slackDesc=self.processor.format_for_slack(raw_desc)
                        ))
                    except Exception as item_err:
                        print(f"⚠️ Failed to process issue {key}: {str(item_err)}")
                        continue

                # Check for the next page token to continue pagination
                next_token = response.get("nextPageToken")
                if not next_token:
                    break
                    
            print(f"✅ Success: Retrieved {len(all_issues)} tickets total.")
            
        except Exception as e:
            print(f"❌ Critical error during Jira API call: {str(e)}")
        
        return all_issues

    async def update_issue_status(self, issue_key: str, status_name_or_id: str) -> Dict[str, Any]:
        """
        Transition a Jira issue to a new status.
        
        Args:
            issue_key (str): The key of the issue to update.
            status_name_or_id (str): The name or ID of the target status.
        Returns:
            Dict: Status message and raw response data.
        """
        try:
            print(f"🔄 Transitioning {issue_key} to status: {status_name_or_id}")
            result = self.jira.issue_transition(issue_key, status_name_or_id)
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
        Assign an issue to a specific user using their accountId.
        
        Args:
            issue_key (str): The key of the issue to update.
            assignee_id (str): The Jira accountId of the new assignee.
        Returns:
            Dict: Status message confirmed via HTTP 204 handler.
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
import json
import traceback
from typing import Dict, Any, Optional, List

from app.services.jira_service import JiraService
from app.services.slack_service import SlackService
from app.services.googlesheet_service import GoogleSheetService
from app.services.qdrant_service import QdrantService
from app.services.voting_service import VotingService
from app.core.config import settings

class WorkflowService:
    """
    The Central Orchestrator for Jira-AI operations.
    Now enhanced with Dynamic JQL support to act as a foundation for 
    LangChain Tools and automated workers.
    """

    def __init__(
        self, 
        jira: JiraService, 
        slack: SlackService, 
        qdrant: QdrantService,
        gsheet: GoogleSheetService,
        voting: VotingService
    ):
        """
        Initializes the service with core integration components.
        """
        self.jira = jira
        self.slack = slack
        self.qdrant = qdrant
        self.voting = voting
        self.gsheet = gsheet
    
    async def sync_gsheet_report(
        self, 
        custom_jql: Optional[str] = None, 
        sprint_metadata: Optional[Dict[str, str]] = None
    ) -> Dict[str, Any]:
        """
        Synchronizes Jira issues to the Google Sheets Dashboard.
        Useful for real-time sprint tracking and management reporting.
        
        Args:
            custom_jql (Optional[str]): Custom filter for issues. 
                Defaults to active sprint issues.
            sprint_metadata (Optional[Dict]): Sprint name and date range.
            
        Returns:
            Dict[str, Any]: Status and sync count.
        """
        print("📊 Starting Google Sheets Dashboard Sync...")
        
        try:
            # 1. Determine JQL and Metadata
            # Default logic targets the currently open sprint
            jql = custom_jql or "project = 'AIO Development' AND sprint in openSprints()"
            
            # Fallback metadata if not provided by the caller (Agent or Scheduler)
            metadata = sprint_metadata or {
                "name": "Current Active Sprint",
                "start_date": "2026-05-01",
                "end_date": "2026-05-15"
            }

            # 2. Fetch data from Jira
            issues = await self.jira.get_issues_by_jql(jql)
            
            if not issues:
                return {"status": "warning", "message": "No issues found for the current filter."}

            # 3. Perform the In-place Upsert on Google Sheets
            
            await self.gsheet.sync_dashboard_upsert(metadata, issues)
            
            print(f"✅ GSheet Sync Complete: {len(issues)} issues processed.")
            return {"status": "success", "synced_count": len(issues)}
            
        except Exception as e:
            print(f"❌ GSheet Sync Failed: {str(e)}")
            traceback.print_exc()
            return {"status": "error", "message": str(e)}
        
    async def sync_jira_to_qdrant(self, project_key: str = "AIO Development") -> Dict[str, Any]:
        """
        Synchronizes issues from a specific Jira project to the Qdrant vector database.
        This builds the knowledge base for AI similarity searches.
        
        Args:
            project_key (str): The Jira project key to sync.
            
        Returns:
            Dict[str, Any]: Synchronization report from QdrantService.
        """
        print(f"📥 Starting Knowledge Base Sync for project: {project_key}")
        
        # 1. Fetch all relevant issues from the project
        jql = f'project = "{project_key}"'
        issues = await self.jira.get_issues_by_jql(jql)
        
        if not issues:
            return {"status": "warning", "message": f"No issues found for project {project_key}"}

        # 2. Vectorize and Upsert to Qdrant
        result = await self.qdrant.upsert_batch_to_qdrant(issues)
        
        print(f"✅ Qdrant Sync Complete: {result.get('synced', 0)} issues updated.")

        return result
    
    async def auto_issue_assignment(self, custom_jql: Optional[str] = None) -> Dict[str, int]:
        """
        Identifies issues and dispatches AI-driven assignee recommendations.
        Supports dynamic JQL to allow AI Agents to scan specific projects or filters.
        
        Args:
            custom_jql (Optional[str]): A specific JQL query. 
                Defaults to 'project = "APG" AND status = "TO DO"' if None.

        Returns:
            Dict[str, int]: Statistics of the workflow run (notified vs skipped).
        """
        # Logic: Use the provided JQL (from an Agent) or fallback to the system default
        jql_query = custom_jql or 'project = "APG" AND status = "TO DO"'
        
        print(f"🤖 Starting AI Assignment Workflow with JQL: {jql_query}")
        
        # 1. Fetch tickets based on the dynamic query
        target_issues = await self.jira.get_issues_by_jql(jql_query)
        
        stats = {"notified": 0, "skipped": 0}
        if not target_issues:
            print("ℹ️ Workflow: No issues matched the query.")
            return stats

        for issue in target_issues:
            issue_key = issue.metadata.key
            
            # 2. Gatekeeper: Check notification history to prevent spam
            if await self.qdrant.check_already_notified(issue_key):
                stats["skipped"] += 1
                continue

            try:
                # 3. AI Research: Find similar historical context in Qdrant
                similarity_results = await self.qdrant.search_similar_issues(
                    query_text=issue.vector_content
                )

                # 4. Intelligence: Perform weighted voting to select the best dev
                decision = await self.voting.get_voting_decision(similarity_results)

                # 5. Data Mapping: Merge AI insights into the issue model
                issue_dict = issue.model_dump()
                issue_dict["metadata"].update({
                    "assignee": decision.recommended_assignee,
                    "assignee_email": decision.assignee_email,
                    "assignee_id": decision.assignee_id,
                    "confidence_score": decision.confidence_score
                })
                
                print(f"🔍 AI Recommendation for {issue_key}: {decision.recommended_assignee} with confidence {decision.confidence_score}")
                # 6. Interaction: Dispatch to Slack for human approval
                success_ts = await self.slack.send_ticket_notification(issue_dict)
                
                if success_ts:
                    await self.qdrant.mark_as_notified(issue_key)
                    stats["notified"] += 1
                    print(f"✅ Notification dispatched for {issue_key}")

            except Exception as e:
                print(f"⚠️ Failed to process issue {issue_key}: {str(e)}")
                traceback.print_exc()

        return stats

    async def sync_apg_status_from_ad(self, custom_jql: Optional[str] = None) -> Dict[str, Any]:
        """
        Synchronizes status between development (AD) and management (APG) tickets.
        Accepts dynamic JQL to allow flexibility in sync timeframes or projects.

        Args:
            custom_jql (Optional[str]): Query to find 'Done' development tickets.
                Defaults to recently updated AD tickets in 'Done' status.

        Returns:
            Dict[str, Any]: Telemetry report of the synchronization process.
        """
        # Default JQL focuses on performance by only checking recently updated tickets
        ad_jql = custom_jql or 'project = "AIO Development" AND status = "Done" AND updated >= -1d'
        
        print(f"🔄 Executing Status Sync with JQL: {ad_jql}")
        done_ad_issues = await self.jira.get_issues_by_jql(ad_jql)
        
        report = {
            "total_ad_found": len(done_ad_issues),
            "synced_count": 0,
            "details": []
        }

        if not done_ad_issues:
            return report

        for ad_issue in done_ad_issues:
            ad_key = ad_issue.metadata.key
            apg_key = ad_issue.metadata.inward_issue_key
            
            sync_entry = {"ad_key": ad_key, "apg_key": apg_key, "status": "pending", "message": ""}

            # Validation: Check for valid APG link
            if not apg_key or apg_key == "None" or not apg_key.startswith("APG"):
                sync_entry.update({"status": "ignored", "message": "No valid APG link found."})
                report["details"].append(sync_entry)
                continue

            # State check for the target APG ticket
            apg_search = await self.jira.get_issues_by_jql(f'key = "{apg_key}"')
            if not apg_search:
                sync_entry.update({"status": "error", "message": "Linked APG ticket not found."})
                report["details"].append(sync_entry)
                continue
            
            apg_issue = apg_search[0]
            
            # Transition APG if it is not already 'Done'
            if apg_issue.metadata.status.upper() != "DONE":
                print(f"⚙️ Syncing: {ad_key} -> {apg_key} (Moving to Done)")
                update_result = await self.jira.update_issue_status(apg_key, "Done")
                
                if update_result.get("status") == "success":
                    sync_entry.update({"status": "synced", "message": "Transitioned to Done."})
                    report["synced_count"] += 1
                else:
                    sync_entry.update({"status": "failed", "message": update_result.get("message")})
            else:
                sync_entry.update({"status": "skipped", "message": "APG already in Done status."})

            report["details"].append(sync_entry)

        return report

    async def handle_slack_interaction(self, payload: Dict[str, Any]):
        """
        Processes real-time user decisions from Slack buttons.
        Updates Jira tickets and provides feedback to the user.
        """
        try:
            # Data Extraction from Slack payload
            action_data = payload["actions"][0]
            parts = action_data["value"].split("|")
            
            action_type, apg_key, assignee_email, assignee_id, ticket_link = parts
            user_mention = f"<@{payload['user']['id']}>"
            channel, ts = payload["channel"]["id"], payload["container"]["message_ts"]

            if action_type == "approve":
                # Step A: Update Management Ticket
                await self.jira.update_issue_status(apg_key, "READY FOR DEV")

                # Step B: Link AD Development Ticket
                ad_jql = f'project = "AIO Development" AND linkedIssue = "{apg_key}"'

                # --- Polling Logic: Wait for Jira Automation to clone APG to AD ticket ---
                # Automation in Jira is asynchronous and may take a few seconds to create the linked AD task.
                # We poll every 2 seconds (up to 5 times) to handle this race condition.
                ad_issues = []
                max_retries = 5

                for attempt in range(max_retries):
                    print(f"🔍 [Attempt {attempt + 1}] Searching for AD task linked to {apg_key}...")
                    
                    ad_jql = f'project = "AIO Development" AND linkedIssue = "{apg_key}"'
                    ad_issues = await self.jira.get_issues_by_jql(ad_jql)
                    
                    if ad_issues:
                        print(f"✅ Linked AD task found: {ad_issues[0].metadata.key}")
                        break
                    
                    # Wait 2s before the next check, totaling up to 10s if needed
                    await asyncio.sleep(2)

                if ad_issues:
                    ad_key = ad_issues[0].metadata.key
                    # Step C: Assign Developer to AD Ticket
                    await self.jira.update_issue_assignee(ad_key, assignee_id)
                    status_msg = (
                        f"✅ *Approved*: <{ticket_link}|{apg_key}> updated.\n"
                        f"Dev task <{settings.JIRA_DOMAIN_URL}/browse/{ad_key}|{ad_key}> "
                        f"assigned to *{assignee_email}* by {user_mention}."
                    )
                else:
                    status_msg = f"✅ *Approved*: {apg_key} updated, but no AD link found."
            else:
                status_msg = f"❌ *Declined*: Suggestion for <{ticket_link}|{apg_key}> rejected by {user_mention}."

            # Update the Slack message to confirm the action
            await self.slack.update_message(channel, ts, status_msg)

        except Exception as e:
            print(f"🔥 Interaction Error: {str(e)}")
            traceback.print_exc()
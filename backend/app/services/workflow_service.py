import json
import asyncio
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
    Enforces a strict standardized output contract across all runtime operational matrices.
    """

    def __init__(
        self, 
        jira: JiraService, 
        slack: SlackService, 
        qdrant: QdrantService,
        gsheet: GoogleSheetService,
        voting: VotingService
    ):
        self.jira = jira
        self.slack = slack
        self.qdrant = qdrant
        self.voting = voting
        self.gsheet = gsheet
    
    async def sync_gsheet_report(self, sprint_metadata: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
        """Maps active Jira issues to the Google Sheets Dashboard."""
        try:
            jql = "project = 'AIO Development' AND sprint in openSprints()"
            metadata = sprint_metadata or {
                "name": "Current Active Sprint",
                "start_date": "2026-05-01",
                "end_date": "2026-05-15"
            }

            issues = await self.jira.get_issues_by_jql(jql)
            if not issues:
                return {"status": "warning", "metrics": {"processed_transactions": 0}, "message": "No issues found."}

            await self.gsheet.sync_dashboard_upsert(issues, metadata)
            return {"status": "success", "metrics": {"processed_transactions": len(issues)}}
            
        except Exception as e:
            return {"status": "error", "metrics": {}, "message": f"GSheet Sync Failed: {str(e)}"}
        
    async def sync_jira_to_qdrant(self, custom_jql: Optional[str] = None) -> Dict[str, Any]:
        """Synchronizes targeted Jira issues to the Qdrant Knowledge Base Cluster."""
        try:
            jql = custom_jql if custom_jql else 'project = "AIO Development"'
            issues = await self.jira.get_issues_by_jql(jql)
            
            if not issues:
                return {"status": "warning", "metrics": {"vector_updates_mapped": 0}, "message": "No issues extracted."}

            result = await self.qdrant.upsert_batch_to_qdrant(issues)
            return {"status": "success", "metrics": {"vector_updates_mapped": result.get("synced", 0)}}
        
        except Exception as e:
            return {"status": "error", "metrics": {}, "message": f"Qdrant Sync Failed: {str(e)}"}
    
    async def auto_issue_assignment(self, custom_jql: Optional[str] = None) -> Dict[str, Any]:
        """Processes AI-driven assignee allocation routines and issues Slack direct notifications."""
        try:
            jql_query = custom_jql if custom_jql else 'project = "APG" AND status = "TO DO"'
            target_issues = await self.jira.get_issues_by_jql(jql_query)
            
            metrics = {"developers_notified": 0, "tickets_skipped": 0}
            if not target_issues:
                return {"status": "warning", "metrics": metrics, "message": "Empty issue array."}

            for issue in target_issues:
                issue_key = issue.metadata.key
                
                if await self.qdrant.check_already_notified(issue_key):
                    metrics["tickets_skipped"] += 1
                    continue

                # Execute RAG knowledge base similarity search matching
                similarity_results = await self.qdrant.search_similar_issues(
                    query_text=issue.vector_content, limit=20, score_threshold=0.62
                )
                decision = await self.voting.get_voting_decision(similarity_results)

                # Merge parameters into model layer
                issue_dict = issue.model_dump()
                issue_dict["metadata"].update({
                    "assignee": decision.recommended_assignee,
                    "assignee_email": decision.assignee_email,
                    "assignee_id": decision.assignee_id,
                    "confidence_score": decision.confidence_score
                })
                
                success_ts = await self.slack.send_ticket_notification(issue_dict)
                if success_ts:
                    await self.qdrant.mark_as_notified(issue_key)
                    metrics["developers_notified"] += 1

            return {"status": "success", "metrics": metrics}
        
        except Exception as e:
            return {"status": "error", "metrics": {}, "message": f"Auto-Assignment Block Failed: {str(e)}"}

    async def sync_apg_status_from_ad(self, custom_jql: Optional[str] = None) -> Dict[str, Any]:
        """Aligns lifecycle statuses between implementation and management tickets."""
        try:
            ad_jql = custom_jql if custom_jql else 'project = "AIO Development" AND status = "Done"'
            done_ad_issues = await self.jira.get_issues_by_jql(ad_jql)
            
            metrics = {"total_ad_found": len(done_ad_issues), "synced_count": 0}
            if not done_ad_issues:
                return {"status": "warning", "metrics": metrics, "message": "No sync targets found."}

            for ad_issue in done_ad_issues:
                apg_key = ad_issue.metadata.inward_issue_key
                
                if not apg_key or apg_key == "None" or not apg_key.startswith("APG"):
                    continue

                apg_search = await self.jira.get_issues_by_jql(f'key = "{apg_key}"')
                if not apg_search:
                    continue
                
                if apg_search[0].metadata.status.upper() != "DONE":
                    update_result = await self.jira.update_issue_status(apg_key, "Done")
                    if update_result.get("status") == "success":
                        metrics["synced_count"] += 1

            return {"status": "success", "metrics": metrics}
        
        except Exception as e:
            return {"status": "error", "metrics": {}, "message": f"Status Sync Interrupted: {str(e)}"}

    async def handle_slack_interaction(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Handles synchronous webhook user button confirmations routed from Slack blocks."""
        try:
            action_data = payload["actions"][0]
            parts = [p.strip() for p in action_data["value"].split("|")]
            action_type, apg_key, assignee_email, assignee_id, ticket_link = parts
            
            user_mention = f"<@{payload['user']['id']}>"
            channel, ts = payload["channel"]["id"], payload["container"]["message_ts"]

            if action_type == "approve":
                await self.jira.update_issue_status(apg_key, "READY FOR DEV")
                
                ad_issues = None
                for _ in range(3):
                    await asyncio.sleep(10)  # Safe backoff interval window for Jira Automation triggers
                    ad_jql = f'project = "AIO Development" AND issueLink="{apg_key}" ORDER BY created DESC'
                    ad_issues = await self.jira.get_issues_by_jql(ad_jql)
                    if ad_issues:
                        break
                    
                if ad_issues:
                    ad_key = ad_issues[0].metadata.key
                    await self.jira.update_issue_assignee(ad_key, assignee_id)
                    status_msg = f"✅ *Approved*: <{ticket_link}|{apg_key}> allocated to Dev task <{settings.JIRA_DOMAIN_URL}/browse/{ad_key}|{ad_key}> by {user_mention}."
                else:
                    status_msg = f"✅ *Approved*: {apg_key} status updated, but race condition met for AD cloning."
            else:
                status_msg = f"❌ *Declined*: Recommendation query for <{ticket_link}|{apg_key}> dropped by {user_mention}."

            await self.slack.update_message(channel, ts, status_msg)

            return {"status": "success", "metrics": {"interaction_processed": 1}}
            
        except Exception as e:
            return {"status": "error", "metrics": {}, "message": f"Interaction Handler Crashed: {str(e)}"}
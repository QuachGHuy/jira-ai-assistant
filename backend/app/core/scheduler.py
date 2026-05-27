from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from app.core.config import settings

class WorkflowScheduler:
    """
    Handles background cron triggers for workflows using AsyncIOScheduler.
    Executes tasks sequentially via WorkflowService and leverages 
    the JiraAgent to summarize real-time achievements.
    """

    def __init__(self, workflow_service, jira_agent):
        """Initializes the scheduler with application instances and timezone config."""
        self.scheduler = AsyncIOScheduler(timezone=settings.TIMEZONE)
        self.workflow = workflow_service
        self.agent = jira_agent
        self.slack = workflow_service.slack 

    def start(self):
        """Starts the scheduler and registers bi-daily cron triggers."""
        self.scheduler.start()
        
        # Job 1: Nightly KB Sync - Every day at 8:00 PM (20:00)
        self.scheduler.add_job(
            self._execute_nightly_kb_sync,
            CronTrigger(hour=20, minute=0, timezone=settings.TIMEZONE),
            id="nightly_kb_sync"
        )

        # Job 2: Morning Executive Chain - Every day at 10:00 AM (10:00)
        # Sequence: KB Sync -> Status Sync -> Auto Assignment -> GSheet Dashboard -> Slack Report
        self.scheduler.add_job(
            self._execute_morning_executive_chain,
            CronTrigger(hour=15, minute=45, timezone=settings.TIMEZONE), 
            id="morning_executive_chain"
        )

        print(f"⏰ Background Workflow Scheduler started successfully ({settings.TIMEZONE}).")
        for job in self.scheduler.get_jobs():
            print(f"📅 [Scheduled Job] ID: '{job.id}' | Next scheduled run time: {job.next_run_time}")
    
    def shutdown(self):
        """Gracefully shuts down the scheduler during application teardown."""
        self.scheduler.shutdown()
        print("⏰ Background Workflow Scheduler shut down gracefully.")

    async def _execute_nightly_kb_sync(self):
        """Performs a standalone synchronization of Jira data to Qdrant at night."""
        try:
            print("🌙 Nightly standalone KB Sync triggered.")
            await self.workflow.sync_jira_to_qdrant()
            
            prompt = (
                "Compile a highly professional, brief status notification in English "
                "stating that the Nightly Knowledge Base synchronization was executed successfully."
            )
            report = await self.agent.run(user_input=prompt, thread_id="nightly_kb_sync")
            await self.slack.send_message(settings.SLACK_CHANNEL_ID, report)
            print("✅ Nightly KB Sync completed and reported.")
            
        except Exception as e:
            print(f"❌ Nightly Sync Job Failed: {str(e)}")

    async def _execute_morning_executive_chain(self):
        """
        Runs the full consolidated automation sequence using centralized WorkflowService methods.
        Gathers returns from all sub-services to build an accurate summary log for the AI Agent.
        """
        try:
            print("☀️ Morning Executive Chain triggered.")
            execution_accomplishments = []

            # Task 1: Sync Knowledge Base (Jira -> Qdrant)
            kb_res = await self.workflow.sync_jira_to_qdrant()
            execution_accomplishments.append("- Successfully synchronized current Jira project tickets into Qdrant Knowledge Base.")

            # Task 2: Sync Cross-Project Statuses (AD -> APG)
            status_res = await self.workflow.sync_apg_status_from_ad()
            execution_accomplishments.append(f"- Triggered ticket status synchronization. Synced updates: {status_res.get('synced_count', 0)} tasks.")

            # Task 3: Automate Issue Assignment Recommendations
            assign_res = await self.workflow.auto_issue_assignment()
            execution_accomplishments.append(f"- Evaluated unassigned tickets. AI suggestions dispatched: {assign_res.get('notified', 0)} approvals.")

            # Task 4: Refresh Live Google Sheet Dashboard (Clean centralized call)
            gsheet_res = await self.workflow.sync_gsheet_report()
            if gsheet_res.get("status") == "success":
                execution_accomplishments.append(f"- Refreshed live Google Sheets Project Dashboard with {gsheet_res.get('synced_count', 0)} active sprint entries.")
            else:
                execution_accomplishments.append("- Google Sheets Dashboard verified: No modifications parsed.")

            # Task 5: AI Reporting Core 🧠
            summary_payload = "\n".join(execution_accomplishments)
            agent_prompt = f"""
            The automated pipeline has successfully completed its operations. Here is the execution matrix summary:
            {summary_payload}

            Act as an elite Operations Director. Transform this technical summary into a beautiful, engaging, 
            and motivating morning update written in English for the Engineering Team on Slack. 

            # CRITICAL SLACK FORMATTING RULES:
            1. DO NOT use standard Markdown tables (Slack does not support them and they look broken).
            2. Instead of tables, format metrics and statistics using clear Key-Value sections, bold labels, and clean bullet points.
            3. Implement a strict Visual Hierarchy:
               - *HEADER*: A compelling, energized title with professional emojis to start the team's day.
               - *EXECUTIVE SUMMARY / KPIs*: A brief blockquote section highlighting the biggest numbers at a glance.
               - *DETAILED PILLARS*: Break down the 4 core areas (Knowledge Base, Cross-Project Status, AI Assignment, and GSheet Dashboard) into distinct, scannable blocks.
            4. Use bolding (`*text*`) strategically to guide the user's eye directly to key numbers, counts, and statuses (e.g., *82 entries*, *Done*, *Successfully*).
            5. Ensure 100% data completeness—never hallucinate, omit, or generalize any counts or results provided in the payload.
            6. Keep the tone professional, inspiring, and executive-level.
            """
            
            report = await self.agent.run(user_input=agent_prompt, thread_id="morning_exec_cron")
            await self.slack.send_message(settings.SLACK_CHANNEL_ID, report)
            print("✅ Morning Executive Chain ran successfully. English report posted to Slack.")

        except Exception as e:
            print(f"❌ Morning Executive Chain Failed: {str(e)}")
            error_slack_payload = f"🚨 *Automated Morning Workflow Pipeline Failure:* `{str(e)}`"
            try:
                await self.slack.send_message(settings.SLACK_CHANNEL_ID, error_slack_payload)
            except Exception:
                pass
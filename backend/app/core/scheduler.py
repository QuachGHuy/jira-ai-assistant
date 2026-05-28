import inspect

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from app.core.config import settings
from app.services.jobs_service import JobsService, JobConfig


class WorkflowScheduler:
    """
    Dynamic background automation engine powered natively by AsyncIOScheduler.
    
    Fetches active job metadata records stored on Qdrant Cloud via JobsService,
    flushes the in-memory schedule registry safely, and dispatches workflow methods
    asynchronously inside the primary FastAPI event loop without blocking or spawning OS threads.
    """

    def __init__(self, workflow_service, jira_agent, jobs_service: JobsService) -> None:
        """
        Initializes the dynamic operations scheduler with robust async failure-tolerance configs.
        """
        job_defaults = {
            "coalesce": False,
            "max_instances": 3,
            "misfire_grace_time": 60 
        }

        self.scheduler = AsyncIOScheduler(
            timezone=settings.TIMEZONE,
            job_defaults=job_defaults
        )
        self.workflow = workflow_service
        self.agent = jira_agent
        self.slack = workflow_service.slack
        self.jobs_service = jobs_service

    def start(self) -> None:
        """
        Activates the background scheduler thread pool daemon.
        """
        self.scheduler.start()
        print(f"⏰ Dynamic Core Async Scheduler activated successfully ({settings.TIMEZONE}).")

    def shutdown(self) -> None:
        """
        Gracefully releases background resources during application teardown.
        """
        self.scheduler.shutdown()
        print("⏰ Background Workflow Scheduler shut down gracefully.")

    async def reload_jobs_from_qdrant(self) -> None:
        """
        Wipes out all scheduled triggers inside the in-memory execution pool
        and rebuilds them sequentially using active records in Qdrant Cloud.
        Pure async implementation prevents startup deadlock.
        """
        try:
            # 1. Flush memory queue to prevent duplicate stale executors
            for job in self.scheduler.get_jobs():
                self.scheduler.remove_job(job.id)
            print("♻️ Flushed memory execution registry. Re-polling configs from Qdrant Cloud...")

            # 2. Pull active scheduling configurations natively using await
            active_jobs = await self.jobs_service.get_all_configs()

            if not active_jobs:
                print("ℹ️ No active cron configurations mapped in database.")
                return

            # 3. Rebuild in-memory APScheduler triggers
            for job_config in active_jobs:
                sched = job_config.scheduler
                
                # Resolve day_of_week mapping: 7 or None translates to every day (*)
                day_param = "*"
                if sched.day_of_week is not None and sched.day_of_week != 7:
                    day_param = str(sched.day_of_week)

                self.scheduler.add_job(
                    self._execute_dynamic_dispatch,
                    CronTrigger(
                        day_of_week=day_param,
                        hour=sched.hour,
                        minute=sched.minute,
                        timezone=settings.TIMEZONE
                    ),
                    id=job_config.id,
                    args=[job_config]
                )
                print(f"📅 [Registered Trigger] ID: '{job_config.id}' | Task: '{job_config.name}' set for {sched.hour:02d}:{sched.minute:02d} (Days: {day_param})")

        except Exception as e:
            print(f"❌ Failed executing dynamic scheduler hot-reload matrix: {e}")

    async def _execute_dynamic_dispatch(self, job_config: JobConfig) -> None:
        """
        Locates functions inside WorkflowService dynamically using reflection,
        passes JQL query parameters safely based on compatibility, and triggers AI reporting.

        Args:
            job_config (JobConfig): The targeted configuration model.
        """
        job_function_name = job_config.name
        resolved_jql = job_config.custom_jql if job_config.custom_jql else job_config.default_jql

        print(f"⚡ Cron Trigger Fired: Invoking '{job_function_name}' via primary Event Loop...")

        try:
            # 1. Verify existence of the targeted execution method
            if not hasattr(self.workflow, job_function_name):
                print(f"❌ Dispatch Error: Method '{job_function_name}' is not registered inside WorkflowService.")
                return

            target_function = getattr(self.workflow, job_function_name)

            # 2. Reflect on function signature to pass custom JQL arguments safely
            sig = inspect.signature(target_function)
            kwargs = {}
            if "custom_jql" in sig.parameters:
                kwargs["custom_jql"] = resolved_jql

            # 3. Trigger asynchronous workflow execution natively
            result = await target_function(**kwargs)

            # 4. Parse telemetry results to build detailed log logs for the LLM Report
            accomplished_text = f"- Executed background method `{job_function_name}` successfully using filters: `{resolved_jql}`."
            if isinstance(result, dict):
                if "synced_count" in result:
                    accomplished_text += f" Processed transactions: {result['synced_count']} items."
                elif "synced" in result:
                    accomplished_text += f" Vector updates mapped: {result['synced']} entries."

            # 5. Delegate report summarization to the AI Agent (Cloud API Powered with precise visual rules)
            agent_prompt = inspect.cleandoc(f"""
                You are an elite Operations Director composing a real-time Slack status update for the Engineering Team.
                Generate a highly structured, scannable update based strictly on the context and structural templates below.

                # EXECUTION CONTEXT
                - Background Task Name: {job_function_name}
                - Filter Used: {resolved_jql}
                - Raw Telemetry Results: {accomplished_text}

                # SLACK OUTPUT ARCHITECTURE (MANDATORY STRUCTURE)
                You MUST follow this exact four-line visual layout using standard Slack Markdown. Do NOT add conversational intro fillers, chatty greetings, or preambles:
                
                Line 1 (Status Header): Use a green check emoji (e.g., ✅), followed by a bold short completion label (e.g., **Sync Complete** or **Mirroring Successful**), followed by a brief summary of the pipeline execution.
                Line 2 (Filter Details): Use a wrench emoji (🔧) followed by "Filter: " and wrap the exact JQL filter used inside inline code backticks (e.g., `project = 'AIO Development' AND created >= -8h`).
                Line 3 (Metrics Details): Use a bar chart emoji (📊) followed by the specific transaction metric, ensuring all numbers/counts are wrapped inside bold brackets (e.g., Vector updates mapped: **1 entry** or Processed transactions: **12 items**).
                Line 4 (Team Closing): Use a rocket emoji (🚀) followed by an encouraging, professional wrap-up phrase (e.g., "Great work, team!" or "Let's keep the momentum going!").

                # REFERENCE TEMPLATE:
                ✅ **Sync Complete** – Jira → Qdrant pipeline ran successfully!
                🔧 Filter: `project = 'AIO Development' AND created >= -8h`
                📊 Vector updates mapped: **1 entry**
                🚀 Great work, team!
            """)
            report = await self.agent.run(user_input=agent_prompt, thread_id=f"cron_{job_config.id}")
            await self.slack.send_message(settings.SLACK_CHANNEL_ID, report)
            print(f"✅ Executed dynamic wrapper for '{job_function_name}' and dispatched reports.")

        except Exception as e:
            print(f"❌ Failure executing core task execution block for '{job_function_name}': {e}")
            error_slack_payload = f"🚨 *Automated Task Failure in Pipeline:* Method `{job_function_name}` aborted execution with details: `{str(e)}`"
            try:
                await self.slack.send_message(settings.SLACK_CHANNEL_ID, error_slack_payload)
            except Exception:
                pass
import gspread
import traceback
import asyncio
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Any, Optional
from google.oauth2.service_account import Credentials
from gspread.utils import ValueInputOption

from app.core.config import settings

class GoogleSheetService:
    """
    Service responsible for maintaining a real-time Project Dashboard on Google Sheets.
    Preserves built-in cell formulas while automating Sprint metadata generation.
    """

    def __init__(self) -> None:
        """Initializes the Google Sheets client using Service Account credentials."""
        scopes = [
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive"
        ]
        self.creds = Credentials.from_service_account_file(
            "service_account.json", 
            scopes=scopes
        )
        self.client = gspread.authorize(self.creds)
        self.sheet_id = settings.GOOGLE_SHEET_ID
        self.sheet_name = settings.GOOGLE_SHEET_NAME

    def _get_worksheet(self, name: str) -> gspread.Worksheet:
        """Opens the spreadsheet by ID and returns the requested worksheet."""
        spreadsheet = self.client.open_by_key(self.sheet_id)
        return spreadsheet.worksheet(name)

    def _calculate_current_sprint(self) -> Dict[str, str]:
        """
        Automatically calculates the current active Sprint context based on a 2-week cycle.
        Uses a bi-weekly cadence anchored to a known historical Thursday start date (Jan 8, 2026).
        
        Returns:
            Dict[str, str]: Derived metadata containing sprint name, start, and end dates.
        """
        # Historical Anchor Date: Thursday, Jan 8, 2026 to align with bi-weekly Thursday-start sprints.
        anchor_date = datetime(2026, 1, 8, tzinfo=timezone.utc) 
        now = datetime.now(timezone.utc)
        
        days_elapsed = (now - anchor_date).days
        sprint_duration = 14 # 2 weeks fixed duration
        
        sprints_passed = days_elapsed // sprint_duration
        
        sprint_start = anchor_date + timedelta(days=sprints_passed * sprint_duration)
        sprint_end = sprint_start + timedelta(days=sprint_duration - 1)
        
        sprint_number = (sprint_start.timetuple().tm_yday // 14) + 1
        sprint_name = f"Sprint {sprint_start.year} - W{sprint_number}"
        
        return {
            "name": sprint_name,
            "start_date": sprint_start.strftime("%Y-%m-%d"),
            "end_date": sprint_end.strftime("%Y-%m-%d")
        }

    def _normalize_issue(self, issue: Any) -> Dict[str, Any]:
        """
        Standardizes inputs from Jira SDK objects, Qdrant vectors, or Pydantic dicts
        into a clean, flattened dictionary structure.

        Args:
            issue (Any): The raw issue data (object or dict).

        Returns:
            Dict[str, Any]: A normalized dictionary containing core ticket fields.
        """
        # --- PATH A: Jira SDK Issue Object (Using safe attribute reflection) ---
        if hasattr(issue, "fields") and hasattr(issue, "key"):
            f = issue.fields
            return {
                "key": str(getattr(issue, "key", "N/A")),
                "taskName": str(getattr(f, "summary", "N/A")),
                "project": str(getattr(getattr(f, "project", None), "name", "N/A")),
                "type": str(getattr(getattr(f, "issuetype", None), "name", "N/A")),
                "assignee": str(getattr(getattr(f, "assignee", None), "displayName", "Unassigned")),
                "status": str(getattr(getattr(f, "status", None), "name", "N/A")),
                "priority": str(getattr(getattr(f, "priority", None), "name", "N/A"))
            }

        # --- PATH B: JSON Dictionary / Pydantic / Qdrant Records ---
        data = issue.model_dump() if hasattr(issue, "model_dump") else issue if isinstance(issue, dict) else {}
        meta = data.get("metadata", data) if isinstance(data, dict) else {}

        return {
            "key": str(meta.get("key") or meta.get("issue_key") or "N/A"),
            "taskName": str(meta.get("taskName") or meta.get("task_name") or meta.get("summary") or "N/A"),
            "project": str(meta.get("project") or "N/A"),
            "type": str(meta.get("type") or meta.get("issue_type") or "N/A"),
            "assignee": str(meta.get("assignee") or meta.get("owner") or "Unassigned"),
            "status": str(meta.get("status") or "N/A"),
            "priority": str(meta.get("priority") or "N/A")
        }

    def _format_full_row(self, normalized_issue: Dict[str, Any]) -> List[Any]:
        """Prepares a raw list matching Column A-H schema for table entry."""
        key = normalized_issue["key"]
        jira_url = f"{settings.JIRA_DOMAIN_URL}/browse/{key}"
        hyperlink_formula = f'=HYPERLINK("{jira_url}", "{key}")'
        
        return [
            hyperlink_formula,               # Col A: Hyperlink
            key,                              # Col B: Issue Key
            normalized_issue["taskName"],     # Col C: Summary
            normalized_issue["project"],      # Col D: Project Name
            normalized_issue["type"],         # Col E: Issue Type
            normalized_issue["assignee"],     # Col F: Assignee
            normalized_issue["status"],       # Col G: Status
            normalized_issue["priority"]      # Col H: Priority
        ]

    async def sync_dashboard_upsert(self, issues: List[Any], sprint_metadata: Optional[dict] = None):
        """
        Executes the synchronization pipeline.
        Protects spreadsheet formulas (E3, F3, etc.) by omitting static metric overwrites.

        Args:
            issues (List[Any]): List of active sprint issues from Jira.
            sprint_metadata (Optional[dict]): Deprecated manual overrides, defaults to auto-calculation.
        """
        try:
            worksheet = self._get_worksheet(self.sheet_name)

            # --- PHASE 1: Data Normalization ---
            normalized_issues = [self._normalize_issue(is_item) for is_item in issues]
            new_issues_map = {
                str(item["key"]).strip(): item 
                for item in normalized_issues if item["key"]
            }

            if not new_issues_map:
                print("⚠️ Sync aborted: No valid issues found.")
                return

            # --- PHASE 2: Automatic Metadata Resolution ---
            # Always dynamically calculate active sprint metadata based on the current datetime
            sprint_metadata = self._calculate_current_sprint()

            print(f"📋 Syncing Target: {sprint_metadata['name']} ({sprint_metadata['start_date']} -> {sprint_metadata['end_date']})")

            # Update ONLY static label cells to preserve pre-existing COUNTIF formulas in the summary area
            summary_batch = [
                {'range': 'C2', 'values': [[sprint_metadata.get('name', 'N/A')]]},
                {'range': 'C5', 'values': [[sprint_metadata.get('start_date', 'N/A')]]},
                {'range': 'C6', 'values': [[sprint_metadata.get('end_date', 'N/A')]]},
            ]
            worksheet.batch_update(summary_batch)

            # --- PHASE 3: Map Current Spreadsheet State (Row 9+) ---
            max_search_row = 500 
            col_b_values = worksheet.col_values(2) 
            
            existing_keys_on_sheet = {} 
            empty_slots = []            
            
            for i in range(8, max_search_row):
                row_idx = i + 1
                val = col_b_values[i] if i < len(col_b_values) else ""
                val_str = str(val).strip()
                
                if val and val_str: 
                    existing_keys_on_sheet[val_str] = row_idx
                else:
                    empty_slots.append(row_idx)

            # --- PHASE 4: Execute Batch Write (Upsert Logic) ---
            update_batch = []
            tickets_to_sync = list(new_issues_map.keys())
            
            for k in tickets_to_sync:
                data = new_issues_map[k]
                full_row_data = self._format_full_row(data)
                
                if k in existing_keys_on_sheet:
                    row_idx = existing_keys_on_sheet[k]
                    update_batch.append({
                        'range': f'A{row_idx}:H{row_idx}',
                        'values': [full_row_data]
                    })
                elif empty_slots:
                    target_row = empty_slots.pop(0)
                    update_batch.append({
                        'range': f'A{target_row}:H{target_row}',
                        'values': [full_row_data]
                    })

            if update_batch:
                worksheet.batch_update(
                    update_batch, 
                    value_input_option=ValueInputOption.user_entered
                )

            # --- PHASE 5: Cleanup Stale Data ---
            rows_to_delete = [
                idx for k, idx in existing_keys_on_sheet.items() 
                if k not in new_issues_map
            ]
            
            if rows_to_delete:
                for row_num in sorted(rows_to_delete, reverse=True):
                    worksheet.delete_rows(row_num)
                print(f"🗑️ Cleaned up {len(rows_to_delete)} stale tickets from tracking range.")

            print(f"✅ Dashboard Sync Complete. Formulas retained. {len(normalized_issues)} entries mapped.")

        except Exception as e:
            print(f"❌ GoogleSheetService Error: {str(e)}")
            traceback.print_exc()
            raise e
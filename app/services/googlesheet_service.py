import gspread
import traceback
import asyncio
from typing import List, Dict, Any, Optional
from google.oauth2.service_account import Credentials
from gspread.utils import ValueInputOption

from app.core.config import settings

class GoogleSheetService:
    """
    Service responsible for maintaining a real-time Project Dashboard on Google Sheets.
    Implements an 'In-place Upsert' strategy to update existing data while preserving 
    spreadsheet formulas and layout structure.
    """

    def __init__(self) -> None:
        """
        Initializes the Google Sheets client using Service Account credentials.
        Sets up the authorized client and targets the specific spreadsheet defined in settings.
        """
        scopes = [
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive"
        ]
        # Authentication via service_account.json file
        self.creds = Credentials.from_service_account_file(
            "service_account.json", 
            scopes=scopes
        )
        self.client = gspread.authorize(self.creds)
        self.sheet_id = settings.GOOGLE_SHEET_ID
        self.sheet_name = settings.GOOGLE_SHEET_NAME

    def _get_worksheet(self, name: str) -> gspread.Worksheet:
        """
        Opens the spreadsheet by ID and returns the requested worksheet.
        
        Args:
            name (str): The name of the specific tab/worksheet.

        Returns:
            gspread.Worksheet: The gspread worksheet object.
        """
        spreadsheet = self.client.open_by_key(self.sheet_id)
        return spreadsheet.worksheet(name)

    def _normalize_issue(self, issue: Any) -> Dict[str, Any]:
        """
        Standardizes input from different sources (Jira API, Qdrant, or Pydantic models).
        Extracts nested metadata to provide a flattened dictionary with consistent keys.

        Args:
            issue (Any): The raw issue data (object or dict).

        Returns:
            Dict[str, Any]: A normalized dictionary containing core ticket fields.
        """
        # Convert Pydantic models to dict if necessary
        if hasattr(issue, 'model_dump'):
            raw_data = issue.model_dump()
        elif isinstance(issue, dict):
            raw_data = issue
        else:
            raw_data = dict(issue)

        # Qdrant results wrap data in 'metadata'; Jira results might be flat
        data = raw_data.get("metadata", raw_data)
        
        return {
            "key": data.get("key") or data.get("Key") or data.get("issue_key"),
            "taskName": data.get("taskName") or data.get("task_name") or data.get("summary", "N/A"),
            "project": data.get("project", "N/A"),
            "type": data.get("type") or data.get("issue_type") or data.get("issuetype", "N/A"),
            "assignee": data.get("assignee") or data.get("owner") or "Unassigned",
            "status": data.get("status", "N/A"),
            "priority": data.get("priority", "N/A")
        }

    def _format_full_row(self, normalized_issue: Dict[str, Any]) -> List[Any]:
        """
        Prepares a list of values matching the column structure of the Dashboard (Col A to H).
        
        Args:
            normalized_issue (Dict[str, Any]): The standardized issue dictionary.

        Returns:
            List[Any]: A list of values formatted as a spreadsheet row.
        """
        key = normalized_issue["key"]
        jira_url = f"{settings.JIRA_DOMAIN_URL}/browse/{key}"
        
        # Generates a clickable Jira link in Column A using spreadsheet formulas
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

    def _calculate_status_counts(self, normalized_issues: List[Dict[str, Any]]) -> Dict[str, int]:
        """
        Calculates frequencies of tasks per status for the summary section.
        
        Args:
            normalized_issues (List[Dict[str, Any]]): Standardized issue list.

        Returns:
            Dict[str, int]: A mapping of status keys to their occurrence counts.
        """
        # Predefined buckets matching the Dashboard Summary layout
        stats = {
            k: 0 for k in [
                "To Do", "In Progress", "Ready for testing", 
                "Testing", "Stuck / Blocker", "Done", "Closed"
            ]
        }
        for issue in normalized_issues:
            status = issue.get("status")
            if not status: 
                continue
            
            # Robust partial matching (e.g., 'Testing' matches 'In Testing')
            for s_key in stats.keys():
                if s_key.lower() in status.lower():
                    stats[s_key] += 1
        return stats

    async def sync_dashboard_upsert(self, sprint_metadata: dict, issues: List[Any]):
        """
        Executes the full synchronization pipeline:
        1. Normalizes all input data.
        2. Updates high-level Summary Metrics (Rows 2-6).
        3. Identifies existing tickets vs. empty slots in the data table (Row 9+).
        4. Performs batch updates to minimize API overhead.
        5. Deletes rows for tickets that are no longer part of the active sync.

        Args:
            sprint_metadata (dict): Context info (Sprint Name, Start/End dates).
            issues (List[Any]): List of issues retrieved from Jira/Qdrant.
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

            # --- PHASE 2: Update Summary Metrics (Header Section) ---
            stats = self._calculate_status_counts(normalized_issues)
            summary_batch = [
                {'range': 'C2', 'values': [[sprint_metadata.get('name', 'N/A')]]},
                {'range': 'C3', 'values': [[len(normalized_issues)]]},
                {'range': 'C5', 'values': [[sprint_metadata.get('start_date', 'N/A')]]},
                {'range': 'C6', 'values': [[sprint_metadata.get('end_date', 'N/A')]]},
                {'range': 'E3', 'values': [[stats["To Do"]]]},
                {'range': 'F3', 'values': [[stats["In Progress"]]]},
                {'range': 'G3', 'values': [[stats["Ready for testing"]]]},
                {'range': 'H3', 'values': [[stats["Testing"]]]},
                {'range': 'F6', 'values': [[stats["Stuck / Blocker"]]]},
                {'range': 'G6', 'values': [[stats["Done"]]]},
                {'range': 'H6', 'values': [[stats["Closed"]]]},
            ]
            worksheet.batch_update(summary_batch)

            # --- PHASE 3: Map Current Spreadsheet State (Row 9+) ---
            # Fetch Column B to check which tickets already exist in the sheet
            max_search_row = 500 
            col_b_values = worksheet.col_values(2) 
            
            existing_keys_on_sheet = {} 
            empty_slots = []            
            
            # Row 9 is index 8 in the values list
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
                    # Update existing row
                    row_idx = existing_keys_on_sheet[k]
                    update_batch.append({
                        'range': f'A{row_idx}:H{row_idx}',
                        'values': [full_row_data]
                    })
                elif empty_slots:
                    # Fill first available empty slot
                    target_row = empty_slots.pop(0)
                    update_batch.append({
                        'range': f'A{target_row}:H{target_row}',
                        'values': [full_row_data]
                    })

            # Commit updates using 'user_entered' to ensure formulas are parsed correctly
            if update_batch:
                worksheet.batch_update(
                    update_batch, 
                    value_input_option=ValueInputOption.user_entered
                )

            # --- PHASE 5: Cleanup Stale Data ---
            # Remove rows for tickets that are no longer in the source Jira project
            rows_to_delete = [
                idx for k, idx in existing_keys_on_sheet.items() 
                if k not in new_issues_map
            ]
            
            if rows_to_delete:
                # Iterate in reverse to keep row indices valid during deletion
                for row_num in sorted(rows_to_delete, reverse=True):
                    worksheet.delete_rows(row_num)
                print(f"🗑️ Cleaned up {len(rows_to_delete)} stale tickets.")

            print(f"✅ Dashboard Sync Complete: {len(normalized_issues)} tickets processed.")

        except Exception as e:
            print(f"❌ GoogleSheetService Error: {str(e)}")
            traceback.print_exc()
            raise e
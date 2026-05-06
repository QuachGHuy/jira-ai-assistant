import gspread
import traceback
from typing import List, Dict, Any
from google.oauth2.service_account import Credentials
from gspread.utils import ValueInputOption
from app.core.config import settings

class GoogleSheetService:
    """
    Service to maintain a real-time Dashboard on Google Sheets.
    Handles data normalization from Jira/Qdrant and performs 'In-place Upsert' 
    to preserve existing spreadsheet layouts and formulas.
    """

    def __init__(self) -> None:
        """Initialize Google Sheets client using Service Account credentials."""
        scopes = [
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive"
        ]
        # Load credentials from the service account JSON file
        self.creds = Credentials.from_service_account_file(
            "service_account.json", 
            scopes=scopes
        )
        self.client = gspread.authorize(self.creds)
        self.sheet_id = settings.GOOGLE_SHEET_ID
        self.sheet_name = settings.GOOGLE_SHEET_NAME

    def _get_worksheet(self, name: str) -> gspread.Worksheet:
        """
        Access a specific worksheet by name.
        
        Args:
            name (str): The name of the tab/worksheet.
        Returns:
            gspread.Worksheet: The worksheet object.
        """
        spreadsheet = self.client.open_by_key(self.sheet_id)
        return spreadsheet.worksheet(name)

    def _normalize_issue(self, issue: Any) -> Dict[str, Any]:
        """
        Standardizes data input from either Pydantic models or raw Dictionaries.
        Extracts nested 'metadata' if the input comes from a Vector DB (Qdrant).

        Args:
            issue (Any): Raw issue data.
        Returns:
            Dict[str, Any]: A flattened dictionary with consistent keys.
        """
        # Handle Pydantic models or Dict conversion
        if hasattr(issue, 'model_dump'):
            raw_data = issue.model_dump()
        elif isinstance(issue, dict):
            raw_data = issue
        else:
            raw_data = dict(issue)

        # Extract nested metadata if present, otherwise use top-level
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
        Formats the normalized issue into a list representing a row (Col A to H).
        Generates a HYPERLINK formula for Column A.

        Args:
            normalized_issue (Dict[str, Any]): The standardized issue dictionary.
        Returns:
            List[Any]: Formatted row data for Google Sheets.
        """
        key = normalized_issue["key"]
        jira_url = f"{settings.JIRA_DOMAIN_URL}/browse/{key}"
        
        # Note: If your Sheet uses a different locale (e.g., Vietnam), 
        # you might need to change the comma (,) inside HYPERLINK to a semicolon (;).
        hyperlink_formula = f'=HYPERLINK("{jira_url}", "{key}")'
        
        return [
            hyperlink_formula,               # Col A: Hyperlink
            key,                              # Col B: Issue Key
            normalized_issue["taskName"],     # Col C: Summary
            normalized_issue["project"],      # Col D: Project Name
            normalized_issue["type"],         # Col E: Issue Type
            normalized_issue["assignee"],     # Col F: Assignee/Owner
            normalized_issue["status"],       # Col G: Current Status
            normalized_issue["priority"]      # Col H: Priority Level
        ]

    def _calculate_status_counts(self, normalized_issues: List[Dict[str, Any]]) -> Dict[str, int]:
        """
        Aggregates task counts based on their status.

        Args:
            normalized_issues (List[Dict[str, Any]]): List of standardized issues.
        Returns:
            Dict[str, int]: Mapping of status names to their respective counts.
        """
        stats = {k: 0 for k in ["To Do", "In Progress", "Ready for testing", "Testing", "Stuck / Blocker", "Done", "Closed"]}
        for issue in normalized_issues:
            status = issue.get("status")
            if not status: 
                continue
            # Case-insensitive partial matching for robustness
            for s_key in stats.keys():
                if s_key.lower() in status.lower():
                    stats[s_key] += 1
        return stats

    async def sync_dashboard_upsert(self, sprint_metadata: dict, issues: List[Any]):
        """
        Main synchronization pipeline:
        1. Updates Summary metrics (C2:H6).
        2. Scans for existing keys or empty rows starting from Row 9.
        3. Updates existing tickets or fills empty slots to keep the dashboard compact.
        4. Removes stale tickets no longer present in the current sync batch.

        Args:
            sprint_metadata (dict): Sprint info (name, start_date, end_date).
            issues (List[Any]): List of issues to sync.
        """
        try:
            worksheet = self._get_worksheet(self.sheet_name)

            # --- PHASE 1: Data Normalization ---
            normalized_issues = [self._normalize_issue(is_item) for is_item in issues]
            new_issues_map = {str(item["key"]).strip(): item for item in normalized_issues if item["key"]}

            if not new_issues_map:
                print("⚠️ Sync aborted: No valid issues found in the source batch.")
                return

            # --- PHASE 2: Update Summary Metrics (Rows 2-6) ---
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

            # --- PHASE 3: Analyze Spreadsheet Current State (Row 9+) ---
            # Fetch all values from Column B (Keys) to identify existing data and empty rows
            max_search_row = 500 
            col_b_values = worksheet.col_values(2) 
            
            existing_keys_on_sheet = {} # Map existing keys to their row indices
            empty_slots = []            # Track row indices of empty rows for slot-filling
            
            # Start scanning from row 9 (index 8)
            for i in range(8, max_search_row):
                row_idx = i + 1
                val = col_b_values[i] if i < len(col_b_values) else ""
                val_str = str(val).strip()
                
                if val and val_str: 
                    existing_keys_on_sheet[val_str] = row_idx
                else:
                    empty_slots.append(row_idx)

            # --- PHASE 4: Execute Batch Write ---
            update_batch = []
            tickets_to_sync = list(new_issues_map.keys())
            
            for k in tickets_to_sync:
                data = new_issues_map[k]
                full_row_data = self._format_full_row(data)
                
                if k in existing_keys_on_sheet:
                    # Case A: Ticket already exists, update the specific row
                    row_idx = existing_keys_on_sheet[k]
                    update_batch.append({
                        'range': f'A{row_idx}:H{row_idx}',
                        'values': [full_row_data]
                    })
                elif empty_slots:
                    # Case B: New ticket found, fill the first available empty row
                    target_row = empty_slots.pop(0)
                    update_batch.append({
                        'range': f'A{target_row}:H{target_row}',
                        'values': [full_row_data]
                    })

            # Commit updates in a single API call to avoid rate limits
            if update_batch:
                worksheet.batch_update(update_batch, value_input_option=ValueInputOption.user_entered)

            # --- PHASE 5: Cleanup (Remove Stale Tickets) ---
            # Identify rows on the sheet that are no longer present in the Jira sync batch
            rows_to_delete = [idx for k, idx in existing_keys_on_sheet.items() if k not in new_issues_map]
            
            if rows_to_delete:
                # Delete rows from bottom to top to maintain index integrity
                for row_num in sorted(rows_to_delete, reverse=True):
                    worksheet.delete_rows(row_num)
                print(f"🗑️ Cleaned up {len(rows_to_delete)} stale tickets from the sheet.")

            print(f"✅ Dashboard Synced Successfully: {len(normalized_issues)} active tickets processed.")

        except Exception as e:
            print(f"❌ GoogleSheetService Error: {str(e)}")
            traceback.print_exc()
            raise e
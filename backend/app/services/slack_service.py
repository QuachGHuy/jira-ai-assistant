import traceback
from typing import List, Dict, Any, Optional
from slack_sdk import WebClient

from app.core.config import settings

class SlackService:
    """
    Service responsible for managing Slack interactions.
    Handles the construction of Block Kit messages and real-time message updates.
    """

    def __init__(self) -> None:
        """
        Initializes the Slack WebClient using the bot token and default channel ID 
        defined in the application settings.
        """
        self.client = WebClient(token=settings.SLACK_BOT_TOKEN.get_secret_value())
        self.channel_id = settings.SLACK_CHANNEL_ID

    def _build_slack_blocks(self, ticket: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Constructs the Slack Block Kit layout based on the structured ticket metadata.
        
        Args:
            ticket (Dict[str, Any]): Dictionary containing normalized ticket and metadata.

        Returns:
            List[Dict[str, Any]]: A list of Slack blocks defining the message UI.
        """
        meta = ticket.get("metadata", {})
        key = meta.get("key", "N/A")
        
        # Determine the ticket link; fallback to standard Jira URL if missing
        link = meta.get("key_link") or f"{settings.JIRA_DOMAIN_URL}/browse/{key}"
        
        # Retrieve technical description; formatted in blockquote in the UI
        description = ticket.get("slack_desc") or "No technical details provided."
        
        # Extract recommendation details for the packed callback string
        assignee_email = meta.get("assignee_email", "None")
        assignee_id = meta.get("assignee_id", "None")
        confidence = meta.get("confidence_score", "N/A")
        
        # Prepare the packed value for button callbacks: action|key|email|id|link
        # This allows the interaction handler to process the decision without re-querying Jira.
        base_callback_value = f"{key}|{assignee_email}|{assignee_id}|{link}"

        return [
            {
                "type": "header",
                "text": {
                    "type": "plain_text",
                    "text": "🎯 AI Assignee Recommendation",
                    "emoji": True
                }
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*Ticket:* <{link}|{key}>\n*Task:* {meta.get('task_name', 'N/A')}\n*Project:* {meta.get('project', 'Others')}"
                }
            },
            {
                "type": "section",
                "fields": [
                    {"type": "mrkdwn", "text": f"*Type:*\n{meta.get('issue_type', 'N/A')}"},
                    {"type": "mrkdwn", "text": f"*Priority:*\n{meta.get('priority', 'N/A')}"}
                ]
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*Technical Details & Description:*\n> {description}"
                }
            },
            {
                "type": "divider"
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"👤 *AI Recommendation:* *{assignee_email}* | *Confidence: {confidence}*"
                }
            },
            {
                "type": "actions",
                "block_id": "report_approval_block",
                "elements": [
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "Approve", "emoji": True},
                        "style": "primary",
                        "value": f"approve|{base_callback_value}",
                        "action_id": "approve_btn"
                    },
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "Decline", "emoji": True},
                        "style": "danger",
                        "value": f"decline|{base_callback_value}",
                        "action_id": "decline_btn"
                    }
                ]
            }
        ]

    async def send_ticket_notification(self, ticket: Dict[str, Any]) -> Optional[str]:
        """
        Dispatches an interactive Block Kit message to the configured Slack channel.
        
        Args:
            ticket (Dict[str, Any]): The unified ticket data dictionary.

        Returns:
            Optional[str]: The message timestamp (ts) if successful, otherwise None.
        """
        try:
            blocks = self._build_slack_blocks(ticket)
            response = self.client.chat_postMessage(
                channel=self.channel_id,
                blocks=blocks,
                text=f"🎯 New recommendation for {ticket.get('metadata', {}).get('key', 'Unknown')}"
            )
            return response["ts"]
        except Exception as e:
            print(f"❌ Slack Notification Error: {str(e)}")
            traceback.print_exc()
            return None

    async def update_message(self, channel: str, ts: str, status_text: str):
        """
        Updates an existing Slack message to display the final decision and remove buttons.
        This prevents multiple interactions on the same ticket.
        
        Args:
            channel (str): The Slack channel ID where the message exists.
            ts (str): The timestamp of the original message to be updated.
            status_text (str): The final text content (e.g., '✅ Approved').
        """
        try:
            self.client.chat_update(
                channel=channel,
                ts=ts,
                text=status_text,
                blocks=[
                    {
                        "type": "section",
                        "text": {"type": "mrkdwn", "text": status_text}
                    }
                ]
            )
        except Exception as e:
            print(f"❌ Slack Update Error: {str(e)}")
            traceback.print_exc()

    async def send_message(self, channel: str, text: str):
        """
        Sends a simple text message to a specified Slack channel.
        
        Args:
            channel (str): The Slack channel ID to send the message to.
            text (str): The content of the message to be sent.
        """
        try:
            self.client.chat_postMessage(
                channel=channel,
                text=text
            )
        except Exception as e:
            print(f"❌ Slack Message Send Error: {str(e)}")
            traceback.print_exc()
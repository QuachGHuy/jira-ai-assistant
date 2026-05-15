import re
import uuid
from datetime import datetime

class TextProcessor:
    """
    Utility service for cleaning and formatting text data from Jira.
    Handles preparation for AI embeddings, Slack notifications, and ID generation.
    """

    @staticmethod
    def clean_jira_text(text: str) -> str:
        """
        Cleans Jira description content by removing code blocks, images, and formatting tags.
        Optimized to create "clean" text for AI Embedding generation.
        
        Args:
            text (str): Raw text from a Jira issue description.

        Returns:
            str: Cleaned text suitable for vectorization.
        """
        if not text: 
            return ""
            
        cleaned = text
        
        # Remove {code} blocks including their content as they usually contain noisy logs
        cleaned = re.sub(r'\{code[:\w]*\}(.*?)\{code\}', '', cleaned, flags=re.DOTALL)
        
        # Remove {noformat} blocks which often contain raw data dumps
        cleaned = re.sub(r'\{noformat\}(.*?)\{noformat\}', '', cleaned, flags=re.DOTALL)
        
        # Remove Jira image tags (e.g., !image.png!)
        cleaned = re.sub(r'![^!]+!', '', cleaned)
        
        # Remove common formatting characters like asterisks for bold/lists
        cleaned = re.sub(r'\*', '', cleaned)
        
        # Remove Jira header markers (h1. to h6.)
        cleaned = re.sub(r'h[1-6]\.\s*', '', cleaned)
        
        # Normalize excessive whitespace (limit to double newlines)
        return cleaned.strip().replace('\n\n\n', '\n\n')

    @staticmethod
    def format_for_slack(text: str) -> str:
        """
        Converts Jira Markdown to Slack Mrkdwn and prunes technical metadata.
        Implements a 'tail-cut' strategy to remove long logs/cURL commands.
        
        Args:
            text (str): Raw text from Jira description.

        Returns:
            str: Formatted string optimized for Slack Block Kit.
        """
        if not text: 
            return "No description provided."
        
        # 1. Pruning Strategy: Cut off content starting from technical headers
        # This prevents long cURL commands and Job IDs from bloating Slack messages.
        trash_headers = [
            "JobID and Payload", "cURL", "Credentials", 
            "Environment:", "Roster date:"
        ]
        for header in trash_headers:
            match = re.search(rf'{header}', text, re.IGNORECASE)
            if match:
                text = text[:match.start()].strip()
        
        # 2. Remove Jira specific Image and Attachment markers
        slack_text = re.sub(r'![^!]+!', '', text)
        slack_text = re.sub(r'\[\^[^\\]+\]', '', slack_text)
        
        # 3. Convert Jira {code} or {quote} blocks to Slack triple-backtick blocks
        slack_text = re.sub(r'\{code[:\w]*\}|\{code\}|\{noformat\}|\{quote\}', '\n```\n', slack_text)
        
        # 4. Transform Jira Headers (h1.-h6.) into Bold text in Slack
        slack_text = re.sub(r'h[1-6]\.\s*(.*?)(?:\r?\n|$)', r'*\1*\n', slack_text)
        
        # 5. Bolden key organizational headers (e.g., 'Actual result:')
        headers = [
            "Environment", "Test case", "Actual result", 
            "Expected result", "Root cause", "Fix", "Issue details"
        ]
        for header in headers:
            # Use regex to bold the header if it isn't already bold
            reg = re.compile(rf'(?<!\*){header}:', re.IGNORECASE)
            slack_text = reg.sub(f'*{header}:*', slack_text)
        
        # 6. Normalize spacing (compress 3+ newlines into 2)
        slack_text = re.sub(r'\n{3,}', '\n\n', slack_text).strip()

        # 7. Truncate for Slack limitations (Slack has a 3000 char limit per block)
        if len(slack_text) > 2500:
            return slack_text[:2500] + "... (View more in Jira)"
            
        return slack_text

    @staticmethod
    def generate_stable_id(text: str) -> str:
        """
        Generates a stable UUID v5 from a Jira Key.
        Ensures that the same Jira Key always results in the same Point ID for Qdrant.
        
        Args:
            text (str): The Jira issue key (e.g., 'APG-136').

        Returns:
            str: A stable UUID string.
        """
        # Using NAMESPACE_DNS as a seed for consistent UUID generation across restarts
        return str(uuid.uuid5(uuid.NAMESPACE_DNS, text))

    @staticmethod
    def format_jira_date(date_str: str) -> str:
        """
        Converts Jira date (+0800) to RFC 3339 (+08:00) for Qdrant compatibility.
        """
        if not date_str or date_str == "None":
            return None
        # Fix timezone: +0800 -> +08:00
        if len(date_str) > 5 and date_str[-5] in ['+', '-'] and ":" not in date_str[-3:]:
            date_str = date_str[:-2] + ":" + date_str[-2:]
        return date_str
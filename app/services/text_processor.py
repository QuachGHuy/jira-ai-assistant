import re
import zlib

class TextProcessor:
    @staticmethod
    def clean_jira_text(text: str) -> str:
        """
        Làm sạch nội dung mô tả từ Jira (xóa code blocks, images, formatting).
        
        Args:
            text (str): Văn bản thô từ Jira description.
        Returns:
            str: Văn bản đã được làm sạch để đưa vào AI Embedding.
        """
        if not text: 
            return ""
        cleaned = text
        cleaned = re.sub(r'\{code[:\w]*\}(.*?)\{code\}', '', cleaned, flags=re.DOTALL)
        cleaned = re.sub(r'\{noformat\}(.*?)\{noformat\}', '', cleaned, flags=re.DOTALL)
        cleaned = re.sub(r'![^!]+!', '', cleaned)
        cleaned = re.sub(r'\*', '', cleaned)
        cleaned = re.sub(r'h[1-6]\.\s*', '', cleaned)
        return cleaned.strip().replace('\n\n\n', '\n\n')

    @staticmethod
    def format_for_slack(text: str) -> str:
        """
        Chuyển đổi Jira Markdown sang Slack Mrkdwn để hiển thị đẹp trên Slack[cite: 1].
        
        Args:
            text (str): Văn bản thô từ Jira description.
        Returns:
            str: Văn bản đã được format theo Block Kit/Mrkdwn.
        """
        if not text: 
            return "No description provided."
        
        # Logic format Slack từ n8n[cite: 1]
        slack_text = re.sub(r'![^!]+!', '', text)
        slack_text = re.sub(r'\[\^[^\\]+\]', '', slack_text)
        slack_text = re.sub(r'\{code[:\w]*\}|\{code\}|\{noformat\}|\{quote\}', '\n```\n', slack_text)
        slack_text = re.sub(r'h[1-6]\.\s*(.*?)(?:\r?\n|$)', r'*\1*\n', slack_text)
        
        headers = ["Environment", "Test case", "Actual result", "Expected result", "Root cause", "Fix"]
        for header in headers:
            reg = re.compile(rf'(?<!\*){header}:', re.IGNORECASE)
            slack_text = reg.sub(f'*{header}:*', slack_text)

        return (slack_text[:2500] + "... (Xem thêm tại Jira)") if len(slack_text) > 2500 else slack_text

    @staticmethod
    def generate_numeric_id(text: str) -> int:
        """
        Tạo Point ID dạng số nguyên từ Jira Key[cite: 1].
        
        Args:
            text (str): Jira Key (ví dụ: 'AD-123').
        Returns:
            int: Số nguyên 32-bit không âm.
        """
        return zlib.adler32(text.encode()) & 0xffffffff
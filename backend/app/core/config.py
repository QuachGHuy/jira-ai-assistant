from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    # APP
    EXTERNAL_BASE_URL: str = "http://localhost:8000"
    SLACK_INTERACTIVE_ENDPOINT: str = "/api/v1/slack/interactive"
    TIMEZONE: str = "Asia/Ho_Chi_Minh"

    # Jira
    JIRA_DOMAIN_URL: str = ""
    JIRA_EMAIL: str = ""
    JIRA_API_TOKEN: SecretStr = SecretStr("")

    # Qdrant
    QDRANT_ENDPOINT_URL: str = ""
    QDRANT_API_TOKEN: SecretStr = SecretStr("")
    QDRANT_COLLECTION_JIRA: str = "jira_issues"
    QDRANT_COLLECTION_NOTIFIED: str = "issue_notified_check"
    QDRANT_COLLECTION_JOBS: str = "cron_jobs"
    QDRANT_VECTOR_SIZE: int = 1024 

    # LLMs 
    LLM_BASE_URL: str = "http://9router:20128/v1"
    LLM_CHAT_MODEL: str = "chat-model"
    LLM_API_KEY: SecretStr = SecretStr("")

    # Ollama
    OLLAMA_BASE_URL: str = "http://ollama:11434/api/embeddings"
    OLLAMA_EMBEDDING_MODEL: str = "bge-m3:567m"

    # Slack
    SLACK_BOT_TOKEN: SecretStr = SecretStr("")
    SLACK_SIGNING_SECRET: SecretStr = SecretStr("")
    SLACK_CHANNEL_ID: str = ""

    # Google Sheets
    GOOGLE_SHEET_ID: str = ""
    GOOGLE_SHEET_NAME: str = "Dashboard"

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

settings = Settings()
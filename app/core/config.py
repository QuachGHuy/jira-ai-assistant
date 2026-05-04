from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    # Jira
    JIRA_DOMAIN_URL: str = ""
    JIRA_EMAIL: str = ""
    JIRA_API_TOKEN: str = ""

    # Qdrant
    QDRANT_ENDPOINT_URL: str = ""
    QDRANT_API_TOKEN: str = ""

    # Ollama
    OLLAMA_BASE_URL: str = ""
    EMBEDDING_MODEL: str = "bge-m3:567m"

    # Slack
    SLACK_BOT_TOKEN: str = ""
    SLACK_SIGNING_SECRET: str = ""
    SLACK_CHANNEL_ID: str = ""

    # Google Sheets
    GOOGLE_SHEET_ID: str = ""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

settings = Settings()
from fastapi import FastAPI
from app.core.config import settings

app = FastAPI(title="Jira AI Assistant Backend")

@app.get("/health")
async def health_check():
    return {
        "status": "healthy",
        "embedding_model": settings.EMBEDDING_MODEL,
        "jira_url": settings.JIRA_DOMAIN_URL,
        "qdrant_url": settings.QDRANT_ENDPOINT_URL,
        "ollama_url": settings.OLLAMA_BASE_URL,
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
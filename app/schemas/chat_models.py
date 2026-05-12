from pydantic import BaseModel
from typing import Optional, List

class ChatRequest(BaseModel):
    message: str
    chat_history: Optional[List[dict]] = []

class ChatResponse(BaseModel):
    reply: str
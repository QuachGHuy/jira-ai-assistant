from typing import Optional
from pydantic import BaseModel, Field

class VotingResult(BaseModel):
    recommended_assignee: str 
    assignee_id: Optional[str] = None 
    assignee_email: Optional[str] = None
    confidence_score: float
    reasoning: str
    total_tasks_found: int
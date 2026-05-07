from pydantic import BaseModel, Field

class VotingResult(BaseModel):
    recommended_assignee: str 
    assignee_id: str 
    assignee_email: str 
    confidence_score: float 
    reasoning: str
    total_tasks_found: int
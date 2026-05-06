from pydantic import BaseModel, Field

class VotingResult(BaseModel):
    recommended_assignee: str = Field(..., alias="recommendedAssignee")
    assignee_id: str = Field(..., alias="assigneeId")
    confidence_score: float = Field(..., alias="confidenceScore")
    reasoning: str = Field(..., alias="reasoning")
    total_tasks_found: int = Field(..., alias="totalTasksFound")
from pydantic import BaseModel, Field
from typing import Optional, List, Any

class JiraMetadata(BaseModel):
    key_link: str
    key: str
    task_name: str
    project: str
    issue_type: str = Field(..., alias="type")
    owner: Optional[str] = None
    owner_id: Optional[str] = None 
    status: str
    priority: str
    created_at: Optional[str] = None

class JiraIssue(BaseModel):
    point_id: int 
    metadata: JiraMetadata
    vector_content: str 
    slack_desc: Optional[str] = None 

class VotingResult(BaseModel):
    decision: str 
    suggested_assignee: str
    suggested_assignee_id: Optional[str]
    confidence: int
    voting_stats: dict
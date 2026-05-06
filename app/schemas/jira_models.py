from pydantic import BaseModel, Field
from typing import Optional, List, Any

class JiraMetadata(BaseModel):
    key_link: str = Field(..., alias="keyLink")
    key: str = Field(..., alias="key")
    task_name: str = Field(..., alias="taskName")
    project: str = Field(..., alias="project")
    issue_type: str = Field(..., alias="type")
    assignee: Optional[str] = Field(None, alias="assignee")
    assignee_id: Optional[str] = Field(None, alias="assigneeId")
    status: str = Field(..., alias="status")
    priority: str = Field(..., alias="priority")
    created_at: Optional[str] = Field(None, alias="createdAt")
    outwardIssue_key: Optional[str] = Field(None, alias="outwardIssueKey")
    inwardIssue_key: Optional[str] = Field(None, alias="inwardIssueKey")

class JiraIssue(BaseModel):
    point_id: int = Field(..., alias="pointId")
    metadata: JiraMetadata
    vector_content: str = Field(..., alias="vectorContent")
    slack_desc: Optional[str] = Field(None, alias="slackDesc")

class VotingResult(BaseModel):
    decision: str = Field(..., alias="decision")
    suggested_assignee: str = Field(..., alias="suggestedAssignee")
    suggested_assignee_id: Optional[str] = Field(None, alias="suggestedAssigneeId")
    confidence: int = Field(..., alias="confidence")
    voting_stats: dict = Field(..., alias="votingStats")
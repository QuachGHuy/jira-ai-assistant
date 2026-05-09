from pydantic import BaseModel
from typing import Optional, Dict

class JiraMetadata(BaseModel):
    key_link: str
    key: str
    task_name: str
    project: str
    type: str
    assignee: Optional[str] = None
    assignee_id: Optional[str] = None
    assignee_email: Optional[str] = None
    status: str
    priority: str
    created_at: Optional[str] = None
    outward_issue_key: Optional[str] = None
    inward_issue_key: Optional[str] = None

class JiraIssue(BaseModel):
    point_id: str
    metadata: JiraMetadata
    desc: str
    content: str
    vector_content: str
    slack_desc: str 
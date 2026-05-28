from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any

class AnalyzeRequest(BaseModel):
    text: str

class SearchInput(BaseModel):
    input: str = Field(description="The core semantic search string")
    filter: Optional[Dict[str, Any]] = Field(
        default=None, 
        description="The strict metadata constraints in Qdrant format"
    )

class JQLInput(BaseModel):
    jql: Optional[str] = Field(None, description="Jira Query Language string. Example: 'project = \"APG\" AND status = \"TO DO\"'")

class ProjectInput(BaseModel):
    project_key: str = Field("AIO Development", description="Jira project key (e.g., 'AIO Development', 'APG').")
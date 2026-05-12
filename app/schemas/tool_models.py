from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any

class SearchInput(BaseModel):
    vector_query: str = Field(description="The core semantic search string")
    filters: Optional[Dict] = Field(default=None, description="Metadata filters")

class JQLInput(BaseModel):
    jql: Optional[str] = Field(None, description="Jira Query Language string. Example: 'project = \"APG\" AND status = \"TO DO\"'")

class ProjectInput(BaseModel):
    project_key: str = Field("AIO Development", description="Jira project key (e.g., 'AIO Development', 'APG').")
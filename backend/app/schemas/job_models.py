from pydantic import BaseModel, Field
from typing import Optional

class JobSchedule(BaseModel):
    hour: int = Field(..., ge=0, le=23, description="Hour of the day (0-23) when the job should run")
    minute: int = Field(..., ge=0, le=59, description="Minute of the hour (0-59) when the job should run")
    day_of_week: Optional[int] = Field(None, ge=0, le=7, description="Day of the week (0-6) when the job should run, where 0 is Monday and 6 is Sunday, and 7 means every day")

class JobConfig(BaseModel):
    id: str = Field(..., description="Unique identifier for the job")
    name: str = Field(..., description="Name of the job")
    custom_jql: Optional[str] = Field(None, description="Custom JQL query for the job")
    default_jql: str = Field(..., description="Default JQL query for the job")
    scheduler: JobSchedule = Field(..., description="Schedule configuration for the job")
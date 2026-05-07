from pydantic import BaseModel

class ActionMetadata(BaseModel):
    """Data structure for the packed 'value' string in Slack buttons."""
    action_type: str
    ticket_key: str
    assignee_email: str
    assignee_id: str
    ticket_link: str

    @classmethod
    def from_packed_string(cls, packed_str: str):
        parts = packed_str.split("|")
        return cls(
            action_type=parts[0],
            ticket_key=parts[1],
            assignee_email=parts[2],
            assignee_id=parts[3],
            ticket_link=parts[4]
        )
from pydantic import BaseModel
from typing import Any, Optional
from datetime import datetime

class AgentMessage(BaseModel):
    case_id: str
    from_agent: str
    to_agent: Optional[str] = None
    message_type: str
    priority: str = "normal"
    payload: dict[str, Any]
    requires_response: bool = False
    created_at: str = datetime.utcnow().isoformat()
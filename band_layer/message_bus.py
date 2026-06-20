from datetime import datetime
from band_layer.context_store import add_message

async def publish_message(
    case_id: str,
    from_agent: str,
    to_agent: str,
    message_type: str,
    payload: dict,
    priority: str = "normal",
    requires_response: bool = False
):
    message = {
        "case_id": case_id,
        "from_agent": from_agent,
        "to_agent": to_agent,
        "message_type": message_type,
        "priority": priority,
        "payload": payload,
        "requires_response": requires_response,
        "created_at": datetime.utcnow().isoformat()
    }

    add_message(case_id, message)
    return message
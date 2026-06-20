from band_layer.message_bus import publish_message

class BandClient:
    async def send_context(self, case_id, from_agent, to_agent, payload):
        return await publish_message(
            case_id=case_id,
            from_agent=from_agent,
            to_agent=to_agent,
            message_type="context_handoff",
            payload=payload,
            requires_response=True
        )

    async def publish_state(self, case_id, from_agent, state, payload):
        return await publish_message(
            case_id=case_id,
            from_agent=from_agent,
            to_agent="workflow",
            message_type=f"state.{state}",
            payload=payload
        )

    async def request_human_approval(self, case_id, from_agent, payload):
        return await publish_message(
            case_id=case_id,
            from_agent=from_agent,
            to_agent="human_reviewer",
            message_type="human_approval.required",
            priority="high",
            payload=payload,
            requires_response=True
        )
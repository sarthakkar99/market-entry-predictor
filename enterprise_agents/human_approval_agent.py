# enterprise_agents/human_approval_agent.py

from band_layer.context_store import save_agent_output
from band_layer.band_client import BandClient

band = BandClient()


async def run_human_approval_agent(case, compliance_context, red_team_context):
    """
    Human Approval Agent

    Purpose:
    - Checks whether the expansion plan needs human review.
    - Triggers approval when risk is high.
    - For hackathon demo, it returns a default simulated decision.
    """

    case_id = case["case_id"]

    compliance_risk = compliance_context.get("regulatory_risk", "low")
    human_required_by_compliance = compliance_context.get(
        "human_approval_required",
        False
    )

    risk_adjustment = red_team_context.get("risk_adjustment", 0)
    challenges = red_team_context.get("challenges", [])

    requires_approval = (
        human_required_by_compliance is True
        or compliance_risk == "high"
        or risk_adjustment <= -10
    )

    if requires_approval:
        output = {
            "agent": "human_approval_agent",
            "status": "approval_required",
            "question": "Approve pilot office after legal and finance review?",
            "options": [
                "approve_pilot",
                "request_more_research",
                "reject"
            ],
            "default_demo_decision": "approve_pilot",
            "reason": {
                "compliance_risk": compliance_risk,
                "human_required_by_compliance": human_required_by_compliance,
                "risk_adjustment": risk_adjustment,
                "red_team_challenges": challenges
            },
            "decision": "approve_pilot",
            "next_step": "Send approved context to Executive Decision Agent"
        }

        await band.request_human_approval(
            case_id=case_id,
            from_agent="human_approval_agent",
            payload=output
        )

    else:
        output = {
            "agent": "human_approval_agent",
            "status": "auto_approved",
            "question": None,
            "options": [],
            "default_demo_decision": "proceed",
            "reason": {
                "compliance_risk": compliance_risk,
                "human_required_by_compliance": human_required_by_compliance,
                "risk_adjustment": risk_adjustment,
                "red_team_challenges": challenges
            },
            "decision": "proceed",
            "next_step": "Send approved context to Executive Decision Agent"
        }

        await band.send_context(
            case_id=case_id,
            from_agent="human_approval_agent",
            to_agent="executive_agent",
            payload=output
        )

    save_agent_output(
        case_id=case_id,
        agent_name="human_approval_agent",
        output=output
    )

    return output
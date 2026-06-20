from band_layer.context_store import save_agent_output, update_case
from band_layer.band_client import BandClient

band = BandClient()

async def run_executive_agent(case, all_context):
    case_id = case["case_id"]

    research = all_context["research"]
    site = all_context["site_selection"]
    incentives = all_context["incentives"]
    finance = all_context["finance"]
    compliance = all_context["compliance"]
    red_team = all_context["red_team"]
    human = all_context["human_approval"]

    probability = research.get("probability", 0)
    location = site.get("recommended_location", {})
    cost = finance.get("first_year_cost", {}).get("estimated_first_year_cost", 0)

    if probability >= 70 and compliance.get("regulatory_risk") != "high":
        decision = "proceed_with_expansion"
    elif probability >= 70 and compliance.get("regulatory_risk") == "high":
        decision = "approve_pilot_after_legal_review"
    elif probability >= 50:
        decision = "partner_led_entry_or_monitor"
    else:
        decision = "monitor_only"

    output = {
        "decision": decision,
        "market_entry_probability": probability,
        "recommended_location": location,
        "government_incentive_fit": incentives.get("incentive_fit", "medium"),
        "estimated_first_year_cost": cost,
        "regulatory_risk": compliance.get("regulatory_risk"),
        "red_team_challenges": red_team.get("challenges", []),
        "human_review_status": human.get("status"),
        "executive_summary": f"Recommended decision: {decision}. Open a pilot office in {location.get('city', 'selected city')} with legal review before full launch."
    }

    save_agent_output(case_id, "executive_agent", output)
    update_case(case_id, "final_decision", output)
    update_case(case_id, "status", "completed")

    await band.publish_state(
        case_id=case_id,
        from_agent="executive_agent",
        state="decision_completed",
        payload=output
    )

    return output
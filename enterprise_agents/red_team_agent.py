from band_layer.context_store import save_agent_output
from band_layer.band_client import BandClient

band = BandClient()

async def run_red_team_agent(case, all_context):
    case_id = case["case_id"]

    research = all_context.get("research", {})
    finance = all_context.get("finance", {})
    compliance = all_context.get("compliance", {})

    challenges = []
    adjustment = 0

    if research.get("probability", 0) < 70:
        challenges.append("Market-entry evidence is not strong enough for full launch.")
        adjustment -= 5

    estimated_cost = finance.get("first_year_cost", {}).get("estimated_first_year_cost", 0)
    if estimated_cost > 900000:
        challenges.append("First-year setup cost is high; phased entry may be safer.")
        adjustment -= 7

    if compliance.get("regulatory_risk") == "high":
        challenges.append("Regulatory risk is high and requires human/legal review.")
        adjustment -= 10

    if not challenges:
        challenges.append("No major blockers found, but assumptions should be monitored.")

    output = {
        "risk_adjustment": adjustment,
        "challenges": challenges,
        "red_team_recommendation": "proceed with caution" if adjustment < 0 else "proceed"
    }

    save_agent_output(case_id, "red_team_agent", output)

    await band.send_context(
        case_id=case_id,
        from_agent="red_team_agent",
        to_agent="human_approval_agent",
        payload=output
    )

    return output
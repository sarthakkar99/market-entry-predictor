from band_layer.context_store import create_case, get_case
from enterprise_agents.research_agent import run_research_agent
from enterprise_agents.site_selection_agent import run_site_selection_agent
from enterprise_agents.incentives_agent import run_incentives_agent
from enterprise_agents.finance_agent import run_finance_agent
from enterprise_agents.compliance_agent import run_compliance_agent
from enterprise_agents.red_team_agent import run_red_team_agent
from enterprise_agents.human_approval_agent import run_human_approval_agent
from enterprise_agents.executive_agent import run_executive_agent
from enterprise_agents.task_assignment_agent import run_task_assignment_agent

async def run_market_expansion_workflow(company, market, country, headcount=10):
    case = create_case(company, market, country, headcount)

    research = await run_research_agent(case)

    site_selection = await run_site_selection_agent(
        case,
        research_context=research
    )

    incentives = await run_incentives_agent(
        case,
        site_context=site_selection
    )

    finance = await run_finance_agent(
        case,
        site_context=site_selection,
        incentives_context=incentives
    )

    compliance = await run_compliance_agent(
        case,
        finance_context=finance
    )

    red_team = await run_red_team_agent(
        case,
        all_context={
            "research": research,
            "site_selection": site_selection,
            "incentives": incentives,
            "finance": finance,
            "compliance": compliance
        }
    )

    human = await run_human_approval_agent(
        case,
        compliance_context=compliance,
        red_team_context=red_team
    )

    executive = await run_executive_agent(
        case,
        all_context={
            "research": research,
            "site_selection": site_selection,
            "incentives": incentives,
            "finance": finance,
            "compliance": compliance,
            "red_team": red_team,
            "human_approval": human
        }
    )

    tasks = await run_task_assignment_agent(case, executive)

    final_case = get_case(case["case_id"])

    return {
        "case": final_case,
        "research": research,
        "site_selection": site_selection,
        "incentives": incentives,
        "finance": finance,
        "compliance": compliance,
        "red_team": red_team,
        "human_approval": human,
        "executive_decision": executive,
        "tasks": tasks
    }
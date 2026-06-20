from band_layer.context_store import save_agent_output

async def run_task_assignment_agent(case, executive_decision):
    case_id = case["case_id"]

    output = {
        "sales": [
            "Identify top 25 enterprise customers in target market",
            "Build partner outreach list",
            "Prepare competitive battlecard"
        ],
        "finance": [
            "Validate first-year office budget",
            "Compare incentive-adjusted cost scenarios",
            "Create pilot ROI estimate"
        ],
        "legal": [
            "Review regulatory requirements",
            "Check local business registration rules",
            "Validate data privacy obligations"
        ],
        "hr": [
            "Estimate hiring timeline",
            "Shortlist local recruiters",
            "Benchmark salaries for first 10 hires"
        ],
        "executive": [
            "Approve pilot scope",
            "Set 90-day expansion milestones",
            "Review risk report"
        ]
    }

    save_agent_output(case_id, "task_assignment_agent", output)
    return output
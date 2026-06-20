import uuid
from datetime import datetime

CASE_STORE = {}

def create_case(company: str, market: str, country: str, headcount: int = 10):
    case_id = f"case_{uuid.uuid4().hex[:8]}"

    case = {
        "case_id": case_id,
        "company": company,
        "market": market,
        "country": country,
        "headcount": headcount,
        "status": "created",
        "created_at": datetime.utcnow().isoformat(),
        "agent_outputs": {},
        "messages": [],
        "human_decisions": [],
        "final_decision": None
    }

    CASE_STORE[case_id] = case
    return case

def get_case(case_id: str):
    return CASE_STORE.get(case_id)

def update_case(case_id: str, key: str, value):
    CASE_STORE[case_id][key] = value
    return CASE_STORE[case_id]

def save_agent_output(case_id: str, agent_name: str, output: dict):
    CASE_STORE[case_id]["agent_outputs"][agent_name] = output
    return CASE_STORE[case_id]

def add_message(case_id: str, message: dict):
    CASE_STORE[case_id]["messages"].append(message)
    return CASE_STORE[case_id]
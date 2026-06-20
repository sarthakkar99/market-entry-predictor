import os
from dotenv import load_dotenv

# Load environment variables from .env
load_dotenv(override=True)


# ============================================================
# Helper functions
# ============================================================

def _env_bool(name: str, default: bool = False) -> bool:
    """
    Reads boolean values from environment variables.

    Accepts:
    true, 1, yes, y, on
    false, 0, no, n, off
    """
    value = os.getenv(name)

    if value is None or value == "":
        return default

    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


def _env_int(name: str, default: int) -> int:
    """
    Reads integer values safely from environment variables.
    """
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return default


# ============================================================
# OpenAI Configuration
# ============================================================

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "").strip()

# Use gpt-4o-mini for cheaper/faster hackathon demo.
# You can switch to gpt-4o if needed.
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini").strip()

MAX_TOKENS = _env_int("MAX_TOKENS", 1000)


# ============================================================
# Bright Data / Search Configuration
# ============================================================

BRIGHTDATA_API_KEY = os.getenv("BRIGHTDATA_API_KEY", "").strip()
BRIGHTDATA_ZONE = os.getenv("BRIGHTDATA_ZONE", "serp").strip()
BRIGHTDATA_API_URL = os.getenv(
    "BRIGHTDATA_API_URL",
    "https://api.brightdata.com/request"
).strip()

SERP_RESULTS = _env_int("SERP_RESULTS", 8)


# ============================================================
# Band Configuration
# ============================================================

BAND_API_KEY = os.getenv("BAND_API_KEY", "").strip()
BAND_PROJECT_ID = os.getenv("BAND_PROJECT_ID", "").strip()
BAND_WORKSPACE_ID = os.getenv("BAND_WORKSPACE_ID", "").strip()

# For now, keep this local unless you have the actual Band SDK/API working.
BAND_LOCAL_MODE = _env_bool("BAND_LOCAL_MODE", True)


# ============================================================
# Mock Mode Configuration
# ============================================================

# Search mock mode:
# Turns on automatically if Bright Data API key is missing.
MOCK_MODE = (
    _env_bool("MOCK_MODE", False)
    or not BRIGHTDATA_API_KEY
)

# LLM mock mode:
# Turns on automatically if OpenAI API key is missing.
LLM_MOCK_MODE = (
    _env_bool("LLM_MOCK_MODE", False)
    or not OPENAI_API_KEY
)

# Full demo mode:
# Use this when you want everything stable without live APIs.
DEMO_MODE = _env_bool("DEMO_MODE", False)

if DEMO_MODE:
    MOCK_MODE = True
    LLM_MOCK_MODE = True
    BAND_LOCAL_MODE = True


# ============================================================
# Market Entry Signal Agents
# ============================================================

AGENTS = {
    "job_posts": {
        "label": "Job Posting Signals",
        "emoji": "💼",
        "max_score": 25,
        "query_tpl": 'site:linkedin.com/jobs "{company}" "{market}" "{country}"',
        "signal": "job postings targeting the market and country",
    },

    "domain_regs": {
        "label": "Domain / Web Expansion Signals",
        "emoji": "🌐",
        "max_score": 25,
        "query_tpl": '"{company}" "{market}" "{country}" domain OR website OR expansion',
        "signal": "new domains, local pages, or brand expansion assets",
    },

    "exec_hires": {
        "label": "Executive Hire Signals",
        "emoji": "👤",
        "max_score": 20,
        "query_tpl": '"{company}" hired VP OR director OR head "{market}" "{country}"',
        "signal": "senior hires signalling strategic market intent",
    },

    "partnerships": {
        "label": "Partnership & Conference Signals",
        "emoji": "🤝",
        "max_score": 15,
        "query_tpl": '"{company}" "{market}" "{country}" partnership OR sponsor OR conference',
        "signal": "partnerships or public ecosystem activity",
    },

    "patents": {
        "label": "Patent & IP Signals",
        "emoji": "📄",
        "max_score": 15,
        "query_tpl": '"{company}" patent "{market}" "{country}" site:patents.google.com OR site:uspto.gov',
        "signal": "patent or IP filings related to the target market",
    },
}

TOTAL_MAX_SCORE = sum(agent["max_score"] for agent in AGENTS.values())


# ============================================================
# Local Competitor Agent
# ============================================================

LOCAL_COMPETITOR_AGENT = {
    "label": "Local Competitor Analysis",
    "emoji": "🏆",
    "query_tpl": 'top "{market}" companies in "{country}" market leaders competitors',
    "signal": "dominant local players",
}


# ============================================================
# Enterprise Workflow Agents
# ============================================================

ENTERPRISE_AGENTS = {
    "research_agent": {
        "label": "Research Agent",
        "emoji": "🔎",
        "skills": ["market_research", "signal_detection", "web_research"],
        "description": "Detects market-entry signals using public evidence.",
    },

    "competitor_agent": {
        "label": "Competitive Intelligence Agent",
        "emoji": "🏆",
        "skills": ["competitor_analysis", "market_positioning"],
        "description": "Analyzes local competitors and market maturity.",
    },

    "site_selection_agent": {
        "label": "Site Selection Agent",
        "emoji": "📍",
        "skills": ["location_scoring", "office_planning", "talent_analysis"],
        "description": "Recommends the best city or state for office setup.",
    },

    "incentives_agent": {
        "label": "Government Incentives Agent",
        "emoji": "🏛️",
        "skills": ["government_incentives", "tax_credits", "grants"],
        "description": "Checks government support, grants, tax credits, and local incentives.",
    },

    "finance_agent": {
        "label": "Finance / Cost Agent",
        "emoji": "💰",
        "skills": ["cost_estimation", "budget_planning", "roi_modeling"],
        "description": "Estimates first-year setup cost and financial feasibility.",
    },

    "compliance_agent": {
        "label": "Compliance Agent",
        "emoji": "⚖️",
        "skills": ["regulatory_review", "legal_risk", "policy_review"],
        "description": "Checks regulatory risk and human-review requirements.",
    },

    "red_team_agent": {
        "label": "Red Team Agent",
        "emoji": "🛡️",
        "skills": ["risk_review", "assumption_testing", "challenge_analysis"],
        "description": "Challenges assumptions before final executive decision.",
    },

    "human_approval_agent": {
        "label": "Human Approval Agent",
        "emoji": "🧑‍💼",
        "skills": ["human_review", "approval_workflow"],
        "description": "Pauses high-risk workflows for human review.",
    },

    "executive_agent": {
        "label": "Executive Decision Agent",
        "emoji": "📊",
        "skills": ["decision_synthesis", "executive_summary"],
        "description": "Combines all agent outputs into a final expansion decision.",
    },

    "task_assignment_agent": {
        "label": "Task Assignment Agent",
        "emoji": "✅",
        "skills": ["task_planning", "department_assignment"],
        "description": "Assigns execution tasks to Sales, Finance, Legal, HR, and Executive teams.",
    },
}


# ============================================================
# Regulated Markets
# ============================================================

REGULATED_MARKETS = {
    "insurance": [
        "insurance distribution licensing",
        "consumer protection",
        "data privacy",
    ],

    "finance": [
        "payments regulation",
        "KYC/AML",
        "data privacy",
    ],

    "banking": [
        "banking license",
        "KYC/AML",
        "financial regulator review",
    ],

    "healthcare": [
        "health data privacy",
        "clinical/regulatory review",
        "patient data security",
    ],

    "ai": [
        "model governance",
        "data governance",
        "AI policy compliance",
    ],

    "fintech": [
        "payments regulation",
        "KYC/AML",
        "consumer financial protection",
        "data privacy",
    ],

    "crypto": [
        "digital asset regulation",
        "KYC/AML",
        "securities law review",
        "consumer protection",
    ],
}


# ============================================================
# Location Scoring Weights
# ============================================================

LOCATION_SCORE_WEIGHTS = {
    "talent_availability": 25,
    "government_incentives": 20,
    "office_cost": 15,
    "customer_proximity": 15,
    "regulatory_friendliness": 10,
    "infrastructure": 10,
    "competition_saturation": 5,
}


# ============================================================
# Finance Cost Profiles
# ============================================================

COST_PROFILES = {
    "low": {
        "monthly_cost_per_employee": 2500,
        "one_time_setup_per_employee": 6000,
        "legal_compliance": 25000,
    },

    "medium": {
        "monthly_cost_per_employee": 4500,
        "one_time_setup_per_employee": 9000,
        "legal_compliance": 50000,
    },

    "high": {
        "monthly_cost_per_employee": 8000,
        "one_time_setup_per_employee": 14000,
        "legal_compliance": 90000,
    },
}

HIGH_COST_CITIES = {
    "san francisco",
    "new york",
    "london",
    "singapore",
    "zurich",
    "tokyo",
    "hong kong",
}

LOW_COST_CITIES = {
    "raleigh",
    "atlanta",
    "pune",
    "hyderabad",
    "chennai",
    "ahmedabad",
    "kolkata",
}


# ============================================================
# Decision Thresholds
# ============================================================

HIGH_PROBABILITY_THRESHOLD = 70
MEDIUM_PROBABILITY_THRESHOLD = 50

HIGH_COST_APPROVAL_THRESHOLD = 500_000
RED_TEAM_APPROVAL_THRESHOLD = -10

DEFAULT_HEADCOUNT = 10
DEFAULT_CONTINGENCY_RATE = 0.15


# ============================================================
# Frontend / Server Configuration
# ============================================================

APP_TITLE = "MarketOps Band"
APP_SUBTITLE = "Enterprise Market Expansion Command Center"

HOST = os.getenv("HOST", "127.0.0.1")
PORT = _env_int("PORT", 8000)


# ============================================================
# Debug
# ============================================================

DEBUG = _env_bool("DEBUG", False)

if DEBUG:
    print("========== CONFIG DEBUG ==========")
    print(f"OPENAI_MODEL={OPENAI_MODEL}")
    print(f"OPENAI_API_KEY_SET={bool(OPENAI_API_KEY)}")
    print(f"BRIGHTDATA_API_KEY_SET={bool(BRIGHTDATA_API_KEY)}")
    print(f"MOCK_MODE={MOCK_MODE}")
    print(f"LLM_MOCK_MODE={LLM_MOCK_MODE}")
    print(f"DEMO_MODE={DEMO_MODE}")
    print(f"BAND_LOCAL_MODE={BAND_LOCAL_MODE}")
    print(f"SERP_RESULTS={SERP_RESULTS}")
    print("==================================")
from pydantic import BaseModel, Field, field_validator
from typing import Optional

class AnalyzeRequest(BaseModel):
    companies:     list[str] = Field(..., example=["Stripe","Adyen"])
    target_market: str       = Field(..., min_length=1, max_length=100)
    country:       str       = Field(default="Global")

    @field_validator("companies")
    @classmethod
    def validate_companies(cls, v):
        cleaned = [c.strip() for c in v if c.strip()]
        if not cleaned:
            raise ValueError("At least one company required")
        return cleaned[:3]

class AgentResult(BaseModel):
    agent_id:  str
    label:     str
    emoji:     str
    score:     int
    max_score: int
    findings:  list[str]
    reasoning: str
    sources:   list[str]

class LocalCompetitor(BaseModel):
    name:       str
    strengths:  list[str]
    weaknesses: list[str]

class CompanyReport(BaseModel):
    company:               str
    market:                str
    country:               str
    probability:           int
    confidence:            str
    timeline:              str
    verdict:               str
    key_findings:          list[str]
    strategic_implication: str
    recommended_actions:   list[str]
    agent_results:         list[AgentResult]
    # Competitor analysis fields
    local_competitors:     list[LocalCompetitor] = []
    winning_strategy:      str = ""
    is_loser:              bool = False

class AnalyzeRequest(BaseModel):
    companies: list[str] = Field(..., example=["Stripe", "Adyen"])
    target_market: str = Field(..., min_length=1, max_length=100)
    country: str = Field(default="Global")
    headcount: int = Field(default=10, ge=1, le=500)
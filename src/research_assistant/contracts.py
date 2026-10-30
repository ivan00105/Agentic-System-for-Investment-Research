from datetime import datetime, timezone
from decimal import Decimal
from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator, model_validator


UNIVERSE = {
    "MSFT": {"name": "Microsoft", "cik": "0000789019", "sector": "Technology"},
    "AAPL": {"name": "Apple", "cik": "0000320193", "sector": "Technology"},
    "AMZN": {"name": "Amazon", "cik": "0001018724", "sector": "Consumer discretionary"},
    "GOOGL": {"name": "Alphabet", "cik": "0001652044", "sector": "Communication services"},
    "NVDA": {"name": "NVIDIA", "cik": "0001045810", "sector": "Technology"},
}
Ticker = Literal["MSFT", "AAPL", "AMZN", "GOOGL", "NVDA"]


class Record(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class ConnectionCheck(Record):
    status: Literal["not_tested", "passed", "failed"] = "not_tested"
    checked_at: AwareDatetime | None = None
    run_id: str | None = None
    message: str | None = None


class ConnectionInfo(Record):
    configured: bool
    provider: str
    model: str | None = None
    configuration_error: str | None = None
    check: ConnectionCheck = Field(default_factory=ConnectionCheck)


class Screen(Record):
    sector: Literal["All", "Technology", "Consumer discretionary", "Communication services"] = "All"
    min_operating_margin: Decimal = Field(default=Decimal("0.10"), ge=-10, le=10)
    limit: int = Field(default=3, ge=1, le=5)


class RunRequest(Record):
    kind: Literal["research", "discovery"] = "research"
    mode: Literal["fresh", "frozen", "replay"]
    ticker: Ticker | None = None
    cutoff: AwareDatetime
    source_run_id: str | None = Field(default=None, max_length=100, pattern=r"^[a-zA-Z0-9-]+$")
    screen: Screen | None = None
    model_analysis: bool = True  # Preserve older clients; the UI submits an explicit choice. Replay ignores it.
    connection_check: Literal["sec", "model"] | None = None
    spending_limit_usd: Decimal | None = Field(default=None, gt=0)
    provider_limit_confirmed: bool = False

    @model_validator(mode="after")
    def validate_request(self):
        self.cutoff = self.cutoff.astimezone(timezone.utc)
        if self.cutoff > datetime.now(timezone.utc):
            raise ValueError("Cutoff cannot be in the future.")
        if self.kind == "research" and (not self.ticker or self.screen is not None):
            raise ValueError("Research requires a supported company and no screen.")
        if self.kind == "discovery" and (self.ticker is not None or self.screen is None):
            raise ValueError("Discovery requires screening criteria and no company.")
        if self.mode in ("frozen", "replay") and not self.source_run_id:
            raise ValueError("Frozen inference and replay require a saved run.")
        if self.mode == "fresh" and self.source_run_id:
            raise ValueError("Fresh retrieval cannot use a saved run.")
        if self.connection_check == "sec" and (self.kind != "research" or self.mode != "fresh" or self.ticker != "MSFT" or self.model_analysis):
            raise ValueError("The SEC connection check retrieves Microsoft facts without model analysis.")
        if self.connection_check == "model":
            if self.kind != "research" or self.mode != "frozen" or not self.model_analysis:
                raise ValueError("The model connection check requires saved company evidence and model analysis.")
            if self.spending_limit_usd is None or not self.provider_limit_confirmed:
                raise ValueError("Set a spending allowance and confirm the provider spending limit before a model check.")
        elif self.spending_limit_usd is not None or self.provider_limit_confirmed:
            raise ValueError("Spending confirmation is only used for a model connection check.")
        return self


class Evidence(Record):
    id: str
    ticker: Ticker
    title: str
    excerpt: str
    source_url: str | None
    available_at: AwareDatetime
    retrieved_at: AwareDatetime
    period: str
    locator: str
    snapshot_hash: str
    synthetic: bool = False


class Metric(Record):
    id: str
    label: str
    value: Decimal | None
    unit: Literal["USD", "ratio"]
    period: str
    formula: str | None = None
    inputs: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    unavailable_reason: str | None = None


class Claim(Record):
    id: str
    statement: str
    kind: Literal["calculation", "interpretation", "fact"]
    status: Literal["supported", "qualified", "corrected", "unresolved"]
    evidence_ids: list[str]
    version: int = 1


class Review(Record):
    claim_id: str
    original: str
    objection: str
    check: str
    revised: str | None
    disposition: Literal["corrected", "unresolved", "unchanged"]
    evidence_ids: list[str]


class Forecast(Record):
    status: Literal["unavailable"] = "unavailable"
    probability: None = None
    benchmark: str = "SPY"
    horizon: str = "20 exchange sessions"
    model_version: str | None = None
    reason: str = "A return forecast is not available. These financial results do not predict future performance."


class CompanyReport(Record):
    ticker: Ticker
    company: str
    support: Literal["supported", "qualified", "abstained"] = "qualified"
    summary: str
    metrics: list[Metric]
    claims: list[Claim]
    reviews: list[Review]
    forecast: Forecast = Field(default_factory=Forecast)
    limitations: list[str]
    source_limitations: list[str] | None = None  # None identifies saved reports from before source/review separation.
    review_status: Literal["not_requested", "pending", "completed", "unavailable", "failed", "not_recorded"] = "not_recorded"
    review_error: str | None = None


class Candidate(Record):
    ticker: Ticker
    company: str
    sector: str
    eligibility: Literal["pass", "fail", "unknown"]
    reason: str
    operating_margin: Decimal | None
    selected: bool = False


class ModelRunInfo(Record):
    provider: str
    model: str | None
    schema_version: str = "financial-review-v1"
    max_output_tokens: int


class ModelCall(Record):
    role: str
    provider: str
    requested_model: str
    returned_model: str | None = None
    response_id: str | None = None
    input_tokens: int | None = Field(default=None, ge=0, strict=True)
    output_tokens: int | None = Field(default=None, ge=0, strict=True)
    total_tokens: int | None = Field(default=None, ge=0, strict=True)
    cost_usd: Decimal | None = Field(default=None, ge=0)
    status: Literal["completed", "failed", "incomplete"]
    error_code: str | None = None


class Report(Record):
    title: str
    synthetic: bool
    companies: list[CompanyReport] = Field(default_factory=list)
    candidates: list[Candidate] = Field(default_factory=list)
    ranking: str | None = None
    limitations: list[str] = Field(default_factory=list)
    model_run: ModelRunInfo | None = None
    model_calls: list[ModelCall] = Field(default_factory=list)


class Action(Record):
    sequence: int
    at: AwareDatetime
    role: str
    message: str


class RunMetadataPatch(Record):
    label: str | None = Field(default=None, max_length=120)
    archived: bool = Field(default=False, strict=True)

    @field_validator("label", mode="before")
    @classmethod
    def normalize_label(cls, value):
        return value.strip() or None if isinstance(value, str) else value

    @model_validator(mode="after")
    def require_change(self):
        if not self.model_fields_set:
            raise ValueError("Provide a name or archive state to update.")
        return self


class Run(Record):
    id: str
    request: RunRequest
    status: Literal["queued", "running", "completed", "failed", "budget_exhausted", "interrupted"]
    created_at: AwareDatetime
    updated_at: AwareDatetime
    stage: str
    actions: list[Action] = Field(default_factory=list)
    report: Report | None = None
    error: str | None = None
    synthetic: bool = False
    label: str | None = None
    archived: bool = False


class DomainError(Exception):
    def __init__(self, message: str, code: str = "invalid_request", status: int = 422):
        super().__init__(message)
        self.code, self.status = code, status


def utcnow():
    return datetime.now(timezone.utc)

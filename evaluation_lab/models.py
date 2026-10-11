from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue, StrictBool, model_validator

SCORER_VERSION = "1.0.0"


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False, validate_default=True)


class Document(Contract):
    id: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,80}$")
    text: str = Field(min_length=1, max_length=20_000)


class Inputs(Contract):
    question: str = Field(min_length=1, max_length=5000)
    documents: list[Document] = Field(default_factory=list, max_length=100)
    payload: dict[str, JsonValue] = Field(default_factory=dict)

    @model_validator(mode="after")
    def unique_documents(self):
        if len({d.id for d in self.documents}) != len(self.documents):
            raise ValueError("Document IDs must be unique")
        return self


class ToolCall(Contract):
    name: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,80}$")
    arguments: dict[str, JsonValue] = Field(default_factory=dict)


class Reference(Contract):
    answer_contains: list[str] = Field(default_factory=list)
    relevant_document_ids: list[str] = Field(default_factory=list)
    expected_tools: list[ToolCall] = Field(default_factory=list)
    tool_order: Literal["ordered", "unordered"] = "ordered"
    forbidden_tools: list[str] = Field(default_factory=list)


class Case(Contract):
    schema_version: Literal["1.0"] = "1.0"
    id: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,80}$")
    task: Literal["rag", "agent", "abstention"]
    inputs: Inputs
    reference: Reference
    tags: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def check_reference(self):
        known = {d.id for d in self.inputs.documents}
        relevant = self.reference.relevant_document_ids
        if len(set(relevant)) != len(relevant) or not set(relevant) <= known:
            raise ValueError("Relevant document IDs must be unique and present in inputs")
        if self.task == "rag" and (not relevant or not self.reference.answer_contains):
            raise ValueError("RAG cases require relevant documents and answer phrases")
        if any(not s.strip() for s in self.reference.answer_contains):
            raise ValueError("Reference phrases must not be blank")
        if any(t.name in self.reference.forbidden_tools for t in self.reference.expected_tools):
            raise ValueError("Expected tools cannot also be forbidden")
        return self


class Prediction(Contract):
    answer: str = Field(min_length=1, max_length=30_000)
    retrieved_ids: list[str] = Field(default_factory=list, max_length=100)
    tool_calls: list[ToolCall] = Field(default_factory=list, max_length=100)
    abstained: StrictBool = False


class Metric(Contract):
    name: str
    score: float | None = Field(default=None, ge=0, le=1)
    threshold: float = Field(default=1, ge=0, le=1)
    reason: str
    error: str | None = None

    @property
    def passed(self):
        return self.error is None and self.score is not None and self.score >= self.threshold


class RunConfig(Contract):
    target: str
    repetitions: int = Field(default=1, ge=1, le=20)
    timeout_seconds: float = Field(default=10, gt=0, le=600)
    latency_budget_ms: float = Field(default=2000, gt=0, le=600_000)
    grounding_threshold: float = Field(default=0.8, ge=0, le=1)
    judge_model: str | None = None
    judge_url: str = "http://localhost:11434"
    judge_timeout_seconds: float = Field(default=30, gt=0, le=120)


class CaseResult(Contract):
    case_id: str
    repetition: int = Field(ge=0)
    status: Literal["ok", "error", "timeout"]
    prediction: Prediction | None = None
    latency_ms: float | None = Field(default=None, ge=0)
    wall_ms: float = Field(ge=0)
    metrics: list[Metric] = Field(default_factory=list)
    error_type: str | None = None

    @property
    def passed(self):
        return self.status == "ok" and bool(self.metrics) and all(m.passed for m in self.metrics)


class Report(Contract):
    schema_version: Literal["1.0"] = "1.0"
    scorer_version: str = SCORER_VERSION
    run_id: str
    created_at: str
    dataset_sha256: str
    scoring_sha256: str
    config: RunConfig
    cases: list[Case]
    results: list[CaseResult]

    @model_validator(mode="after")
    def complete_results(self):
        if not self.cases or len({c.id for c in self.cases}) != len(self.cases):
            raise ValueError("Reports require a nonempty set of unique cases")
        expected = {(c.id, r) for c in self.cases for r in range(self.config.repetitions)}
        actual = [(r.case_id, r.repetition) for r in self.results]
        if len(actual) != len(set(actual)) or set(actual) != expected:
            raise ValueError("Report has missing, duplicated or unexpected results")
        return self

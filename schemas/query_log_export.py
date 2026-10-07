"""Private query_log rows for offline review; returned course IDs are never ground truth."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from schemas.feedback_candidate import RetrievalMode, TrafficKind, text_sha256

QueryReviewRequirement = Literal[
    'privacy_review_required', 'results_not_ground_truth', 'no_retrieval_snapshot',
    'missing_request_context', 'missing_history_content', 'unverified_traffic_origin',
    'unknown_retrieval_mode',
]


class PrivateQueryText(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    query: str = Field(min_length=1, max_length=500, repr=False)
    rejection_reason: str | None = Field(min_length=1, max_length=1000, repr=False)


class QueryLogExportRow(BaseModel):
    """query_log keeps no filters, chat history or index snapshot; the gaps stay on every row."""

    model_config = ConfigDict(extra='forbid', strict=True)
    format_version: Literal['1'] = '1'
    log_id: int = Field(gt=0)
    created_at: str
    route: Literal['search', 'chat']
    traffic_kind: TrafficKind
    eval_run_sha256: str | None = Field(default=None, pattern=r'^[0-9a-f]{64}$')
    retrieval_mode: RetrievalMode
    k: int | None = Field(ge=1, le=50)
    latency_ms: float | None = Field(ge=0, allow_inf_nan=False)
    result_course_ids: list[str]
    query_sha256: str = Field(pattern=r'^[0-9a-f]{64}$')
    review_state: Literal['pending'] = 'pending'
    ground_truth: Literal[False] = False
    review_requirements: list[QueryReviewRequirement]
    private_text: PrivateQueryText | None = Field(default=None, repr=False)

    @field_validator('ground_truth', mode='before')
    @classmethod
    def strictly_false(cls, value):
        if value is not False:
            raise ValueError('Query rows cannot be ground truth')
        return value

    @field_validator('created_at')
    @classmethod
    def utc_timestamp(cls, value):
        parsed = datetime.strptime(value, '%Y-%m-%dT%H:%M:%SZ')
        if parsed.strftime('%Y-%m-%dT%H:%M:%SZ') != value:
            raise ValueError('Canonical UTC timestamp required')
        return value

    @model_validator(mode='after')
    def provenance_consistency(self):
        if (self.traffic_kind == 'eval') != (self.eval_run_sha256 is not None):
            raise ValueError('Evaluation group must follow original traffic kind')
        required = {'privacy_review_required', 'results_not_ground_truth', 'no_retrieval_snapshot',
                    'missing_request_context'}
        if self.route == 'chat':
            required.add('missing_history_content')
        if self.traffic_kind != 'eval':
            required.add('unverified_traffic_origin')
        if self.retrieval_mode == 'unknown':
            required.add('unknown_retrieval_mode')
        if set(self.review_requirements) != required or len(self.review_requirements) != len(required):
            raise ValueError('Review requirements must retain provenance gaps')
        if self.private_text is not None and text_sha256(self.private_text.query) != self.query_sha256:
            raise ValueError('Private text must match the query hash')
        return self

"""Private, pending-review snapshots; usefulness votes are never ground truth."""

from datetime import datetime
import hashlib
import json
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from schemas.answer_feedback import MAX_ANSWER_CHARS

TrafficKind = Literal['unmarked', 'eval', 'unknown']
RetrievalMode = Literal['alias', 'hybrid', 'hyde_rescued', 'context', 'program', 'empty', 'rejected', 'unknown']
ReviewRequirement = Literal[
    'privacy_review_required', 'usefulness_not_ground_truth', 'unverified_traffic_origin',
    'missing_request_context', 'missing_history_content', 'no_retrieval_snapshot',
    'unknown_retrieval_mode',
]


def text_sha256(text: str) -> str:
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def context_sha256(context: dict) -> str:
    return text_sha256(json.dumps(context, ensure_ascii=False, sort_keys=True, separators=(',', ':')))


class ReviewRequestContext(BaseModel):
    """Only fields captured by 06B; absent fields remain unknown, not defaults."""

    model_config = ConfigDict(extra='forbid', strict=True)
    k: int | None = Field(default=None, ge=1, le=20)
    term: str | None = None
    credits: int | None = Field(default=None, ge=0, le=12)
    delivery_mode: str | None = None
    professor: str | None = None
    program_id: str | None = Field(default=None, min_length=1, max_length=64)
    context_course_ids: list[str] | None = Field(default=None, max_length=10)
    history_turn_count: int | None = Field(default=None, ge=0, le=12)

    @model_validator(mode='before')
    @classmethod
    def nonnullable_when_recorded(cls, value):
        if isinstance(value, dict) and any(
            key in value and value[key] is None for key in ('k', 'context_course_ids', 'history_turn_count')
        ):
            raise ValueError('Recorded counters must have explicit values')
        return value


class PrivateCandidateText(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    query: str = Field(min_length=1, max_length=500, repr=False)
    answer: str = Field(min_length=1, max_length=MAX_ANSWER_CHARS, repr=False)
    request_context: dict[str, Any] = Field(repr=False)

    @field_validator('answer')
    @classmethod
    def nonblank_answer(cls, value):
        if not value.strip():
            raise ValueError('Completed answer required')
        return value

    @field_validator('request_context')
    @classmethod
    def bounded_whitelisted_context(cls, value):
        ReviewRequestContext.model_validate(value)
        if len(json.dumps(value, ensure_ascii=False, sort_keys=True)) > 8192:
            raise ValueError('Context outside capture budget')
        return value


class FeedbackCandidate(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    format_version: Literal['1'] = '1'
    answer_id: str = Field(pattern=r'^[0-9a-f]{32}$')
    query_log_id: int = Field(gt=0)
    source_revision: str = Field(pattern=r'^[0-9a-f]{64}$')
    query_sha256: str = Field(pattern=r'^[0-9a-f]{64}$')
    answer_sha256: str = Field(pattern=r'^[0-9a-f]{64}$')
    request_context_sha256: str = Field(pattern=r'^[0-9a-f]{64}$')
    prompt_version: str = Field(min_length=1, max_length=64)
    rating: Literal['up', 'down']
    traffic_kind: TrafficKind
    eval_run_sha256: str | None = Field(default=None, pattern=r'^[0-9a-f]{64}$')
    retrieval_mode: RetrievalMode
    result_course_ids: list[str]
    query_created_at: str
    answer_created_at: str
    feedback_created_at: str
    feedback_updated_at: str
    context_status: Literal['recorded', 'missing']
    history_turn_count: int | None = Field(ge=0, le=12)
    context_course_count: int | None = Field(ge=0, le=10)
    review_state: Literal['pending'] = 'pending'
    ground_truth: Literal[False] = False
    review_requirements: list[ReviewRequirement]
    private_text: PrivateCandidateText | None = Field(default=None, repr=False)

    @field_validator('ground_truth', mode='before')
    @classmethod
    def strictly_false(cls, value):
        if value is not False:
            raise ValueError('Candidates cannot be ground truth')
        return value

    @field_validator('query_created_at', 'answer_created_at', 'feedback_created_at', 'feedback_updated_at')
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
        times = [self.query_created_at, self.answer_created_at, self.feedback_created_at, self.feedback_updated_at]
        if times != sorted(times):
            raise ValueError('Source timestamps are inconsistent')
        required = {'privacy_review_required', 'usefulness_not_ground_truth', 'no_retrieval_snapshot'}
        if self.traffic_kind != 'eval':
            required.add('unverified_traffic_origin')
        if self.context_status == 'missing':
            required.add('missing_request_context')
        if self.history_turn_count is None or self.history_turn_count > 0:
            required.add('missing_history_content')
        if self.retrieval_mode == 'unknown':
            required.add('unknown_retrieval_mode')
        if set(self.review_requirements) != required or len(self.review_requirements) != len(required):
            raise ValueError('Review requirements must retain provenance gaps')
        if self.private_text is not None:
            private = self.private_text
            if (text_sha256(private.query) != self.query_sha256
                or text_sha256(private.answer) != self.answer_sha256
                or context_sha256(private.request_context) != self.request_context_sha256):
                raise ValueError('Private text must match the snapshot hashes')
            context = ReviewRequestContext.model_validate(private.request_context)
            count = len(context.context_course_ids) if context.context_course_ids is not None else None
            status = 'recorded' if set(private.request_context) == set(ReviewRequestContext.model_fields) else 'missing'
            if (context.history_turn_count != self.history_turn_count
                or count != self.context_course_count or status != self.context_status):
                raise ValueError('Private context must match provenance counters')
        return self

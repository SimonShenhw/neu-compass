"""Private completed-answer receipt; no user ID, raw query or free-text vote."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

MAX_ANSWER_CHARS = 64000
FEEDBACK_TTL_SECONDS = 7 * 24 * 60 * 60


class AnswerFeedbackReceipt(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    answer_id: str = Field(pattern=r'^[0-9a-f]{32}$')
    answer_sha256: str = Field(pattern=r'^[0-9a-f]{64}$')
    feedback_token: str = Field(pattern=r'^[A-Za-z0-9_-]{43}$', repr=False)


class AnswerFeedbackRequest(AnswerFeedbackReceipt):
    rating: Literal['up', 'down']


class AnswerFeedbackResponse(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    answer_id: str = Field(pattern=r'^[0-9a-f]{32}$')
    rating: Literal['up', 'down']

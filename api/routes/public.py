"""GET /privacy and GET /config: what the web front end shows and needs, from the API's own settings (R2a).

The privacy words come from api/privacy_text.py, the same functions the Streamlit page uses; here they are built from
the API's settings, so the page says what the API that keeps the data actually does. Both routes are public, read only
and the same for everyone.

中文：GET /privacy 和 GET /config：新前端要显示的内容和要知道的设置，按 API 自己的设置生成（R2a）。隐私页的文字来自
api/privacy_text.py，和 Streamlit 页用的是同一批函数；这里按 API 的设置生成，所以页面写的就是保存数据的这个 API 实际
怎么做。两个接口都公开、只读，对谁都一样。
"""

from __future__ import annotations

from fastapi import APIRouter

from api.models import PrivacyResponse, PrivacySectionOut, PublicConfigResponse
from api.privacy_text import DELETE_WHAT, INTRO, QUERY_LOG_NOTICE_BASE, capture_notice, privacy_sections
from api.routes.auth import login_configured
from config import settings

router = APIRouter(tags=["public"])


@router.get(
    "/privacy",
    response_model=PrivacyResponse,
    summary="The 数据与隐私 page, from the API's own settings (R2a)",
    description=(
        "The sections of the privacy page (heading and plain-text sentences, in page order), the note on what an "
        "account deletion removes, and the two notices next to the ask box. Built from this API's "
        "QUERY_LOG_RETENTION_DAYS, ANSWER_FEEDBACK_ENABLED and PRIVACY_CONTACT_EMAIL; `capture_notice` is null "
        "while answer feedback is off. The front end adds its own pointer to the page after `query_log_notice`."
    ),
)
def privacy() -> PrivacyResponse:
    return PrivacyResponse(
        intro=INTRO,
        sections=[PrivacySectionOut(heading=heading, sentences=sentences)
                  for heading, sentences in privacy_sections(settings)],
        delete_what=DELETE_WHAT,
        query_log_notice=QUERY_LOG_NOTICE_BASE,
        capture_notice=capture_notice(settings.query_log_retention_days)
        if settings.answer_feedback_enabled is True else None,
    )


@router.get(
    "/config",
    response_model=PublicConfigResponse,
    summary="What the web front end needs to know about this API (R2a)",
    description=(
        "`answer_feedback_enabled`: whether to show the opt-in and the votes. `login_available`: Google's client ID "
        "and secret and a SESSION_SECRET are all configured, so `/auth/login-url` and the cookie login work (the "
        "same condition as login-url's 503)."
    ),
)
def public_config() -> PublicConfigResponse:
    return PublicConfigResponse(
        answer_feedback_enabled=settings.answer_feedback_enabled is True,
        login_available=login_configured(),
    )

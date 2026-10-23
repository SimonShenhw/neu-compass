"""Moved to api/session_tokens.py in R2a (2026-10-22). The same functions, re-exported for the Streamlit UI until it is
retired; new code imports from api.session_tokens.

中文：R2a（2026-10-22）搬到了 api/session_tokens.py。这里转发的是同一批函数，给 Streamlit 版用到它退役为止；新代码从
api.session_tokens 导入。
"""

from api.session_tokens import issue_session_token, verify_session_token

__all__ = ["issue_session_token", "verify_session_token"]

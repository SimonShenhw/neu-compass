"""Streamlit Co-op page: progressive-unlock listing of NEU Co-op rows.

Run:
    uv run streamlit run app/coop_view.py

Tier model (PLAN §6.4 give-to-get gate, ADR §3.4):
  level 0: company + role + term + duration  (visible to everyone)
  level 1: + interview_summary + technical_questions
           (requires user.contribution_count >= 1)
  level 2: + salary_range_usd
           (requires user.contribution_count >= 2)

The API does the actual filtering — it returns only rows whose
visibility_level is ≤ user.contribution_count. We render whatever it gives
us. For locked tiers, we show a placeholder "🔒 Contribute to unlock".

Upload form is inline at the bottom; on submit it POSTs to /coop, which
applies k-anonymity (k=2) before persisting. UI surfaces the 422 detail
verbatim if the row would be uniquely identifying.
"""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def render() -> None:
    """Render the Co-op page. Lazily imports Streamlit so tests can `import
    app.coop_view` without spinning up Streamlit's session machinery."""
    import streamlit as st  # noqa: PLC0415

    from app.api_client import ApiClient, ApiError  # noqa: PLC0415
    from app.state_manager import init_state, is_logged_in  # noqa: PLC0415
    from app.streamlit_auth_ui import (  # noqa: PLC0415
        handle_oauth_callback,
        render_auth_sidebar,
    )

    st.set_page_config(page_title="NEU-Compass · Co-op", layout="wide")
    init_state(st.session_state)
    handle_oauth_callback()
    render_auth_sidebar()

    st.title("📊 NEU Co-op Experiences")
    st.caption("PII k=2 anonymity enforced server-side. F1 合规.")

    user_id = st.session_state.get("user_id")
    if not is_logged_in(st.session_state):
        st.info(
            "Browsing as guest — only preview-tier rows visible. "
            "Log in to see interview details + salary buckets after contributing."
        )

    # === Listing ===
    with ApiClient(user_id=user_id) as api:
        try:
            coops = api.list_coop()
        except ApiError as e:
            st.error(f"Could not load Co-op listing: {e.detail}")
            coops = []

    if not coops:
        st.warning("No Co-op records to show yet. Be the first to contribute!")
    else:
        for c in coops:
            with st.container(border=True):
                cols = st.columns([3, 1])
                cols[0].markdown(
                    f"**{c['company']}** — {c['role']}"
                    + (f" · {c['coop_term']}" if c.get("coop_term") else "")
                )
                cols[1].markdown(f"`level {c['visibility_level']}`")

                if c.get("industry"):
                    st.caption(f"Industry: {c['industry']}")
                if c.get("duration_months"):
                    st.caption(f"Duration: {c['duration_months']} months")

                # Detail tier
                if c.get("interview_summary"):
                    with st.expander("Interview summary"):
                        st.markdown(c["interview_summary"])
                if c.get("technical_questions"):
                    with st.expander("Technical questions"):
                        st.markdown(c["technical_questions"])

                # Premium tier
                if c.get("salary_range_usd"):
                    st.markdown(f"💰 **Compensation**: {c['salary_range_usd']}")

    # === Upload form (logged-in users only) ===
    st.divider()
    st.subheader("Submit a Co-op record")

    if not is_logged_in(st.session_state):
        st.info("Log in with your NEU email to submit a Co-op record.")
        return

    with st.form("coop_upload"):
        company = st.text_input("Company *")
        role = st.text_input("Role *")
        coop_term = st.text_input("Co-op term (e.g. 'Summer 2025')")
        # format_func renders None as a clear "(unspecified)" prompt instead
        # of the literal string "None" — users were confused thinking they
        # had to pick "None" as an explicit value.
        industry = st.selectbox(
            "Industry",
            options=[None, "quant_fintech", "big_tech", "biotech_health",
                     "startup", "consulting", "other"],
            format_func=lambda x: (
                "(unspecified)" if x is None
                else x.replace("_", " ").title()
            ),
        )
        duration_months = st.number_input(
            "Duration (months)", min_value=1, max_value=8, value=6, step=1,
        )
        related_courses = st.text_input(
            "Related courses (comma-separated codes, e.g. 'AAI 6600, DS 5220')"
        )
        interview_summary = st.text_area(
            "Interview summary (already PII-redacted)", max_chars=10_000,
        )
        technical_questions = st.text_area(
            "Technical questions (already PII-redacted)", max_chars=10_000,
        )
        salary_range_usd = st.text_input(
            "Salary bucket (e.g. '$30-35/hr') — optional"
        )

        submitted = st.form_submit_button("Submit")
        if submitted:
            payload: dict = {
                "company": company.strip(),
                "role": role.strip(),
                "coop_term": coop_term.strip() or None,
                "industry": industry,
                "duration_months": int(duration_months) if duration_months else None,
                "related_courses": [
                    c.strip() for c in related_courses.split(",") if c.strip()
                ],
                "interview_summary": interview_summary.strip() or None,
                "technical_questions": technical_questions.strip() or None,
                "salary_range_usd": salary_range_usd.strip() or None,
            }
            with ApiClient(user_id=user_id) as api:
                try:
                    resp = api.upload_coop(payload)
                    st.success(
                        f"Submitted as `{resp['coop_id']}` "
                        f"(level {resp['visibility_level']})."
                    )
                except ApiError as e:
                    if e.status_code == 422:
                        st.error(
                            f"Submission rejected: {e.detail}\n\n"
                            "Try generalizing one field (e.g. industry bucket "
                            "instead of company name) and resubmit."
                        )
                    else:
                        st.error(f"Submission failed: {e.detail}")


if __name__ == "__main__" or "streamlit" in sys.argv[0].lower():
    render()

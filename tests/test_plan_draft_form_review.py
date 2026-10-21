"""AppTest widget values alone do not prove the browser's clear-on-submit policy."""

from tests import test_plan_draft_view as view

backend = view.backend


def test_draft_form_protocol_preserves_text_after_unsuccessful_submit(backend):
    app = view.page()
    forms = app.get("form")
    assert len(forms) == 1 and forms[0].proto.form.form_id == "plan-draft-form"
    assert forms[0].proto.form.clear_on_submit is False

    view.add(app, "<b>bad</b>")
    assert not backend["calls"] and not app.session_state["plan_draft_courses"]
    assert app.get("form")[0].proto.form.clear_on_submit is False

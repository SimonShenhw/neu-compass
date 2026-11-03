"""Batch T, policy P2: the 数据与隐私 page (api/privacy_text.py, which GET /privacy serves) says what the code does,
and its variable parts follow the settings.

Synthetic settings only. 中文：「数据与隐私」页的文字说的就是代码的做法，可变的部分跟着设置。只用合成设置。
"""

from types import SimpleNamespace

import pytest

from api.privacy_text import BACKUP_COPIES, DELETE_WHAT, capture_notice, privacy_sections

CONTACT = "synthetic.student@northeastern.edu"


def page_text(days=90, feedback=True, contact=CONTACT):
    settings = SimpleNamespace(query_log_retention_days=days, answer_feedback_enabled=feedback,
                               privacy_contact_email=contact)
    return "\n".join(f"{heading}: {sentence}" for heading, sentences in privacy_sections(settings) for sentence in sentences)


def test_the_configured_policy_is_what_the_page_says():
    text = page_text()
    lines = text.splitlines()
    assert "原文保存 90 天，到期以后换成一段带密钥的哈希" in text and "提问原文：90 天，到期换成哈希。" in text
    assert "登录了也不记是谁问的" in text and "Gemini" in text and "Cloudflare" in text
    assert "勾选「允许保存」以后，回答和你的 👍／👎 才会保存，同样不记是谁" in text
    assert "留多久: 保存的回答和评价：90 天后删除。" in lines and "想删除可以写邮件联系" not in text
    assert f"写邮件到 {CONTACT}" in text and "本页最下面删除你的账号和 Co-op 投稿" in text
    assert f"留多久: 每日备份保留 {BACKUP_COPIES} 份，所以到期清理掉的内容，在备份里最多再多留大约两周。" in lines


def test_the_page_says_what_a_redacted_row_keeps_and_who_else_sees_what():
    """A24 L6 and its NITs: the row keeps more than a count, k=2 counts contributors, published Co-op is shown to
    visitors, and Cloudflare sees the traffic. 中文：换过的那一行还留着什么、k=2 数的是投稿人、谁还能看到。"""
    text = page_text()
    assert "那一行还留着时间、搜到的课程和检索方式，用来统计。" in text
    assert "至少有两个不同投稿人的投稿通过审核，才一起公开" in text
    assert "公开的 Co-op 经验按贡献等级给访客看" in text and "Cloudflare 能看到传输的内容" in text
    # A24 L1 (pinned in test_api_auth_route.py) and the recheck's NIT-R3. 中文：A24 L1 和复核的 NIT-R3。
    assert "登录只记学校域名和贡献数，不记是谁。" in text and "以及第一次和最近一次登录的时间" in text
    assert "贡献数和登录时间" in DELETE_WHAT


def test_the_page_says_how_google_treats_the_paid_api():
    """The user confirmed a paid key on 10-21; the sentence follows the Gemini API terms for paid services.
    中文：用户 10-21 确认是付费的 key；这句照 Gemini API 条款里付费服务的做法写。"""
    text = page_text()
    assert "本站用的是付费的 Gemini API" in text and "不会被拿去改进 Google 的产品" in text
    assert "保留一段有限的时间，只用来发现和防止违规使用、维护安全，以及法律或监管要求的披露" in text
    # Not tied to the retention period, and Google's agents count too (A24 recheck 2, NIT-G). 中文：存放地点不绑在保留期上。
    gemini = next(line for line in text.splitlines() if "付费的 Gemini API" in line)
    assert "可能临时存放或缓存在 Google 或其代理设有设施的任何国家" in gemini and "期间" not in gemini
    assert "具体以 Google 的条款为准" in text


def test_a_switched_off_cleanup_or_feedback_is_never_promised():
    off = page_text(days=0, feedback=False, contact=None)
    assert "目前没有自动清理提问原文" in off and "提问原文：目前没有自动清理。" in off
    assert "到期" not in off and "那一行还留着" not in off
    assert f"留多久: 每日备份保留 {BACKUP_COPIES} 份，大约两周。" in off.splitlines()
    assert "回答反馈功能目前关闭：回答不保存。" in off and "保存的回答" not in off
    assert "写邮件" not in off and "@" not in off


@pytest.mark.parametrize(("days", "contact", "line"), [
    (90, CONTACT, "保存的回答和评价：90 天后删除。"),
    (90, None, "保存的回答和评价：90 天后删除。"),
    (30, CONTACT, "保存的回答和评价：30 天后删除。"),
    (0, CONTACT, "保存的回答和评价：目前没有自动清理；想删除可以写邮件联系。"),
    (0, None, "保存的回答和评价：目前没有自动清理。"),
])
def test_the_saved_answer_line_follows_the_retention_and_the_contact(days, contact, line):
    """The same task deletes saved answers after the same period (the user chose this on 10-21)."""
    assert [s for s in page_text(days=days, contact=contact).splitlines() if "保存的回答和评价" in s] == [f"留多久: {line}"]


@pytest.mark.parametrize(("days", "feedback", "line"), [
    (90, True, "提问和保存的回答都不记是谁（登录了也一样），挑不出哪一条是你的，只能等到期清理。"),
    (90, False, "提问都不记是谁（登录了也一样），挑不出哪一条是你的，只能等到期清理。"),
    (0, True, "提问和保存的回答都不记是谁（登录了也一样），挑不出哪一条是你的，目前也没有自动清理。"),
])
def test_the_delete_section_says_what_carries_no_account(days, feedback, line):
    assert f"怎么删: {line}" in page_text(days=days, feedback=feedback).splitlines()


@pytest.mark.parametrize("days", [90, 30, 0])
def test_the_consent_notice_says_the_same_retention_as_the_page(days):
    """A24 M1: the notice next to the opt-in and the page read the same setting (GET /privacy serves both).
    中文：勾选旁的说明和页面读同一个设置（GET /privacy 两个都给）。"""
    notice, page = capture_notice(days), page_text(days=days)
    if days:
        assert f"保存的回答和评价 {days} 天后删除" in notice and "不会自动删除" not in notice.split("已经导出")[0]
        assert "每日备份里最多再留大约两周" in notice and "在备份里最多再多留大约两周" in page
        assert "已经导出的文件不会自动删除" in notice  # B24: the clause is pinned too. 中文：这一句也钉住。
        assert f"保存的回答和评价：{days} 天后删除。" in page
    else:
        assert "数据、备份和导出不会自动删除" in notice and "保存的回答和评价：目前没有自动清理" in page


def test_the_deletion_warning_names_the_withdrawal_and_what_it_cannot_reach():
    assert "只剩一个人的，那份也会撤回" in DELETE_WHAT and "提问和保存的回答本来就不和账号关联，不受影响" in DELETE_WHAT


def test_backup_count_matches_the_backup_sidecar():
    import importlib.util
    from pathlib import Path

    path = Path(__file__).resolve().parent.parent / "scripts" / "backup_daemon.py"
    spec = importlib.util.spec_from_file_location("backup_daemon_for_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.KEEP == BACKUP_COPIES


def compose_environment(service):
    from pathlib import Path

    from eval.route_world import _unquote, _yaml_block

    lines = (Path(__file__).resolve().parent.parent / "docker-compose.yml").read_text(encoding="utf-8").splitlines()
    pairs = [item.partition(":") for item in _yaml_block(lines, ("services", service, "environment"))]
    return {_unquote(key.strip()): _unquote(value.strip()) for key, _, value in pairs}


def test_compose_gives_the_api_the_policy_the_page_states():
    from config.settings import Settings

    api = compose_environment("api")
    # GET /privacy (R2a) builds the page from the api's own settings. 中文：GET /privacy 按 api 自己的设置生成这一页。
    assert (api["QUERY_LOG_RETENTION_DAYS"], api["ANSWER_FEEDBACK_ENABLED"], api["MODEL_DAILY_CALL_LIMIT"],
            api["REQUEST_GUARD_ENABLED"]) == ("90", "true", "200", "true")
    assert Settings(privacy_contact_email=api["PRIVACY_CONTACT_EMAIL"]).privacy_contact_email == api["PRIVACY_CONTACT_EMAIL"]


@pytest.mark.parametrize("value", ["a@b", "<x>@example.com", "x y@example.com", "x@example", "[x](y)@example.com"])
def test_contact_setting_rejects_values_that_are_not_a_plain_address(monkeypatch, value):
    from config.settings import Settings
    from pydantic import ValidationError

    monkeypatch.setenv("PRIVACY_CONTACT_EMAIL", value)
    with pytest.raises(ValidationError):
        Settings()
    monkeypatch.setenv("PRIVACY_CONTACT_EMAIL", CONTACT)
    assert Settings().privacy_contact_email == CONTACT


@pytest.mark.parametrize("value", ["", "   "])
def test_a_blank_contact_setting_is_unset_and_still_starts(monkeypatch, value):
    """The .env.example line uncommented as written (B24): unset, so the page hides the line. 中文：空值就是没设。"""
    from config.settings import Settings

    monkeypatch.setenv("PRIVACY_CONTACT_EMAIL", value)
    assert Settings().privacy_contact_email is None
    assert "写邮件" not in page_text(contact=Settings().privacy_contact_email)

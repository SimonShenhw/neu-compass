"""The words of the 数据与隐私 page and of the notices next to the ask box (batch T, moved here in R2a).

One copy for both front ends: `GET /privacy` builds them from the API's own settings (api/routes/public.py), and the
Streamlit page (app/privacy_view.py, app/answer_feedback_view.py) from the UI's. Every sentence follows what the code
does today, and the variable parts come from QUERY_LOG_RETENTION_DAYS, ANSWER_FEEDBACK_ENABLED and
PRIVACY_CONTACT_EMAIL, so the page cannot promise a cleanup that is switched off. Plain text only: nothing here comes
from a user, and the contact address is shown as written. No legal promises; it describes practice. Words that point at
one layout ("见左侧……") stay with that front end.

中文：「数据与隐私」页和提问框旁边那两段说明的文字（T 批，R2a 搬到这里）。两个前端共用一份：`GET /privacy` 按 API
自己的设置生成（api/routes/public.py），Streamlit 页（app/privacy_view.py、app/answer_feedback_view.py）按 UI 的设置
生成。每句话都对应代码现在的做法，可变的部分取自 QUERY_LOG_RETENTION_DAYS、ANSWER_FEEDBACK_ENABLED 和
PRIVACY_CONTACT_EMAIL，所以页面不会承诺一个没打开的清理。只用纯文字：这里没有用户输入，联系邮箱原样显示。不做法律
意义上的承诺，只写实际做法。指向某种布局的字（「见左侧……」）留在那个前端里。
"""

from __future__ import annotations

from typing import Any

BACKUP_COPIES = 14  # scripts/backup_daemon.py KEEP. 中文：与 scripts/backup_daemon.py 的 KEEP 一致。
INTRO = "这里写的是本站现在的实际做法，不是法律意义上的承诺。"
# Shown before the ask box (06C-1). The query log has no answer column, so with capture off no answer text is kept.
# Each front end adds its own pointer to the page. 中文：显示在提问框之前（06C-1）。查询日志没有回答列，所以关闭保存时
# 不会留下回答内容。指向隐私页的那半句由各自的前端接上。
QUERY_LOG_NOTICE_BASE = "你的提问原文会记进不公开的查询日志。请不要输入个人信息或密码之类的秘密。"


def capture_notice(days):
    """The consent notice next to the opt-in. Its retention sentence follows QUERY_LOG_RETENTION_DAYS, the same setting
    the 数据与隐私 page reads (batch T), so the two never disagree. 中文：勾选框旁边的说明；保留期那一句跟着
    QUERY_LOG_RETENTION_DAYS，和「数据与隐私」页读同一个设置，两边不会说得不一样。"""
    keep = (f'保存的回答和评价 {days} 天后删除，每日备份里最多再留大约两周，已经导出的文件不会自动删除；'
            '7 天只是投票凭证的有效期；' if days else
            '7 天只是投票凭证的有效期，数据、备份和导出不会自动删除；')
    return ('勾不勾选都不影响上面的查询日志。'
            '勾选后，如果服务可用，本次会话之后正常完成的回答和筛选条件会不公开地保存下来，'
            '即使你不点击 👍／👎 也会保存；对话历史只多记轮数，不多存完整历史文本。'
            + keep + '取消勾选、清空对话或登出都不会删除已经保存的数据。')


def privacy_sections(settings: Any, *, web: bool = False) -> list[tuple[str, list[str]]]:
    """(heading, sentences) in page order; a pure function of the settings. `web`: for the web front end, where each
    course page has its own address, so the browser's history keeps the courses opened (R3e); the Streamlit page never
    puts a course in its address. 中文：按页面顺序的（标题，句子）。`web`：给新前端用，那里每门课的页面有自己的网址，
    浏览器历史会记下打开过的课（R3e）；Streamlit 页的网址里从不放课。"""
    days = settings.query_log_retention_days
    feedback = settings.answer_feedback_enabled is True
    contact = settings.privacy_contact_email
    kept = [
        "你每次搜索和提问的原文，会存进不公开的查询日志。日志不和你的账号关联：登录了也不记是谁问的。",
        (f"原文保存 {days} 天，到期以后换成一段带密钥的哈希；那一行还留着时间、搜到的课程和检索方式，用来统计。" if days
         else "目前没有自动清理提问原文。"),
        "运行日志里，提问只记带密钥的哈希和长度，不记原文；登录只记学校域名和贡献数，不记是谁。",
        ("回答由 Google 的 Gemini 生成：你的问题、这次对话最近几轮和检索到的课程信息会发给 Gemini。"
         "个别搜索在判断要不要放弃时，也会把问题发给 Gemini 再确认一次。"
         # The user confirmed a paid key on 10-21; the Gemini API terms say how Google treats paid traffic. A free key
         # would need this sentence changed. 中文：用户 10-21 确认是付费的 key；换成免费档要改这句。
         "本站用的是付费的 Gemini API：按 Google 的条款，这些内容不会被拿去改进 Google 的产品；Google 会把它们保留一段有限的时间，"
         "只用来发现和防止违规使用、维护安全，以及法律或监管要求的披露。这些内容可能临时存放或缓存在 Google 或其代理设有设施的任何国家。"
         "具体以 Google 的条款为准。"),
        "用 Google 账号登录时，记下你的邮箱、名字、学校域名，以及第一次和最近一次登录的时间，用来识别你，并计算 Co-op 贡献等级。",
        "Co-op 投稿先私下保存、人工审核；同一公司、职位、学期至少有两个不同投稿人的投稿通过审核，才一起公开，公开时不显示投稿人。",
        ("只有你勾选「允许保存」以后，回答和你的 👍／👎 才会保存，同样不记是谁；不勾选时只有上面的查询日志。" if feedback
         else "回答反馈功能目前关闭：回答不保存。"),
        "选课草案和课程对比只在这次会话里，刷新或登出就清空，不写数据库。",
    ]
    if web:
        kept.append("每门课的页面有自己的网址（比如 /course/CS-6140）：打开过的课程页会和浏览别的网站一样，留在你这台设备的"
                    "浏览器历史里，可以在浏览器里清除；分享出去的链接里也带着课号。")
    who = ["服务器上的数据只有维护者能看，不卖、也不交给第三方；公开的 Co-op 经验按贡献等级给访客看；"
           "生成回答要把问题发给 Google Gemini，见上。",
           "网站经 Cloudflare 转发到服务器：连接在 Cloudflare 那里解密再转发，所以 Cloudflare 能看到传输的内容。"]
    keep_for = [
        f"提问原文：{days} 天，到期换成哈希。" if days else "提问原文：目前没有自动清理。",
        (f"每日备份保留 {BACKUP_COPIES} 份，所以到期清理掉的内容，在备份里最多再多留大约两周。" if days
         else f"每日备份保留 {BACKUP_COPIES} 份，大约两周。"),
        "账号和 Co-op 投稿：保留到你删除为止。",
    ]
    if feedback:
        # The same task deletes them (db.query_log_retention.delete_expired_answers). 中文：同一个清理任务删除。
        if days:
            keep_for.append(f"保存的回答和评价：{days} 天后删除。")
        else:
            keep_for.append("保存的回答和评价：目前没有自动清理；想删除可以写邮件联系。" if contact
                            else "保存的回答和评价：目前没有自动清理。")
    unnamed = "提问和保存的回答" if feedback else "提问"
    delete = [
        "登录以后，可以在本页最下面删除你的账号和 Co-op 投稿。",
        f"{unnamed}都不记是谁（登录了也一样），挑不出哪一条是你的，"
        + ("只能等到期清理。" if days else "目前也没有自动清理。"),
    ]
    if contact:
        delete.append(f"别的问题或删除请求，写邮件到 {contact}。")
    return [("记了什么", kept), ("谁能看", who), ("留多久", keep_for), ("怎么删", delete)]


DELETE_WHAT = ("会删掉：你的账号（邮箱、名字、学校域名、贡献数和登录时间），你提交的全部 Co-op 投稿（包括已经公开的）和解锁记录，以及别人对"
               "你那些公开经验的解锁记录。同一组公开的投稿如果因此只剩一个人的，那份也会撤回，等有新的同组投稿再一起公开。"
               "提问和保存的回答本来就不和账号关联，不受影响。已经做进每日备份的数据，最多还会在备份里留大约两周。删除不能撤销。")


__all__ = ["BACKUP_COPIES", "DELETE_WHAT", "INTRO", "QUERY_LOG_NOTICE_BASE", "capture_notice", "privacy_sections"]

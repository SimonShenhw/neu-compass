"""Pure text escaping for distinct Markdown and HTML contexts.

中文：仅依赖标准库；一行 HTML、多行 HTML 与 Markdown 标签不互换策略。
"""

from __future__ import annotations

import html
import re

WORD_JOINER = "\u2060"
_URL_START = re.compile(r"(?i)(?:h(?=ttps?://)|w(?=ww\.))")
_ASCII_PUNCTUATION = re.compile(r"[!-/:-@\[-`{-~]")


def literal_markdown(value: object) -> str:
    """One line of plain text for a Markdown context, e.g. a course name from the database in a
    label: whitespace runs (line breaks included) become one space, every ASCII punctuation
    character is escaped, and URL starts and ":" get the same word joiner as answer_markdown().
    An e-mail address may still become a mail link.
    中文：放进 Markdown 的一行纯文字，例如标签里来自数据库的课程名：连续空白（含换行）变成一个
    空格，每个 ASCII 标点都转义，网址开头和 ":" 后面插入和 answer_markdown() 一样的 word joiner。
    邮箱地址仍可能变成邮件链接。"""
    text = _URL_START.sub(lambda match: match.group(0) + WORD_JOINER, " ".join(str(value).split()))
    return _ASCII_PUNCTUATION.sub(
        lambda match: "\\" + match.group(0) + (WORD_JOINER if match.group(0) == ":" else ""), text)


def _one_line(value: object) -> str:
    """Escaped data for the one-block HTML these helpers build: line breaks become spaces, because
    a blank line would end the HTML block and the rest would be read as Markdown (links included).
    中文：这些函数拼出的单块 HTML 里的数据：转义，换行变成空格；空行会结束 HTML 块，后面的内容
    就会被当成 Markdown（包括链接）。"""
    return html.escape(" ".join(str(value).splitlines()))


def plain_text_html(text: object) -> str:
    """Escaped text for a block-level HTML tag that STARTS the st.markdown string (see
    labelled_line_html). Newlines become <br>, so the value stays inside one HTML block,
    which the Markdown parser never reads as Markdown (no links, emphasis, math or
    directives from the data). Next to Markdown text, inside a paragraph, it would still be
    parsed, so never use it there.

    中文：用于放在 st.markdown 字符串开头的块级 HTML 标签里（见 labelled_line_html）。
    换行改成 <br>，值留在同一个 HTML 块里，Markdown 解析器不会把它当 Markdown 解析
    （数据里的链接、强调、公式、指令都不会生效）。如果和 Markdown 文字放在同一段落里，
    仍会被解析，所以不要那样用。"""
    return html.escape(str(text)).replace("\r", "").replace("\n", "<br>")


def labelled_line_html(label: str, value: object) -> str:
    """'<label>：value' as a single escaped HTML line (the value is data, e.g. extracted
    fields; the label is ours). 中文：「标签：值」的单行转义 HTML；值是数据（例如抽取字段），
    标签是我们自己的文字。"""
    return (
        f'<div class="nc-line"><span class="nc-line-label">{html.escape(label)}：</span>'
        f"{plain_text_html(value)}</div>"
    )

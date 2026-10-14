"""Exact existing outputs frozen before SIM-04; similar escaping contexts are not interchangeable."""

import string

import pytest

from app.answer_evidence_view import literal_markdown
from app.ui_theme import _one_line, labelled_line_html, plain_text_html


@pytest.mark.parametrize("value,expected", [
    (None, "None"), (False, "False"), (42, "42"), ("", ""),
    ("  a\r\n\tb\u00a0 c\x1f d  ", "a b c d"),
    ("界☃🙂", "界☃🙂"),
    (":smile:", "\\:\u2060smile\\:\u2060"),
    ("https://elsewhere.example/a?x=1#b", "h\u2060ttps\\:\u2060\\/\\/elsewhere\\.example\\/a\\?x\\=1\\#b"),
    ("www.example.invalid", "w\u2060ww\\.example\\.invalid"),
    ("<b>bold</b> *x* [link](url)", "\\<b\\>bold\\<\\/b\\> \\*x\\* \\[link\\]\\(url\\)"),
    ("a\ue000b\ue001", "a\ue000b\ue001"),
])
def test_literal_markdown_exact_output(value, expected):
    assert literal_markdown(value) == expected


@pytest.mark.parametrize("character", list(string.punctuation))
def test_literal_markdown_escapes_every_ascii_punctuation(character):
    assert literal_markdown(character) == "\\" + character + ("\u2060" if character == ":" else "")


@pytest.mark.parametrize("value,single_line,block", [
    ("a\rb", "a b", "ab"),
    ("a\n", "a", "a<br>"),
    ("\n\n", " ", "<br><br>"),
    ("a\r\nb", "a b", "a<br>b"),
    ("a\u2028b\x85c\vb\fd\x1ce", "a b c b d e", "a\u2028b\x85c\vb\fd\x1ce"),
    (" a \t b\nc ", " a \t b c ", " a \t b<br>c "),
    (None, "None", "None"),
    ("<b>&'\"</b>", "&lt;b&gt;&amp;&#x27;&quot;&lt;/b&gt;", "&lt;b&gt;&amp;&#x27;&quot;&lt;/b&gt;"),
])
def test_html_contexts_keep_exact_and_distinct_line_semantics(value, single_line, block):
    assert _one_line(value) == single_line
    assert plain_text_html(value) == block


def test_label_is_escaped_without_using_the_values_line_normalization():
    assert labelled_line_html("<'label'>\n", "a\rb\nc&") == (
        '<div class="nc-line"><span class="nc-line-label">&lt;&#x27;label&#x27;&gt;\n：</span>'
        'ab<br>c&amp;</div>'
    )

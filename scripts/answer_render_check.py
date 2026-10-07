"""Manual check of answer_markdown() in Streamlit's real renderer, which the unit tests only
approximate with markdown-it-py (react-markdown with remark-gfm, remark-math, remark-directive and
Streamlit's own emoji / icon / colour / typography plugins).

Run from the repo root in the project venv:
    streamlit run scripts/answer_render_check.py --server.headless true
Open the page, wait until the first line's case count matches the rendered cases, then paste
scripts/answer_render_check.js into the browser console. It prints counts only: links by kind
(catalog / mail / Streamlit's heading anchors / other), embedded media, KaTeX, directive, icon,
tooltip or coloured elements (Streamlit's heading wrappers, code highlighting and code-block copy
buttons excluded), URL text outside links and code, non-catalog URLs in code, and
plain cases whose shown text (word joiners removed) differs from the input, by first differing
characters. Each case is a keyed container (st-key-case-<kind>-<n>) with st.markdown(answer_markdown
(case)); a plain case also shows its input with st.text for the comparison.

Cases: the unit tests' exact-output inputs; 400 seeded combinations of Markdown fragments (seed 7)
and 400 of plain fragments (seed 107), from tests/test_answer_evidence_view.py; Streamlit
shortcodes, directives, math and arrows written plainly; fenced code with a math info string.
Result on 2026-10-06 (Streamlit 1.57.0, Chromium 152): see docs/development-change-log.md 13.

中文：在 Streamlit 真实渲染器里手动检查 answer_markdown()（单元测试只用 markdown-it-py 近似）。用法见上；
控制台脚本只输出计数。用例来自单元测试的精确用例、两组固定种子的随机组合，以及直接写出的短代码、
指令、公式、箭头和 math 代码块。2026-10-06 的结果见 docs/development-change-log.md 第 13 节。
"""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import streamlit as st  # noqa: E402

from app.answer_evidence_view import answer_markdown  # noqa: E402
from tests.test_answer_evidence_view import EXPECTED, FRAGMENTS, PLAIN_FRAGMENTS, samples  # noqa: E402

PLAIN_STREAMLIT = [
    "a :streamlit: a", "a :smile: a", "a :material/home: a", "a :red[x] :blue-background[y] :small[z] a",
    "a :help[tip] a", "a :rainbow[x] a", "a ::note a", "a :::note a", "a $x$ a", "a $$x$$ a",
    "a -> b <- c => d",
]
MATH_FENCES = [
    "a $x$ a\n\n```math\ny\n```", "a $x$ a\n\n~~~ Math\ny\n~~~", "a $x$ a\n\n> ```math\n> y\n> ```",
    "a $x$ a\n\n- ```math\n  y\n  ```", "a $x$ a\n\n```python\ny = 1\n```", "a $x$ a\n\n```\tmath\ny\n```",
]

cases = [("exact", raw) for raw, _ in EXPECTED]
cases += [("fuzz", raw) for raw in samples(FRAGMENTS, 7, count=400)]
cases += [("plain", f"a {sample} a") for sample in samples(PLAIN_FRAGMENTS, 107, count=400)]
cases += [("plain", text) for text in PLAIN_STREAMLIT]
cases += [("fence", text) for text in MATH_FENCES]

st.markdown(f"render check: {len(cases)} cases")
for number, (kind, raw) in enumerate(cases):
    with st.container(key=f"case-{kind}-{number}"):
        st.markdown(answer_markdown(raw))
        if kind == "plain":
            st.text(raw)

"""Calibrated rejection gate — ADR-0018 (2026-06 RAG quality pass).

Why this exists: the ADR-0016 gate is `max(reranker sigmoid) < 0.05`.
Its own calibration data shows the limit of that design — answerable
theory-jargon queries (q018 "VC dimension PAC learning", max σ 0.0051)
score BELOW adversarial fake course codes (q040 "CS 0001", max σ 0.0278).
The two distributions interleave in [0.005, 0.03], so NO scalar threshold
on max-sigmoid can separate them: at T=0.05 production false-rejects 4/38
real queries (measured live, eval/api_eval_pool10_int8.json).

为什么需要它:ADR-0016 的门是 `max(reranker sigmoid) < 0.05`。它自己的校准
数据恰恰暴露了这个设计的极限 —— 可回答的理论黑话查询(q018 "VC dimension
PAC learning",max σ 0.0051)得分反而低于对抗性的伪课程代码(q040
"CS 0001",max σ 0.0278)。两个分布在 [0.005, 0.03] 区间内彼此交织,任何
建在 max-sigmoid 上的标量阈值都无法把它们分开:T=0.05 时线上真实查询里
有 4/38 被误拒(实测于 eval/api_eval_pool10_int8.json)。

The fix is information, not threshold-tuning. The cross-encoder under-rates
exact-jargon matches, but the retrieval legs it sits on do not:
q013 "graph algorithms BFS DFS shortest paths" has a huge BM25 score
against the right course's raw_text. Conversely "CS 0001" looks like a
course code, ALREADY failed alias resolution (or it would never reach the
gate), and matches nothing lexically specific. The gate therefore fuses:

解法是补充信息,而不是调阈值。交叉编码器低估了精确的专业黑话匹配,但它
所依赖的检索两路并不会:q013 "graph algorithms BFS DFS shortest paths" 对
正确课程的 raw_text 有很高的 BM25 分数。反过来,"CS 0001" 长得像课程代码、
且已经没通过别名解析(否则根本到不了这道门),词面上也毫无具体匹配。
于是这道门融合了以下特征:

    x1 = logit(max_sigmoid)      cross-encoder confidence (log-odds scale)
    x2 = log1p(bm25_top)         lexical evidence from the BM25 leg
    x3 = vec_top                 dense cosine of the best vector hit
    x4 = code_pattern_miss       query looks like "DEPT 1234" but the alias
                                 tier missed → likely nonexistent course

    x1 = logit(max_sigmoid)      交叉编码器置信度(log-odds 尺度)
    x2 = log1p(bm25_top)         BM25 路的词面证据
    x3 = vec_top                 最佳向量命中的稠密余弦值
    x4 = code_pattern_miss       查询形似 "DEPT 1234",但别名层没命中
                                 → 很可能是不存在的课程

into P(answerable) = sigmoid(w·x + b), rejecting below REJECT_BELOW.

得到 P(可回答) = sigmoid(w·x + b),低于 REJECT_BELOW 时拒答。

Coefficients are DATA-LOCKED by scripts/calibrate_rejection.py (run on the
NAS against the production OpenVINO stack; calibration set = synthesized
answerable queries built from catalog raw_text + synthesized unanswerable
queries across 8 UAEval4RAG-style categories; eval test_set v0.2 is fully
held out). Re-fit + update here if the embedder/reranker/corpus changes.
See docs/adr/0018-calibrated-rejection-gate.md.

系数由 scripts/calibrate_rejection.py 数据锁定(在 NAS 上针对生产环境的
OpenVINO 技术栈跑出;校准集 = 由 catalog raw_text 合成的可回答查询 +
覆盖 8 个 UAEval4RAG 风格类别的合成不可回答查询;eval test_set v0.2 完全
留出、未参与校准)。embedder / reranker / 语料变化时需要重新拟合并更新
此处。详见 docs/adr/0018-calibrated-rejection-gate.md。

Rollout: settings.rejection_mode selects "threshold" (ADR-0016 behavior,
default) or "calibrated" (this gate). NAS compose opts in explicitly.

上线方式:settings.rejection_mode 选择 "threshold"(ADR-0016 的行为,
默认值)或 "calibrated"(本模块这道门)。NAS compose 需要显式选择开启。
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Callable

# Queries shaped like a course code ("CS 5800", "aai9999", "CSYE 0042").
# Mirrors rag/query_normalizer's ASCII discipline: CJK must not extend the
# word boundary. 4-5 digits covers NEU's 4-digit codes + typo'd 5-digit.
# 中文:形似课程代码的查询("CS 5800"、"aai9999"、"CSYE 0042")。与
# rag/query_normalizer 的 ASCII 纪律一致:CJK 字符不能扩展词边界。
# 4-5 位数字覆盖 NEU 的 4 位课程号 + 打错成 5 位的情况。
_COURSE_CODE_RE = re.compile(r"\b([A-Za-z]{2,5})\s?\d{4,5}\b", re.ASCII)

# Words that satisfy the letters-then-digits shape but are calendar terms,
# not department codes: "fall 2025" / "spring 2026" must NOT count as a
# code-pattern miss — they're routine in perfectly answerable queries.
# 中文:符合"字母+数字"形状、但其实是日历用词而非系代码的词:"fall 2025" /
# "spring 2026" 不能算作 code-pattern-miss —— 它们在完全可回答的查询里很常见。
_NOT_DEPT_WORDS = frozenset({
    "fall", "spring", "summer", "winter", "autumn", "term", "year", "since",
})

# CJK detection for the cjk_dominant feature. The BM25 leg is ASCII-only
# (rag/hybrid.py documented limitation), so bm25_top is STRUCTURALLY zero
# for Chinese queries — without this feature the gate reads missing lexical
# evidence as negative evidence and false-rejects answerable 中文 queries
# (v0.3 eval first surfaced this: q091/q093). The coefficient learned from
# Chinese calibration samples compensates.
# 中文:cjk_dominant 特征所需的 CJK 检测。BM25 路只认 ASCII(rag/hybrid.py
# 里记录的已知限制),因此中文查询的 bm25_top 在结构上必然为零 —— 没有
# 这个特征,门会把"缺失词面证据"误读成"负面证据",从而误拒可回答的中文
# 查询(v0.3 评测首次发现:q091/q093)。从中文校准样本学到的系数正好补偿。
_CJK_RE = re.compile(r"[一-鿿㐀-䶿]")

# Fitted on the NAS 2026-06-11 (v5 run, post-ADR-0020 corpus) by
# scripts/calibrate_rejection.py against the production stack (openvino
# int8, pool=10, search_expansion live, acronym expander on). The ADR-0020
# doc-expansion field shifted the BM25 score distribution (gibberish like
# "keyboard mash" suddenly matched piano-course expansions and leaked
# through the v4 fit) — exactly the "corpus 大改" re-fit trigger. Note the
# fit's own response: w_log1p_bm25 dropped 0.96 → 0.78, the model learned
# lexical evidence is now mildly inflated. Calibration set: 50 easy + 15
# hard-jargon + 15 zh answerable / 50 unanswerable. Grid at p<0.4: 0/79
# false-rejects, 39/50 caught. Do not hand-edit — re-run the script if the
# embedder/reranker/quantization/corpus changes.
# 中文:2026-06-11 在 NAS 上拟合(v5 版本,ADR-0020 语料之后),由
# scripts/calibrate_rejection.py 针对生产技术栈跑出(openvino int8,
# pool=10,search_expansion 已上线,acronym 扩写已开启)。ADR-0020 的文档
# 扩展字段挪动了 BM25 分数分布("keyboard mash" 这类乱码意外匹配到钢琴课
# 的扩展词、在 v4 拟合里漏了进来)—— 这正是触发"语料大改需要重新拟合"的
# 典型场景。注意拟合本身的反应:w_log1p_bm25 从 0.96 降到 0.78,模型学到
# 词面证据现在被轻微高估了。校准集:50 个简单 + 15 个高难黑话 + 15 个
# 中文可回答 / 50 个不可回答。p<0.4 网格搜索结果:0/79 误拒,39/50 命中。
# 请勿手改 —— embedder/reranker/量化/语料变化时请重跑脚本。
DEFAULT_COEFFICIENTS: dict[str, float] = {
    "bias": -1.6277,
    "w_logit_sigmoid": 0.5944,
    "w_log1p_bm25": 0.7822,
    "w_vec_top": 2.9949,
    "w_code_miss": -3.4026,
    "w_cjk": 1.7244,
}

REJECT_BELOW = 0.4
"""Reject when P(answerable) < this. NOT the LR midpoint (0.5) on purpose:
the operating rule is "maximize unanswerable catch subject to ZERO
false-rejects on the calibration answerable set", which the v4 grid
resolves to 0.4 (false-rej 0/80, caught 39/50; 0.5 trades a false-reject
for 2 more catches). Product asymmetry: refusing a real student query is
worse than returning weak results for an unanswerable one — /chat's
grounded prompt still answers "not in catalog" for the latter. Measured
residual on the held-out set: q018-style pure theory jargon (p≈0.26)
remains below the line; q042 homework-admin (p≈0.28) stays correctly
rejected. Adjust only together with a re-fit (ADR-0018).

中文:当 P(可回答) 低于这个值时拒答。故意不用逻辑回归的中点 0.5 ——
运行规则是"在校准可回答集上零误拒的前提下,最大化对不可回答查询的命中
率",v4 网格搜索给出的解是 0.4(误拒 0/80,命中 39/50;若用 0.5,会用
一次误拒换来多命中 2 个)。产品层面的不对称性:拒答一个真实学生查询,
比对一个不可回答查询给出偏弱的结果更糟 —— 后者反正 /chat 的 grounded
prompt 也会如实回答"目录里没有"。在留出集上的实测残差:q018 这类纯理论
黑话(p≈0.26)仍落在线下;q042 作业行政问题(p≈0.28)仍被正确拒答。
只应与重新拟合(ADR-0018)一起调整这个值。
"""

_LOGIT_EPS = 1e-6  # max_sigmoid=0.0 → logit ≈ -13.8 instead of -inf
# 中文:max_sigmoid=0.0 时 logit ≈ -13.8,而不是 -inf。


@dataclass(frozen=True)
class RejectionFeatures:
    """Inputs the gate fuses. All cheap — computed from values the request
    already produced (no extra model calls).

    中文:门融合的输入特征。计算成本都很低 —— 全部来自请求已经产出的值
    (不需要额外的模型调用)。
    """

    max_sigmoid: float
    bm25_top: float
    vec_top: float
    code_pattern_miss: bool
    cjk_dominant: bool = False


def query_has_code_pattern(query: str) -> bool:
    """True iff the query contains a course-code-shaped token (excluding
    calendar phrases like "fall 2025"). Callers on the hybrid path combine
    this with the fact that alias resolution already missed (or the request
    would have returned at the alias tier).

    中文:当查询包含形似课程代码的 token 时返回 True(排除 "fall 2025"
    这类日历短语)。混合检索路径的调用方会把这个结果和"别名解析已经没
    命中"这一事实结合起来使用(否则请求早就在别名层返回了)。
    """
    return any(
        m.group(1).lower() not in _NOT_DEPT_WORDS
        for m in _COURSE_CODE_RE.finditer(query)
    )


def query_is_cjk_dominant(query: str, *, threshold: float = 0.3) -> bool:
    """True iff CJK characters make up more than `threshold` of the query's
    non-space characters — the regime where the ASCII-only BM25 leg goes
    structurally silent and bm25_top=0 carries no signal.

    中文:当 CJK 字符占查询非空白字符的比例超过 `threshold` 时返回 True ——
    这正是只认 ASCII 的 BM25 路结构性失声、bm25_top=0 不携带任何信号的场景。
    """
    chars = [c for c in query if not c.isspace()]
    if not chars:
        return False
    cjk = sum(1 for c in chars if _CJK_RE.match(c))
    return cjk / len(chars) > threshold


def _logit(p: float) -> float:
    # Clamp to (_LOGIT_EPS, 1-_LOGIT_EPS) before the log-odds transform so
    # p=0.0 / p=1.0 don't blow up to ±inf.
    # 中文:在做 log-odds 变换前,先把 p 夹到 (_LOGIT_EPS, 1-_LOGIT_EPS)
    # 区间,避免 p=0.0 或 p=1.0 时结果炸到 ±inf。
    p = min(max(p, _LOGIT_EPS), 1.0 - _LOGIT_EPS)
    return math.log(p / (1.0 - p))


class CalibratedRejectionGate:
    """Tiny logistic-regression gate over RejectionFeatures.

    中文:基于 RejectionFeatures 的小型逻辑回归门。
    """

    def __init__(
        self,
        coefficients: dict[str, float] | None = None,
        *,
        reject_below: float = REJECT_BELOW,
    ) -> None:
        self._c = dict(DEFAULT_COEFFICIENTS if coefficients is None else coefficients)
        self.reject_below = reject_below

    def probability(self, f: RejectionFeatures) -> float:
        """P(answerable) ∈ (0, 1).

        The BM25 term is an INTERACTION with (not cjk): lexical evidence
        only counts for non-CJK queries. Plain additive cjk couldn't
        express "BM25 is trustworthy only when the ASCII tokenizer saw the
        query" — fitting Chinese samples additively collapsed the BM25
        weight globally (1.51→0.07) and regressed the English queries BM25
        was rescuing. With the interaction, w_log1p_bm25 is learned on
        English-only variation and w_cjk absorbs the missing-evidence
        regime's baseline shift.

        中文:P(可回答) ∈ (0, 1)。
        BM25 项是与 (1 - cjk) 的交互项,而不是单纯加性的 cjk 项:词面证据
        只在非 CJK 查询里才算数。单纯加性的 cjk 项没法表达"只有当 ASCII
        分词器真正见过这个查询时,BM25 才可信"这件事 —— 用中文样本做加性
        拟合会把 BM25 权重整体压垮(1.51→0.07),还连带拖累了本该由 BM25
        拯救的英文查询。加了交互项之后,w_log1p_bm25 只在纯英文的变化上
        学习,w_cjk 单独吸收"证据缺失"这个状态下的基线偏移。
        """
        is_cjk = 1.0 if f.cjk_dominant else 0.0
        z = (
            # Intercept ("b" in the module docstring's "w·x + b").
            # 中文:截距项(模块 docstring 里 "w·x + b" 中的 b)。
            self._c["bias"]
            # x1: cross-encoder confidence, log-odds scale.
            # 中文:x1 —— 交叉编码器置信度,log-odds 尺度。
            + self._c["w_logit_sigmoid"] * _logit(f.max_sigmoid)
            # x2: lexical evidence, gated off for CJK-dominant queries via (1 - is_cjk).
            # 中文:x2 —— 词面证据,CJK 主导的查询里被 (1 - is_cjk) 关闭。
            + self._c["w_log1p_bm25"]
            * math.log1p(max(f.bm25_top, 0.0)) * (1.0 - is_cjk)
            # x3: dense cosine of the best vector hit.
            # 中文:x3 —— 最佳向量命中的稠密余弦值。
            + self._c["w_vec_top"] * f.vec_top
            # x4: code-shaped query that already missed alias resolution.
            # 中文:x4 —— 形似课程代码、但已经没通过别名解析的查询。
            + self._c["w_code_miss"] * (1.0 if f.code_pattern_miss else 0.0)
            # CJK baseline shift, compensating the structurally-silent BM25 leg.
            # 中文:CJK 基线偏移项,用来补偿结构性失声的 BM25 路。
            + self._c.get("w_cjk", 0.0) * is_cjk
        )
        return 1.0 / (1.0 + math.exp(-z))

    def decide(self, f: RejectionFeatures) -> tuple[bool, float, str]:
        """Returns (reject, p_answerable, reason).

        中文:返回 (是否拒答, p_answerable, 原因说明)。
        """
        p = self.probability(f)
        reject = p < self.reject_below
        reason = (
            f"calibrated_gate p_answerable={p:.3f} "
            f"{'<' if reject else '>='} {self.reject_below} "
            f"(max_sigmoid={f.max_sigmoid:.4f}, bm25_top={f.bm25_top:.2f}, "
            f"vec_top={f.vec_top:.3f}, code_miss={f.code_pattern_miss}, "
            f"cjk={f.cjk_dominant})"
        )
        return reject, p, reason


def build_gate_fn(
    *,
    query: str,
    bm25_top: float,
    vec_top: float,
    gate: CalibratedRejectionGate | None = None,
) -> Callable[[list[float]], tuple[bool, str]]:
    """Adapter for rerank_blend_with_rejection's `gate_fn` hook.

    The reranker pass produces the sigmoid list INSIDE that function, so the
    route can't precompute max_sigmoid — it hands this closure over instead.
    Leg diagnostics (bm25_top / vec_top) come from
    HybridRetriever.last_diagnostics; code_pattern_miss is derivable here
    because any request that reaches the hybrid path already missed alias.

    中文:适配 rerank_blend_with_rejection 的 `gate_fn` 钩子。
    重排调用在其内部才产出 sigmoid 列表,路由层没法提前算出 max_sigmoid ——
    于是改为把这个闭包交给它。两路诊断值(bm25_top / vec_top)来自
    HybridRetriever.last_diagnostics;code_pattern_miss 在这里可以直接
    推出,因为凡是走到混合检索路径的请求,都已经先没通过别名解析。
    """
    g = gate or CalibratedRejectionGate()
    code_miss = query_has_code_pattern(query)
    cjk = query_is_cjk_dominant(query)

    def gate_fn(sigmoids: list[float]) -> tuple[bool, str]:
        f = RejectionFeatures(
            max_sigmoid=max(sigmoids) if sigmoids else 0.0,
            bm25_top=bm25_top,
            vec_top=vec_top,
            code_pattern_miss=code_miss,
            cjk_dominant=cjk,
        )
        reject, p, reason = g.decide(f)
        # Routes read this to scope the ADR-0019 rescue: a HIGH-CONFIDENCE
        # rejection (p far below the line) gets no LLM second opinion —
        # observed leak: Gemini's verdict flips run-to-run on borderline
        # gibberish, but the gate's p≈0.02 was never in doubt.
        # 中文:路由层读取这个值来限定 ADR-0019 rescue 的范围:高置信度的
        # 拒答(p 远低于分界线)不会再获得 LLM 第二意见 —— 观察到的问题是
        # Gemini 对模糊乱码的判断会反复翻转,但门给出的 p≈0.02 从未动摇过。
        gate_fn.last_p = p  # type: ignore[attr-defined]
        return reject, reason

    gate_fn.last_p = 1.0  # type: ignore[attr-defined]
    return gate_fn


__all__ = [
    "DEFAULT_COEFFICIENTS",
    "REJECT_BELOW",
    "CalibratedRejectionGate",
    "RejectionFeatures",
    "build_gate_fn",
    "query_has_code_pattern",
    "query_is_cjk_dominant",
]

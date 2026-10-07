"""Checks for real /chat answers: internal IDs, links, review counts, RMP attribution, caveats,
estimate wording, link-label language, repeated disclaimers.

Pure functions over the answer text and what the prompt supplied (AnswerContext);
scripts/eval_answers_live.py runs them against the real model. The patterns were tuned on real
gemini-2.5-flash answers to prompts 4.1/4.2 (2026-10-05); they flag likely problems for a person
to read, they do not prove an answer correct.

中文：真实 /chat 回答的检查：内部 ID、链接、评价条数、RMP 归属、各项说明、估计值措辞、链接
标签语言、重复的免责句。只看回答文本和提示词提供的内容（AnswerContext），是纯函数；
scripts/eval_answers_live.py 用它们检查真实模型的回答。这些模式是用 2026-10-05 gemini-2.5-flash
对 4.1/4.2 提示词的真实回答调出来的，作用是标出可能的问题给人看，不能证明回答正确。
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field

# JSON field names and warning/notice codes the prompt contains; an answer must not print them.
FIELD_NAMES = ("snapshot_id", "source_kind", "recorded_sources", "field_evidence", "catalog_url",
               "source_review_ids", "missing_fields", "supported_value", "recorded_metadata")
CODES = ("catalog_source_unavailable", "catalog_retrieval_date_unknown", "catalog_metadata_conflict",
         "extracted_evidence_not_official_facts", "field_evidence_value_conflict", "topics_source_unavailable",
         "prerequisite_logic_unavailable", "program_seed_unverified", "synthetic_record_not_real_course",
         "program_schedule_unverified")

CATALOG_HEX = re.compile(r"catalog:[0-9a-fA-F]+")
HEX_RUN = re.compile(r"[0-9a-fA-F]{12,}")
ID_PREFIX = re.compile(r"(?<![A-Za-z0-9])(?:rmp_review_|reddit_|syllabus_|synthetic_seed_|catalog_)[A-Za-z0-9_\-=]*")
BASE64_CANDIDATE = re.compile(r"[A-Za-z0-9+/=_\-]{16,}")
COURSE_ID = re.compile(r"\bneu-[a-z]{2,6}-\d{4}[a-z]?\b")

MD_LINK = re.compile(r"!?\[([^\]]*)\]\(\s*<?([^)\s>]*)>?(?:\s+[\"'][^\"']*[\"'])?\s*\)")
# Any scheme, and case-insensitive: the renderer links HTTPS:// and WWW. too.
AUTOLINK = re.compile(r"<([A-Za-z][A-Za-z0-9+.\-]{1,31}:[^<>\s]*)>")
REF_DEF = re.compile(r"^\s*\[([^\]]+)\]:\s*(\S+)", re.M)
BARE_URL = re.compile(r"(?:https?://|www\.)[^\s<>()\[\]\"'，。、；）（]+", re.I)
PROGRAM_LABEL = re.compile(r"培养方案|\bprograms?\b", re.I)  # Not "Programming" in a course name.
CJK = re.compile(r"[一-鿿]")

COUNT_ZH = re.compile(
    r"(\d+|[一二两三四五六七八九十百]+)\s*(?:\+|多)?\s*(?:条|位|个|份|名|篇|则)\s*"
    r"(?:来自\s*)?(?:RateMyProfessors\s*|RMP\s*)?(?:上的?\s*)?(?:学生的?)?"
    r"(?:评价|评论|点评|评分|打分|学生|同学|反馈|用户)")
# Up to two words between the number and the noun, but never a preposition ("3 options for
# students" is not a count of reviews); a hyphenated word that starts with one ("in-depth") is not
# a preposition. 中文：数字和名词之间最多两个词，但不能是介词；以介词开头的连字符词（in-depth）不算介词。
COUNT_EN = re.compile(
    r"\b(\d+|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|twenty|thirty|fifty|dozens?)"
    r"\s+(?:(?!(?:for|to|in|on|at|with|about|per|from|by|into|than)\b(?!-))[A-Za-z\-]+\s+){0,2}"
    r"(?:reviews?|reviewers?|students?|ratings?|comments?)\b", re.I)
# The 4-digit number of a course code ("CS 5800 students") is not a count.
COURSE_CODE_BEFORE = re.compile(r"\b[A-Z]{2,5}\s?$")

SINGULAR = {"1", "一", "one"}

RMP_NAME = re.compile(r"RateMyProfessors|Rate ?My ?Professors?|\bRMP\b", re.I)
# 评价 also means assessment: 评价方式 / 评价标准 / 成绩评价 / 考核评价 are about grading, not reviews.
# 中文：评价也指考核：评价方式、评价标准、成绩评价、考核评价说的是打分方式，不是评价网站的评论。
REVIEW_WORD = re.compile(r"(?<!成绩)(?<!考核)评价(?!方式|标准|体系|方法)|评论|点评|口碑|学生反馈|"
                         r"reviews?|reviewers?|ratings?", re.I)
# Word boundaries: without them "professor" also matched inside "RateMyProfessors", so every RMP
# mention looked instructor-attributed. 中文：要有词边界，否则 "professor" 会在 "RateMyProfessors"
# 里面也匹配，任何提到 RMP 的回答都会被当成「归给了老师」。
INSTRUCTOR = re.compile(r"(任课|授课)?(老师|教师|教授|讲师)|\b(?:instructor|professor|teacher)s?\b", re.I)
OTHER_COURSE = re.compile(
    r"(其他|别的|另外的|其它|其他的)(课|课程)|不一定(是|针对|关于|只)?(这门|本|该)课|未必(是|针对|关于)?(这门|本|该)课|"
    r"不(只|仅)(是|针对|限于)?(这门|本|该)课|可能(是|针对|关于|涉及|来自|包括|包含)[^。\n]{0,12}(其他|别的|其它|另一门)|"
    r"other (?:courses?|classes)|another (?:course|class)|not necessarily (?:about |for )?(?:this|the|CS)|"
    r"not (?:specific|limited) to (?:this|the|CS)", re.I)

FETCH_DATE = re.compile(
    r"(抓取|获取|采集|检索|收录|爬取|更新)(的)?(日期|时间)[^。\n]{0,12}(未知|不明|不详|不清楚|没有记录|未记录)|"
    r"(日期|时间)(未知|不明|不详)|不是实时|非实时|并非实时|而非实时|不是[^。\n]{0,8}实时|实时核[对查实验]|"
    r"存档|快照|保存的?副本|副本|"
    r"fetch(?:ed)? date|retriev\w* date|when it was (?:fetched|retrieved|captured)|saved copy|stored copy|"
    r"copy of the catalog|not a live|not live|archived|snapshot|recorded (?:copy|version)|"
    r"may (?:have changed|be out ?of ?date|be outdated|not reflect)|not (?:necessarily )?(?:the )?current", re.I)
# 无 but not 无法 / 无论: "无法实时核对目录" is about the saved copy, not a missing catalog.
# 中文：「无」但不是「无法」「无论」：「无法实时核对目录」说的是存档副本，不是没有目录。
NO_CATALOG = re.compile(
    r"(没有|缺少|无(?!法|论)|缺乏|未找到|找不到)[^。\n]{0,10}(目录|catalog)|(目录|catalog)[^。\n]{0,10}(缺失|不可用|没有|未找到)|"
    r"no (?:official |recorded )?catalog|catalog (?:record|entry|snapshot|description|data)s? (?:is |are )?"
    r"(?:not available|unavailable|missing)|lacks? (?:a |an )?(?:official )?catalog|without (?:a |an )?(?:official )?catalog", re.I)
PREREQ_LOGIC = re.compile(
    r"(并且|且|或者|或|和/或|全部|都需要|都要|任一|任意一门|其中一门|组合|是否需要全部)[^。\n]{0,40}"
    r"(不清楚|不明确|无法确定|无法判断|没有说明|未说明|未注明|不确定|未知|没有标明|需要[^。\n]{0,6}(核实|确认))|"
    r"(不清楚|不明确|无法确定|无法判断|没有说明|未说明|未注明|不确定|没有标明)[^。\n]{0,40}(并且|且|或|全部|都|任一|其中一门)|"
    r"(且|或)的?关系|AND/OR|and/or|logical relationship|"
    r"\b(?:all|both|either|any one|any)\b[^.\n]{0,80}\b(?:unclear|not (?:specified|indicated|stated|clear)|"
    r"doesn't (?:say|specify|indicate)|does not (?:say|specify|indicate)|cannot (?:tell|determine|confirm)|unknown)\b|"
    r"\b(?:unclear|not (?:specified|indicated|stated|clear)|doesn't (?:say|specify|indicate)|does not (?:say|specify|indicate)|"
    r"cannot (?:tell|determine|confirm)|unknown)\b[^.\n]{0,80}\b(?:all|both|either|any one|whether)\b", re.I)
PROGRAM_CAVEAT = re.compile(
    r"(没有|无|尚无|并无|暂无|缺少)[^。\n]{0,15}(核实|核验|验证|确认|官方)[^。\n]{0,15}(学期|课表|安排|计划|顺序)|"
    r"并非官方|不是官方|非官方|不代表官方|不是[^。\n]{0,8}官方|未经(核实|核验|验证)|"
    r"no verified|not (?:an |the )?official|unverified|isn't (?:an |the )?official", re.I)
PROGRAMS_PAGE = re.compile(r"培养方案|Programs page|\bPrograms\b", re.I)
SAVED_COPY = re.compile(r"副本|saved copy|stored copy|copy of the catalog|不是实时|非实时|not a live", re.I)

# A sentence ends at 。！？!?, at a line break, or at a period followed by a space or the end; not at
# the period in 4.0, in dotted initials (U.S.) or after an abbreviation such as e.g., Ph.D. or approx. A
# single capital letter does end one ("... Part A. Reviews say ..."), so a lone initial in a name
# splits it. 中文：句子在 。！？!?、换行、或后面跟空白/结尾的英文句号处结束；4.0、U.S. 这种连续缩写
# 和 e.g.、Ph.D.、approx. 这类缩写不算。单个大写字母后的句号算结束（"... Part A. Reviews say ..."），所以
# 人名里单独的首字母会把句子分开。
SENTENCE_END = re.compile(r"[。！？!?]+|\.(?=\s|$)|\n")
ABBREVIATION = re.compile(r"\b(?:(?i:e\.g|i\.e|ph\.d|approx|vs|cf|prof|dr|mrs?|ms|fig)|(?:[A-Z]\.)+[A-Z])$")
# A pronoun in a review sentence refers the review to a person, i.e. the instructor ("RMP 上的评价说他
# 讲得清楚"); 其他/他们/他人 are not pronouns for one person. 中文：评价句里的人称代词指的是某个人，也就是
# 老师；其他、他们、他人不算。
PERSON = re.compile(r"(?<!其)他(?![们人])|她(?![们人])|\b(?:he|she|his|her|him)\b", re.I)
REPORT_CUE = re.compile(r"报告|称|表示|提到|指出|反映|认为|评价(显示|说)|评论(显示|说)|据[^。\n]{0,20}(评价|评论)|"
                        r"根据[^。\n]{0,40}(评价|评论)|\breport|\bsay|\bsaid\b|\baccording to\b|\bmention|"
                        r"\bnote[sd]?\b|\bdescribe|\breviews?\b|\breviewers?\b", re.I)
ESTIMATE_CUE = re.compile(r"估计|估算|推断|推测|抽取|提取|整理|得出|预估|estimat|inferr|\binfer\b|extract|derived", re.I)
RECORD_CUE = re.compile(r"记录|存储|recorded|stored|the record|record shows|record lists", re.I)


@dataclass(frozen=True)
class AnswerContext:
    """What the prompt supplied for one question. 中文：一个问题的提示词里提供了什么。"""

    lang: str  # "zh" or "en": the language the question was asked in
    allowed_urls: frozenset[str] = frozenset()  # catalog_url of each supplied course with a valid snapshot
    has_rmp_data: bool = False
    fetch_date_relevant: bool = False  # a supplied snapshot has no retrieved_at
    no_catalog_relevant: bool = False  # a supplied course has no snapshot
    prereq_relevant: bool = False
    program_notice: bool = False  # program_schedule_unverified was passed
    unstated_values: tuple[float, ...] = ()  # numeric estimates that no supplied quote states
    prompt_keys: frozenset[str] = field(default_factory=frozenset)  # JSON keys in the prompt's course block


def _context(text: str, match: re.Match, width: int = 40) -> str:
    return text[max(0, match.start() - width):min(len(text), match.end() + width)].replace("\n", " ")


def number_pattern(value: float) -> re.Pattern:
    """A number as an answer may write it (12 / 12.0), not part of a larger number or a credit count."""
    core = rf"{int(value)}(?:\.0+)?" if float(value).is_integer() else re.escape(str(value))
    return re.compile(rf"(?<![\d.]){core}(?![\d]|\.\d|\s*(?:学分|credits?|credit-hours?))", re.I)


def sentences(text: str) -> list[str]:
    """The answer's sentences (see SENTENCE_END), blank ones dropped. 中文：回答里的句子，空句去掉。"""
    parts, start = [], 0
    for end in SENTENCE_END.finditer(text):
        if end.group(0) == "." and ABBREVIATION.search(text, start, end.start()):
            continue
        parts.append(text[start:end.end()])
        start = end.end()
    parts.append(text[start:])
    return [part for part in parts if part.strip()]


def review_attribution(parts: list[str], has_rmp_data: bool) -> str:
    """How the sentences that cite reviews attribute them. Consecutive review sentences form one
    passage; each passage must name the instructor (or refer to them as he/she) itself, so an
    unrelated "professor" elsewhere does not count, and neither does the site's own name ("Rate
    My Professors"). Every passage needs the other-course caveat, inside it or in the sentence
    right after it. 中文：引用评价的句子怎样归属。连续的评价句算一段；每段自己要提到老师（或用
    他/她指代），别处无关的 "professor" 不算，网站名本身（"Rate My Professors"）也不算。每段都要有
    "可能是别的课"的提示，在段内或紧接着的下一句。"""
    reviewing = [bool(RMP_NAME.search(part)) or (has_rmp_data and bool(REVIEW_WORD.search(part))) for part in parts]
    passages, index = [], 0
    while index < len(parts):
        if not reviewing[index]:
            index += 1
            continue
        end = index
        while end + 1 < len(parts) and reviewing[end + 1]:
            end += 1
        passages.append((index, end))
        index = end + 1
    if not passages:
        return "not used"
    if not all(any(INSTRUCTOR.search(RMP_NAME.sub(" ", part)) or PERSON.search(part) for part in parts[start:end + 1])
               for start, end in passages):
        return "UNQUALIFIED"
    if all(any(OTHER_COURSE.search(part) for part in parts[start:end + 2]) for start, end in passages):
        return "instructor + may be another course"
    return "instructor, no other-course caveat"


def find_links(text: str) -> list[dict]:
    """Markdown links, autolinks, reference definitions and bare URLs, with their labels."""
    links, rest = [], text
    for pattern, kind in ((MD_LINK, "markdown"), (AUTOLINK, "autolink"), (REF_DEF, "refdef")):
        for match in pattern.finditer(rest):
            label, target = (match.group(1), match.group(2)) if kind != "autolink" else ("", match.group(1))
            links.append({"kind": kind, "label": label, "target": target})
        rest = pattern.sub(" ", rest)
    links.extend({"kind": "bare", "label": "", "target": match.group(0).rstrip(".,;:!?)")}
                 for match in BARE_URL.finditer(rest))
    return links


def check_answer(text: str, context: AnswerContext) -> dict:
    """Every check for one answer. Hard failures: ids_fail, links_fail, counts_fail, rmp_fail.
    The rest are signals for a person to read. 中文：一个回答的全部检查。硬失败：ids_fail、links_fail、
    counts_fail、rmp_fail；其余是给人看的信号。"""
    ids = {
        "catalog_hex": CATALOG_HEX.findall(text),
        "hex_runs": HEX_RUN.findall(text),
        "id_prefixes": ID_PREFIX.findall(text),
        "base64_like": [token for token in BASE64_CANDIDATE.findall(text)
                        if re.search(r"[A-Z]", token) and re.search(r"[a-z]", token) and re.search(r"\d", token)],
        "course_ids": COURSE_ID.findall(text),
        "field_names": [name for name in FIELD_NAMES if re.search(rf"\b{re.escape(name)}\b", text)],
        "codes": [code for code in CODES if code in text],
        "prompt_keys": sorted(key for key in context.prompt_keys if "_" in key and re.search(rf"\b{re.escape(key)}\b", text)),
    }
    links = find_links(text)
    for link in links:
        link["allowed_target"] = link["target"] in context.allowed_urls
        link["literal_catalog_url"] = link["target"].strip() == "catalog_url"
        link["programs_label"] = bool(PROGRAM_LABEL.search(link["label"]))
    labels = [link["label"] for link in links if link["kind"] == "markdown"]
    # "一条评论提到…" / "one review reported…" names the single quoted review, which is accurate;
    # only counts above one can overstate. 中文：「一条评论提到……」指的是被引用的那一条，属实；
    # 只有大于一的条数才可能夸大。
    counts = [_context(text, m) for pattern in (COUNT_ZH, COUNT_EN) for m in pattern.finditer(text)
              if m.group(1).lower() not in SINGULAR
              and not (len(m.group(1)) == 4 and m.group(1).isdigit()
                       and COURSE_CODE_BEFORE.search(text, max(0, m.start() - 8), m.start()))]

    parts = sentences(text)
    rmp = review_attribution(parts, context.has_rmp_data)

    # 4.3 asks for the saved-copy note only when a catalog description was used, which the answer
    # shows by linking the catalog. The no-catalog sentence may say 存档 / 副本 too; it is not that
    # note. 中文：4.3 只在用到目录描述时要求说明存档副本，回答用了就会链接目录。「没有目录描述」那句
    # 也可能说到存档、副本，但它不是那条说明。
    used_catalog = any(link["allowed_target"] for link in links)
    catalog_sentences = "\n".join(part for part in parts if not NO_CATALOG.search(part))
    caveats = {"fetch_date": (context.fetch_date_relevant and used_catalog, FETCH_DATE, catalog_sentences),
               "no_catalog": (context.no_catalog_relevant, NO_CATALOG, text),
               "prereq_logic": (context.prereq_relevant, PREREQ_LOGIC, text),
               "program_caveat": (context.program_notice, PROGRAM_CAVEAT, text)}
    missing = [name for name, (relevant, pattern, searched) in caveats.items() if relevant and not pattern.search(searched)]
    if context.program_notice and not PROGRAMS_PAGE.search(text):
        missing.append("programs_page_pointer")

    estimates = []
    for sentence in parts:
        for value in sorted(set(context.unstated_values)):
            for number in number_pattern(value).finditer(sentence):
                before = sentence[max(0, number.start() - 20):number.start()]
                if RECORD_CUE.search(before):
                    kind = "attributed to the record"
                elif ESTIMATE_CUE.search(sentence):
                    kind = "qualified as estimate"
                elif REPORT_CUE.search(sentence):
                    kind = "AS REVIEWER-REPORTED"
                else:
                    kind = "unattributed"
                estimates.append({"value": value, "kind": kind, "sentence": sentence.strip()[:220]})

    return {
        "ids": ids, "ids_fail": any(ids.values()),
        "links": links, "links_fail": any(not l["allowed_target"] or l["programs_label"] or l["literal_catalog_url"] for l in links),
        "label_language_ok": (all(CJK.search(label) for label in labels) if context.lang == "zh"
                              else not any(CJK.search(label) for label in labels)) if labels else None,
        "counts": counts, "counts_fail": bool(counts),
        "rmp": rmp, "rmp_fail": rmp == "UNQUALIFIED",
        "caveats_missing": missing,
        "estimates": estimates,
        "estimates_as_reported": [item for item in estimates if item["kind"] == "AS REVIEWER-REPORTED"],
        # Sentences, not matches: one sentence often says both 副本 and 非实时.
        # The no-catalog note may also say 副本 / "saved copy"; it is not a repeat of the saved-copy one.
        "saved_copy_mentions": sum(1 for part in parts if SAVED_COPY.search(part) and not NO_CATALOG.search(part)),
        "chars": len(text),
    }


HARD_FAILURES = ("ids_fail", "links_fail", "counts_fail", "rmp_fail")


def summarize(checks: list[dict]) -> dict:
    """Counts across answers, for the report table. 中文：跨回答的计数，用于报告表格。"""
    rmp = Counter(item["rmp"] for item in checks)
    return {
        "answers": len(checks),
        **{name: sum(1 for item in checks if item[name]) for name in HARD_FAILURES},
        "label_language_bad": sum(1 for item in checks if item["label_language_ok"] is False),
        "caveats_missing": dict(Counter(name for item in checks for name in item["caveats_missing"])),
        "estimates_as_reported": sum(len(item["estimates_as_reported"]) for item in checks),
        "repeated_saved_copy": sum(1 for item in checks if item["saved_copy_mentions"] > 1),
        "rmp": dict(rmp),
    }


__all__ = ["AnswerContext", "HARD_FAILURES", "check_answer", "find_links", "number_pattern", "review_attribution",
           "sentences", "summarize"]

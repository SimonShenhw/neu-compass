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

CHECKER_VERSION = "2.5-review-gaps"
NUMERIC_FIELDS = ("workload_hours_per_week", "difficulty_score")
ANSWER_COURSE_CODE = re.compile(r"(?<![A-Za-z0-9])([A-Z]{2,4})[ \t]*(\d{4}[A-Z]?)(?![A-Za-z0-9])", re.I)
# A second number after a separator shares the first code's department ("CS 5800 和 5200"), unless it reads as a level
# ("7000-level", "5000- or 6000-level", "5000–6000 级", "6000 系列", "6000+") or, for a 2010–2039 number, a year: a term,
# a catalog or cohort word, or the rest of a year range ("2026 Fall", "2026 catalog", "2027 届", "2026–27"). DS 2001
# stays a course, and so does 5200 in "5200 or 6000-level": a range needs a dash, 至/到, or a hyphen before "or",
# except after a round thousand ("5000 or 6000-level", "5000/6000 级" are levels).
SHORT_CODE = re.compile(r"\s*(?:以及|或者|还是|和|与|及|或|跟|、|，|,\s*(?:and|or)\b|and\b|or\b|vs\.?|&|[,/])\s*"
                        r"(\d{4}[A-Z]?)(?![A-Za-z0-9])", re.I)
SHORT_CODE_LEVEL = re.compile(r"\s*(?:(?:-\s*(?:or|and|to|through|或|和|至|到)|[~～–—\-－]|至|到)\s*\d{4}\s*)?-?\s*"
                              r"(?:level\b(?!\s*\d)|级|年|学年|series\b|系列|以上|以下|\+)", re.I)
SHORT_CODE_ROUND_RANGE = re.compile(r"\s*(?:or|and|to|through|或|和|与|及|、|/)\s*\d{4}\s*-?\s*(?:level\b|级|series\b|系列|以上|\+)",
                                    re.I)
# A full code that names a level is not a course: any code written "CS 6100-level", and a round thousand followed by a
# level word, 以上, a "+" that does not lead into another code, or a range with a dash or 至/到 ("CS 6000 级", "CS 6000
# 以上", "CS 6000+", "CS 5000–6000-level"). Real courses can be round thousands (CS 3000, DS 3000), so a bare connective,
# "+ CS 3800" or 以下 after one keeps it, and so do "CS 5800 级别的课" and "CS 5800 Level 2". 中文：表示级别的完整课号不算
# 课：写成「CS 6100-level」的任何课号，以及后面跟着级别词、「以上」、不接课号的加号或带破折号、「至、到」区间的整千课号；
# 整千也可能是真课号（CS 3000、DS 3000），后面是裸连接词、接课号的加号或「以下」时仍算课。
FULL_CODE_HYPHEN_LEVEL = re.compile(r"-\s*level\b(?!\s*\d)", re.I)
FULL_CODE_LEVEL = re.compile(r"\s*(?:(?:-\s*(?:or|and|to|through|或|和|至|到)|[~～–—\-－]|至|到)\s*\d{4}\s*)?-?\s*"
                             r"(?:level\b(?!\s*\d)|级|series\b|系列|以上|\+(?!\s*[A-Za-z]{2,4}\s*\d))", re.I)
SHORT_CODE_YEAR = re.compile(r"\s*(?:fall|spring|summer|winter|秋|春|夏|冬|catalog\b|目录|届|学年|academic\s+year|cohort\b|"
                             r"[-–—/~]\s*(?:20)?\d\d(?!\d))", re.I)
WORKLOAD_UNIT = re.compile(r"小时|\bhours?\b|\bhrs?\b|每周|per week", re.I)
DIFFICULTY_UNIT = re.compile(r"难度|difficulty|/\s*5\b", re.I)
COURSE_COUNT_UNIT = re.compile(r"\s*(?:门|courses?\b|classes?\b|prerequisites?\b)", re.I)
NUMERIC_DATE = re.compile(r"(?<!\d)(?:\d{4}([-/])\d{1,2}\1\d{1,2}|\d{1,2}([-/])\d{1,2}\2\d{4})(?!\d)")
# Numbers that count something else or name a date, week or grade; identified contexts never read them as estimates.
NOT_ESTIMATE_AFTER = re.compile(r"\s*(?:[%％]|次|assignments?\b|个\s*学分|个?\s*(?:作业|项目|考试|测验)|[周月日号]|"
                                r"days?\b|weeks?\b|projects?\b|exams?\b|quiz(?:zes)?\b|homework\b|GPA\b|(?:st|nd|rd|th)\b)"
                                r"|-\s*credits?\b", re.I)
NOT_ESTIMATE_BEFORE = re.compile(r"(?:(?:学分数?|credits?|GPA|日期|date)\s*(?:要求|requirement)?\s*(?:为|是|of|is|:)?|第)\s*$",
                                 re.I)
# Month names and their abbreviations only, capitalised: "Maybe 12" and "Decent 12" are estimates.
MONTH_BEFORE = re.compile(r"\b(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|June?|July?|Aug(?:ust)?|"
                          r"Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\.?\s*$")

# JSON field names and warning/notice codes the prompt contains; an answer must not print them.
FIELD_NAMES = ("snapshot_id", "source_kind", "recorded_sources", "field_evidence", "catalog_url",
               "source_review_ids", "missing_fields", "supported_value", "recorded_metadata")
CODES = ("catalog_source_unavailable", "catalog_retrieval_date_unknown", "catalog_metadata_conflict",
         "extracted_evidence_not_official_facts", "field_evidence_value_conflict", "topics_source_unavailable",
         "prerequisite_logic_unavailable", "program_seed_unverified", "synthetic_record_not_real_course",
         "program_schedule_unverified", "requisites_differ_by_catalog_year", "requisite_clause_unparsed",
         "structured_requisites_unusable")

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

# The saved-copy / fetch-date note. Its date and live-check wording counts anywhere; the bare words
# (存档, 副本, snapshot, ...) also appear in the no-catalog note ("没有目录描述的存档"), so they count
# only in a clause that is not that note. 中文：存档副本/抓取日期的说明。说日期、「不是实时」的措辞在哪里
# 都算；单独的「存档」「副本」等词也会出现在「没有目录描述」那句里，所以只在不是那句的分句里才算。
FETCH_DATE_DATED = re.compile(
    r"(抓取|获取|采集|检索|收录|爬取|更新)(的)?(日期|时间)[^。\n]{0,12}(未知|不明|不详|不清楚|没有记录|未记录)|"
    r"(没有|未)记录[^。\n]{0,6}(抓取|获取|采集|检索|收录|爬取|更新)(的)?(日期|时间)|"
    r"(日期|时间)(未知|不明|不详)|不是实时|非实时|并非实时|而非实时|不是[^。\n]{0,8}实时|实时核[对查实验]|"
    r"fetch(?:ed)? date|retriev\w* date|when it was (?:fetched|retrieved|captured)|not a live|not live|"
    r"may (?:have changed|be out ?of ?date|be outdated|not reflect)|not (?:necessarily )?(?:the )?current", re.I)
FETCH_DATE_WORDS = re.compile(
    r"存档|快照|保存的?副本|副本|saved copy|stored copy|copy of the catalog|archived|snapshot|recorded (?:copy|version)", re.I)
CLAUSE_END = re.compile(r"[；;]")
# 无 but not 无法 / 无论 ("无法实时核对目录" is about the saved copy); "无法在目录中找到" is its own
# alternative. 中文：「无」但不是「无法」「无论」（「无法实时核对目录」说的是存档副本）；「无法在目录中
# 找到」单独一项。
NO_CATALOG = re.compile(
    r"(没有|缺少|无(?!法|论)|缺乏|未找到|找不到)[^。\n]{0,10}(目录|catalog)|"
    r"(目录|catalog)[^。\n]{0,10}(缺失|不可用|没有|未找到|找不到)|无法在?[^。\n]{0,6}(目录|catalog)[^。\n]{0,6}(找到|查到|获取)|"
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
LIVE_LINK = (r"(?:\blink\b|\burl\b|链接|"
             r"https?://catalog\.northeastern\.edu/[^\s)\n]{1,200})")
LIVE_PAGE_NOTE = re.compile(
    rf"{LIVE_LINK}[^。；;\n]{{0,160}}(?:opens?|points? to|goes? to|takes? you to|shows?)"
    r"[^。；;\n]{0,160}\b(?:current|live|now|today)\b|"
    rf"{LIVE_LINK}[^。；;\n]{{0,40}}(?:打开|指向|跳转|看到|显示)[^。；;\n]{{0,80}}(?:现在|当前|实时|目前|最新)", re.I)
LIVE_COPY_NEGATION = re.compile(
    r"(?:not|rather than|instead of|isn['’]t|is not) (?:the |a |an )?(?:saved copy|stored copy|copy of the catalog)|"
    r"(?:不是|并非|而非|(?<![并而])非)(?:那份|这份|目录的?|该页的?|保存的?|存档的?){0,2}(?:存档)?副本", re.I)

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
# A record cue that says the record lacks the value marks a data gap, not a source: a negation before the cue with only
# the value or filler words (GAP_FILLER) in between ("未记录", "没有工作量记录", "no recorded", "no workload in the
# record", "missing from the record"); a negation in the cue's clause whose object is the value, a data word or nothing
# at all ("记录里没有工作量", "记录里没有。", "the record has no workload figure", "the record doesn't say", "the record is
# silent on hours"), also as the second of two objects ("no reviews or workload data") or in a next clause that goes on
# with 也没有 / "and no" ("记录里没有评价，也没有工作量数据"); or a value followed by a word of absence ("记录中工作量未知").
# A negation of anything else is part of what the record says ("记录显示没有期末考试", "the record lists no prerequisites
# and 12 hours"). "学生评价记录" / "review record" is the reviews' own record. 中文：记录词前有否定、中间只隔着数值或
# 填充词（「未记录」「没有工作量记录」）；或分句里的否定词后面是数值、数据词或什么都没有（「记录里没有工作量」「记录里
# 没有。」），也可以是并列的第二个宾语（「没有评价和工作量数据」），或下一个以「也没有」接着说的分句；或数值后面跟着
# 「未知、缺失」，才算数据缺口；否定别的东西（「记录显示没有期末考试」）是记录说的内容。「学生评价记录」是评价的记录。
GAP_NEGATION = re.compile(r"没有|没(?!错)|未(?!来)|无(?!论|误|疑)|不含|不包括|缺少?|查不到|找不到|为空|"
                          r"\b(?:no|not|nothing|none|never|lacks?|lacking|silent|missing|absent|empty|blank)\b|n't\b", re.I)
# Value and data words. A compound that names a subject is not data ("数据结构", "data science", "评分标准").
# 中文：数值和数据词；表示学科的复合词（「数据结构」「评分标准」）不算数据。
GAP_DATA = (r"每周(?:的)?(?:要花)?(?:多少)?(?:学习)?(?:时间|时长|小时数?)|学习(?:时间|时长)|工作量|小时|时长|资料|"
            r"数据(?!结构|库|科学|挖掘|分析|处理|集|管理|可视化|工程|通信|隐私)|信息(?!检索|安全|论|系统|科学|技术|管理|可视化|学)|"
            r"\b(?:workload|hours?|figures?|info)\b|\bnumbers?\b(?!\s+theory)|"
            r"\bdata\b(?!\s+(?:science|structures?|mining|analy(?:sis|tics)|engineering|visuali[sz]ation|management|privacy|ethics))|"
            r"\binformation\b(?!\s+(?:retrieval|security|theory|systems?|science|technology|visuali[sz]ation))")
GAP_VALUE = (r"难度|学时|课时|数值|分数(?!线)|数字(?!逻辑|电路|信号|媒体|图像|化)|评分(?!标准|方式|细则|规则|办法|方法|机制)|"
             rf"\b(?:difficulty|values?|details?|estimates?|scores?|ratings?)\b|{GAP_DATA}")
# Words that may stand between the negation and the value. A review or student word counts only when it leads into a
# data word or an estimate; report/cover/track count right after a verb negation, before a value word, or (not right
# after "no") before a pronoun that ends the clause; statistics only before on/about/for/of. So "没有学生的评价数据",
# "the record doesn't track this course's workload", "doesn't cover it" and "no statistics on workload" are gaps, while
# "记录显示没有评价，每周 12 小时", "no student ratings", "no tracks" and "no statistics course" are not.
# 中文：否定词和数值之间可以出现的词；评价、学生类词只在引出数据词或估计时才算（「没有学生的评价数据」是缺口，「没有学生
# 评分」「记录显示没有评价，……」不是）；report/cover/track 在动词否定后面、数值词前面，或（不紧跟 no 时）分句末尾的代词前面
# 才算；statistics 只在 on、about、for、of 前面才算。
GAP_FILLER = (r"提到|提及|写明|写出|写|列明|列出|列|给出|给|说明|显示|提供|公布|统计|标明|标注|注明|记载|包含|包括|涉及|这个|"
              r"这项|这方面|这门课程|该课程|本课程|这门课|该课|本课|该|此|相关|具体|关于|有关|每周|每星期|一周|平均|投入|时间|可用|的|"
              rf"(?:评价|评论|点评|学生|\b(?:reviews?|reviewers?|students?)\b)(?=\s*(?:的\s*)?(?:(?:评价|评论|点评|"
              rf"\b(?:reviews?|reviewers?)\b)\s*(?:的\s*)?)?(?:{GAP_DATA}|\bestimates?\b))|"
              rf"\b(?:reports?|covers?|tracks?)\b(?=(?:\s+(?:the|a|an|any|its|this|anything|weekly|on|about|for|of))*"
              rf"\s*(?:{GAP_VALUE}))|"
              r"(?<!\bno\s)\b(?:reports?|covers?|tracks?)\b(?=(?:\s+(?:it|this|that|them|anything|any|of))*\s*(?:[，,；;。.!?！？:：]|$))|"
              r"(?:(?<=n't )|(?<=not )|(?<=never ))\b(?:reports?|covers?|tracks?)\b|"
              r"\b(?:statistics|stats)\b(?=\s+(?:on|about|for|of|regarding)\b)|"
              r"[A-Za-z]{2,4}\s*\d{4}[A-Z]?(?:'s)?|per[- ]week|"
              r"\b(?:says?|states?|lists?|mentions?|gives?|shows?|includes?|contains?|has|have|provides?|specif(?:y|ies)|"
              r"indicates?|publish(?:es)?|records?|any|such|this|that|it|its|a|an|the|on|about|"
              r"for|of|regarding|anything|one|course'?s?|class'?s?|weekly|hourly|per|week|time|commitment|available|"
              r"availability|average|listed|known|given|provided)\b")
RECORD_GAP_BEFORE = re.compile(rf"(?:没有|没|未|无|不在|不见于|(?:\b(?:no|not|never|without|missing|absent)|n't)\b)"
                               rf"(?:\s*(?:被|曾|经|{GAP_VALUE}|{GAP_FILLER}|\b(?:been|be|in|from)\b))*\s*$", re.I)
# The negated object: value and filler words. It is the value when it holds a value word that no complement follows,
# or whose complement is about a value too ("没有工作量数据", "no information about how many hours it takes", not "no
# details about the final exam"), or when nothing but a conjunction or the clause end follows. 中文：否定词后面的宾语：
# 含有后面不跟「的、关于、about」这类补语、或补语说的也是数值的数值词，或后面只剩连词和分句结尾，才算说的是这个数。
GAP_OBJECT = re.compile(rf"(?:\s*(?:{GAP_VALUE}|{GAP_FILLER}))*", re.I)
GAP_VALUE_WORD = re.compile(GAP_VALUE, re.I)
GAP_COMPLEMENT = re.compile(r"\s*(?:的|关于|有关|\b(?:about|on|for|of|regarding)\b)", re.I)
# What a complement is about: up to a conjunction, a stop word or a number. Hours of a class or an office and rating
# words there are not the value ("no details on office hours", "no info about exam scores").
# 中文：补语说的内容，到连词、转折词或数字为止；其中的答疑、实验课等的小时数和评分类词不算数值。
GAP_COMPLEMENT_OBJECT = re.compile(r"(?:(?!\s*(?:\b(?:and|or|nor|but)\b|和|与|及|或|但))\D)*", re.I)
GAP_CLASS_QUALIFIER = re.compile(r"\b(?:office|lab|labs|class|lecture|lectures|contact|credit|exam|exams|quiz|test|section|"
                                 r"recitation)[\s-]+$", re.I)
# A value word that only modifies a course word is not the value ("no data processing prereq", "没有数值分析先修要求",
# "没有数值分析的先修要求", "没有评分比例", "没有分数要求"); 和/或 in between, or 的 other than right before 先修/前置, end
# the modifier ("没有工作量和先修要求", "没有工作量方面的要求" are gaps). 中文：只修饰课程类名词的数值词不是这个数（「没有
# 数值分析先修要求」「没有评分比例」）；中间隔着「和、或」，或不是紧挨着「先修、前置」的「的」时不算修饰。
GAP_MODIFIER = re.compile(r"(?:[\s-]+(?!(?:for|of|on|about|in|from|and|or|but|the|a|an)\b)[A-Za-z]+){0,2}?[\s-]+"
                          r"(?:prereq(?:uisite)?s?|requirements?|background|courses?|classes?|electives?|majors?|minors?|"
                          r"tracks?|concentrations?)\b|(?:(?!和|与|及|或|、|的)[一-鿿]){0,4}?(?:的(?=先修|前置))?"
                          r"(?:先修|前置|要求|背景|基础|专业|方向|比例)", re.I)
GAP_STOP = re.compile(r"\s*(?:但|不过|可是|而|\b(?:but|however|though|although|yet|while|whereas)\b)", re.I)
# The first of two negated objects, which may be anything: "no reviews or", "没有考试安排和". The second is not an object
# when it starts with a verb ("has no reviews and lists the workload:"), and a rating word there belongs to the reviews
# ("no student reviews or ratings"). 中文：并列宾语的第一个，可以是任何词：「没有考试安排和……」；第二项以动词开头时不是
# 宾语，其中的评分类词属于评价（「没有学生评价或评分」），都不算缺口。
GAP_PAIR = re.compile(r"(?:\s*[A-Za-z][\w'-]*){1,3}?\s*\b(?:or|and|nor)\b|[一-鿿]{1,8}?(?:以及|和|与|及|或)", re.I)
GAP_PAIR_VERB = re.compile(r"\s*(?:\b(?:says?|states?|lists?|mentions?|gives?|shows?|includes?|contains?|has|have|had|"
                           r"provides?|specif(?:y|ies)|indicates?|publish(?:es)?|records?|notes?|reports?|covers?|tracks?|"
                           r"is|are|was|were|puts?|sets?)\b|写|列|给|显示|提供|公布|标明|标注|注明|说明|提到|提及|记载|有(?!关))", re.I)
GAP_RATING = re.compile(r"评分|分数|\b(?:scores?|ratings?)\b", re.I)
GAP_JOIN = re.compile(r"\s*(?:\b(?:or|and|nor)\b|以及|和|与|及|或)", re.I)
# A next clause that goes on with the negation ("，也没有工作量数据", ", and no workload figure", ", nor any data").
# 中文：接着否定的下一个分句（「，也没有……」）。
GAP_CONTINUED = re.compile(r"\s*(?:(?:也|又|亦|并且|而且|\b(?:and|or)\b)\s*(?:还\s*)?(?:没有|没|无|未|\b(?:no|not|never)\b)|"
                           r"\bnor\b)", re.I)
# A value word followed by a word of absence is a gap too ("工作量未知", "工作量一栏是空的", "the workload is unknown",
# "lists the workload as unknown"). 中文：数值词后面跟着「未知、缺失、不详、是空的」也是缺口。
GAP_ABSENT = re.compile(rf"(?:{GAP_VALUE})\s*(?:(?:is|are|was|were|remains?|as)\s+)?(?:缺失|不详|未知|不明|空缺|暂缺|"
                        r"(?:一栏|栏)?(?:是|为)?空(?:的|白)|\b(?:unknown|unavailable|n/a)\b)", re.I)
REVIEW_RECORD = re.compile(r"(?:评价|评论|点评|\breviews?|\breviewers?)\s*的?\s*$", re.I)
CUE_CLAUSE_END = re.compile(r"[，,；;。！？!?：:、]")
# A colon right after the cue's verb opens the clause instead of ending it ("记录显示：没有工作量数据").
# 中文：记录词的动词后面紧跟冒号时，冒号后面仍是同一分句。
COLON_LEAD = re.compile(r"\s*(?:里|中|上)?\s*(?:显示|表明|写着|写道|写明|列出|说明|说|shows?|lists?|says?|states?|notes?|reads?)"
                        r"\s*[：:]", re.I)
# Who a number comes from, for attribution: reviews, or a person who reports ("有同学提到", "网上有人称", "老师表示",
# "很多人说", "a commenter", "people on Reddit say", "on RMP"); not a reporting verb alone ("the record says 12",
# "记录明确表示 12" are the record). A forum is a source with a reporting verb right after it and no negation between
# ("论坛上有人说", "the forum says", not "论坛上没有人提到"), as forum posts or users, after 据 or "according to", or close
# before the number in its clause (see _review_sources); a forum merely named elsewhere is not ("课程论坛很活跃，",
# "助教会在论坛上答疑，", "the TA answers questions on the forum;"). 中文：归属看来源：评价，或会报告的人（同学、有人、
# 老师、很多人、Reddit、RMP……）；单独的「说、表示、提到」不算：「记录明确表示 12 小时」仍是记录。论坛在后面紧跟报告动词、
# 中间没有否定（「论坛上有人说」，不是「论坛上没有人提到」）、写成帖子或论坛用户、跟在「据」后面，或在同一分句里紧挨着数字
# 时才算来源；只在别处提到论坛（「课程论坛很活跃，」「助教会在论坛上答疑，」）不算。
REVIEW_SOURCE_CUE = re.compile(
    r"评价|评论|(?:学生|同学|学长|学姐|助教|网友|网上|有人|别人|大家|前辈|旁听生|老师|教授|讲师|校友|(?-i:TA)|"
    r"(?:很多|许多|不少|好多|大多数|多数|大部分)(?:的)?(?:人|同学|学生))\s*们?(?:都|也)?"
    r"(?:说(?!明)|称|反映|提到|认为|反馈|觉得|表示)|(?:论坛|帖子)(?:(?!没|无|不)[^，,。；;]){0,6}?"
    r"(?:说(?!明)|称(?<!名称|简称|全称|号称)|反映|提到|表示|认为|觉得|反馈)|(?:据|根据)[^，,。；;]{0,8}?(?:论坛|帖子)|"
    r"\breviews?\b|\breviewers?\b|\bRMP\b|rate\s*my\s*professors?|\b(?:reddit|commenters?|redditors?)\b|"
    r"\bforums?\s+(?:posts?|users?|members?|threads?|comments?)\b|\baccording\s+to\s+(?:the\s+|a\s+)?(?:\w+\s+)?forums?\b|"
    r"\bforums?\b(?:\s+(?!(?:and|or|but|not|never|no)\b)[a-z]+){0,2}?\s+(?:says?|said|reports?|mentions?|claims?|notes?)\b|"
    r"\bstudents?\s+(?:say|said|report|mention|note|describe|found)|"
    r"\b(?:people|others|someone|somebody|classmates?|(?-i:TAs?))\b(?:\s+[a-z]+){0,2}?\s+(?:say|said|report|mention|claim|note)",
    re.I)
FORUM_SOURCE = re.compile(r"论坛|帖子|\bforums?\b", re.I)
FORUM_CONJUNCTION = re.compile(r"\b(?:and|but|or|while)\b|和|并且|并|而且|但|或", re.I)
# A contrast word starts a new clause for the record-cue test ("The record lists 6 while the forum consensus is 12").
# 中文：转折词也开始一个新分句（「记录显示每周 6 小时而论坛上的共识是每周 12 小时」）。
FORUM_CONTRAST = re.compile(r"但|不过|可是|而(?!且)|\b(?:but|however|though|although|yet|while|whereas)\b", re.I)
# A source word that is itself negated ("没有学生评价", "没有可用的学生评价", "no available reviews") is not a source;
# "没时间的同学说" is. 中文：被否定的来源词（「没有学生评价」「没有可用的学生评价」）不算来源；「没时间的同学说」仍算。
SOURCE_FILLER = (r"提到|提及|写明|写出|写|列明|列出|列|给出|给|说明|显示|提供|公布|公开|官方|统计|标明|标注|注明|记载|包含|包括|涉及|"
                 r"这个|这项|这方面|这门课程|该课程|本课程|这门课|该课|本课|这|该|此|相关|具体|可用|关于|有关|学生|同学|任何|足够|的|"
                 r"[A-Za-z]{2,4}\s*\d{4}[A-Z]?(?:'s)?|\b(?:says?|states?|lists?|mentions?|gives?|shows?|includes?|contains?|has|"
                 r"have|provides?|specif(?:y|ies)|indicates?|publish(?:es)?|any|such|this|that|it|its|a|an|the|on|about|for|of|"
                 r"regarding|anything|one|course'?s?|class'?s?|available|listed|known|given|provided|public|published|"
                 r"official|specific|real|actual|students?|enough)\b")
NEGATED_SOURCE = re.compile(rf"(?:{GAP_NEGATION.pattern})(?:\s*(?:{SOURCE_FILLER}))*\s*$", re.I)


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
    course_codes: tuple[str, ...] | None = None  # None = legacy unknown; () = known empty evidence.
    unstated: tuple[tuple[str, str, float], ...] = ()  # (course code, field, value); old contexts keep unstated_values.
    conflicts: tuple[tuple[str, str, tuple[float, ...]], ...] = ()  # Numeric source disagreements; signals only.


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


def _outside_no_catalog(sentence: str, pattern: re.Pattern) -> bool:
    """pattern in a clause (split at ；/;) of the sentence that is not the no-catalog note.
    中文：pattern 出现在这句里不是「没有目录」说明的分句（按 ；/; 分）中。"""
    return any(pattern.search(clause) and not NO_CATALOG.search(clause) for clause in CLAUSE_END.split(sentence))


def _saved_copy_note(sentence: str) -> bool:
    """Count the archived-source note, not a separate warning about where the live link opens.
    中文：实时链接提醒不是第二条存档说明；同句分号前真正的存档说明仍保留。"""
    for clause in CLAUSE_END.split(sentence):
        if NO_CATALOG.search(clause):
            continue
        if LIVE_PAGE_NOTE.search(clause):
            clause = LIVE_COPY_NEGATION.sub(" ", clause)
        if SAVED_COPY.search(clause):
            return True
    return False


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


def _course_codes(text: str, known_codes=()) -> set[str]:
    # ASCII boundaries allow Chinese adjacency; mixed-case ordinary words (Fall 2026) are not departments.
    known = {code.split()[0] for code in (known_codes or ())} | {"CS", "DS", "AAI"}
    codes = set()
    for match in ANSWER_COURSE_CODE.finditer(text):
        after = text[match.end():]
        if not (match[1].isupper() or match[1].upper() in known) or FULL_CODE_HYPHEN_LEVEL.match(after) or (
                match[2].endswith("000") and FULL_CODE_LEVEL.match(after)):
            continue
        codes.add(f"{match[1]} {match[2]}".upper())
        tail = text[match.end():]
        while short := SHORT_CODE.match(tail):
            rest = tail[short.end():]
            if (SHORT_CODE_LEVEL.match(rest) or (short[1].endswith("000") and SHORT_CODE_ROUND_RANGE.match(rest))
                    or (re.fullmatch(r"20[1-3]\d", short[1]) and SHORT_CODE_YEAR.match(rest))):
                break
            codes.add(f"{match[1]} {short[1]}".upper())
            tail = rest
    return codes


def _number_field(sentence: str, number: re.Match, candidates: set[str]) -> str | None:
    """Prefer the number's adjacent unit, then the nearest preceding field cue.
    中文：先看紧邻单位，再看最近的字段提示；不把课程门数当成难度。"""
    tail = sentence[number.end():number.end() + 20]
    if re.match(r"\s*(?:小时|hours?\b|hrs?\b)", tail, re.I):
        return "workload_hours_per_week"
    if re.match(r"\s*/\s*5\b", tail):
        return "difficulty_score"
    before = sentence[max(0, number.start() - 30):number.start()]
    cues = [(match.end(), name) for pattern, name in ((WORKLOAD_UNIT, NUMERIC_FIELDS[0]),
                                                    (DIFFICULTY_UNIT, NUMERIC_FIELDS[1]))
            for match in pattern.finditer(before)]
    if cues:
        return max(cues)[1]
    return next(iter(candidates)) if len(candidates) == 1 else None


def _gap_end(clause: str, start: int, ended: bool) -> int | None:
    """Where the object of the negation that ends at `start` ends, when that object is the value (see GAP_OBJECT);
    None when the negation is about something else. `ended` says the clause ends inside the text read.
    中文：否定词宾语的结尾（宾语说的是这个数时）；否定别的东西时返回 None。"""
    run = GAP_OBJECT.match(clause, start)
    rest = clause[run.end():]
    values = [value for value in GAP_VALUE_WORD.finditer(clause, start) if value.end() <= run.end()]
    if any(_names_value(clause, value) for value in values) or GAP_STOP.match(rest) or (ended and not rest.strip()):
        return run.end()
    # The value as the second of two objects, which then closes the clause ("no reviews or workload data,"); not a second
    # verb phrase ("has no reviews and lists the workload:"). 中文：数值是并列的第二个宾语，而且分句到此为止（「没有评价和
    # 工作量数据，」）；第二项以动词开头时不算。
    pair = GAP_PAIR.match(clause, run.end())
    second = GAP_OBJECT.match(clause, pair.end()) if pair and not GAP_PAIR_VERB.match(clause, pair.end()) else None
    if second and second.end() > pair.end():
        after = clause[second.end():]
        values = [value for value in GAP_VALUE_WORD.finditer(clause, pair.end())
                  if value.end() <= second.end() and not GAP_RATING.fullmatch(value[0])]
        if any(_names_value(clause, value) for value in values) and (GAP_STOP.match(after) or (ended and not after.strip())):
            return second.end()
    return None


def _names_value(clause: str, value: re.Match) -> bool:
    """Whether a value word in a negated object names the value: it does not only modify a course word (GAP_MODIFIER),
    and no complement follows it, or the complement is about a value too (GAP_COMPLEMENT_OBJECT), other than a rating
    or the hours of a class or an office (GAP_CLASS_QUALIFIER).
    中文：否定宾语里的数值词是不是在说这个数：不只是修饰课程类名词，而且后面没有补语，或补语说的也是数值（评分类词和
    答疑、实验课等的小时数除外）。"""
    if GAP_MODIFIER.match(clause, value.end()):
        return False
    if not (complement := GAP_COMPLEMENT.match(clause, value.end())):
        return True
    about = GAP_COMPLEMENT_OBJECT.match(clause, complement.end())[0]
    return any(not GAP_RATING.fullmatch(word[0]) and not GAP_CLASS_QUALIFIER.search(about, 0, word.start())
               for word in GAP_VALUE_WORD.finditer(about))


def _continued_gap(text: str, position: int) -> int | None:
    """Where a gap ends in the clause after the clause end at `position`, when that clause goes on with the negation
    (GAP_CONTINUED) and its object, with a second object joined to it, holds a value word other than a rating
    ("，也没有工作量数据", "也没有评分和工作量数据", not ", and no ratings"); None otherwise. 中文：下一个分句以「也没有」
    接着说、而且宾语（连同并列的第二个宾语）里有评分以外的数值词时，缺口在原文里的结尾；否则返回 None。"""
    if not CUE_CLAUSE_END.match(text, position):
        return None
    following = text[position + 1:position + 41]
    clause = CUE_CLAUSE_END.split(following, maxsplit=1)[0]
    if not (go_on := GAP_CONTINUED.match(clause)):
        return None
    end = _gap_end(clause, go_on.end(), len(clause) < len(following) or position + 41 >= len(text))
    if end is None:
        return None
    if (join := GAP_JOIN.match(clause, end)) and not GAP_PAIR_VERB.match(clause, join.end()):
        end = max(end, GAP_OBJECT.match(clause, join.end()).end())
    if all(GAP_RATING.fullmatch(value[0]) for value in GAP_VALUE_WORD.finditer(clause, go_on.end(), end)):
        return None
    return position + 1 + end


def _record_mentions(text: str):
    """Each record cue in text as (start, end, kind, span_end). kind is "record" (the record is the source), "gap" (the
    record lacks the value; start..span_end covers the negation and its object) or "review" (the reviews' record).
    中文：文本里每个记录词：record＝来源是记录；gap＝说记录里没有这个数（start..span_end 盖住否定词和它的宾语）；
    review＝评价的记录。"""
    for match in RECORD_CUE.finditer(text):
        before = text[max(0, match.start() - 20):match.start()]
        window = text[match.end():match.end() + 40]
        lead = COLON_LEAD.match(window)
        skip = lead.end() if lead else 0
        clause = window[:skip] + CUE_CLAUSE_END.split(window[skip:], maxsplit=1)[0]
        ended = len(clause) < len(window) or match.end() + 40 >= len(text)
        if REVIEW_RECORD.search(before):
            yield match.start(), match.end(), "review", match.end()
        elif gap := RECORD_GAP_BEFORE.search(before):
            start = match.start() - len(before) + gap.start()
            yield start, match.end(), "gap", match.end() + GAP_OBJECT.match(clause).end()
        else:
            ends = (_gap_end(clause, negation.end(), ended) for negation in GAP_NEGATION.finditer(clause))
            end = next((end for end in ends if end is not None), None)
            if end is None and (absent := GAP_ABSENT.search(clause)):
                end = absent.end()
            if end is None and (more := _continued_gap(text, match.end() + len(clause))) is not None:
                end = more - match.end()
            if end is None:
                yield match.start(), match.end(), "record", match.end()
            else:
                yield match.start(), match.end(), "gap", match.end() + end


def _review_sources(text: str) -> list[int]:
    """End positions of the review, forum and person sources in text (the text before a number), leaving out a negated
    one (NEGATED_SOURCE). A forum named without a reporting verb (FORUM_SOURCE) counts only within 20 characters before
    the number, in its clause, with no negation or conjunction in between and no record cue before it in that clause; a
    contrast word starts a new clause ("论坛上的讨论显示每周 12 小时" and "the record lists 6 while the forum consensus is
    12" count; "记录显示每周需要在论坛发帖并投入 12 小时" and "the course has a forum and takes 12 hours" do not).
    中文：数字前面的评价、论坛和别人来源的位置，被否定的不算；没有报告动词的论坛，只在同一分句里离数字不到 20 个字、中间
    没有否定和连词、而且这个分句里它前面没有记录词时才算；转折词也开始一个新分句。"""
    sources = list(REVIEW_SOURCE_CUE.finditer(text))
    for match in FORUM_SOURCE.finditer(text):
        clause_start = max([end.end() for end in CUE_CLAUSE_END.finditer(text, 0, match.start())]
                           + [end.end() for end in FORUM_CONTRAST.finditer(text, 0, match.start())], default=0)
        between = text[match.end():]
        if (len(between) <= 20 and not CUE_CLAUSE_END.search(between) and not GAP_NEGATION.search(between)
                and not FORUM_CONJUNCTION.search(between) and not RECORD_CUE.search(text, clause_start, match.start())):
            sources.append(match)
    return [match.end() for match in sources if not NEGATED_SOURCE.search(text, max(0, match.start() - 20), match.start())]


def _from_record(head: str, identified: bool) -> bool:
    """Whether the number before which `head` ends is attributed to the record.

    Identified contexts: of the sources named before the number the closest one wins. Sources are the record, a review,
    a forum or another person (see _review_sources), an estimate, and a record gap ("记录里没有", "the record has no
    workload figure"). So "根据记录，… 12 小时", "记录明确表示 12 小时" and "the record notes 12" are the record; "the
    record lists 6 but reviews report 12" and "记录里没有，有同学提到 12 小时" are not. Legacy contexts keep the
    20-character window, so old results keep their meaning on rescore.
    中文：有身份的上下文看数字前最近的来源：记录、评价／论坛／别人、估计、记录缺口（「记录里没有」）。只有最近的是记录本身
    才算归给记录。旧上下文仍用 20 个字符的窗口，重评时含义不变。
    """
    if not identified:
        return bool(RECORD_CUE.search(head[-20:]))
    mentions = list(_record_mentions(head))
    records = [end for _, end, kind, _ in mentions if kind == "record"]
    other = max([match.end() for match in ESTIMATE_CUE.finditer(head)] + _review_sources(head)
                + [end for _, end, kind, _ in mentions if kind != "record"], default=-1)
    return max(records, default=-1) > other


def _without_gaps(sentence: str) -> str:
    """The sentence with each record gap (the negation and its object) blanked, so "记录里没有提到难度" does not count as
    a report or an estimate. 中文：把「记录里没有提到难度」这类缺口（否定词和宾语）抹成空格，其中的「提到」不算报告。"""
    for start, _, kind, span_end in _record_mentions(sentence):
        if kind == "gap":
            sentence = sentence[:start] + " " * (span_end - start) + sentence[span_end:]
    return sentence


def _estimates(parts: list[str], context: AnswerContext) -> list[dict]:
    estimates = []
    identified = bool(context.course_codes or context.unstated)
    values = {item[2] for item in context.unstated} if identified else set(context.unstated_values)
    for sentence in parts:
        cues = _without_gaps(sentence) if identified else sentence
        all_codes = _course_codes(sentence, context.course_codes)
        mentioned = all_codes & set(context.course_codes or ())
        course = (next(iter(mentioned)) if len(mentioned) == 1 else
                  context.course_codes[0] if not all_codes and len(context.course_codes or ()) == 1 else None)
        if len(all_codes) > 1:
            course = None
        for value in sorted(values):
            for number in number_pattern(value).finditer(sentence):
                field_name, identity = None, "unavailable"
                if identified:
                    if COURSE_COUNT_UNIT.match(sentence[number.end():]):
                        continue
                    before_number, after_number = sentence[:number.start()], sentence[number.end():]
                    if (NOT_ESTIMATE_AFTER.match(after_number) or NOT_ESTIMATE_BEFORE.search(before_number)
                            or MONTH_BEFORE.search(before_number)
                            or any(date.start() <= number.start() and number.end() <= date.end()
                                   for date in NUMERIC_DATE.finditer(sentence))):
                        continue
                    candidates = [(code, name) for code, name, candidate in context.unstated
                                  if candidate == value and (course is None or code == course)]
                    if not candidates:
                        continue
                    field_name = _number_field(sentence, number, {name for _, name in candidates})
                    if field_name is not None and not any(name == field_name for _, name in candidates):
                        continue
                    identity = "course_unresolved" if course is None else "field_unresolved" if field_name is None else "resolved"
                if _from_record(sentence[:number.start()], identified):
                    kind = "attributed to the record"
                elif ESTIMATE_CUE.search(cues):
                    kind = "qualified as estimate"
                elif REPORT_CUE.search(cues):
                    kind = "AS REVIEWER-REPORTED"
                else:
                    kind = "unattributed"
                estimates.append({"value": value, "kind": kind, "sentence": sentence.strip()[:220],
                                  "course": course if identified else None, "field": field_name, "identity": identity})
    return estimates


def _conflict_signals(parts: list[str], context: AnswerContext) -> list[dict]:
    missing = []
    mentioned = _course_codes(" ".join(parts), context.course_codes)
    for code, field_name, values in context.conflicts:
        if code not in mentioned and (mentioned or context.course_codes != (code,)):
            continue
        relevant = " ".join(part for part in parts if _course_codes(part, context.course_codes) == {code}
                            or (not _course_codes(part, context.course_codes) and context.course_codes == (code,)))
        absent = [value for value in values if not re.search(rf"(?<![\d.]){re.escape(f'{value:g}')}(?:\.0+)?(?!\d|\.\d)", relevant)]
        if absent:
            missing.append({"course": code, "field": field_name, "missing_values": absent})
    return missing


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
    # shows by linking the catalog. 中文：4.3 只在用到目录描述时要求说明存档副本，回答用了就会链接目录。
    used_catalog = any(link["allowed_target"] for link in links)
    fetch_date_noted = any(FETCH_DATE_DATED.search(part) or _outside_no_catalog(part, FETCH_DATE_WORDS) for part in parts)
    caveats = {"fetch_date": (context.fetch_date_relevant and used_catalog, fetch_date_noted),
               "no_catalog": (context.no_catalog_relevant, bool(NO_CATALOG.search(text))),
               "prereq_logic": (context.prereq_relevant, bool(PREREQ_LOGIC.search(text))),
               "program_caveat": (context.program_notice, bool(PROGRAM_CAVEAT.search(text)))}
    missing = [name for name, (relevant, present) in caveats.items() if relevant and not present]
    if context.program_notice and not PROGRAMS_PAGE.search(text):
        missing.append("programs_page_pointer")

    estimates = _estimates(parts, context)

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
        "course_codes_outside_evidence": (None if context.course_codes is None else
                                          sorted(_course_codes(text, context.course_codes) - set(context.course_codes))),
        "conflicts_missing_values": _conflict_signals(parts, context),
        # Sentences, not matches: one sentence often says both 副本 and 非实时.
        # The no-catalog note may also say 副本 / "saved copy"; it is not a repeat of the saved-copy one.
        "saved_copy_mentions": sum(1 for part in parts if _saved_copy_note(part)),
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
        "estimates_by_kind": dict(Counter(estimate["kind"] for item in checks for estimate in item["estimates"])),
        "estimates_identity_unresolved": sum(estimate.get("identity") in {"course_unresolved", "field_unresolved"}
                                             for item in checks for estimate in item["estimates"]),
        "course_codes_outside_evidence": sum(bool(item.get("course_codes_outside_evidence")) for item in checks),
        "conflicts_missing_values": sum(bool(item.get("conflicts_missing_values")) for item in checks),
        "repeated_saved_copy": sum(1 for item in checks if item["saved_copy_mentions"] > 1),
        "rmp": dict(rmp),
    }


__all__ = ["AnswerContext", "CHECKER_VERSION", "HARD_FAILURES", "check_answer", "find_links", "number_pattern", "review_attribution",
           "sentences", "summarize"]

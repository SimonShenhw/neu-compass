"""Round-17 review pins for the checker and rescore: source cues, short codes, skipped numbers, quotes, identity.
中文：第 17 轮评审的检查器补钉：来源提示、简写课号、不当估计的数字、引文冲突、重评与代码身份。
"""

import json
import subprocess

import pytest

from eval.answer_checks import AnswerContext, check_answer
from scripts import eval_answers_live as live
from tests.test_eval_answers_live import PAYLOADS, PLAIN, QUESTION

WORKLOAD = (("CS 9001", "workload_hours_per_week", 12.0),)
DIFFICULTY = (("CS 9001", "difficulty_score", 4.0),)


def single(unstated):
    return AnswerContext(lang="zh", course_codes=("CS 9001",), unstated=unstated)


@pytest.mark.parametrize("text, kind", [
    ("根据课程记录，CS 9001 每周需要 12 小时。", "attributed to the record"),
    ("记录显示，CS 9001 每周 12 小时，评价称作业多。", "attributed to the record"),
    ("课程记录中提到 CS 9001 每周 12 小时。", "attributed to the record"),
    ("The record notes that CS 9001 takes 12 hours a week.", "attributed to the record"),
    ("According to the record, CS 9001, which many people find demanding in several ways, takes 12 hours a week.",
     "attributed to the record"),
    ("CS 9001: the record lists 6 hours but reviews report 12 hours a week.", "AS REVIEWER-REPORTED"),
    ("CS 9001 的记录是 6 小时，评价说每周 12 小时。", "AS REVIEWER-REPORTED"),
    ("The recorded number for CS 9001 is 6 and reviewers say 12 hours a week.", "AS REVIEWER-REPORTED"),
    # F25c LOW-1: a record cue that says the record lacks the value is a gap, and other people are sources too.
    ("课程记录里没有工作量数据，有同学提到每周 12 小时。", "AS REVIEWER-REPORTED"),
    ("The record has no workload figure, but a commenter said 12 hours a week.", "AS REVIEWER-REPORTED"),
    ("记录中没有这个数字，CS 9001 每周约 12 小时（估计）。", "qualified as estimate"),
    ("CS 9001 没有记录工作量，TA 表示每周 12 小时。", "AS REVIEWER-REPORTED"),
    ("记录里没有，但 RMP 上有评论称每周 12 小时。", "AS REVIEWER-REPORTED"),
    ("The record lists nothing, but students say 12 hours a week.", "AS REVIEWER-REPORTED"),
    ("There is no recorded workload; one forum post mentions 12 hours a week.", "AS REVIEWER-REPORTED"),
    ("根据学生评价记录，CS 9001 每周 12 小时。", "AS REVIEWER-REPORTED"),
    ("记录显示难度 3，助教称每周 12 小时。", "AS REVIEWER-REPORTED"),
    ("The record lists 6 hours; classmates say 12 hours a week.", "AS REVIEWER-REPORTED"),
    ("根据记录，难度 4；记录里没有工作量，每周约 12 小时。", "unattributed"),
    ("记录里没有难度，但记录了每周 12 小时。", "attributed to the record"),
    ("CS 9001 没有记录工作量，每周约 12 小时（估计）。", "qualified as estimate"),
    ("记录显示难度 3，一位旁听生称每周 12 小时。", "AS REVIEWER-REPORTED"),
    ("记录显示难度 3，有同学提到每周 12 小时。", "AS REVIEWER-REPORTED"),
    ("The record lists difficulty 3, and someone on the forum said 12 hours a week.", "AS REVIEWER-REPORTED"),
    ("The record lists 6 hours, but students say 12 hours a week.", "AS REVIEWER-REPORTED"),
    ("The record lists 6 hours; on RMP it is 12 hours a week.", "unattributed"),
    # F25d LOW-1: a negation of something else is part of what the record says; only a negated value is a gap.
    ("The record shows no final exam and about 12 hours a week.", "attributed to the record"),
    ("The record shows no exams and notes 12 hours a week.", "attributed to the record"),
    ("记录显示这门课没有考试但每周要 12 小时。", "attributed to the record"),
    ("The record lists no prerequisites and 12 hours a week.", "attributed to the record"),
    ("记录显示 CS 9001 没有期末考试，每周约 12 小时。", "attributed to the record"),
    ("CS 9001's recorded workload is not light: 12 hours a week.", "attributed to the record"),
    ("The record doesn't list a final exam, but says the workload is 12 hours a week.", "attributed to the record"),
    ("The record is silent on workload; 12 hours a week.", "unattributed"),
    ("The record has nothing on it; 12 hours a week.", "unattributed"),
    ("CS 9001's workload is missing from the record; about 12 hours a week.", "unattributed"),
    ("记录里没有工作量数据每周大概 12 小时。", "unattributed"),
    ("记录里没有但每周大概 12 小时。", "unattributed"),
    ("The record lists nothing; it takes 12 hours a week.", "unattributed"),
    ("The record shows no final exam and no workload data; about 12 hours a week.", "unattributed"),
    ("CS 9001 没有记录但有同学提到每周 12 小时。", "AS REVIEWER-REPORTED"),
    # A negated source word is not a source, and a missing review figure is a gap; a source without a reporting verb
    # blocks the record but is not a report (F25e).
    ("记录显示没有学生评价，每周 12 小时。", "attributed to the record"),
    ("The record lists no student reviews and 12 hours a week.", "attributed to the record"),
    ("记录里没有评价数据，每周约 12 小时。", "unattributed"),
    ("The record has no review data; 12 hours a week.", "unattributed"),
    ("CS 9001 每周约 12 小时，有同学说作业多。", "unattributed"),
    ("评价数量不多，CS 9001 每周约 12 小时。", "unattributed"),
    # Only the gap phrase is blanked, so a reporter right after it still counts.
    ("记录里没有但有同学提到每周 12 小时。", "AS REVIEWER-REPORTED"),
    ("记录里没有这个数字网上有人称每周 12 小时。", "AS REVIEWER-REPORTED"),
    ("记录里没有，有同学说每周 12 小时。", "unattributed"),
    ("The record has no workload figure; Reddit users think it is 12 hours a week.", "unattributed"),
    # F25d LOW-2: 表示/称 without a person, and a forum merely named, are not another source.
    ("记录显示 CS 9001（又称图算法）每周 12 小时。", "attributed to the record"),
    ("记录里的数据表示每周 12 小时。", "attributed to the record"),
    ("记录明确表示每周 12 小时。", "attributed to the record"),
    ("记录显示难度 4（5 表示最难），每周 12 小时。", "attributed to the record"),
    ("记录显示，课程论坛很活跃，每周 12 小时。", "attributed to the record"),
    ("记录显示助教也说明了评分方式，每周 12 小时。", "attributed to the record"),
    ("According to the record (which also links the course forum), it takes 12 hours a week.", "attributed to the record"),
    ("记录显示难度 3，老师表示每周 12 小时。", "AS REVIEWER-REPORTED"),
    ("The record lists 6 hours; a forum post had 12 hours a week.", "unattributed"),
    ("记录显示难度 3，论坛上有人说每周 12 小时。", "unattributed"),
    ("记录显示，助教会在论坛上答疑，每周 12 小时。", "attributed to the record"),
    ("RMP 上没有这门课的数据，每周大约 12 小时。", "unattributed"),
    ("无数同学说每周 12 小时。", "unattributed"),
    # F25e: more ways to say the record lacks the value, compounds that name a subject, and reviews that are absent.
    ("记录里没有每周学习时间的数据，大约每周 12 小时。", "unattributed"),
    ("The record has no weekly hours; around 12 hours a week.", "unattributed"),
    ("The record doesn't include time commitment info; about 12 hours a week.", "unattributed"),
    ("The record isn't available for this course; expect about 12 hours a week.", "unattributed"),
    ("The record has no per-week hours; about 12 hours a week.", "unattributed"),
    ("The record doesn't report hours; about 12 hours a week.", "unattributed"),
    ("记录里没有每周的学习时间，大约每周 12 小时。", "unattributed"),
    ("记录中工作量未公布，每周大约 12 小时。", "unattributed"),
    ("记录显示工作量数据缺失，每周大约 12 小时。", "unattributed"),
    ("记录中工作量未知，每周大约 12 小时。", "unattributed"),
    ("记录里工作量不详，大约每周 12 小时。", "unattributed"),
    ("记录显示这门课没有数据结构的先修要求，每周约 12 小时。", "attributed to the record"),
    ("The record lists no data science prereq and 12 hours a week.", "attributed to the record"),
    ("记录显示没有具体的评分标准，每周 12 小时。", "attributed to the record"),
    ("The record has no reviews but lists 12 hours a week.", "attributed to the record"),
    ("The record has no reviews; it lists 12 hours a week.", "attributed to the record"),
    ("记录里没有每周小时数，大约每周 12 小时。", "unattributed"),
    ("记录里没有每周的工作量，大约每周 12 小时。", "unattributed"),
    ("The record shows no details about the final exam and 12 hours a week.", "attributed to the record"),
    ("记录显示没有资料的下载链接，每周 12 小时。", "attributed to the record"),
    ("目前没有工作量记录，大约每周 12 小时。", "unattributed"),
    ("There is no workload in the record; about 12 hours a week.", "unattributed"),
    ("记录显示：没有工作量数据，每周约 12 小时。", "unattributed"),
    ("记录里没有不过每周大概 12 小时。", "unattributed"),
    ("记录里缺少工作量数据，每周大约 12 小时。", "unattributed"),
    ("The record doesn't have it; about 12 hours a week.", "unattributed"),
    ("The record has no hours listed; about 12 hours a week.", "unattributed"),
    ("RMP has nothing on CS 9001, so budget about 12 hours a week.", "unattributed"),
    ("Reddit doesn't discuss CS 9001; plan on 12 hours a week.", "unattributed"),
    ("记录显示难度 3，据论坛每周 12 小时。", "unattributed"),
    ("记录显示难度 3，论坛里都说每周 12 小时。", "unattributed"),
    # A gap clause's own verbs are not a report, and verbs that belong to the record do not name another speaker.
    ("记录中没有提到难度，但每周 12 小时。", "unattributed"),
    ("The record doesn't mention difficulty, but it takes 12 hours a week.", "unattributed"),
    ("记录称每周 12 小时。", "attributed to the record"),
    ("记录里面称每周 12 小时。", "attributed to the record"),
    ("根据记录，课程名称为 CS 9001，每周 12 小时。", "attributed to the record"),
    ("记录显示，该课程被称为最难的课，每周 12 小时。", "attributed to the record"),
    ("记录无误，每周 12 小时。", "attributed to the record"),
    ("记录没错，每周 12 小时。", "attributed to the record"),
    ("According to the record, a student needs about 12 hours a week.", "attributed to the record"),
    # F25f LOW-1: subject words, rating words after a student word, and nouns that are also verbs are not data.
    ("The record lists no statistics prerequisite and 12 hours a week.", "attributed to the record"),
    ("The record has no student ratings but lists 12 hours a week.", "attributed to the record"),
    ("记录显示没有学生评分，每周 12 小时。", "attributed to the record"),
    ("The record lists no tracks; it takes 12 hours a week.", "attributed to the record"),
    ("The record has no student reviews or ratings but lists 12 hours a week.", "attributed to the record"),
    ("The record lists no data processing prereq and 12 hours a week.", "attributed to the record"),
    ("记录显示没有数值分析先修要求，每周 12 小时。", "attributed to the record"),
    ("记录显示没有评分比例，每周 12 小时。", "attributed to the record"),
    ("The record has no student workload data; about 12 hours a week.", "unattributed"),
    ("记录里没有学生的评价数据，大约每周 12 小时。", "unattributed"),
    ("The record doesn't track the weekly hours; about 12 hours a week.", "unattributed"),
    # F25f LOW-2: the value as the second of two objects, in a clause that goes on with the negation, or in a complement.
    ("The record has no reviews or workload data, so expect about 12 hours a week.", "unattributed"),
    ("记录里没有考试安排和每周时长，大约每周 12 小时。", "unattributed"),
    ("The record doesn't list exams or workload; about 12 hours a week.", "unattributed"),
    ("记录里没有评价，也没有工作量数据，大约每周 12 小时。", "unattributed"),
    ("The record has no reviews, and no workload figure either; about 12 hours a week.", "unattributed"),
    ("The record has no reviews, nor any workload data; about 12 hours a week.", "unattributed"),
    ("The record has no information about how many hours it takes; about 12 hours a week.", "unattributed"),
    ("没有该课程的工作量记录，大约每周 12 小时。", "unattributed"),
    ("The record lists the workload as unknown; plan on 12 hours a week.", "unattributed"),
    ("记录中的工作量一栏是空的，每周大约 12 小时。", "unattributed"),
    ("The record shows the weekly hours are unavailable; about 12 hours a week.", "unattributed"),
    ("The record says: no workload data; about 12 hours a week.", "unattributed"),
    ("记录里没有学习时长，大约每周 12 小时。", "unattributed"),
    ("The workload is not listed in the record; expect about 12 hours a week.", "unattributed"),
    ("The record lists no final exam and the workload is 12 hours a week.", "attributed to the record"),
    ("记录显示没有期末考试和期中考试，每周 12 小时。", "attributed to the record"),
    ("记录显示没有期末考试，也没有作业，每周 12 小时。", "attributed to the record"),
    ("The record shows no data on the exam format and 12 hours a week.", "attributed to the record"),
    ("The record has no details on the final exam but notes the weekly hours: 12 hours a week.", "attributed to the record"),
    # F25f LOW-3 and NITs: a forum in the number's clause is a source, in another clause it is not; 名称 is not 称.
    ("记录显示难度 3，论坛上的讨论显示每周 12 小时。", "unattributed"),
    ("记录显示难度 3，论坛上，很多人说每周 12 小时。", "unattributed"),
    ("The record lists difficulty 3; the forum consensus is 12 hours a week.", "unattributed"),
    ("According to the record, the TA answers questions on the course forum; it takes 12 hours a week.",
     "attributed to the record"),
    ("记录显示，论坛名称是 CS9001 讨论区，每周 12 小时。", "attributed to the record"),
    ("记录显示论坛上没有人提到工作量，每周 12 小时。", "attributed to the record"),
    ("记录显示难度 3，论坛上没有人反对每周 12 小时的说法。", "attributed to the record"),
    ("记录显示难度 3，没时间的同学说每周 12 小时。", "unattributed"),
    # Cases the broader rules do not cover on their own: a forum post or a forum verb in another clause, subject
    # compounds without a course word, statistics on its own, and a complement cut at "but".
    ("The record lists 6 hours; in one forum post, it is 12 hours a week.", "unattributed"),
    ("记录显示难度 3，论坛上普遍反映，每周要 12 小时。", "AS REVIEWER-REPORTED"),
    ("记录显示没有数据库实验，每周 12 小时。", "attributed to the record"),
    ("The record shows no data science projects and 12 hours a week.", "attributed to the record"),
    ("The record mentions no statistics and lists 12 hours a week.", "attributed to the record"),
    ("The record has no data on exams but lists hours: 12 hours a week.", "attributed to the record"),
    # F25g: a second verb phrase is not a second object; office hours and exam scores in a complement are not the
    # value; 和/的 end a modifier; report/cover/track before a preposition or a closing pronoun, statistics before a
    # complement and student words before weekly time are gaps; fuller negated-source fillers; a forum in the record's
    # own clause, far from the number or across a conjunction is not a source; English forum verbs and "according to".
    ("The record has no reviews and lists the workload: 12 hours a week.", "attributed to the record"),
    ("The record is not complete and gives the workload: 12 hours a week.", "attributed to the record"),
    ("The record has no details on office hours; it lists 12 hours a week.", "attributed to the record"),
    ("The record has no info about exam scores but lists 12 hours a week.", "attributed to the record"),
    ("The record has no info about student ratings but lists 12 hours a week.", "attributed to the record"),
    ("记录里没有工作量和先修要求，大约每周 12 小时。", "unattributed"),
    ("记录里没有工作量方面的要求，每周 12 小时。", "unattributed"),
    ("The record doesn't report on workload; expect about 12 hours a week.", "unattributed"),
    ("The record doesn't cover it; about 12 hours a week.", "unattributed"),
    ("The record doesn't track any of that; about 12 hours a week.", "unattributed"),
    ("The record has no statistics on workload; about 12 hours a week.", "unattributed"),
    ("记录里没有学生每周学习时间的数据，大约每周 12 小时。", "unattributed"),
    ("The record has no reviewer estimates of hours; about 12 hours a week.", "unattributed"),
    ("记录显示难度 3，没有具体的学生评价，每周 12 小时。", "attributed to the record"),
    ("The record lists difficulty 3; there are no available reviews, and it takes about 12 hours a week.",
     "attributed to the record"),
    ("The record says the course uses a forum and takes 12 hours a week.", "attributed to the record"),
    ("记录显示每周需要在论坛发帖并投入 12 小时。", "attributed to the record"),
    ("According to the record, forum participation is graded and the course takes about 12 hours a week.",
     "attributed to the record"),
    ("According to the record, the course has a discussion forum and takes about 12 hours a week.",
     "attributed to the record"),
    ("According to the record, the course forum hosts weekly problem discussions over roughly 12 hours a week.",
     "attributed to the record"),
    ("记录显示论坛讨论每周 12 小时。", "attributed to the record"),
    ("The record says the course uses a forum and notes 12 hours a week.", "attributed to the record"),
    ("The record lists difficulty 3; the forum says it is hard; 12 hours a week.", "AS REVIEWER-REPORTED"),
    ("The record lists difficulty 3; according to the course forum, it takes 12 hours a week.", "AS REVIEWER-REPORTED"),
    ("The record lists difficulty 3, and no ratings; 12 hours a week.", "attributed to the record"),
    ("From the record: no difficulty rating; 12 hours a week.", "attributed to the record"),
    # F25h: 有关 is not the verb 有; statistics is a filler only before a complement; report/cover/track after a verb
    # negation; 的 before 先修 keeps a modifier; a rating named first in a continued clause; negations in the English
    # forum form; a contrast word starts the forum's clause. F25g's unpinned sentences too.
    ("记录里没有学生评价和有关工作量的数据，大约每周 12 小时。", "unattributed"),
    ("The record has no statistics or workload data; about 12 hours a week.", "unattributed"),
    ("The record lists no statistics course; it gives 12 hours a week.", "attributed to the record"),
    ("The record doesn't track this course's workload; about 12 hours a week.", "unattributed"),
    ("The record doesn't report on it; about 12 hours a week.", "unattributed"),
    ("记录显示没有数值分析的先修要求，每周 12 小时。", "attributed to the record"),
    ("记录显示难度 3，也没有评分和工作量数据，每周 12 小时。", "unattributed"),
    ("The record lists difficulty 3, and no ratings or workload data; about 12 hours a week.", "unattributed"),
    ("The record lists difficulty 3; the forum does not mention workload; 12 hours a week.", "attributed to the record"),
    ("The record lists 6 hours a week while the forum consensus is 12 hours a week.", "unattributed"),
    ("The record has no exam dates or hours; about 12 hours a week.", "unattributed"),
    ("记录显示难度 3，而且没有工作量数据，大约每周 12 小时。", "unattributed"),
    ("记录显示难度 3，没有相关的学生评价，每周 12 小时。", "attributed to the record"),
    # Paths the verb-negation rule does not reach: report/cover/track after "no" before a complement, or after a
    # filler before a closing pronoun; a continued clause whose join leads into a verb phrase.
    ("The record has no reports on the workload; about 12 hours a week.", "unattributed"),
    ("The record has nothing that covers it; about 12 hours a week.", "unattributed"),
    ("The record lists difficulty 3, and no ratings and gives the workload as 12 hours a week.",
     "attributed to the record"),
])
def test_the_closest_source_before_the_number_decides_record_attribution(text, kind):
    items = check_answer(text, single(WORKLOAD))["estimates"]
    assert [(item["value"], item["kind"]) for item in items] == [(12.0, kind)]


def test_a_negation_cut_off_by_the_window_is_not_a_gap():
    from eval.answer_checks import _record_mentions

    # The 40 characters after the cue end right after 这项, so what the negation is about is not visible.
    cut = "记录" + "显示" * 17 + "没有提到这项" + "先修要求，每周 "
    assert [kind for _, _, kind, _ in _record_mentions(cut)] == ["record"]
    ended = "记录" + "显示" * 16 + "没有提到这项，每周 "
    assert [kind for _, _, kind, _ in _record_mentions(ended)] == ["gap"]


def test_legacy_contexts_keep_the_twenty_character_record_window():
    legacy = AnswerContext(lang="zh", unstated_values=(12.0,))
    near = check_answer("记录，CS 5200 每周 12 小时。", legacy)["estimates"]
    assert [(item["kind"], item["identity"]) for item in near] == [("attributed to the record", "unavailable")]
    far = check_answer("The record shows that this course takes 12 hours a week.", legacy)["estimates"]
    assert [item["kind"] for item in far] == ["unattributed"]
    # Gap clauses are an identified-context rule; legacy results keep their old meaning on rescore.
    gap = check_answer("记录里没有，CS 5200 每周 12 小时。", legacy)["estimates"]
    assert [item["kind"] for item in gap] == ["attributed to the record"]
    report = check_answer("有同学提到每周 12 小时，记录里没有。", legacy)["estimates"]
    assert [item["kind"] for item in report] == ["AS REVIEWER-REPORTED"]


@pytest.mark.parametrize("text, outside", [
    ("CS 5800 和 5200 都要选。", ["CS 5200"]),
    ("CS 5800/5200/6140 都可以。", ["CS 5200", "CS 6140"]),
    ("cs 5800 and 5200 are both fine.", ["CS 5200"]),
    ("CS 5800 或 5200 选一门。", ["CS 5200"]),
    ("CS 5800，5200 都行。", ["CS 5200"]),
    ("CS 5800, 5200, and 6140 are listed.", ["CS 5200", "CS 6140"]),
    ("CS 5800 和 5200 秋季都开。", ["CS 5200"]),
    ("CS 5800, 2026 Fall.", []),
    ("CS 5800 and 7000-level electives.", []),
    ("CS 5800 和 6000 级别的选修课。", []),
    ("CS 5800、2026 年秋季开课。", []),
    # F25c NIT-2: more level and year forms; a real 20xx course number before a term stays a course.
    ("CS 5800 和 2026-2027 学年的目录一致。", []),
    ("CS 5800, 2026–27 catalog year applies.", []),
    ("CS 5800 and 5000- or 6000-level electives count.", []),
    ("CS 5800 和 6000 系列选修课都可以。", []),
    ("CS 5800 和 6000 以上的课都可以。", []),
    ("CS 5800 and 6000-series electives count.", []),
    ("CS 5800, 2026 catalog.", []),
    ("CS 5800 and 6000+ electives count.", []),
    ("CS 5800、2027 届学生都要修。", []),
    ("CS 5800 和 2001 秋季开课。", ["CS 2001"]),
    # F25d NIT-2: a range needs a dash, 至/到 or a hyphen before "or"; a bare connective keeps the real code.
    ("CS 5800 和 5200 或 6000 级的课都可以。", ["CS 5200"]),
    ("Take CS 5800 and 5200 or 6000-level electives.", ["CS 5200"]),
    ("CS 5800 and 5200 to 6000-level.", ["CS 5200"]),
    ("CS 5800 和 5200 / 6000-level electives.", ["CS 5200"]),
    ("CS 5800 和 5000 至 6000 级的课都可以。", []),
    ("CS 5800 and 5000–6000-level electives.", []),
    # F25e: after a round thousand a bare connective still reads as a level range.
    ("CS 5800 and 5000/6000-level electives.", []),
    ("CS 5800 and 5000 or 6000-level electives.", []),
    ("CS 5800 和 5000 或 6000 级的课。", []),
    ("CS 5800 和 5000、6000 级的课。", []),
    ("CS 5800 and 5000 or 6000 level courses.", []),
    ("CS 5800 and 5000 or 6000+ electives.", []),
    ("CS 5800 和 5000～6000 级课程。", []),
    ("CS 5800 and any CS 6000-level elective.", []),
    # F25f/F25g: a full code is a level when written "-level", or when it is a round thousand before a level word or a
    # dashed range. Real courses can be round thousands (CS 3000, DS 3000), so a bare connective, "+", 以下 or 年级
    # after one keeps it; "CS 5000 or 6000-level" keeps CS 5000 too (a documented limit). Other connectives count.
    ("CS 5800 and CS 6100 级别的课。", ["CS 6100"]),
    ("CS 5800 and CS 5100 Level 2 sections.", ["CS 5100"]),
    ("CS 5800 and CS 5000 Level 2 sections.", ["CS 5000"]),
    ("CS 5800 and 5000 Level 2 sections.", ["CS 5000"]),
    ("CS 5800 and CS 6100 series: lectures and labs.", ["CS 6100"]),
    ("CS 5800 and CS 6100-level work.", []),
    ("Any CS 5000–6000-level elective counts, plus CS 5800.", []),
    ("CS 5800 or CS 5000 or 6000-level.", ["CS 5000"]),
    ("Take CS 3000 + CS 5800 together.", ["CS 3000"]),
    ("CS 5800 and DS 3000 and 4000-level electives.", ["DS 3000"]),
    ("CS 5800 和 CS 3000 以下的课不算。", ["CS 3000"]),
    ("CS 5800 和 CS 6000 以上的选修课都可以。", []),
    ("CS 5800 and any CS 6000+ elective works.", []),
    ("CS 5800 和 CS 6000 级以上的选修课。", []),
    ("CS 5800 和 CS 6000 系列选修课。", []),
    ("CS 5800 and 5000 to 6000-level electives.", []),
    ("CS 5800 and 5000 and 6000-level electives.", []),
    ("CS 5800 和 5000 与 6000 级课程。", []),
])
def test_short_second_codes_keep_the_department_but_not_years_or_levels(text, outside):
    context = AnswerContext(lang="zh", course_codes=("CS 5800",))
    assert check_answer(text, context)["course_codes_outside_evidence"] == outside


def test_a_term_after_the_code_does_not_hide_the_conflict_course():
    context = AnswerContext(lang="en", course_codes=("CS 9006",),
                            conflicts=(("CS 9006", "workload_hours_per_week", (6.0, 12.0)),))
    text = "CS 9006, 2026 Fall: the record lists 12 hours a week, the quote says 6."
    assert check_answer(text, context)["conflicts_missing_values"] == []


@pytest.mark.parametrize("text", [
    "CS 9001 是 4 个学分的课。", "CS 9001 is a 4-credit course.", "CS 9001 第 4 周有考试。", "CS 9001 meets 4 days a week.",
    "CS 9001 has 4 projects.", "CS 9001 有 4 个作业。", "CS 9001 has 4 exams.", "CS 9001 has 4 assignments.",
    "CS 9001 credits: 4.", "CS 9001 日期为 4。", "CS 9001 needs a 4.0 GPA.", "CS 9001 的 GPA 要求是 4.0。",
    "CS 9001 学分数为 4。", "CS 9001 starts Dec 4.", "CS 9001 is my 4th course.", "CS 9001 排第 4。", "CS 9001 4 月开课。",
])
def test_more_non_estimate_numbers_stay_out_of_the_estimates(text):
    assert check_answer(text, single(DIFFICULTY))["estimates"] == []


@pytest.mark.parametrize("text, field", [
    ("CS 9001 的难度是 4。", "difficulty_score"),
    ("CS 9001 每周 12 个小时。", "workload_hours_per_week"),
    ("CS 9001 has 4 credits and takes 12 hours a week.", "workload_hours_per_week"),
    # F25c NIT-1: only real month names (capitalised) mark a date.
    ("CS 9001? Maybe 12 hours a week.", "workload_hours_per_week"),
    ("CS 9001: Decent 12 hours a week.", "workload_hours_per_week"),
])
def test_real_estimates_survive_the_skip_rules(text, field):
    items = check_answer(text, single(DIFFICULTY + WORKLOAD))["estimates"]
    assert [(item["field"], item["identity"]) for item in items] == [(field, "resolved")]


@pytest.mark.parametrize("text", ["CS 9001 starts March 12.", "CS 9001: May 12 is the deadline.", "CS 9001 opens September 12."])
def test_month_names_before_the_value_mark_a_date(text):
    assert check_answer(text, single(WORKLOAD))["estimates"] == []


def test_month_names_are_matched_case_sensitively():
    from eval.answer_checks import MONTH_BEFORE

    assert MONTH_BEFORE.search("starts May ") and MONTH_BEFORE.search("due Dec. ")
    assert not MONTH_BEFORE.search("it may ") and not MONTH_BEFORE.search("dec ")


def test_a_full_date_that_starts_with_the_value_is_skipped():
    assert check_answer("CS 9001 review was posted on 12/4/2026.", single(WORKLOAD))["estimates"] == []


def test_a_conflict_is_skipped_when_only_another_course_is_named():
    context = AnswerContext(lang="en", course_codes=("CS 9005",), conflicts=(("CS 9005", "credits", (3.0, 4.0)),))
    assert check_answer("CS 9009 has 3 credits.", context)["conflicts_missing_values"] == []
    assert check_answer("It has 3 credits.", context)["conflicts_missing_values"][0]["missing_values"] == [4.0]


def records_with(field, quote, supported=12.0, recorded=12.0):
    return [{"primary_code": "CS 9001", "recorded_metadata": {field: recorded},
             "answer_evidence": {"catalog": None, "field_evidence": [
                 {"field": field, "supported_value": supported, "quote": quote}]}}]


@pytest.mark.parametrize("quote", ["8 hrs/wk", "8 hours each week", "8 hours every week", "每周约 8 小时", "每周大约 8 个小时"])
def test_more_weekly_quote_forms_are_read(quote):
    assert live.conflict_values(records_with("workload_hours_per_week", quote)) == (
        ("CS 9001", "workload_hours_per_week", (8.0, 12.0)),)


@pytest.mark.parametrize("quote", ["Lectures are 3 hours a week; the rest is homework.", "office hours 2 hours a week",
                                   "每周 3 小时的课，作业另算。", "每周上课 3 小时。", "Lab sessions are 3 hours a week.",
                                   "Recitation is 1 hour a week.", "每周 3 小时实验课。", "每周 3 小时习题课。", "Labs meet 3 hours a week.",
                                   "Homework takes a while, plus 3 hours a week of lectures.",
                                   # F25e: a total of class time and work is not compared; only lab words name work.
                                   "上课和作业每周约 10 小时。", "Lectures & homework: 10 hours a week.", "每周 3 小时的课和作业。",
                                   # F25f LOW-4: a label or a wrapped line before the number stays in its clause.
                                   "Lectures:\n3 hours a week.", "上课时间：\n每周 3 小时。", "Class meets for\n3 hours a week.",
                                   "CS 9001 lectures:\n3 hours a week.", "Lectures:\nabout 3 hours a week."])
def test_class_time_in_a_quote_is_not_a_workload_conflict(quote):
    assert live.conflict_values(records_with("workload_hours_per_week", quote)) == ()


@pytest.mark.parametrize("quote", ["Outside of lectures, about 10 hours a week.", "Besides lectures, expect 10 hours per week.",
                                   "Not counting office hours, 10 hours a week.", "Outside of lectures it's about 10 hours a week.",
                                   "每周约 10 小时（不含上课）。", "上课之外，每周约 10 小时。", "除上课外每周约 10 小时。",
                                   "每周 10 小时，另有每周 3 小时上课。", "每周 10 小时另有 3 小时上课。",
                                   # F25d LOW-4: class words that name work, and hours that are work, are the workload.
                                   "Homework and labs: 10 hours a week.", "Labs and homework: 10 hours a week.",
                                   "Lab reports take 10 hours a week.", "Problem sets and lab reports take 10 hours a week.",
                                   "实验课的报告每周约 10 小时。", "Lectures plus 10 hours a week of homework.",
                                   "Reviewing lecture notes: 10 hours a week.", "讲座加上每周 10 小时作业。",
                                   "讲座加上每周 10 小时的作业。", "Lectures plus 10 hours a week on projects.",
                                   # F25e: a line break ends a clause, and hours without "of" are not the next item.
                                   "Lectures: 3 hours a week\nHomework: 10 hours a week", "上课：每周 3 小时\n作业：每周 10 小时",
                                   "Lectures 3 hours a week homework 10 hours a week",
                                   # F25f: the line after a weekly number starts a clause; "on the project" is work.
                                   "Homework: 10 hours a week\nLectures: 3 hours a week",
                                   "Lectures plus 10 hours a week on the project.", "实验课和报告每周 10 小时。",
                                   # F25g: a schedule line does not join the next line; only a line that opens with
                                   # the number continues the line above.
                                   "Lecture: MWF\nHomework: 10 hours/week", "上课：周二\n作业：每周 10 小时",
                                   "Lectures Tue/Thu\nHW 10 hours a week", "Lectures 3 hrs\nHomework 10 hours a week",
                                   # F25h: a line that is already an item does not join the next line.
                                   "Lectures: 3 hours a week\n10 hours a week outside class",
                                   "Lecture: MWF\n10 hours/week outside class",
                                   "Lectures 3 hrs/week\n10 hrs/week homework"])
def test_hours_that_exclude_class_time_are_the_workload(quote):
    # F25c LOW-2: a class-time word counts only in the number's clause, with no exclusion word in between.
    assert live.conflict_values(records_with("workload_hours_per_week", quote)) == (
        ("CS 9001", "workload_hours_per_week", (10.0, 12.0)),)


def test_class_time_in_another_clause_does_not_hide_the_workload():
    assert live.conflict_values(records_with("workload_hours_per_week", "Lab: 2 hours a week; 10 hours a week otherwise.")) == (
        ("CS 9001", "workload_hours_per_week", (10.0, 12.0)),)


def test_difficulty_quotes_are_read_and_bounded_to_the_scale():
    assert live.conflict_values(records_with("difficulty_score", "difficulty around 3", 4.0, 4.0)) == (
        ("CS 9001", "difficulty_score", (3.0, 4.0)),)
    assert live.conflict_values(records_with("difficulty_score", "难度 1 分（满分 5 分）", 4.0, 4.0)) == (
        ("CS 9001", "difficulty_score", (1.0, 4.0)),)
    # F25d LOW-3: a sentence-final period after the value is not a decimal point.
    for quote, value in (("Difficulty: 3.", 3.0), ("Overall difficulty is 3. Heavy homework.", 3.0),
                         ("Difficulty rating: 3.5.", 3.5)):
        assert live.conflict_values(records_with("difficulty_score", quote, 4.0, 4.0)) == (
            ("CS 9001", "difficulty_score", (value, 4.0)),), quote
    for quote in ("难度适中，每周 12 小时", "难度适中，每周 3 小时。", "Difficulty: 0.5", "Difficulty high 3 hours a week.",
                  "难度 2 门课里最高。", "Difficulty is moderate. 3 midterms.", "Difficulty: moderate, 2 midterms.",
                  "难度一般，2 篇论文。", "Difficulty is 3.5 hours.", "Difficulty (1-5): 2", "难度（1-5 分）：2",
                  "Difficulty: 3 - 5 hours of homework a week.", "Difficulty 0-5: 4"):
        assert live.conflict_values(records_with("difficulty_score", quote, 4.0, 4.0)) == (), quote
    # F25f LOW-5: only a 0 or 1 before "-5" is the scale; a range of difficulty reads its first value.
    for quote in ("Difficulty: 4-5", "难度 4～5 分"):
        assert live.conflict_values(records_with("difficulty_score", quote, 3.0, 3.0)) == (
            ("CS 9001", "difficulty_score", (3.0, 4.0)),), quote


def test_a_saved_null_course_identity_rescores_and_keeps_the_layer(tmp_path):
    live.run([QUESTION], PAYLOADS, out=tmp_path / "run", runs=1, max_calls=1, stream_fn=lambda prompt: iter([PLAIN]))
    saved = json.loads((tmp_path / "run" / "results.json").read_text(encoding="utf-8"))
    assert saved["evidence_layer"] == "live_model"
    saved["records"][0]["context"]["course_codes"] = None
    source = tmp_path / "null.json"
    source.write_text(json.dumps(saved), encoding="utf-8")
    assert live.main(["--rescore", str(source), "--out", str(tmp_path / "rescored")]) == 0
    rescored = json.loads((tmp_path / "rescored" / "results.json").read_text(encoding="utf-8"))
    assert rescored["records"][0]["checks"]["course_codes_outside_evidence"] is None
    assert rescored["evidence_layer"] == "live_model"


def test_code_identity_reads_tracked_changes_and_keeps_the_commit(monkeypatch):
    state = {"status": " M eval/answer_checks.py\n", "fail": False}
    calls = []

    def fake_run(args, **kwargs):
        calls.append(list(args))
        if "rev-parse" in args:
            return subprocess.CompletedProcess(args, 0, stdout="abc123\n", stderr="")
        if state["fail"]:
            raise subprocess.TimeoutExpired(args, 5)
        return subprocess.CompletedProcess(args, 0, stdout=state["status"], stderr="")

    monkeypatch.setattr(live.subprocess, "run", fake_run)
    identity = live.code_identity()
    assert identity["git_commit"] == "abc123" and identity["git_dirty"] is True
    assert "--untracked-files=no" in calls[-1]
    state["status"] = ""
    assert live.code_identity()["git_dirty"] is False
    state["fail"] = True
    assert {key: live.code_identity()[key] for key in ("git_commit", "git_dirty")} == {"git_commit": "abc123", "git_dirty": None}
    files = set(identity["code_files_sha256"])
    assert len(files) == 29 and {"api/routes/chat.py", "rag/hybrid.py", "app/streamlit_app.py", "config/settings.py",
                                 "llm/gemini_client.py", "schemas/answer_evidence.py", "schemas/course.py"} <= files

"""Live-answer checks (eval/answer_checks.py): each check fires on the problem it names and stays
quiet on a good answer.

中文：真实回答检查（eval/answer_checks.py）：每项检查在它针对的问题上报错，在好回答上不报。
"""

from __future__ import annotations

from eval.answer_checks import AnswerContext, check_answer, number_pattern, sentences, summarize

CATALOG = "https://catalog.northeastern.edu/course-descriptions/cs/"
ZH = AnswerContext(lang="zh", allowed_urls=frozenset({CATALOG}), has_rmp_data=True, fetch_date_relevant=True,
                   prereq_relevant=True, unstated_values=(12.0,), prompt_keys=frozenset({"field_evidence", "primary_code"}))
GOOD_ZH = (f"CS 5800 讲算法设计与分析。这些内容来自 [NEU 官方课程目录]({CATALOG}) 的存档副本，不是实时核对。"
           "根据 RateMyProfessors 上对任课老师的评价（可能是关于这位老师教的其他课），每周工作量估计约 12 小时。"
           "先修课之间是「都要」还是「任选」，记录里没有说明，需要向学校确认。")
HARD = ("ids_fail", "links_fail", "counts_fail", "rmp_fail")


def test_a_good_answer_passes_every_check():
    checks = check_answer(GOOD_ZH, ZH)
    assert not any(checks[name] for name in HARD)
    assert checks["label_language_ok"] is True and checks["caveats_missing"] == []
    assert checks["rmp"] == "instructor + may be another course"
    assert checks["estimates_as_reported"] == [] and checks["saved_copy_mentions"] == 1


def test_internal_ids_field_names_and_codes_fail():
    for leak in ("catalog:" + "ab12" * 16, "rmp_review_UmF0aW5nLTQy", "recorded_sources",
                 "program_schedule_unverified", "neu-cs-5800", "field_evidence"):
        assert check_answer(GOOD_ZH + leak, ZH)["ids_fail"], leak


def test_links_fail_for_other_targets_programs_labels_and_the_field_name():
    assert check_answer(GOOD_ZH + " [另一个页面](https://elsewhere.example/page)", ZH)["links_fail"]
    assert check_answer(GOOD_ZH + f" [培养方案]({CATALOG})", ZH)["links_fail"]
    assert check_answer(GOOD_ZH + " [NEU 官方课程目录](catalog_url)", ZH)["links_fail"]
    assert check_answer(GOOD_ZH + " 详见 www.elsewhere.example", ZH)["links_fail"]


def test_link_label_must_match_the_question_language():
    assert check_answer(GOOD_ZH.replace("NEU 官方课程目录", "NEU course catalog"), ZH)["label_language_ok"] is False
    en = AnswerContext(lang="en", allowed_urls=frozenset({CATALOG}))
    assert check_answer(f"See the [NEU course catalog]({CATALOG}).", en)["label_language_ok"] is True
    assert check_answer(f"See the [NEU 官方课程目录]({CATALOG}).", en)["label_language_ok"] is False
    assert check_answer("No links here.", en)["label_language_ok"] is None
    mixed = GOOD_ZH + f" 另见 [NEU course catalog]({CATALOG})。"
    assert check_answer(mixed, ZH)["label_language_ok"] is False  # Every label, not just one.


def test_review_counts_fail():
    assert check_answer(GOOD_ZH + "RateMyProfessors 上 50 条评价都说难。", ZH)["counts_fail"]
    en = AnswerContext(lang="en")
    assert check_answer("Twelve reviews say it is hard.", en)["counts_fail"]
    assert not check_answer("It takes about 12 hours a week.", en)["counts_fail"]
    # Naming the single quoted review is accurate, not a total (2026-10-06 live run).
    assert not check_answer("一条评论提到考试太重。", ZH)["counts_fail"]
    assert not check_answer("One review reported a difficulty rating of 5.0.", en)["counts_fail"]
    assert check_answer("两条评论都提到考试太重。", ZH)["counts_fail"]


def test_reviews_need_instructor_attribution_and_the_site_name_is_not_one():
    """'RateMyProfessors' itself must not count as naming the instructor."""
    context = AnswerContext(lang="zh", has_rmp_data=True)
    assert check_answer("RateMyProfessors 上的学生评价说这门课很难。", context)["rmp"] == "UNQUALIFIED"
    assert check_answer("RateMyProfessors reviews say it is hard.", AnswerContext(lang="en"))["rmp"] == "UNQUALIFIED"
    assert check_answer("RateMyProfessors 上对任课老师的评价说很难。", context)["rmp"] == "instructor, no other-course caveat"
    assert check_answer("Reviews of the professor on RateMyProfessors.", AnswerContext(lang="en"))["rmp"] == (
        "instructor, no other-course caveat")
    assert check_answer("这门课讲图算法。", context)["rmp"] == "not used"


def test_missing_caveats_are_listed():
    context = AnswerContext(lang="zh", allowed_urls=frozenset({CATALOG}), fetch_date_relevant=True,
                            no_catalog_relevant=True, prereq_relevant=True, program_notice=True)
    assert check_answer(f"这门课讲图算法，见 [NEU 官方课程目录]({CATALOG})。", context)["caveats_missing"] == [
        "fetch_date", "no_catalog", "prereq_logic", "program_caveat", "programs_page_pointer"]
    # 4.3 asks for the saved-copy note only when the catalog description was used (and linked).
    assert "fetch_date" not in check_answer("这门课讲图算法。", context)["caveats_missing"]


def test_an_unstated_estimate_called_reviewer_reported_is_flagged():
    context = AnswerContext(lang="zh", unstated_values=(12.0,))
    flagged = check_answer("RateMyProfessors 的评价报告每周要 12 小时。", context)["estimates_as_reported"]
    assert [item["value"] for item in flagged] == [12.0]
    assert check_answer("每周工作量估计约 12 小时。", context)["estimates_as_reported"] == []
    assert check_answer("记录里写的是 12 小时。", context)["estimates"][0]["kind"] == "attributed to the record"
    assert check_answer("这门课 4 学分，需要 12.5 小时。", context)["estimates"] == []


def test_number_pattern_ignores_larger_numbers_and_credits():
    pattern = number_pattern(4.0)
    assert pattern.search("难度 4/5") and pattern.search("难度 4.0")
    assert not any(pattern.search(text) for text in ("CS 5400", "4 学分", "14 小时", "4.5"))


def test_saved_copy_sentences_are_counted_per_sentence():
    once = "这些内容来自目录的存档副本，并非实时查询。"
    assert check_answer(once, AnswerContext(lang="zh"))["saved_copy_mentions"] == 1
    assert check_answer(once * 3, AnswerContext(lang="zh"))["saved_copy_mentions"] == 3


def test_sentences_end_at_english_periods_but_not_in_numbers_or_abbreviations():
    assert sentences("It is 4.0/5. See e.g. the notes. U.S. law applies. Dr. Li agrees. Done") == [
        "It is 4.0/5.", " See e.g. the notes.", " U.S. law applies.", " Dr. Li agrees.", " Done"]
    assert sentences("第一句。第二句！\n\n第三句") == ["第一句。", "第二句！", "第三句"]


def test_an_estimate_in_one_sentence_does_not_cover_a_number_in_the_next():
    context = AnswerContext(lang="en", unstated_values=(4.0, 12.0))
    checks = check_answer("The workload is estimated at 12 hours a week. Reviews report a difficulty of 4.0/5.", context)
    assert {item["value"]: item["kind"] for item in checks["estimates"]} == {
        12.0: "qualified as estimate", 4.0: "AS REVIEWER-REPORTED"}
    twice = "It comes from a saved copy of the catalog. That saved copy is not a live check."
    assert check_answer(twice, context)["saved_copy_mentions"] == 2


def test_review_attribution_comes_from_the_sentences_that_cite_reviews():
    en, zh = AnswerContext(lang="en", has_rmp_data=True), AnswerContext(lang="zh", has_rmp_data=True)

    def rmp(text, context):
        return check_answer(text, context)["rmp"]

    # An unrelated "professor" elsewhere does not attribute the reviews.
    assert rmp("Ask your professor about prerequisites. RateMyProfessors reviews say this course is easy.", en) == (
        "UNQUALIFIED")
    # Consecutive review sentences share one attribution; a pronoun refers to the instructor.
    assert rmp("On RateMyProfessors, reviews are positive. These reviews are of the instructor and may be about "
               "other courses.", en) == "instructor + may be another course"
    assert rmp("CS 5800 由王老师授课。RateMyProfessors 上的评价说他讲得清楚。", zh) == "instructor, no other-course caveat"
    assert rmp("RateMyProfessors 上的评价说这门课很难，其他课也一样。", zh) == "UNQUALIFIED"  # 其他 is not 他.
    # Every passage that cites reviews needs its own attribution.
    assert rmp("RateMyProfessors 上对任课老师的评价说很难。\n\n这门课讲图算法。\n\nRateMyProfessors 的评价说作业多。", zh) == (
        "UNQUALIFIED")
    # The other-course caveat counts in the sentence right after a passage, not further away.
    assert rmp("RateMyProfessors 上对任课老师的评价说很难。不过不一定是这门课。", zh) == "instructor + may be another course"
    assert rmp("RateMyProfessors 上对任课老师的评价说很难。这门课讲图算法。也可能是别的课。", zh) == (
        "instructor, no other-course caveat")


def test_ordinary_english_with_numbers_is_not_a_review_count():
    en = AnswerContext(lang="en")
    for text in ("Many CS 5800 students find it hard.", "Here are 3 options for students.",
                 "CS 5200 reviews on the record are mixed."):
        assert not check_answer(text, en)["counts_fail"], text
    assert check_answer("50 of the reviews say it is hard.", en)["counts_fail"]
    assert check_answer("Twelve positive reviews say it is easy.", en)["counts_fail"]


def test_review_attribution_edge_cases():
    en, zh = AnswerContext(lang="en", has_rmp_data=True), AnswerContext(lang="zh", has_rmp_data=True)

    def rmp(text, context):
        return check_answer(text, context)["rmp"]

    # 评价 as assessment is not a review.
    assert rmp("这门课的评价方式包括作业和考试。成绩评价以作业为主。", zh) == "not used"
    # The site's spaced name is not an instructor.
    assert rmp("Rate My Professors 上的评价说作业很多。", zh) == "UNQUALIFIED"
    # 他们 / 他人 / 她们 are not one person; he / she are.
    assert rmp("RateMyProfessors 上的评价说他们觉得作业多。", zh) == "UNQUALIFIED"
    assert rmp("RateMyProfessors 上的评价说她讲得清楚。", zh) == "instructor, no other-course caveat"
    assert rmp("RateMyProfessors reviews say she explains proofs well.", en) == "instructor, no other-course caveat"
    # Every passage needs its own other-course caveat.
    two = ("RateMyProfessors 上对任课老师的评价说很难，可能是关于别的课。\n\n这门课讲图算法。\n\n"
           "RateMyProfessors 上对任课老师的评价还说作业多。")
    assert rmp(two, zh) == "instructor, no other-course caveat"


def test_link_checks_ignore_course_names_but_catch_uppercase_and_other_schemes():
    context = AnswerContext(lang="en", allowed_urls=frozenset({CATALOG}))
    assert not check_answer(f"See [CS 5010 Programming Design Paradigm]({CATALOG}).", context)["links_fail"]
    assert check_answer(f"See the [Programs page]({CATALOG}).", context)["links_fail"]
    assert check_answer("Visit HTTPS://ELSEWHERE.EXAMPLE or WWW.ELSEWHERE.EXAMPLE.", context)["links_fail"]
    assert check_answer("Write to <mailto:office@elsewhere.example>.", context)["links_fail"]


def test_the_no_catalog_note_is_not_a_repeated_saved_copy_sentence():
    text = "这些内容来自目录的存档副本，不是实时核对。CS 5200 没有官方目录描述的存档副本。"
    assert check_answer(text, AnswerContext(lang="zh"))["saved_copy_mentions"] == 1


def test_a_single_capital_letter_ends_a_sentence_but_dotted_initials_and_approx_do_not():
    assert sentences("Most of it is Part A. RMP reviews say it is easy.") == [
        "Most of it is Part A.", " RMP reviews say it is easy."]
    assert sentences("It is a U.S. course. It takes approx. 12 hours.") == [
        "It is a U.S. course.", " It takes approx. 12 hours."]


def test_summary_counts():
    summary = summarize([check_answer(GOOD_ZH, ZH), check_answer(GOOD_ZH + " neu-cs-5800", ZH),
                         check_answer("同上。这些内容来自存档副本。" * 2, ZH)])
    assert summary["answers"] == 3 and summary["ids_fail"] == 1 and summary["links_fail"] == 0
    assert summary["repeated_saved_copy"] == 1
    assert summary["rmp"] == {"instructor + may be another course": 2, "not used": 1}

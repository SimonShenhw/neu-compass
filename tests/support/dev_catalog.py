"""The dev API's synthetic catalog (R3e): programs with their per-semester lists, version-checked plans, more courses
and their catalog requisites, so the web front end's search page and course pages have something to show on this
machine. The records are taken from the fixture generators of R3d (the landing), R4a (the plans) and R3a (the
requisites), without their policy archives. As in those fixtures, the course codes and names are the public
catalog's; the descriptions, ratings, instructors, policies and plans are made up, and none of it is user data. All of
it goes in through production's own schemas and repositories, on top of tests/conftest.py's three courses.

  - four programs, three of them featured on the landing (aai-ms, cs-ms, ds-ms): aai-ms and cs-ms have a course to
    start with in semester 1, ds-ms has only an elective there, so it has none;
  - cs-ms has four plans: three checked against their source (2026-2027 standard and align, 2025-2026 standard) and a
    draft (bridge), which a question can never go with; ds-ms has one with a concentration;
  - CS 6140 has everything a course page can show (R3b's fixture) and the catalog's requisites for two years, CS 7800
    only the old flat prerequisite list, and "ML" is a nickname of both CS 6140 and DS 5220, so /course/ML is a link
    that names two courses.

中文：开发 API 的合成目录（R3e）：带每学期课表的项目、核对过版本的方案、更多课程和它们在目录里的先修要求，好让前端的搜索页
和课程页在本机有东西可看。数据取自 R3d（落地页）、R4a（方案）、R3a（先修）的假数据生成脚本，不带政策存档；和那些假数据一样，课号和
课名是公开目录里的，描述、评价、老师、政策和方案都是编的，没有用户数据。都走生产自己的 schema 和 repository，加在
tests/conftest.py 那三门课之上：四个项目，落地页推荐其中三个；cs-ms 四份方案
（三份核对过来源，一份草稿，草稿不能随问题带上），ds-ms 一份带 concentration；CS 6140 课程页能显示的全都有（R3b 的
假数据），还有两年的目录先修，CS 7800 只有旧的平铺先修；「ML」同时是 CS 6140 和 DS 5220 的简称，所以 /course/ML 是指向
两门课的链接。
"""

from __future__ import annotations

from datetime import date, datetime, timezone

NOTE = " (Synthetic text for local development.)"
IMPORTED = datetime(2026, 9, 29, 3, 0, tzinfo=timezone.utc)
CAPTURED = datetime(2026, 9, 28, 14, 5, tzinfo=timezone.utc)
GRADUATE = "https://catalog.northeastern.edu/graduate/"

# (course_id, code, name, the text the retrievers index), beyond tests/conftest.py's AAI 6600, CS 5800 and DS 5220.
# 中文：（course_id，课号，课名，检索用的文字），tests/conftest.py 的三门课之外的。
COURSES = (
    ("c-aai-5025", "AAI 5025", "Introduction to AI Programming",
     "easy ai elective for ml beginner introduction to ai programming in python"),
    ("c-aai-7980", "AAI 7980", "Applied AI Capstone", "applied ai capstone project"),
    ("c-cs-5001", "CS 5001", "Intensive Foundations of Computer Science", "intensive foundations programming python"),
    ("c-cs-5008", "CS 5008", "Data Structures, Algorithms, and Their Applications within Computer Systems",
     "data structures algorithms c programming computer systems"),
    ("c-cs-5010", "CS 5010", "Programming Design Paradigm", "programming design paradigm object oriented design java"),
    ("c-cs-5100", "CS 5100", "Foundations of Artificial Intelligence",
     "foundations of artificial intelligence ai search planning machine learning introduction"),
    ("c-cs-5200", "CS 5200", "Database Management Systems", "database management systems sql relational design"),
    ("c-cs-6140", "CS 6140", "Machine Learning", "machine learning ml class supervised learning model selection"),
    ("c-cs-6220", "CS 6220", "Data Mining Techniques", "data mining techniques clustering association rules"),
    ("c-cs-7800", "CS 7800", "Advanced Algorithms", "advanced algorithms approximation randomized algorithms"),
    ("c-cs-7990", "CS 7990", "Thesis", "thesis research"),
    ("c-ds-5110", "DS 5110", "Essentials of Data Science", "essentials of data science data wrangling visualization"),
    ("c-pjm-5900", "PJM 5900", "Foundations of Project Management",
     "foundations of project management planning scheduling"),
)
# What some courses have beyond their code and name; CS 6140 has everything a course page can show (R3b's fixture).
# 中文：几门课在课号课名之外的字段；CS 6140 是课程页能显示的全都有（R3b 的假数据）。
DETAILS = {
    "c-cs-6140": dict(
        term="Fall 2026", credits=4, delivery_mode="in_person",
        professor=["Synthetic Professor A", "Synthetic Professor B"],
        workload_hours_per_week=7.5, difficulty_score=4.0,
        grading=[("Homework", 0.3), ("Midterm", 0.125), ("Participation", None), ("Final project", 0.575)],
        topics_covered=["Supervised learning", "Model selection", "Kernel methods"],
        skill_tags=["Python", "scikit-learn", "Model evaluation"],
        career_relevance=["Machine learning engineer", "Data scientist"],
        ai_policy=dict(permitted_tools=["ChatGPT for brainstorming", "GitHub Copilot"],
                       banned_tools=["Any tool in exams"], disclosure_required=True,
                       notes="Disclose every AI use in a short note." + NOTE),
        snippets=[("workload_hours_per_week", 7.5, "rmp_review_cs6140_1", "About seven or eight hours a week.", 0.875),
                  ("difficulty_score", 4.0, "reddit_cs6140_thread", "Hard but fair.", 0.125),
                  ("skill_tags", ["Python", "scikit-learn"], "syllabus_cs6140_2026",
                   "Assignments use Python and scikit-learn.", 0.9),
                  ("career_relevance", "Machine learning engineer", "rmp_review_cs6140_2",
                   "Good preparation for ML jobs.", 0.5)],
        source_review_ids=["rmp_review_cs6140_1", "rmp_review_cs6140_2", "reddit_cs6140_thread",
                           "syllabus_cs6140_2026"]),
    "c-cs-5010": dict(term="Fall 2026", credits=4, delivery_mode="in_person"),
    "c-aai-5025": dict(term="Spring 2027", credits=4, delivery_mode="online"),
}
# course_id -> (catalog description, credits): the catalog's own record. 中文：目录自己的记录（描述、学分）。
CATALOG = {
    "c-cs-6140": ("Covers supervised learning, model selection and evaluation.\n\nStudents complete a final project."
                  + NOTE, 4),
    "c-cs-5010": ("Studies the design of programs: data, abstraction, testing and object-oriented design." + NOTE, 4),
}
# A nickname two courses share. 中文：两门课共用的简称。
SHARED_NICKNAME = ("ML", ("c-cs-6140", "c-ds-5220"))
PROGRAMS = (
    ("aai-ms", "MS in Applied Artificial Intelligence (synthetic)", "AAI", None),
    ("cs-ms", "MS in Computer Science (synthetic)", "CS", "Synthetic program notes for local development."),
    ("ds-ms", "MS in Data Science (synthetic)", "DS", None),
    ("pjm-ms", "MS in Project Management (synthetic)", "PJM", None),
)
# (program, course, requirement type, recommended semester, notes). 中文：（项目，课程，要求类型，推荐学期，备注）。
EDGES = (
    ("aai-ms", "c-aai-5025", "elective_pool", 1, None), ("aai-ms", "c-aai-6600", "foundation", 1, None),
    ("aai-ms", "c-cs-5100", "core", 1, None), ("aai-ms", "c-aai-7980", "capstone", None, None),
    ("cs-ms", "c-cs-5010", "core", 1, "Synthetic edge note: usually taken first."),
    ("cs-ms", "c-cs-5800", "core", 1, None), ("cs-ms", "c-cs-6140", "core", 2, None),
    ("cs-ms", "c-cs-5200", "elective_pool", 2, None), ("cs-ms", "c-cs-7990", "capstone", None, None),
    ("ds-ms", "c-ds-5110", "elective_pool", 1, None), ("ds-ms", "c-ds-5220", "core", 2, None),
    ("ds-ms", "c-cs-6140", "elective_pool", 2, None),
    ("pjm-ms", "c-pjm-5900", "core", 1, None),
)
ML_2026 = ("(CS 5800 with a minimum grade of C- or CS 7800 with a minimum grade of C-) and "
           "(DS 5220 with a minimum grade of C- (Graduate) or CS 6220 (may be taken concurrently))")
# course_id -> (catalog year, prerequisite clause, corequisite clause, credit hours, description paragraphs).
# 中文：course_id -> （目录年份，先修条款，共修条款，学分，课程描述段落）。
REQUISITES = {
    "c-cs-6140": (
        ("2026-2027", ML_2026, "CS 6220", "4 Hours",
         ["Covers supervised learning, model selection and evaluation." + NOTE,
          "Restricted to students in the MS program; permission of the instructor is required for others." + NOTE]),
        ("2025-2026", "CS 5800 with a minimum grade of C-", None, "1-4 Hours",
         ["Surveys supervised and unsupervised learning and the issues of using learned models." + NOTE]),
    ),
    "c-cs-5008": (
        ("2026-2027", "CS 5001 with a minimum grade of C-", "CS 5800", "4 Hours",
         ["Students must be registered in the align program or obtain approval from the program office." + NOTE]),
    ),
    "c-ds-5220": (("2026-2027", "Graduate standing and permission of the instructor", None, None, None),),
    "c-cs-6220": (("2026-2027", "CS 5800 with a minimum grade of B", None, "4 Hours", None),),
}
# The old flat prerequisite list (course, prerequisite, requirement). 中文：旧的平铺先修（课程，先修课，要求）。
FLAT_PREREQUISITES = (
    ("c-cs-6140", "c-cs-5800", "required"), ("c-cs-6140", "c-cs-5100", "recommended"),
    ("c-cs-5008", "c-cs-5001", "required"),
    ("c-cs-7800", "c-cs-5800", "required"), ("c-cs-7800", "c-cs-5100", "recommended"),
    ("c-cs-7800", "c-cs-6140", "concurrent"),
)


def _plans():
    from schemas.program_plan import CourseRange, ProgramPlan, RequirementNode  # noqa: PLC0415

    def course(label, code):
        return RequirementNode(kind="course", label=label, course_code=code)

    def plan(plan_id, *, program_id="cs-ms", year="2026-2027", pathway="standard", concentration=None,
             coverage="partial", review="source_checked",
             path="computer-information-science/computer-science-mscs-boston/", requirements):
        return ProgramPlan(
            plan_id=plan_id, program_id=program_id, campus="boston", catalog_year=year, pathway=pathway,
            concentration=concentration, coverage=coverage, review_status=review,
            checked_by="synthetic-reviewer" if review == "source_checked" else None,
            checked_on=date(2026, 10, 3) if review == "source_checked" else None,
            source_url=GRADUATE + path, source_title="Synthetic program page", source_catalog_year=year,
            source_excerpt="Students complete the synthetic core and choose electives from the listed pool." + NOTE,
            captured_on=date(2026, 10, 1),
            notes="Synthetic plan notes: the pool and the minimums are invented for local development." + NOTE,
            requirements=requirements)

    return (
        plan("cs-ms-boston-2026-2027-standard", requirements=RequirementNode(
            kind="all_of", label="Synthetic core and electives", children=[
                course("Programming design core (synthetic)", "CS 5010"),
                course("Algorithms core (synthetic)", "CS 5800"),
                RequirementNode(kind="select", label="Synthetic elective pool",
                                course_codes=["CS 6140", "CS 5200", "CS 6220"], min_courses=2),
                RequirementNode(kind="select", label="Synthetic breadth", subject_codes=["DS"],
                                course_ranges=[CourseRange(start="CS 5000", end="CS 5999")],
                                excluded_course_codes=["CS 5010"], min_credits=8),
                RequirementNode(kind="unmodeled", label="Further rules not modeled yet (synthetic)"),
            ])),
        plan("cs-ms-boston-2026-2027-align", pathway="align", coverage="complete", requirements=RequirementNode(
            kind="any_of", label="Synthetic align options", children=[
                course("Algorithms option (synthetic)", "CS 5800"),
                RequirementNode(kind="optional", label="Synthetic thesis branch",
                                activate_when="Only for students who choose the thesis option (synthetic)",
                                children=[course("Thesis (synthetic)", "CS 7990")]),
                RequirementNode(kind="select", label="Synthetic area electives", course_codes=["CS 5200", "CS 6140"],
                                areas={"Systems": ["CS 5200"], "Learning": ["CS 6140"]}, min_courses=2, min_areas=2),
                RequirementNode(kind="condition", label="A program GPA of at least 3.0 (synthetic)"),
            ])),
        plan("cs-ms-boston-2026-2027-bridge", pathway="bridge", review="draft",
             requirements=course("Bridge course (synthetic, unchecked)", "CS 5010")),
        plan("cs-ms-boston-2025-2026-standard", year="2025-2026",
             requirements=course("Algorithms (synthetic)", "CS 5800")),
        plan("ds-ms-boston-2026-2027-standard-ai", program_id="ds-ms", concentration="Synthetic AI concentration",
             path="computer-information-science/data-science-ms-boston/", requirements=RequirementNode(
                 kind="all_of", label="Synthetic data science core", children=[
                     course("Supervised learning core (synthetic)", "DS 5220"),
                     RequirementNode(kind="select", label="Synthetic data science electives",
                                     course_codes=["CS 6140", "DS 5110"], min_courses=1),
                 ])),
    )


def _details(fields: dict) -> dict:
    """DETAILS' shorthand as Course's fields. 中文：把 DETAILS 的简写换成 Course 的字段。"""
    from schemas.course import AIPolicy, EvidenceSnippet, GradingComponent  # noqa: PLC0415

    out = {key: value for key, value in fields.items() if key not in ("grading", "ai_policy", "snippets")}
    if "grading" in fields:
        out["grading_components"] = [GradingComponent(name=name, weight=weight) for name, weight in fields["grading"]]
    if "ai_policy" in fields:
        out["ai_policy"] = AIPolicy(**fields["ai_policy"])
    if "snippets" in fields:
        out["evidence_snippets"] = [EvidenceSnippet(field=field, value=value, source_id=source, quote=quote + NOTE,
                                                    confidence=confidence)
                                    for field, value, source, quote, confidence in fields["snippets"]]
    return out


def seed_catalog(conn) -> None:
    """The catalog above, through production's own repositories. The caller commits.
    中文：上面这套目录，都走生产自己的 repository；由调用方提交。"""
    from db.alias_repository import AliasRepository  # noqa: PLC0415
    from db.catalog_source_repository import CatalogSourceRepository  # noqa: PLC0415
    from db.course_requisite_repository import CourseRequisiteRepository  # noqa: PLC0415
    from db.program_plan_repository import ProgramPlanRepository  # noqa: PLC0415
    from db.program_repository import ProgramRepository  # noqa: PLC0415
    from db.repository import CourseRepository  # noqa: PLC0415
    from schemas.alias import Alias, AliasReviewStatus, AliasSource, AliasType  # noqa: PLC0415
    from schemas.catalog_credit_hours import CatalogCreditHours  # noqa: PLC0415
    from schemas.course import Course  # noqa: PLC0415
    from schemas.course_description_evidence import CourseDescriptionEvidence  # noqa: PLC0415
    from schemas.course_requisite_document import CourseRequisiteDocument  # noqa: PLC0415
    from schemas.program import CoursePrerequisite, Program, ProgramRequiredCourse  # noqa: PLC0415
    from scrapers.course_requisites import parse_clause  # noqa: PLC0415
    from scrapers.neu_catalog import CatalogEntry  # noqa: PLC0415

    courses = CourseRepository(conn)
    for course_id, code, name, text in COURSES:
        courses.insert(Course(course_id=course_id, primary_code=code, primary_name=name,
                              **_details(DETAILS.get(course_id, {}))), raw_text=text)
        courses.mark_indexed(course_id)
    catalog = CatalogSourceRepository(conn)
    for course_id, (description, credits) in CATALOG.items():
        code, name = next((code, name) for known, code, name, _ in COURSES if known == course_id)
        department = code.split()[0].lower()
        catalog.store(course_id, CatalogSourceRepository.snapshot(CatalogEntry(
            course_code=code, course_name=name, description=description, credits=credits,
            catalog_url=f"https://catalog.northeastern.edu/course-descriptions/{department}/")))
    nickname, targets = SHARED_NICKNAME
    for course_id in targets:
        AliasRepository(conn).add(Alias(alias_text=nickname, alias_type=AliasType.SLANG, primary_course_id=course_id,
                                        confidence=1.0, source=AliasSource.MANUAL,
                                        review_status=AliasReviewStatus.APPROVED))
    programs = ProgramRepository(conn)
    for program_id, full_name, prefix, notes in PROGRAMS:
        programs.upsert_program(Program(program_id=program_id, full_name=full_name, prefix=prefix, notes=notes))
    for program_id, course_id, requirement, semester, notes in EDGES:
        programs.add_required_course(ProgramRequiredCourse(program_id=program_id, course_id=course_id,
                                                           requirement_type=requirement,
                                                           semester_recommended=semester, notes=notes))
    for course_id, prerequisite, requirement in FLAT_PREREQUISITES:
        programs.add_prerequisite(CoursePrerequisite(course_id=course_id, prereq_course_id=prerequisite,
                                                     requirement=requirement))
    plans = ProgramPlanRepository(conn)
    for plan in _plans():
        plans.store(plan)
    names = {course_id: (code, name) for course_id, code, name, _ in COURSES}
    names["c-ds-5220"] = ("DS 5220", "Supervised ML")  # tests/conftest.py's. 中文：tests/conftest.py 里的。
    def section(clause):
        return {"status": "not_listed"} if clause is None else parse_clause(clause)

    store = CourseRequisiteRepository(conn)
    for course_id, editions in REQUISITES.items():
        code, name = names[course_id]
        department = code.split()[0].lower()
        for year, prerequisite, corequisite, hours, paragraphs in editions:
            store.store(CourseRequisiteDocument(
                course_id=course_id, course_code=code, course_name=name, catalog_year=year, imported_at=IMPORTED,
                source={"url": f"https://catalog.northeastern.edu/course-descriptions/{department}/",
                        "catalog_year": year, "captured_at": CAPTURED, "sha256": "b" * 64, "byte_count": 1000,
                        "page_title": f"Synthetic catalog page ({department.upper()})"},
                requisites={"prerequisite": section(prerequisite), "corequisite": section(corequisite)},
                description_evidence=(None if paragraphs is None
                                      else CourseDescriptionEvidence.from_paragraphs(paragraphs)),
                credit_hours=None if hours is None else CatalogCreditHours.from_text(hours)))

"""Seed AAI 6600 (Applied Artificial Intelligence) — first ground truth course.

Day 3 dry run, updated for schema v1.1: builds a realistic Course record from
the Spring 2026 syllabus (Dr. Hema Seshadri), persists via repository,
registers manual L2 aliases, verifies v_course_lookup, dumps to
data/ground_truth/.

Doubles as the reference example for Day 6-13 team double-blind annotation.

v1.0 -> v1.1 migration upshot: 5 schema gaps the original Day 3 dry run
surfaced (no grading weights / no instructor / no textbook / no meeting /
no ai_policy) are now closed. AAI 6600 below populates all four new fields
from the syllabus and uses GradingComponent.weight=None for discussion-board
+ project + assignments (weights truly unknown — syllabus does not publish).

Usage:
    python scripts/seed_aai6600.py
    python scripts/seed_aai6600.py --db-path /tmp/test.db --output-dir /tmp/gt
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# Windows 中文终端 cp936 默认无法渲染 UTF-8 输出 (DB / JSON 数据本身是对的,
# 只是 print 显示乱码)。reconfigure 让 stdout 强制 UTF-8。
if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from datetime import date, time  # noqa: E402

from db.connection import connect  # noqa: E402
from db.repository import CourseRepository  # noqa: E402
from schemas.course import (  # noqa: E402
    AIPolicy,
    Course,
    DayOfWeek,
    DeliveryMode,
    EvidenceSnippet,
    GradingComponent,
    InstructorContact,
    MeetingSchedule,
    MeetingSlot,
    Textbook,
)
from scripts.init_db import init_database  # noqa: E402

COURSE_ID = "neu-aai-6600"
SYLLABUS_SOURCE_ID = "syllabus_aai6600_spring2026"


# Curated excerpt of the syllabus (omits Title IX / accommodations boilerplate
# that's identical across every NEU course; keeps the substantive content for
# embedding). Email redacted as PII hygiene even though publicly listed.
RAW_TEXT = """\
Title: Applied Artificial Intelligence
Code: AAI 6600
Term: Spring 2026 (Jan 7 — Apr 26)
Format: Hybrid · Snell Library 119 · Tuesday 5:50-7:10 PM
Credits: 3
Instructor: Dr. Hema Seshadri
Prerequisites: None

Description:
This course provides a comprehensive introduction to artificial intelligence,
tracing its historical evolution and foundational principles. Students will
delve into search algorithms for problem-solving, knowledge representation
and reasoning, planning, and decision-making. The curriculum also covers
probabilistic learning and the foundational aspects of machine learning.

Course Learning Outcomes:
- CLO1: Analyze Data & AI systems in historical context, identifying key
  developments and applying foundational principles.
- CLO2: Develop machine learning solutions by implementing decision trees,
  neural networks, and statistical learning methods on real datasets.
- CLO3: Synthesize AI concepts via a substantial integrative project.
- CLO4: Implement and compare search algorithms (BFS, DFS, iterative deepening,
  A*, best-first), analyzing complexity, completeness, optimality.
- CLO5: Apply first-order logic, knowledge representation, knowledge-based
  agents to enable intelligent systems to reason about the world.

Required textbook: Analytics for Business Success (Seshadri).
Optional: Russell & Norvig, AI: A Modern Approach (4th ed., 2021).

Participation: weekly primary discussion-board post by Wed 11:59 PM EST,
two secondary responses by Sun 11:59 PM EST.

AI Policy: Permitted tools = Microsoft Copilot + Claude (claude.northeastern.edu).
Strict disclosure required. Penalties for undisclosed AI use: 50% grade reduction
on 1st offense, OSCCR report on 2nd.
"""


def build_course() -> Course:
    """Build the AAI 6600 Course from the real Spring 2026 syllabus (v1.1).

    Hard fields are syllabus-direct (high confidence). Soft fields synthesized
    from Course Description + CLOs (~0.85). Fields requiring student review
    data (workload_hours, difficulty_score) stay None — those only become
    reliable after Reddit/RMP ingestion in Week 2-3.

    v1.1 additions populated from syllabus:
      - instructor_contact (Dr. Seshadri's NEU email + AAI lead backup)
      - textbooks (1 required + 1 optional Russell & Norvig)
      - meeting_schedule (Tuesday 17:50-19:10 @ Snell 119, Jan 7 - Apr 26)
      - ai_policy (Copilot + Claude permitted, strict disclosure)
      - grading_components with weight=None (syllabus does not publish weights)
    """
    return Course(
        # === Identity ===
        course_id=COURSE_ID,
        primary_code="AAI 6600",
        primary_name="Applied Artificial Intelligence",

        # === L1 hard fields (Catalog/Syllabus, high confidence) ===
        professor=["Dr. Hema Seshadri"],
        term="Spring 2026",
        credits=3,
        prereqs=[],  # syllabus: "Course prerequisites: None"
        delivery_mode=DeliveryMode.HYBRID,

        # === L1.5 structured catalog details (v1.1) ===
        instructor_contact=InstructorContact(
            name="Dr. Hema Seshadri",
            email="h.seshadri@northeastern.edu",
            office_hours="By appointment via email; allow up to 48 hours for reply",
            secondary_contact="John Wilder (AAI Academic Lead) <j.wilder@northeastern.edu>",
        ),
        textbooks=[
            Textbook(
                title="Analytics for Business Success",
                authors=["Hema Seshadri"],
                is_required=True,
                url="https://a.co/d/07war9q",
            ),
            Textbook(
                title="Artificial Intelligence: A Modern Approach (4th ed.)",
                authors=["Stuart Russell", "Peter Norvig"],
                is_required=False,
            ),
        ],
        meeting_schedule=MeetingSchedule(
            slots=[
                MeetingSlot(
                    day_of_week=DayOfWeek.TUESDAY,
                    start_time=time(17, 50),
                    end_time=time(19, 10),
                    location="Snell Library 119",
                ),
            ],
            timezone="America/New_York",
            start_date=date(2026, 1, 7),
            end_date=date(2026, 4, 26),
        ),
        ai_policy=AIPolicy(
            permitted_tools=[
                "Microsoft Copilot",
                "Claude (claude.northeastern.edu)",
            ],
            disclosure_required=True,
            notes=(
                "Permitted uses: idea generation, process enhancement, learning "
                "support. Submitting unmodified AI work is prohibited. Penalties: "
                "1st offense undisclosed use = 50% grade reduction + mandatory "
                "resubmission; 2nd offense = zero on assignment + OSCCR report; "
                "AI-generated data falsification = zero on assignment + OSCCR "
                "report on 1st offense."
            ),
        ),

        # === L2 soft fields ===
        topics_covered=[
            "AI history and foundational principles",
            "Search algorithms (BFS, DFS, iterative deepening)",
            "Heuristic search (A*, best-first)",
            "Knowledge representation and reasoning",
            "First-order logic",
            "Knowledge-based agents",
            "Planning and decision-making",
            "Probabilistic learning",
            "Bayesian methods",
            "Decision trees",
            "Neural networks",
            "Statistical learning methods",
        ],

        # v1.1: weight=None for components whose weights aren't published.
        # Records existence + structure even when the rubric is opaque.
        grading_components=[
            GradingComponent(name="Discussion Board (weekly primary + 2 secondary)", weight=None),
            GradingComponent(name="Assignments", weight=None),
            GradingComponent(name="Integrative Project", weight=None),
        ],

        skill_tags=[
            "python",
            "search-algorithms",
            "decision-trees",
            "neural-networks",
            "bayesian-inference",
            "knowledge-representation",
        ],

        career_relevance=[
            "AI Engineer (entry)",
            "ML Engineer (entry)",
            "Data Science (foundational)",
            "AI Research Assistant",
        ],

        # AAI 6600 has no genuine course-quality red flags from syllabus alone.
        # AI policy now lives in the structured ai_policy field, not as a free-form
        # warning. Real controversial_signals would come from RMP/Reddit later.
        controversial_signals=[],

        # === Provenance ===
        evidence_snippets=[
            EvidenceSnippet(
                field="skill_tags",
                value=["decision-trees", "neural-networks"],
                source_id=SYLLABUS_SOURCE_ID,
                quote="implementing decision trees, neural networks, and statistical "
                      "learning methods on real datasets",
                confidence=0.95,
            ),
            EvidenceSnippet(
                field="skill_tags",
                value=["search-algorithms"],
                source_id=SYLLABUS_SOURCE_ID,
                quote="coding both blind search (breadth-first, depth-first, iterative "
                      "deepening) and heuristic search (A*, best-first) algorithms",
                confidence=0.95,
            ),
            EvidenceSnippet(
                field="skill_tags",
                value=["knowledge-representation"],
                source_id=SYLLABUS_SOURCE_ID,
                quote="first-order logic, knowledge representation, and knowledge-based "
                      "agents, core concepts that enable intelligent systems to reason",
                confidence=0.9,
            ),
            EvidenceSnippet(
                field="career_relevance",
                value=["AI Engineer (entry)", "ML Engineer (entry)"],
                source_id=SYLLABUS_SOURCE_ID,
                quote="solve an organizational problem by integrating the principles, "
                      "tools, and methods of AI and ML while making informed decisions "
                      "about the design and deployment of systems",
                confidence=0.7,  # PLOs are aspirational; real placement data needs RMP/LinkedIn
            ),
        ],

        # v1.1: bumped from 0.9 to 0.92 — more catalog facts captured (instructor,
        # textbooks, meeting, AI policy) without adding speculation.
        extraction_confidence=0.92,

        source_review_ids=[SYLLABUS_SOURCE_ID],
    )


# Day 3 manually-known aliases. Week 2 will move these into
# data/aliases_manual.json (one entry per Ground Truth course).
MANUAL_ALIASES: list[tuple[str, str]] = [
    ("Applied AI", "slang"),
    ("6600", "slang"),
    ("Hema's AI class", "professor_attribution"),
    ("Dr. Seshadri's class", "professor_attribution"),
    ("应用 AI", "slang"),
    ("应用人工智能", "slang"),
]


def insert_aliases(conn: sqlite3.Connection) -> int:
    inserted = 0
    for alias_text, alias_type in MANUAL_ALIASES:
        cursor = conn.execute(
            """
            INSERT OR IGNORE INTO course_aliases
                (alias_text, alias_type, primary_course_id, source, review_status, confidence)
            VALUES (?, ?, ?, 'manual', 'approved', 0.95)
            """,
            (alias_text, alias_type, COURSE_ID),
        )
        if cursor.rowcount > 0:
            inserted += 1
    return inserted


def verify_lookup(conn: sqlite3.Connection) -> list[tuple[str, str]]:
    rows = conn.execute(
        "SELECT searchable_term, alias_type FROM v_course_lookup "
        "WHERE course_id = ? ORDER BY alias_type, searchable_term",
        (COURSE_ID,),
    ).fetchall()
    return [(r["searchable_term"], r["alias_type"]) for r in rows]


def write_ground_truth_json(course: Course, output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / "aai_6600.json"
    output_path.write_text(course.model_dump_json(indent=2), encoding="utf-8")
    return output_path


def main(db_path: str | None = None, output_dir: Path | None = None) -> int:
    if db_path is None:
        from config import settings  # noqa: PLC0415 (lazy: only load .env when needed)
        db_path = settings.sqlite_path
    if output_dir is None:
        output_dir = PROJECT_ROOT / "data" / "ground_truth"

    print(f"=> Initializing schema at {db_path}")
    init_database(db_path)

    print("=> Building AAI 6600 Course from Spring 2026 syllabus")
    course = build_course()
    print(f"   primary_code  : {course.primary_code}")
    print(f"   primary_name  : {course.primary_name}")
    print(f"   term          : {course.term}")
    print(f"   professor     : {', '.join(course.professor)}")
    print(f"   topics        : {len(course.topics_covered)} entries")
    print(f"   skill_tags    : {len(course.skill_tags)} entries")
    print(f"   evidence      : {len(course.evidence_snippets)} snippets")

    conn = connect(db_path)
    try:
        repo = CourseRepository(conn)

        print("=> Persisting via CourseRepository.upsert")
        repo.upsert(course, raw_text=RAW_TEXT)
        conn.commit()
        print(f"   status        : {repo.get_status(COURSE_ID)}")

        print(f"=> Inserting {len(MANUAL_ALIASES)} manual L2 aliases")
        n_new = insert_aliases(conn)
        conn.commit()
        print(f"   inserted      : {n_new} new ({len(MANUAL_ALIASES) - n_new} already existed)")

        print("=> Verifying v_course_lookup view")
        lookup = verify_lookup(conn)
        for term, atype in lookup:
            marker = "*" if atype == "primary" else " "
            print(f"   {marker} [{atype:25s}] {term}")
        expected_min = 1 + len(MANUAL_ALIASES)
        if len(lookup) < expected_min:
            print(f"FAIL: expected >= {expected_min} lookup rows, got {len(lookup)}")
            return 1

        print("=> Writing ground truth JSON")
        json_path = write_ground_truth_json(course, output_dir)
        size = json_path.stat().st_size
        print(f"   {json_path} ({size} bytes)")

    finally:
        conn.close()

    print(f"\nOK Day 3 dry run complete. course_id = {COURSE_ID}")
    print("   Re-run is idempotent. --db-path /tmp/x.db for ephemeral test.")
    return 0


def cli() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db-path", default=None, help="Override settings.sqlite_path")
    parser.add_argument("--output-dir", default=None, type=Path,
                        help="Override data/ground_truth/ for JSON dump")
    args = parser.parse_args()
    return main(db_path=args.db_path, output_dir=args.output_dir)


if __name__ == "__main__":
    sys.exit(cli())

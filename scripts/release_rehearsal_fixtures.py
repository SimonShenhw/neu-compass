"""Explicitly synthetic release inputs, created only in a fresh empty directory.

These pages are NOT captured official sources, even though schemas require
official-shaped URLs. No runtime DB, real seed, network, or Settings is used.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import sqlite3

from db.repository import CourseRepository
from schemas.course import Course
from scrapers.neu_catalog import _parse_dept_html
from scripts.release_preflight import ROOT, _existing

COURSES = (('design', 'CS 5004', 'Design'), ('algo', 'CS 5800', 'Algorithms'))
QUERY_MARKER = 'eval:synthetic-release-rehearsal'


@dataclass(frozen=True)
class RehearsalInputs:
    root: Path
    db: Path
    catalog_dir: Path
    plan_file: Path
    program_dir: Path
    requisite_manifest: Path
    requisite_dir: Path


def _write_json(path, data):
    with path.open('x', encoding='utf-8') as stream:
        json.dump(data, stream, ensure_ascii=False)


def _archive(directory, content, *, url, title):
    fingerprint = hashlib.sha256(content).hexdigest()
    metadata = dict(url=url, catalog_year='2026-2027', captured_at='2026-10-01T10:00:00Z',
        sha256=fingerprint, byte_count=len(content), page_title=title)
    with (directory / f'{fingerprint}.html').open('xb') as stream:
        stream.write(content)
    _write_json(directory / f'{fingerprint}.json', metadata)
    return metadata


def build_inputs(workspace: Path) -> RehearsalInputs:
    """Internal fixture builder; refuses nonempty or linked workspaces."""
    root = _existing(workspace, directory=True)
    if any(root.iterdir()):
        raise ValueError('synthetic_workspace_must_be_empty')
    catalog, program, requisite = (root / name for name in ('catalog', 'program', 'requisite'))
    for directory in (catalog, program, requisite):
        directory.mkdir()

    course_url = 'https://catalog.northeastern.edu/course-descriptions/cs/'
    course_html = b'''<h1>Computer Science (CS)</h1><p>2026-2027 Edition</p>
<div class="courseblock"><p class="courseblocktitle">CS 5004. Design. (4 Hours)</p>
<p class="cb_desc">Synthetic design description.</p>
<p class="courseblockextra"><strong>Prerequisite(s): </strong>CS 5001 or CS 5010</p>
<p class="courseblockextra"><strong>Corequisite(s): </strong>CS 5005</p></div>
<div class="courseblock"><p class="courseblocktitle">CS 5800. Algorithms. (4 Hours)</p>
<p class="cb_desc">Synthetic algorithm description.</p>
<p class="courseblockextra"><strong>Prerequisite(s): </strong>Instructor permission required.</p></div>'''
    metadata = _archive(requisite, course_html, url=course_url, title='Computer Science (CS)')
    manifest = root / 'requisite-manifest.json'
    _write_json(manifest, [metadata])
    with (catalog / 'synthetic.jsonl').open('x', encoding='utf-8') as stream:
        for entry in _parse_dept_html(course_html.decode(), source_url=course_url):
            stream.write(entry.model_dump_json() + '\n')

    concentrations = (
        ('computer-science', 'Computer Science', 'Khoury College of Computer Sciences'),
        ('data-design-visualization', 'Data Design and Visualization', 'College of Arts, Media and Design'),
    )
    program_url = 'https://catalog.northeastern.edu/graduate/university-interdisciplinary-programs/science-data-ms-bos/'
    parts = ['<h1>Data Science, MS (Boston)</h1><p>2026-2027 Edition</p>', '<div id="textcontainer"><ul>']
    parts += [f'<li>{name}—{college}</li>' for _, name, college in concentrations]
    parts.append('</ul></div>')
    for _, name, college in concentrations:
        parts.append(f'<h2>{name} Concentration—{college}</h2><table class="sc_courselist">'
            '<tr><td>Complete 4 semester hours</td></tr><tr><td>DS 5110</td></tr>'
            '<tr><td>Optional Co-op</td></tr><tr><td>EEAM 6964</td></tr></table>')
    program_meta = _archive(program, ''.join(parts).encode(), url=program_url, title='Data Science, MS (Boston)')
    plans = []
    for concentration, _, _ in concentrations:
        plans.append(dict(plan_id=f'synthetic-ds-{concentration}', program_id='ds-ms', campus='boston',
            catalog_year='2026-2027', pathway='standard', concentration=concentration,
            coverage='partial', review_status='source_checked', checked_by='synthetic-fixture-not-official-review',
            checked_on='2026-10-02', captured_on='2026-10-01', source_catalog_year='2026-2027',
            source_url=program_url, source_title='Data Science, MS (Boston), 2026-2027 Edition',
            source_html_sha256=program_meta['sha256'], source_excerpt='synthetic-private-source-canary',
            notes='Synthetic incomplete fixture, not an official plan or eligibility evidence.',
            requirements=dict(kind='all_of', label='Synthetic partial rules', children=[
                dict(kind='select', label='Synthetic selection', course_codes=['DS 5110'], min_credits=4),
                dict(kind='optional', label='Synthetic optional', activate_when='If independently approved',
                    children=[dict(kind='course', label='Synthetic experience', course_code='EEAM 6964')]),
                dict(kind='unmodeled', label='Unknown complete policy and personal eligibility')])))
    plan_file = root / 'plans.json'
    _write_json(plan_file, plans)

    db = root / 'synthetic.sqlite3'
    if db.exists():
        raise ValueError('synthetic_database_already_exists')
    conn = sqlite3.connect(db)
    try:
        conn.row_factory = sqlite3.Row
        base_sql = (ROOT / 'db/init.sql').read_text(encoding='utf-8-sig').split('-- BEGIN COOP_MODERATION_V1_3', 1)[0]
        conn.executescript(base_sql)
        conn.execute('PRAGMA journal_mode=DELETE')
        conn.execute('PRAGMA foreign_keys=ON')
        repo = CourseRepository(conn)
        for cid, code, name in COURSES:
            repo.insert(Course(course_id=cid, primary_code=code, primary_name=name, credits=4,
                topics_covered=['synthetic-existing-syllabus-topic'], source_review_ids=['synthetic-existing-review']),
                raw_text='synthetic-existing-mixed-retrieval-canary')
            repo.mark_indexed(cid)
        conn.execute("UPDATE courses SET search_expansion='synthetic-existing-expansion-canary'")
        conn.execute("INSERT INTO users(user_id,email,domain,contribution_count) VALUES('synthetic-user','student@example.invalid','example.invalid',2)")
        conn.execute("INSERT INTO coop_experiences(coop_id,company,role,contributor_user_id,visibility_level) "
            "VALUES('synthetic-coop','Synthetic Company','Synthetic Role','synthetic-user',1)")
        conn.execute("INSERT INTO user_unlocks(user_id,coop_id) VALUES('synthetic-user','synthetic-coop')")
        conn.execute("INSERT INTO user_courses(user_id,course_id,term) VALUES('synthetic-user','algo','synthetic-term')")
        conn.execute("INSERT INTO programs(program_id,full_name,prefix) VALUES('ds-ms','Synthetic DS fixture','DS')")
        conn.execute("INSERT INTO program_required_courses(program_id,course_id,requirement_type,notes) "
            "VALUES('ds-ms','algo','elective_pool','synthetic-legacy-not-verified')")
        conn.execute("INSERT INTO course_prerequisites(course_id,prereq_course_id,requirement,notes) "
            "VALUES('algo','design','recommended','synthetic-legacy-edge-unchanged')")
        conn.execute("INSERT INTO course_aliases(alias_text,alias_type,primary_course_id,source) VALUES('5800','slang','algo','manual')")
        conn.execute("INSERT INTO query_log(log_id,route,query,user_id) VALUES(41,'chat','synthetic-private-query-canary',?)", (QUERY_MARKER,))
        conn.execute("INSERT INTO query_log(log_id,route,query,user_id) VALUES(42,'search','synthetic-private-search-canary',?)", (QUERY_MARKER,))
        conn.commit()
    finally:
        conn.close()
    return RehearsalInputs(root, db, catalog, plan_file, program, manifest, requisite)

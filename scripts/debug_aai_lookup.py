"""One-off: why doesn't 'AAI 6640' find via alias path? Compare to CS 5800."""
from __future__ import annotations

import os
import sqlite3
import sys

sys.path.insert(0, "/mnt/h/neu-compass")
os.chdir("/mnt/h/neu-compass")

from db.alias_repository import AliasRepository  # noqa: E402
from rag.query_normalizer import normalize_query_to_course_ids  # noqa: E402

conn = sqlite3.connect("/home/shen_haowei/neu-compass-data/courses.db")
conn.row_factory = sqlite3.Row

print("=== AAI 6640 in v_course_lookup (all forms) ===")
for r in conn.execute(
    "SELECT searchable_term, alias_type, course_id FROM v_course_lookup WHERE course_id = ?",
    ("neu-aai-6640",),
):
    print(f"  {r['searchable_term']!r:30}  ({r['alias_type']:10})  -> {r['course_id']}")

print()
print("=== CS 5800 in v_course_lookup (working baseline) ===")
for r in conn.execute(
    "SELECT searchable_term, alias_type, course_id FROM v_course_lookup WHERE course_id = ?",
    ("neu-cs-5800",),
):
    print(f"  {r['searchable_term']!r:30}  ({r['alias_type']:10})  -> {r['course_id']}")

print()
print("=== alias_type distribution ===")
for r in conn.execute("SELECT alias_type, COUNT(*) c FROM v_course_lookup GROUP BY alias_type ORDER BY c DESC"):
    print(f"  {r['alias_type']:15}  {r['c']}")

print()
print("=== query_normalizer behavior ===")
repo = AliasRepository(conn)
for q in [
    "aai 6640",
    "AAI 6640",
    "aai6640",
    "AAI6640",
    "cs 5800",
    "CS 5800",
    "cs5800",
    "那aai 6640这门课的信息能给我说说吗",
]:
    ids = normalize_query_to_course_ids(q, alias_repo=repo)
    print(f"  {q!r:50} -> {ids}")

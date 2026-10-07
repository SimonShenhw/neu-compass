"""Repair course names that are a sentence of the course description instead of the catalog title.

CS 5200's stored primary_name is the first sentence of its own description ("Introduces relational
database management systems as a class of software systems."), most likely left by the pre-2026-06
enrichment that wrote the whole LLM output back (llm/review_enrichment.py now merges soft fields
only). sync_catalog_sources.py attaches a snapshot only when the stored name equals the catalog
title, so that course also never got its catalog snapshot.

Default: read-only report of every course whose stored name differs from its archived catalog
title. --commit repairs only the unambiguous kind: the stored name ends like a sentence and appears
verbatim in the course's own description (archived description or stored raw_text). The archive
entry is matched by course code; an archive that gives any code two different titles aborts the
whole run before the database is opened. Other mismatches (renamed courses, edition differences)
are listed, never changed. A repair goes through CourseRepository.rename: name column and Course JSON
change together, and status stays as it was, because neither index reads the name (FAISS embeds
raw_text, BM25 indexes raw_text + search_expansion), so nothing needs re-indexing and the course
never drops out of search. One transaction; explicit existing DB and archive directory; no network.
Afterwards run sync_catalog_sources.py to attach the snapshots that now match.

--use-catalog-title CODE (repeatable) also gives a listed other mismatch its archived catalog title,
for a rename a person decided (e.g. AAI 6600). A named code must be in the archive and match exactly
one course, or the run fails before anything is written; a named code that already matches counts as
matched, so a re-run changes nothing.

中文：修复「课程名其实是课程描述里的一句话、而不是目录标题」的记录。CS 5200 存的 primary_name 是它
自己描述的第一句，多半是 2026-06 之前把整个 LLM 输出写回的富化留下的（现在 review_enrichment
只合并软字段）。sync_catalog_sources.py 只在存的名称和目录标题完全一致时才挂快照，所以这门课一直
没有目录快照。默认只读，列出所有与存档目录标题不一致的课程；--commit 只修明确的那一类：存的名称
以句号等结尾、并且原样出现在这门课自己的描述里（存档描述或存的 raw_text）。存档按课程代码对应；
存档里只要有一个代码对应两个不同标题，整个运行就在打开数据库之前中止。其他不一致（改名、版本差异）
只列出、不改。修复走 CourseRepository.rename：名称列和
Course JSON 一起改，status 保持不变，因为两个索引都不读名称（FAISS 嵌入 raw_text，BM25 索引
raw_text + search_expansion），所以不用重建索引，这门课也不会从搜索里消失。一个事务；必须显式给出
已存在的数据库和存档目录；不联网。之后再跑 sync_catalog_sources.py，把现在能对上的快照挂上。

--use-catalog-title CODE（可重复）把列出来的某个「其他不一致」也改成存档里的目录标题，用于由人决定
的改名（例如 AAI 6600）。点名的代码必须在存档里、并且在库里正好对应一门课，否则在写入任何东西之前
就失败；点名的代码如果已经一致，就算作 matched，所以重跑不会改任何东西。
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from db.repository import CourseNotFound, CourseRepository  # noqa: E402
from scrapers.neu_catalog import CatalogEntry  # noqa: E402

SENTENCE_ENDINGS = (".", "!", "?", "。")
MIN_SENTENCE_CHARS = 25  # Short titles ending in a period ("... of the U.S.") are not sentences.


def load_titles(catalog_dir: str | Path) -> dict[str, CatalogEntry]:
    """Every archived entry by course code; two different titles for one code abort the run."""
    archive = Path(catalog_dir).resolve(strict=True)
    files = sorted(archive.glob("*.jsonl"))
    if not files:
        raise ValueError("No JSONL catalog archives found")
    entries: dict[str, CatalogEntry] = {}
    for source in files:
        with source.open(encoding="utf-8-sig") as handle:
            for line in handle:
                if not line.strip():
                    continue
                entry = CatalogEntry.model_validate_json(line)
                previous = entries.get(entry.course_code)
                if previous is not None and previous.course_name != entry.course_name:
                    raise ValueError(f"Conflicting archived titles for {entry.course_code}")
                entries.setdefault(entry.course_code, entry)
    return entries


def _flat(text: str | None) -> str:
    return " ".join((text or "").split())


def is_description_sentence(name: str, texts: list[str | None]) -> bool:
    """True when `name` reads as a sentence copied from the course's own description."""
    flat = _flat(name)
    if len(flat) < MIN_SENTENCE_CHARS or not flat.endswith(SENTENCE_ENDINGS):
        return False
    return any(flat in _flat(text) for text in texts)


def repair_names(db_path: str | Path, catalog_dir: str | Path, *, commit: bool = False,
                 use_catalog_title: list[str] | tuple[str, ...] = ()) -> dict:
    titles = load_titles(catalog_dir)  # Validate the whole archive before opening the database.
    named = set(use_catalog_title)
    unknown = sorted(named - titles.keys())
    if unknown:
        raise ValueError(f"--use-catalog-title codes not in the archive: {', '.join(unknown)}")
    path = Path(db_path).resolve(strict=True)
    conn = sqlite3.connect(f"{path.as_uri()}?mode={'rw' if commit else 'ro'}", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        report = {"archive_records": len(titles), "matched": 0, "skipped_unknown_or_ambiguous": 0,
                  "repairs": [], "named_repairs": [], "other_mismatches": [], "committed": commit,
                  "repaired": 0}
        for code, entry in sorted(titles.items()):
            rows = conn.execute("SELECT course_id, primary_name, raw_text FROM courses WHERE primary_code=?",
                                (code,)).fetchall()
            if len(rows) != 1:
                if code in named:
                    raise ValueError(f"--use-catalog-title {code}: {len(rows)} courses in the database, "
                                     "need exactly one")
                report["skipped_unknown_or_ambiguous"] += 1
                continue
            row = rows[0]
            if row["primary_name"] == entry.course_name:
                report["matched"] += 1  # Also a named code that an earlier run already renamed.
                continue
            item = {"course_id": row["course_id"], "code": code, "stored": row["primary_name"],
                    "catalog": entry.course_name}
            if is_description_sentence(row["primary_name"], [entry.description, row["raw_text"]]):
                report["repairs"].append(item)
            elif code in named:
                report["named_repairs"].append(item)  # A person chose the catalog title.
            else:
                report["other_mismatches"].append(item)
        renames = report["repairs"] + report["named_repairs"]
        if commit and renames:
            repo = CourseRepository(conn)
            for item in renames:
                repo.rename(item["course_id"], item["catalog"])  # Status kept: no index reads the name.
            conn.commit()
            report["repaired"] = len(renames)
        return report
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def cli(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--db-path", required=True)
    parser.add_argument("--catalog-dir", required=True)
    parser.add_argument("--commit", action="store_true")
    parser.add_argument("--use-catalog-title", action="append", default=[], metavar="CODE",
                        help="also give this listed mismatch (e.g. 'AAI 6600') its archived catalog title; repeatable")
    args = parser.parse_args(argv)
    try:
        report = repair_names(args.db_path, args.catalog_dir, commit=args.commit,
                              use_catalog_title=args.use_catalog_title)
    # CourseNotFound itself, not LookupError: that would also swallow a KeyError or IndexError bug.
    except (OSError, sqlite3.Error, ValueError, CourseNotFound) as exc:
        print(f"Course name repair failed ({type(exc).__name__}); no transaction committed.")
        return 1
    print(json.dumps(report, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(cli())

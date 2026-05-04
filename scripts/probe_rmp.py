"""One-shot RMP GraphQL probe: confirm endpoint, find NEU school id, fetch a
sample teacher search response. Saves the JSON to tests/fixtures/rmp/ for
fixture-backed parser tests.

Run:
    uv run python scripts/probe_rmp.py
    uv run python scripts/probe_rmp.py --teacher "smith"

Not part of the regular pytest run — this is a manual probe to verify RMP's
schema hasn't drifted.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import httpx

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

URL = "https://www.ratemyprofessors.com/graphql"
AUTH = "Basic dGVzdDp0ZXN0"
HEADERS = {
    "Authorization": AUTH,
    "Content-Type": "application/json",
    "User-Agent": "neu-compass/0.1 (academic project)",
}

SCHOOL_QUERY = """
query SearchSchool($query: SchoolSearchQuery!) {
  newSearch {
    schools(query: $query) {
      edges { node { id legacyId name city state } }
    }
  }
}
"""

TEACHER_QUERY = """
query SearchTeacher($query: TeacherSearchQuery!) {
  newSearch {
    teachers(query: $query, first: 5) {
      edges {
        node {
          id legacyId firstName lastName department
          school { name }
          avgRating avgDifficulty numRatings wouldTakeAgainPercent
          ratings(first: 5) {
            edges {
              node {
                id comment date class qualityRating
                difficultyRatingRounded ratingTags
              }
            }
          }
        }
      }
    }
  }
}
"""

OUT_DIR = PROJECT_ROOT / "tests" / "fixtures" / "rmp"


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--teacher", default="smith", help="teacher name search term")
    p.add_argument("--save", action="store_true", help="save responses as fixtures")
    args = p.parse_args()

    OUT_DIR.mkdir(parents=True, exist_ok=True)

    with httpx.Client(timeout=15.0, headers=HEADERS) as c:
        # 1) Find NEU school id
        r = c.post(URL, json={
            "query": SCHOOL_QUERY,
            "variables": {"query": {"text": "Northeastern University"}},
        })
        print("=== school search ===")
        print(f"status: {r.status_code}")
        data = r.json()
        edges = (data.get("data") or {}).get("newSearch", {}).get("schools", {}).get("edges", [])
        if not edges:
            print("ERRORS:", json.dumps(data.get("errors"), indent=2)[:500])
            return 1
        for e in edges[:5]:
            n = e["node"]
            print(f"  id={n['id']!r:<30} legacyId={n['legacyId']!r:<8} "
                  f"{n['name']} ({n.get('city')}, {n.get('state')})")

        # Pick the Boston main campus (legacyId 696 historically).
        neu_id = next(
            (e["node"]["id"] for e in edges if e["node"].get("legacyId") == 696),
            edges[0]["node"]["id"],
        )
        print(f"=> NEU school id (chosen): {neu_id!r}")

        if args.save:
            (OUT_DIR / "school_search.json").write_text(
                json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8",
            )

        # 2) Search for a teacher at that school
        r = c.post(URL, json={
            "query": TEACHER_QUERY,
            "variables": {"query": {"text": args.teacher, "schoolID": neu_id}},
        })
        print("\n=== teacher search ===")
        print(f"status: {r.status_code}")
        data = r.json()
        print(json.dumps(data, indent=2, ensure_ascii=False)[:3500])

        if args.save:
            (OUT_DIR / "teacher_search.json").write_text(
                json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8",
            )
            print(f"\n=> saved fixtures to {OUT_DIR}")

    return 0


if __name__ == "__main__":
    sys.exit(main())

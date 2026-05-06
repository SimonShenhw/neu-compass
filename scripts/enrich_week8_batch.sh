#!/usr/bin/env bash
# PLAN v2.3 §3.4 — 16 课 Gemini enrich,跳过已 done 的 cs-5200 留 15 课。
# Idempotent:每课失败 continue 不阻塞;重跑会 upsert 覆盖之前的 enrich 结果。
set -uo pipefail

cd /mnt/h/neu-compass

COURSES=(
  neu-cs-6140
  neu-ds-5230
  neu-math-7233
  neu-aly-6010
  neu-info-6105
  neu-cs-6200
  neu-aly-6140
  neu-eece-5645
  neu-cs-6240
  neu-ds-5500
  neu-aly-6080
  neu-aai-5015
  neu-ds-5110
  neu-cs-2000
  neu-info-6150
)

total=${#COURSES[@]}
i=0
ok=0
fail=0
fail_list=""

for cid in "${COURSES[@]}"; do
  i=$((i+1))
  echo "===[$i/$total]=== $cid ==="
  if uv run python scripts/enrich_course_via_rmp.py --course-id "$cid" --live --save 2>&1 | tail -8; then
    ok=$((ok+1))
  else
    fail=$((fail+1))
    fail_list="$fail_list $cid"
  fi
  echo
done

echo "============================="
echo "ENRICH DONE: ok=$ok fail=$fail"
echo "fail_list:$fail_list"
echo "============================="

echo "=== rebuilding FAISS ==="
uv run python scripts/rebuild_faiss.py --all 2>&1 | tail -5
echo "=== ALL DONE ==="

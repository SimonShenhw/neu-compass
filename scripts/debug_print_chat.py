"""One-off: print parsed /chat NDJSON response from /tmp/rl.ndjson."""
from __future__ import annotations

import json
import sys

path = sys.argv[1] if len(sys.argv) > 1 else "/tmp/rl.ndjson"
with open(path) as f:
    events = [json.loads(line) for line in f if line.strip()]
meta = next(e for e in events if e["type"] == "meta")
tokens = [e["text"] for e in events if e["type"] == "token"]
print(f'matched_via   = {meta["matched_via"]}')
print(f'retrieval_ms  = {meta["retrieval_ms"]}')
print(f'rejection_reason = {meta.get("rejection_reason")}')
print("results:")
for r in meta["results"]:
    print(f'  - {r["primary_code"]:10}  {r["primary_name"]}  score={r["score"]:.3f}')
print()
print("=== LLM answer ===")
print("".join(tokens))

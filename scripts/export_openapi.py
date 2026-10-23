"""Write the API's OpenAPI document to web/openapi.json, or check that the committed copy is current (R2b).

The web front end generates its TypeScript types from this file (`npm run gen:api` in web/). Both files are committed,
so a change to the API's shapes shows up in the pull request; CI runs `--check` here and the front end checks its
generated types against this file, so a change that is not carried through turns CI red.

The document is built in process from `create_app(run_startup=False)`: no server, no model, no database. Keys are
sorted and the file ends in one LF, so the bytes depend only on the code and the locked dependency versions.

中文：把 API 的 OpenAPI 文档写到 web/openapi.json，或者用 `--check` 查提交的那份是不是最新的（R2b）。新前端从这个
文件生成 TypeScript 类型（web/ 里的 `npm run gen:api`）。两个文件都提交，接口的改动在 PR 里看得见；CI 在这里跑
`--check`，前端再拿生成的类型和这个文件比，没跟着改就红。文档在进程里用 `create_app(run_startup=False)` 生成，不起
服务、不加载模型、不连数据库；键排序、以一个 LF 结尾，所以内容只取决于代码和锁定的依赖版本。
"""

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from api.main import create_app  # noqa: E402

DEFAULT_OUT = ROOT / "web" / "openapi.json"


def openapi_text() -> str:
    """The OpenAPI document as the exact text that is committed. 中文：要提交的那份文字，一字不差。"""
    document = create_app(run_startup=False).openapi()
    return json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n", 1)[0])
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT, help="where to write (default: web/openapi.json)")
    parser.add_argument("--check", action="store_true",
                        help="write nothing; exit 1 if the file differs from what would be written")
    args = parser.parse_args(argv)
    text = openapi_text()
    if args.check:
        current = args.out.read_bytes().decode("utf-8") if args.out.exists() else None
        if current != text:
            print(f"{args.out} is out of date: run `python scripts/export_openapi.py` and commit the result, "
                  "then `npm run gen:api` in web/.", file=sys.stderr)
            return 1
        print(f"{args.out} is up to date.")
        return 0
    args.out.write_bytes(text.encode("utf-8"))
    print(f"Wrote {args.out}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""CLI：验证 A 榜全部题目的 doc_ids 均可映射到本地文件。

用法：
    python -m agent.check_doc_map

成功（missing 与 errors 均为空）时生成 processed_data/doc_id_map.json，退出码 0；
否则打印缺失明细，退出码 1（仍会写出 JSON 便于排查）。
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone

from agent.doc_id_map import build_group_doc_map
from agent.paths import PROCESSED_DATA_DIR, REPO_ROOT

DOC_ID_MAP_PATH = PROCESSED_DATA_DIR / "doc_id_map.json"


def main() -> int:
    result = build_group_doc_map(REPO_ROOT)

    payload = {
        "generated_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        "group": "group_a",
        **result,
    }

    PROCESSED_DATA_DIR.mkdir(parents=True, exist_ok=True)
    with DOC_ID_MAP_PATH.open("w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    by_domain: dict[str, int] = {}
    for m in result["mappings"]:
        by_domain[m["domain"]] = by_domain.get(m["domain"], 0) + 1

    print(f"[scan] questions={result['question_count']} unique_docs={result['unique_doc_count']}")
    for domain, n in sorted(by_domain.items()):
        print(f"[scan]   {domain}: {n} docs")
    print(f"[out] {DOC_ID_MAP_PATH}")

    ok = not result["missing"] and not result["errors"]
    if ok:
        print("[ok] 全部 doc_ids 映射成功，missing=0 errors=0")
        return 0

    for item in result["missing"]:
        print(f"[missing] {item}", file=sys.stderr)
    for item in result["errors"]:
        print(f"[error] {item}", file=sys.stderr)
    print(
        f"[fail] missing={len(result['missing'])} errors={len(result['errors'])}",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

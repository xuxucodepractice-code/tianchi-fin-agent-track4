"""隔离旧平铺 reasoning cache 中的 mock、0-token 和未知 qid 文件。"""

from __future__ import annotations

import argparse
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from agent.load_questions import load_all_questions
from agent.paths import QUARANTINED_REASONING_SAMPLES_DIR, REASONING_SAMPLES_ROOT


def _reason(data: Any, official_qids: set[str]) -> str | None:
    if not isinstance(data, dict):
        return "not_json_object"
    qid = str(data.get("qid", ""))
    if qid not in official_qids:
        return "unknown_qid"
    if data.get("mode") != "qwen":
        return f"non_qwen_mode:{data.get('mode')}"
    if int(data.get("prompt_tokens") or 0) <= 0 or int(data.get("total_tokens") or 0) <= 0:
        return "non_positive_tokens"
    return None


def quarantine_invalid_flat_cache(
    cache_root: Path = REASONING_SAMPLES_ROOT,
    quarantine_root: Path = QUARANTINED_REASONING_SAMPLES_DIR,
    *,
    apply: bool = False,
) -> list[dict[str, str]]:
    official_qids = {str(q["qid"]) for q in load_all_questions()}
    findings: list[dict[str, str]] = []
    for path in sorted(cache_root.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            data = None
        reason = _reason(data, official_qids)
        if reason is None:
            continue
        target = quarantine_root / "legacy_flat_invalid" / path.name
        findings.append(
            {
                "source": str(path),
                "target": str(target),
                "reason": reason,
                "mode": str(data.get("mode", "")) if isinstance(data, dict) else "",
                "pipeline_version": (
                    str(data.get("pipeline_version") or "v0") if isinstance(data, dict) else ""
                ),
                "prompt_tokens": str(data.get("prompt_tokens", "")) if isinstance(data, dict) else "",
                "total_tokens": str(data.get("total_tokens", "")) if isinstance(data, dict) else "",
            }
        )
        if apply:
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists():
                raise FileExistsError(f"quarantine target already exists: {target}")
            shutil.move(str(path), str(target))
    if apply and findings:
        manifest = quarantine_root / "legacy_flat_invalid" / "quarantine_manifest.json"
        payload = {
            "quarantined_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
            "count": len(findings),
            "files": findings,
        }
        manifest.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return findings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m agent.quarantine_reasoning_cache")
    parser.add_argument("--apply", action="store_true", help="实际移动；默认只报告")
    args = parser.parse_args(argv)
    try:
        findings = quarantine_invalid_flat_cache(apply=args.apply)
    except (OSError, ValueError) as exc:
        print(f"[error] {exc}")
        return 1
    action = "quarantined" if args.apply else "would_quarantine"
    print(f"[{action}] count={len(findings)}")
    for item in findings:
        print(f"[{action}] {item['source']} -> {item['target']} ({item['reason']})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

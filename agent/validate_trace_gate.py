"""Validate an Agent trace and/or a frozen candidate provenance gate."""

from __future__ import annotations

import argparse
from pathlib import Path

from agent.trace_gate import validate_candidate_freeze, validate_trace_directory


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m agent.validate_trace_gate")
    parser.add_argument("--trace-dir", type=Path)
    parser.add_argument("--artifact-dir", type=Path)
    parser.add_argument("--candidate-dir", type=Path)
    parser.add_argument("--label-reveal", type=Path)
    parser.add_argument(
        "--require-label-reveal",
        action="store_true",
        help="上传前要求 temporal_gate=PASS；PENDING 将返回失败",
    )
    parser.add_argument(
        "--diagnostic",
        action="store_true",
        help="允许 Gold Oracle 等不可晋升为候选的诊断 trace",
    )
    args = parser.parse_args(argv)
    if not args.trace_dir and not args.candidate_dir:
        parser.error("at least one of --trace-dir or --candidate-dir is required")

    ok = True
    if args.trace_dir:
        report = validate_trace_directory(
            args.trace_dir,
            artifact_dir=args.artifact_dir,
            require_candidate_eligible=not args.diagnostic,
            require_current_code_match=False,
        )
        ok = ok and bool(report["ok"])
        status = "VALID" if report["ok"] else "INVALID"
        print(
            f"[{status}] trace calls={report.get('call_count', 0)} "
            f"derivations={report.get('derivation_count', 0)}"
        )
        for error in report.get("errors", []):
            print(f"[error] {error}")

    if args.candidate_dir:
        report = validate_candidate_freeze(
            args.candidate_dir,
            label_reveal_path=args.label_reveal,
        )
        if args.require_label_reveal and report.get("temporal_gate") != "PASS":
            report = {
                **report,
                "ok": False,
                "errors": [
                    *report.get("errors", []),
                    "label reveal is required before upload",
                ],
            }
        ok = ok and bool(report["ok"])
        status = "VALID" if report["ok"] else "INVALID"
        print(
            f"[{status}] candidate temporal_gate={report.get('temporal_gate')} "
            f"frozen_at={report.get('candidate_frozen_at')}"
        )
        for error in report.get("errors", []):
            print(f"[error] {error}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())

"""Register the first time blind labels became visible for a frozen candidate."""

from __future__ import annotations

import argparse
from pathlib import Path

from agent.trace_gate import register_label_reveal, validate_candidate_freeze


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m agent.register_label_reveal")
    parser.add_argument("--candidate-dir", type=Path, required=True)
    parser.add_argument("--labels", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        output = register_label_reveal(
            args.candidate_dir,
            labels_path=args.labels,
        )
        report = validate_candidate_freeze(
            args.candidate_dir,
            label_reveal_path=output,
        )
    except (OSError, ValueError) as exc:
        print(f"[error] {exc}")
        return 1
    if not report["ok"]:
        for error in report["errors"]:
            print(f"[error] {error}")
        return 1
    print(f"[ok] label reveal -> {output}")
    print("[PASS] candidate_frozen_at < label_revealed_at")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path

from agent.merge_submission import merge_submission_bundles
from agent.paths import REPO_ROOT, bundle_paths
from agent.validate_submission import validate_submission_files


V0_DIR = (
    REPO_ROOT
    / "workspace"
    / "03_baseline_improvement"
    / "submissions"
    / "a_leaderboard_v0"
    / "2026-07-05_score_63_2607"
)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_empty_rerun_copies_parent_bundle_byte_for_byte(tmp_path: Path):
    output = tmp_path / "merged"
    paths = merge_submission_bundles(
        V0_DIR,
        None,
        output,
        set(),
        parent_version="v0",
        experiment_id="E000-C",
        experiment_pipeline_version="v0",
    )

    for source, target in zip(bundle_paths(V0_DIR), paths):
        assert _sha(source) == _sha(target)


def _make_single_qid_rerun(tmp_path: Path, qid: str) -> Path:
    rerun = tmp_path / "rerun"
    rerun.mkdir()
    with (V0_DIR / "answer.csv").open("r", encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    row = next(row for row in rows if row["qid"] == qid)
    with (rerun / "answer.csv").open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(row))
        writer.writeheader()
        writer.writerow(
            {
                "qid": "summary",
                "answer": "",
                "prompt_tokens": row["prompt_tokens"],
                "completion_tokens": row["completion_tokens"],
                "total_tokens": row["total_tokens"],
            }
        )
        writer.writerow(row)
    evidence = json.loads((V0_DIR / "evidence.json").read_text(encoding="utf-8"))
    record = next(record for record in evidence if record["qid"] == qid)
    (rerun / "evidence.json").write_text(
        json.dumps([record], ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (rerun / "run_manifest.json").write_text(
        json.dumps(
            {
                "run_id": "test-rerun",
                "run_started_at": "2026-07-14T00:00:00+08:00",
                "mode": "qwen",
                "model": record.get("model", "qwen-plus"),
                "pipeline_version": "v-test",
                "qids": [qid],
                "success_count": 1,
                "failure_count": 0,
                "total_prompt_tokens": int(row["prompt_tokens"]),
                "total_completion_tokens": int(row["completion_tokens"]),
                "total_tokens": int(row["total_tokens"]),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return rerun


def test_nonempty_merge_has_valid_lineage(tmp_path: Path):
    qid = "ins_a_007"
    rerun = _make_single_qid_rerun(tmp_path, qid)
    output = tmp_path / "candidate"
    merge_submission_bundles(
        V0_DIR,
        rerun,
        output,
        {qid},
        parent_version="v0",
        experiment_id="E-test",
        experiment_pipeline_version="v-test",
    )

    report = validate_submission_files(*bundle_paths(output))

    assert report["ok"] is True, report["errors"]
    manifest = json.loads((output / "run_manifest.json").read_text(encoding="utf-8"))
    assert manifest["rerun_qids"] == [qid]
    assert manifest["per_record_lineage"][qid]["source_kind"] == "rerun"
    assert manifest["per_record_lineage"]["fc_a_001"]["source_kind"] == "parent"

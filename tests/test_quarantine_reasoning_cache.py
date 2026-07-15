from __future__ import annotations

import json
from pathlib import Path

from agent.quarantine_reasoning_cache import quarantine_invalid_flat_cache


def test_quarantine_moves_only_invalid_flat_cache(tmp_path: Path):
    cache = tmp_path / "cache"
    quarantine = tmp_path / "quarantine"
    cache.mkdir()
    valid = {
        "qid": "ins_a_001",
        "mode": "qwen",
        "pipeline_version": "v0",
        "prompt_tokens": 10,
        "total_tokens": 12,
    }
    invalid = {**valid, "qid": "ins_a_002", "mode": "dry_run_mock", "prompt_tokens": 0, "total_tokens": 0}
    (cache / "ins_a_001.json").write_text(json.dumps(valid), encoding="utf-8")
    (cache / "ins_a_002.json").write_text(json.dumps(invalid), encoding="utf-8")
    (cache / "q2.json").write_text(json.dumps({"qid": "q2"}), encoding="utf-8")

    findings = quarantine_invalid_flat_cache(cache, quarantine, apply=True)

    assert {Path(item["source"]).name for item in findings} == {"ins_a_002.json", "q2.json"}
    assert (cache / "ins_a_001.json").exists()
    assert not (cache / "ins_a_002.json").exists()
    assert (quarantine / "legacy_flat_invalid" / "ins_a_002.json").exists()
    assert (quarantine / "legacy_flat_invalid" / "quarantine_manifest.json").exists()

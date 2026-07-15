# v1-S1 Reconstruction Note

This directory is an audit reconstruction, not a guaranteed byte-for-byte copy of the originally submitted v1-S1 artifacts.

Known issue:
- Before v1-S1 was frozen, the test suite command `python -m pytest tests/ -q` overwrote `submission/` with a two-question dry-run sample.
- The same dry-run path also overwrote `processed_data/reasoning_samples/ins_a_001.json` and `processed_data/reasoning_samples/ins_a_002.json` with zero-token dry-run samples.

Reliable facts from the actual online submission:
- Online score: 61.8540
- Original total tokens observed before overwrite: 1280096
- Pipeline version: v1s1
- Reused pipeline versions observed before overwrite: `{"v0": 76}`
- Answer flips versus v0 were all insurance multi questions, documented in `v1_s1_diagnosis_and_v2_plan.md`.

Reconstructed files in this folder are useful for audit context, but they should not be submitted or treated as exact original v1-S1 artifacts. The authoritative baseline remains v0:

`workspace/03_baseline_improvement/submissions/a_leaderboard_v0/2026-07-05_score_63_2607/`

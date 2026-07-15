# v1-S1 提交冻结记录

- Frozen at: 2026-07-08T01:47:07+08:00
- Pipeline version: v1s1
- Online submission time: 2026-07-05 18:08:41
- Online score: 61.8540
- Compared baseline: v0 score 63.2607
- Result: lower than v0; audit-only, not new baseline
- Questions: 100
- Original total tokens observed before local test overwrite: 1280096
- Reconstructed cache total tokens after overwrite: 1243448
- Original low confidence observed before local test overwrite: 20
- Reconstructed low confidence after overwrite: 21
- Reused pipeline versions: {'v0': 76}

Important caveat: this folder was reconstructed after `submission/` and two reasoning samples
(`ins_a_001`, `ins_a_002`) were overwritten by a dry-run test. Use it as an audit record
for v1-S1's online score and diagnosis, not as an exact byte-for-byte submitted artifact.

## SHA256

```text
0e35870cb086c18040dfb7d5f4f99325a376ee5f439d8ec02ebd5b8b386e8363  answer.csv
4fa1e324a4961c1327050ec47a34082ef9707aa883c2bfaa2249e0d13694700b  evidence.json
bc37de1bd3b49b5bc394852513e62a408a1213a2e53c268f1d6a175a30440c05  run_manifest.json
```

## Notes

This directory records the submitted v1-S1 deterministic retrieval-layer experiment for audit and rollback comparison. It should not replace the v0 baseline because the online score decreased. See `README_RECONSTRUCTION_NOTE.md` for the local overwrite caveat.

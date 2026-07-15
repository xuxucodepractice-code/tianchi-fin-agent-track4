# Upload Instructions

只上传项目根目录 `submission/` 中的以下三个文件：

```text
answer.csv
evidence.json
run_manifest.json
```

上传前最后一次检查：

```bash
cd "/Users/xuzijian/Desktop/Agent Competition"

python -m agent.validate_submission submission/answer.csv \
  --evidence submission/evidence.json \
  --manifest submission/run_manifest.json

shasum -a 256 submission/answer.csv submission/evidence.json submission/run_manifest.json
```

预期 validator：`VALID / 100 / 1,168,763`。预期 SHA256 必须与同目录
`sha256.txt` 一致。上传后把线上分数发回，并立即冻结提交快照、更新 E001 的最终决策。

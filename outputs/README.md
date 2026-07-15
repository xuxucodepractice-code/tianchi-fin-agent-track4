# Runtime Outputs

本目录保存非正式运行产物，并与根目录 `submission/` 隔离。

```text
outputs/
├── tests/          # pytest 产物
├── dry_runs/       # dry-run 和 mock
├── experiments/    # 单变量实验运行产物
└── candidates/     # 已通过离线评估的候选提交产物
```

除必要的小型说明文件外，大型运行产物默认不应进入 Git。正式上传出口仍为根目录 `submission/`，任何测试不得写入该目录。

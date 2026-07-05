"""集中管理仓库内路径，避免各模块散落硬编码。

约定：
- repo root 以本文件所在目录的父目录为准（agent/ 直接位于仓库根下）。
- submission/ 与 processed_data/ 为本地运行产物目录，默认不进 Git。
- public_dataset_upload/raw 只读，任何代码不得写入。
"""

from __future__ import annotations

from pathlib import Path

# agent/paths.py -> agent/ -> repo root
REPO_ROOT: Path = Path(__file__).resolve().parent.parent

# 官方数据（只读）
PUBLIC_DATASET_DIR: Path = REPO_ROOT / "public_dataset_upload"
QUESTIONS_GROUP_A_DIR: Path = PUBLIC_DATASET_DIR / "questions" / "group_a"
RAW_DATA_DIR: Path = PUBLIC_DATASET_DIR / "raw"  # 只读，禁止修改

# 本地运行产物（默认不进 Git）
SUBMISSION_DIR: Path = REPO_ROOT / "submission"
PROCESSED_DATA_DIR: Path = REPO_ROOT / "processed_data"  # Task 2+ 使用，预留

ANSWER_CSV_PATH: Path = SUBMISSION_DIR / "answer.csv"
EVIDENCE_JSON_PATH: Path = SUBMISSION_DIR / "evidence.json"
RUN_MANIFEST_PATH: Path = SUBMISSION_DIR / "run_manifest.json"

# 提交线过程记录
SUBMISSIONS_NOTES_DIR: Path = (
    REPO_ROOT / "workspace" / "03_baseline_improvement" / "submissions"
)
A_LEADERBOARD_V0_NOTES_DIR: Path = SUBMISSIONS_NOTES_DIR / "a_leaderboard_v0"


def ensure_output_dirs() -> None:
    """创建运行所需的输出目录（幂等）。"""
    SUBMISSION_DIR.mkdir(parents=True, exist_ok=True)
    A_LEADERBOARD_V0_NOTES_DIR.mkdir(parents=True, exist_ok=True)

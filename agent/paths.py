"""集中管理仓库内路径，避免各模块散落硬编码。

约定：
- repo root 以本文件所在目录的父目录为准（agent/ 直接位于仓库根下）。
- submission/ 仅作为显式正式上传出口。
- tests、dry-run、实验和候选产物必须写入 outputs/ 对应子目录。
- processed_data/reasoning_samples/by_pipeline/<version>/ 保存版本化正式推理缓存。
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
OUTPUTS_DIR: Path = REPO_ROOT / "outputs"
TEST_OUTPUTS_DIR: Path = OUTPUTS_DIR / "tests"
DRY_RUN_OUTPUTS_DIR: Path = OUTPUTS_DIR / "dry_runs"
EXPERIMENT_OUTPUTS_DIR: Path = OUTPUTS_DIR / "experiments"
CANDIDATE_OUTPUTS_DIR: Path = OUTPUTS_DIR / "candidates"
REASONING_SAMPLES_ROOT: Path = PROCESSED_DATA_DIR / "reasoning_samples"
VERSIONED_REASONING_SAMPLES_DIR: Path = REASONING_SAMPLES_ROOT / "by_pipeline"
QUARANTINED_REASONING_SAMPLES_DIR: Path = REASONING_SAMPLES_ROOT / "quarantine"

ANSWER_CSV_PATH: Path = SUBMISSION_DIR / "answer.csv"
EVIDENCE_JSON_PATH: Path = SUBMISSION_DIR / "evidence.json"
RUN_MANIFEST_PATH: Path = SUBMISSION_DIR / "run_manifest.json"

# 提交线过程记录
SUBMISSIONS_NOTES_DIR: Path = (
    REPO_ROOT / "workspace" / "03_baseline_improvement" / "submissions"
)
A_LEADERBOARD_V0_NOTES_DIR: Path = SUBMISSIONS_NOTES_DIR / "a_leaderboard_v0"


def ensure_output_dirs(output_dir: Path | None = None) -> None:
    """创建运行所需目录（幂等）；不隐式把普通运行指向正式提交出口。"""
    for path in (
        OUTPUTS_DIR,
        TEST_OUTPUTS_DIR,
        DRY_RUN_OUTPUTS_DIR,
        EXPERIMENT_OUTPUTS_DIR,
        CANDIDATE_OUTPUTS_DIR,
        VERSIONED_REASONING_SAMPLES_DIR,
        QUARANTINED_REASONING_SAMPLES_DIR,
    ):
        path.mkdir(parents=True, exist_ok=True)
    if output_dir is not None:
        output_dir.mkdir(parents=True, exist_ok=True)
    A_LEADERBOARD_V0_NOTES_DIR.mkdir(parents=True, exist_ok=True)


def bundle_paths(output_dir: Path) -> tuple[Path, Path, Path]:
    """返回某个隔离目录内的三份提交产物路径。"""
    return (
        output_dir / "answer.csv",
        output_dir / "evidence.json",
        output_dir / "run_manifest.json",
    )

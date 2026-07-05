"""doc_id -> 本地 raw 文件的确定性映射。

规则（按领域，不逐题硬编码）：
- insurance:            raw/insurance/{doc_id}.pdf
- financial_contracts:  raw/financial_contracts/{doc_id}.pdf
- research:             raw/research/{doc_id}.pdf
- financial_reports:    raw/financial_reports/{doc_id}.PDF|.pdf（扩展名大小写不统一）
- regulatory:
    csrc_NNNN_attN  -> raw/regulatory/attachments/{doc_id}.pdf
    csrc_NNNN       -> raw/regulatory/html/{doc_id}.html
    strict_v3_NNN_* -> raw/regulatory/txt/strict_v3_NNN_*.txt
                       （本地文件名 mojibake，只按 strict_v3_NNN 数字前缀 glob；
                         命中 0 个或多个都报错）

B 榜预留：B 榜题目无 doc_ids，本模块只负责 doc_id -> path 解析；
候选文档检索由后续模块负责。
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from agent.paths import REPO_ROOT

Question = dict[str, Any]

_ATT_RE = re.compile(r"^csrc_\d+_att\d+$")
_CSRC_RE = re.compile(r"^csrc_\d+$")
_STRICT_RE = re.compile(r"^(strict_v3_\d+)_")


class DocMapError(Exception):
    """doc_id 无法映射到本地文件时抛出，信息中包含 domain、doc_id 与尝试路径/模式。"""


def _raw_dir(repo_root: Path) -> Path:
    return repo_root / "public_dataset_upload" / "raw"


def resolve_doc_path(repo_root: Path, domain: str, doc_id: str) -> Path:
    """把 (domain, doc_id) 解析为存在的本地文件路径；失败抛 DocMapError。"""
    raw = _raw_dir(repo_root)

    if domain in ("insurance", "financial_contracts", "research"):
        path = raw / domain / f"{doc_id}.pdf"
        if path.is_file():
            return path
        raise DocMapError(f"domain={domain} doc_id={doc_id} 未找到文件，尝试路径: {path}")

    if domain == "financial_reports":
        # 扩展名大小写不统一（.PDF/.pdf）。不能靠 is_file() 逐个探测：
        # 在大小写不敏感的文件系统上会命中但返回错误大小写的路径。
        # 改为列目录、按真实文件名匹配（stem 精确、后缀不区分大小写）。
        reports_dir = raw / domain
        matches = [
            p
            for p in reports_dir.iterdir()
            if p.is_file() and p.stem == doc_id and p.suffix.lower() == ".pdf"
        ]
        if len(matches) == 1:
            return matches[0]
        if not matches:
            raise DocMapError(
                f"domain={domain} doc_id={doc_id} 未找到文件，"
                f"匹配模式: {reports_dir / doc_id}.PDF|.pdf"
            )
        raise DocMapError(
            f"domain={domain} doc_id={doc_id} 匹配到 {len(matches)} 个文件，"
            f"拒绝随机选择: {[p.name for p in matches]}"
        )

    if domain == "regulatory":
        return _resolve_regulatory(raw, doc_id)

    raise DocMapError(f"未知 domain={domain}（doc_id={doc_id}）")


def _resolve_regulatory(raw: Path, doc_id: str) -> Path:
    reg = raw / "regulatory"

    if _ATT_RE.match(doc_id):
        path = reg / "attachments" / f"{doc_id}.pdf"
        if path.is_file():
            return path
        raise DocMapError(f"domain=regulatory doc_id={doc_id} 未找到附件 PDF，尝试路径: {path}")

    if _CSRC_RE.match(doc_id):
        path = reg / "html" / f"{doc_id}.html"
        if path.is_file():
            return path
        raise DocMapError(f"domain=regulatory doc_id={doc_id} 未找到 HTML，尝试路径: {path}")

    m = _STRICT_RE.match(doc_id)
    if m:
        prefix = m.group(1)  # e.g. strict_v3_017
        pattern = f"{prefix}_*.txt"
        matches = sorted((reg / "txt").glob(pattern))
        if len(matches) == 1:
            return matches[0]
        if not matches:
            raise DocMapError(
                f"domain=regulatory doc_id={doc_id} 未找到 TXT，匹配模式: {reg / 'txt' / pattern}"
            )
        raise DocMapError(
            f"domain=regulatory doc_id={doc_id} 前缀 {prefix} 匹配到 {len(matches)} 个文件，"
            f"拒绝随机选择: {[p.name for p in matches]}"
        )

    raise DocMapError(f"domain=regulatory doc_id={doc_id} 不符合任何已知命名规则（csrc_*/csrc_*_att*/strict_v3_NNN_*）")


def source_type_of(path: Path) -> str:
    """根据文件后缀返回 source_type: pdf/html/txt。"""
    suffix = path.suffix.lower()
    return {".pdf": "pdf", ".html": "html", ".txt": "txt"}[suffix]


def resolve_question_doc_paths(
    repo_root: Path, question: Question
) -> list[dict[str, Any]]:
    """解析一道题的全部 doc_ids，返回映射条目列表；任一失败抛 DocMapError。"""
    domain = question.get("domain", "")
    entries = []
    for doc_id in question.get("doc_ids", []):
        path = resolve_doc_path(repo_root, domain, doc_id)
        entries.append(
            {
                "domain": domain,
                "doc_id": doc_id,
                "source_type": source_type_of(path),
                "path": str(path.relative_to(repo_root)),
            }
        )
    return entries


def build_group_doc_map(
    repo_root: Path = REPO_ROOT, questions: list[Question] | None = None
) -> dict[str, Any]:
    """扫描全部题目，构建去重后的映射表。

    返回 dict：
        mappings: [{domain, doc_id, source_type, path}, ...]（按 (domain, doc_id) 去重）
        missing:  [{domain, doc_id, qid, error}, ...]
        errors:   [其他异常描述, ...]
    """
    if questions is None:
        from agent.load_questions import load_all_questions

        questions = load_all_questions()

    mappings: dict[tuple[str, str], dict[str, Any]] = {}
    missing: list[dict[str, Any]] = []
    errors: list[str] = []

    for q in questions:
        domain = q.get("domain", "")
        for doc_id in q.get("doc_ids", []):
            key = (domain, doc_id)
            if key in mappings:
                continue
            try:
                path = resolve_doc_path(repo_root, domain, doc_id)
                mappings[key] = {
                    "domain": domain,
                    "doc_id": doc_id,
                    "source_type": source_type_of(path),
                    "path": str(path.relative_to(repo_root)),
                }
            except DocMapError as exc:
                missing.append(
                    {"domain": domain, "doc_id": doc_id, "qid": q.get("qid", ""), "error": str(exc)}
                )
            except Exception as exc:  # 意外异常单独归类
                errors.append(f"qid={q.get('qid', '')} domain={domain} doc_id={doc_id}: {exc!r}")

    return {
        "question_count": len(questions),
        "unique_doc_count": len(mappings),
        "mappings": sorted(mappings.values(), key=lambda m: (m["domain"], m["doc_id"])),
        "missing": missing,
        "errors": errors,
    }

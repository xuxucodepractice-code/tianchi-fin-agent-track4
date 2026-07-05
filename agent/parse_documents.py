"""解析 A 榜涉及文档为统一 chunks（Task 3）。

用法：
    python -m agent.parse_documents --group group_a

输入：processed_data/doc_id_map.json（Task 2 产物）
输出：processed_data/chunks.jsonl、processed_data/parse_report.json

三条管线：
    pdf  -> pypdf 逐页抽取，保留页码，长页滑窗切分（不做 OCR）
    html -> BeautifulSoup 去 script/style/noscript/nav 噪声，h1/h2/h3/title 作 section
    txt  -> utf-8-sig / utf-8 / gb18030 依次尝试，按章/条切分，超长再滑窗

不调用任何模型，不做检索，不使用 embedding。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from agent.chunk_schema import make_chunk
from agent.paths import PROCESSED_DATA_DIR, REPO_ROOT

DOC_ID_MAP_PATH = PROCESSED_DATA_DIR / "doc_id_map.json"
CHUNKS_PATH = PROCESSED_DATA_DIR / "chunks.jsonl"
PARSE_REPORT_PATH = PROCESSED_DATA_DIR / "parse_report.json"
PARSE_CACHE_DIR = PROCESSED_DATA_DIR / "parse_cache"  # 逐文档缓存，支持断点续跑

MAX_CHARS = 1800
OVERLAP = 200
MIN_CHARS = 20  # 少于该长度且不是标题的片段不写入

# 中文法规/条款标题模式（用于 TXT 切分与"短标题豁免"判断）
_HEADING_RE = re.compile(
    r"^(第[一二三四五六七八九十百千0-9０-９]+[章节条编]|附则|附件|目录|总则)"
)


def _is_heading(text: str) -> bool:
    return bool(_HEADING_RE.match(text.strip()))


def _keep(text: str) -> bool:
    t = text.strip()
    return bool(t) and (len(t) >= MIN_CHARS or _is_heading(t))


def _sliding_window(text: str, max_chars: int = MAX_CHARS, overlap: int = OVERLAP) -> list[str]:
    """超长文本滑窗切分，步长 max_chars - overlap，保证终止。"""
    text = text.strip()
    if len(text) <= max_chars:
        return [text] if text else []
    step = max_chars - overlap
    return [text[i : i + max_chars].strip() for i in range(0, len(text), step) if text[i : i + max_chars].strip()]


# ---------------------------------------------------------------- PDF


def parse_pdf(
    abs_path: Path, mapping: dict[str, Any], failures: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    from pypdf import PdfReader

    chunks: list[dict[str, Any]] = []
    reader = PdfReader(str(abs_path))
    for page_no, page in enumerate(reader.pages, start=1):
        try:
            text = page.extract_text() or ""
        except Exception as exc:  # 单页失败不拖垮整个文档
            failures.append(
                {
                    "domain": mapping["domain"],
                    "doc_id": mapping["doc_id"],
                    "path": mapping["path"],
                    "stage": f"pdf_page_{page_no}",
                    "error": repr(exc),
                }
            )
            continue
        for idx, piece in enumerate(_sliding_window(text)):
            if not _keep(piece):
                continue
            chunks.append(
                make_chunk(
                    domain=mapping["domain"],
                    doc_id=mapping["doc_id"],
                    source_type="pdf",
                    source_path=mapping["path"],
                    page=page_no,
                    section="",
                    text=piece,
                    chunk_index=idx,
                )
            )
    return chunks


# ---------------------------------------------------------------- HTML

_HTML_NOISE_TAGS = ["script", "style", "noscript", "nav", "header", "footer", "iframe"]
_HTML_TEXT_TAGS = ["h1", "h2", "h3", "h4", "p", "li", "td", "pre", "blockquote"]


def parse_html(
    abs_path: Path, mapping: dict[str, Any], failures: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    from bs4 import BeautifulSoup

    raw = abs_path.read_bytes()
    soup = BeautifulSoup(raw, "html.parser")
    for tag in soup(_HTML_NOISE_TAGS):
        tag.decompose()

    title = (soup.title.get_text(strip=True) if soup.title else "") or ""

    # 按文档顺序收集文本块，h1/h2/h3 更新当前 section
    blocks: list[tuple[str, str]] = []  # (section, text)
    section = title
    for el in soup.find_all(_HTML_TEXT_TAGS):
        text = el.get_text(" ", strip=True)
        if not text:
            continue
        if el.name in ("h1", "h2", "h3"):
            section = text
            continue
        blocks.append((section, text))

    # 兜底：结构化标签收不到正文时（div 布局页面），退化为整页文本
    if sum(len(t) for _, t in blocks) < 200:
        whole = soup.get_text("\n", strip=True)
        blocks = [(title, para) for para in whole.split("\n") if para.strip()]

    # 相邻同 section 的段落合并到 MAX_CHARS 以内，再滑窗兜底
    chunks: list[dict[str, Any]] = []
    chunk_index = 0
    buf, buf_section = "", ""
    merged: list[tuple[str, str]] = []
    for sec, text in blocks:
        if buf and (sec != buf_section or len(buf) + len(text) + 1 > MAX_CHARS):
            merged.append((buf_section, buf))
            buf, buf_section = "", ""
        if not buf:
            buf_section = sec
        buf = f"{buf}\n{text}".strip()
    if buf:
        merged.append((buf_section, buf))

    for sec, text in merged:
        for piece in _sliding_window(text):
            if not _keep(piece):
                continue
            chunks.append(
                make_chunk(
                    domain=mapping["domain"],
                    doc_id=mapping["doc_id"],
                    source_type="html",
                    source_path=mapping["path"],
                    page=None,
                    section=sec,
                    text=piece,
                    chunk_index=chunk_index,
                )
            )
            chunk_index += 1
    return chunks


# ---------------------------------------------------------------- TXT


def _read_txt(abs_path: Path) -> str:
    """依次尝试 utf-8-sig / utf-8 / gb18030。文件名 mojibake 与正文无关。"""
    for enc in ("utf-8-sig", "utf-8", "gb18030"):
        try:
            return abs_path.read_text(encoding=enc)
        except UnicodeDecodeError:
            continue
    raise UnicodeDecodeError("all", b"", 0, 1, f"无法用 utf-8-sig/utf-8/gb18030 解码: {abs_path}")


def parse_txt(
    abs_path: Path, mapping: dict[str, Any], failures: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    content = _read_txt(abs_path)
    lines = content.splitlines()

    # 按 章/条 切分：标题行开新块；无标题结构时按空行分段
    blocks: list[tuple[str, str]] = []  # (section, text)
    current_section = ""
    buf: list[str] = []

    def flush() -> None:
        text = "\n".join(buf).strip()
        if text:
            blocks.append((current_section, text))
        buf.clear()

    has_structure = any(_is_heading(line) for line in lines)
    if has_structure:
        for line in lines:
            stripped = line.strip()
            if _is_heading(stripped):
                flush()
                current_section = stripped
                buf.append(stripped)
            else:
                buf.append(line)
        flush()
    else:
        for para in re.split(r"\n\s*\n", content):
            if para.strip():
                blocks.append(("", para.strip()))

    chunks: list[dict[str, Any]] = []
    chunk_index = 0
    for sec, text in blocks:
        for piece in _sliding_window(text):
            if not _keep(piece):
                continue
            chunks.append(
                make_chunk(
                    domain=mapping["domain"],
                    doc_id=mapping["doc_id"],
                    source_type="txt",
                    source_path=mapping["path"],
                    page=None,
                    section=sec,
                    text=piece,
                    chunk_index=chunk_index,
                )
            )
            chunk_index += 1
    return chunks


# ---------------------------------------------------------------- 主流程

_PARSERS = {"pdf": parse_pdf, "html": parse_html, "txt": parse_txt}


def load_doc_map(path: Path = DOC_ID_MAP_PATH) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(
            f"缺少 {path}。请先运行: python -m agent.check_doc_map"
        )
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def _cache_path(mapping: dict[str, Any]) -> Path:
    # doc_id 可能含中文与〔〕等字符，可作文件名；仅替换路径分隔符以防万一
    safe_id = mapping["doc_id"].replace("/", "_")
    return PARSE_CACHE_DIR / f"{mapping['domain']}__{safe_id}.json"


def _parse_one_cached(
    mapping: dict[str, Any], refresh: bool = False
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """解析单文档，带缓存。返回 (chunks, failures)。缓存写入为原子操作。"""
    cache = _cache_path(mapping)
    if cache.is_file() and not refresh:
        with cache.open("r", encoding="utf-8") as f:
            data = json.load(f)
        return data["chunks"], data["failures"]

    failures: list[dict[str, Any]] = []
    abs_path = REPO_ROOT / mapping["path"]
    chunks = _PARSERS[mapping["source_type"]](abs_path, mapping, failures)

    PARSE_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    tmp = cache.with_suffix(".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump({"chunks": chunks, "failures": failures}, f, ensure_ascii=False)
    tmp.replace(cache)
    return chunks, failures


def parse_all(
    doc_map: dict[str, Any], refresh: bool = False
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """解析 doc_map 中全部文档，返回 (chunks, report)。单文档失败不中断。"""
    failures: list[dict[str, Any]] = []
    all_chunks: list[dict[str, Any]] = []
    stats_src: dict[str, dict[str, int]] = {}
    stats_dom: dict[str, dict[str, int]] = {}
    parsed_count = 0
    failed_docs = 0

    mappings = doc_map["mappings"]
    for mapping in mappings:
        src, dom = mapping["source_type"], mapping["domain"]
        try:
            chunks, doc_failures = _parse_one_cached(mapping, refresh=refresh)
            failures.extend(doc_failures)
            all_chunks.extend(chunks)
            parsed_count += 1
            stats_src.setdefault(src, {"documents": 0, "chunks": 0})
            stats_src[src]["documents"] += 1
            stats_src[src]["chunks"] += len(chunks)
            stats_dom.setdefault(dom, {"documents": 0, "chunks": 0})
            stats_dom[dom]["documents"] += 1
            stats_dom[dom]["chunks"] += len(chunks)
        except Exception as exc:
            failed_docs += 1
            failures.append(
                {
                    "domain": dom,
                    "doc_id": mapping["doc_id"],
                    "path": mapping["path"],
                    "stage": "document",
                    "error": repr(exc),
                }
            )

    report = {
        "generated_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        "input_doc_map": str(DOC_ID_MAP_PATH.relative_to(REPO_ROOT)),
        "output_chunks": str(CHUNKS_PATH.relative_to(REPO_ROOT)),
        "document_count": len(mappings),
        "parsed_document_count": parsed_count,
        "failed_document_count": failed_docs,
        "chunk_count": len(all_chunks),
        "by_source_type": stats_src,
        "by_domain": stats_dom,
        "failures": failures,
    }
    return all_chunks, report


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="python -m agent.parse_documents",
        description="解析 A 榜涉及文档为统一 chunks（不调用模型）",
    )
    parser.add_argument("--group", default="group_a", choices=["group_a"], help="题目组别")
    parser.add_argument(
        "--refresh", action="store_true", help="忽略 parse_cache 缓存，强制重新解析"
    )
    args = parser.parse_args()

    try:
        doc_map = load_doc_map()
    except FileNotFoundError as exc:
        print(f"[error] {exc}", file=sys.stderr)
        return 1

    chunks, report = parse_all(doc_map, refresh=args.refresh)

    PROCESSED_DATA_DIR.mkdir(parents=True, exist_ok=True)
    with CHUNKS_PATH.open("w", encoding="utf-8") as f:
        for chunk in chunks:
            f.write(json.dumps(chunk, ensure_ascii=False) + "\n")
    with PARSE_REPORT_PATH.open("w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    print(
        f"[parse] documents={report['document_count']} "
        f"parsed={report['parsed_document_count']} failed={report['failed_document_count']} "
        f"chunks={report['chunk_count']}"
    )
    for src, s in sorted(report["by_source_type"].items()):
        print(f"[parse]   {src}: {s['documents']} docs, {s['chunks']} chunks")
    print(f"[out] {CHUNKS_PATH}")
    print(f"[out] {PARSE_REPORT_PATH}")
    if report["failures"]:
        print(f"[warn] failures={len(report['failures'])}（详见 parse_report.json）", file=sys.stderr)

    if report["parsed_document_count"] == 0:
        print("[fail] 所有文档解析失败", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

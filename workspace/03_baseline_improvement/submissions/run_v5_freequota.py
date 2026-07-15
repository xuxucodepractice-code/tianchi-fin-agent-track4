"""
v5 实验 —— 用免费额度模型跑完整 100 题。

相比 v4（run_v4_chunk10000.py）的改动：
  1. MODEL: qwen-plus-latest → qwen-plus-2025-07-28
     （v4 用的 latest 不在免费额度名单里，走了付费导致第70题起欠费中断；
      qwen-plus-2025-07-28 有 100万免费额度、实测可用、属 Qwen 系列合规）
  2. CHUNK_CHARS: 10000 → 6000（单题token砍约40%，100题约90万，控制在免费额度内）
  3. sleep: 0.2 → 0.5（防瞬时限流）
  4. 输出: answer_v5.csv

对照基线：v3（step4_run_all.py，3000字，29.2375）。
本版同时变了"模型"和"截断长度"两个量，严格说不是纯单变量对照 v3；
但相对 v4 只为解决额度问题做最小改动，目的是先拿到一份完整可提交结果。
"""

import os
import re
import csv
import json
import time
from pathlib import Path

import pypdf
from bs4 import BeautifulSoup
import dashscope

MODEL = "qwen-plus-2025-07-28"   # 免费额度覆盖的模型（Qwen系列，合规）
CHUNK_CHARS = 6000           # ← v5：10000→6000，控制在免费额度内跑完100题
OUT_CSV = "answer_v5.csv"
DATA_ROOT = Path(__file__).parent / "official_data" / "public_dataset_upload"


def load_all_questions() -> list[dict]:
    qdir = DATA_ROOT / "questions" / "group_a"
    questions = []
    for jp in sorted(qdir.glob("*.json")):
        questions.extend(json.load(jp.open(encoding="utf-8")))
    return questions


_doc_cache: dict[tuple, str] = {}


def find_doc_file(domain: str, doc_id: str) -> "Path | None":
    """在领域目录（含子目录）递归找 doc_id.*，返回第一个匹配文件。"""
    root = DATA_ROOT / "raw" / domain
    for p in root.rglob(doc_id + ".*"):
        if p.is_file():
            return p
    return None


def extract_text(path: Path) -> str:
    """按扩展名抽文字：pdf / html / txt。"""
    suffix = path.suffix.lower()
    try:
        if suffix == ".pdf":
            reader = pypdf.PdfReader(str(path))
            return "\n".join((pg.extract_text() or "") for pg in reader.pages)
        if suffix in (".html", ".htm"):
            html = path.read_text(encoding="utf-8", errors="ignore")
            soup = BeautifulSoup(html, "lxml")
            for tag in soup(["script", "style"]):
                tag.decompose()
            return soup.get_text(separator="\n")
        if suffix == ".txt":
            return path.read_text(encoding="utf-8", errors="ignore")
    except Exception as e:
        return f"[读取失败 {path.name}: {e}]"
    return f"[未知格式 {path.name}]"


def read_doc_text(domain: str, doc_id: str) -> str:
    key = (domain, doc_id)
    if key in _doc_cache:
        return _doc_cache[key]
    path = find_doc_file(domain, doc_id)
    text = extract_text(path) if path else f"[文档不存在: {domain}/{doc_id}]"
    _doc_cache[key] = text
    return text


def build_prompt(question: dict, docs_text: dict) -> str:
    fmt_rule = {
        "mcq": "这是单选题，只回复一个大写字母，如 A。",
        "multi": "这是多选题，回复所有正确选项的大写字母，按字母升序、无分隔符，如 BC。",
        "tf": "这是判断题，只回复一个大写字母 A 或 B。",
    }.get(question.get("answer_format"), "只回复选项大写字母。")

    parts = ["以下是若干参考文档（可能只截取了开头部分）：\n"]
    for doc_id, text in docs_text.items():
        parts.append(f"【文档{doc_id}】\n{text[:CHUNK_CHARS]}\n")
    parts.append(f"\n问题：{question['question']}\n选项：")
    for k, v in question.get("options", {}).items():
        parts.append(f"{k}. {v}")
    parts.append(f"\n要求：{fmt_rule} 只输出答案本身，不要解释。")
    return "\n".join(parts)


def normalize_answer(raw: str, fmt: str) -> str:
    letters = re.findall(r"[A-D]", raw.upper())
    if not letters:
        return ""
    if fmt == "multi":
        return "".join(sorted(set(letters)))
    return letters[0]


def ask_qwen(api_key: str, prompt: str):
    resp = dashscope.Generation.call(
        api_key=api_key, model=MODEL,
        messages=[{"role": "user", "content": prompt}],
        result_format="message",
    )
    if resp.status_code != 200:
        raise RuntimeError(f"code={resp.status_code} {resp.code} {resp.message}")
    answer = resp.output.choices[0].message.content.strip()
    u = resp.usage
    return answer, u.get("input_tokens", 0), u.get("output_tokens", 0)


def main() -> int:
    api_key = os.environ.get("DASHSCOPE_API_KEY")
    if not api_key:
        print("❌ 没读到 DASHSCOPE_API_KEY")
        return 1
    if not DATA_ROOT.exists():
        print(f"❌ 数据目录不存在: {DATA_ROOT}")
        return 1

    questions = load_all_questions()
    print(f"共加载 {len(questions)} 题（v4，CHUNK_CHARS={CHUNK_CHARS}，v5），模型 {MODEL}\n")

    rows, sum_p, sum_c, sum_t = [], 0, 0, 0
    domain_doc_chars: dict = {}

    for i, q in enumerate(questions, 1):
        qid, domain, fmt = q["qid"], q["domain"], q.get("answer_format")
        try:
            docs = {d: read_doc_text(domain, d) for d in q.get("doc_ids", [])}
            doc_chars = sum(len(t) for t in docs.values())
            domain_doc_chars[domain] = domain_doc_chars.get(domain, 0) + doc_chars
            answer_raw, ptok, ctok = ask_qwen(api_key, build_prompt(q, docs))
            answer = normalize_answer(answer_raw, fmt)
        except Exception as e:
            print(f"  [{i}/100] {qid} ❌ {e}")
            answer, ptok, ctok = "", 0, 0
        ttok = ptok + ctok
        rows.append((qid, answer, ptok, ctok, ttok))
        sum_p += ptok; sum_c += ctok; sum_t += ttok
        print(f"  [{i}/100] {qid} ({domain}/{fmt}) -> {answer or '空'} | tok {ttok}")
        time.sleep(0.5)

    out_path = Path(__file__).parent / OUT_CSV
    with out_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["qid", "answer", "prompt_tokens", "completion_tokens", "total_tokens"])
        w.writerow(["summary", "", sum_p, sum_c, sum_t])
        for r in rows:
            w.writerow(r)

    budget = 5_000_000
    tscore = max(0, min(1, (budget - sum_t) / budget))
    print("\n" + "=" * 44)
    print(f"✅ 已写出 {out_path}")
    print(f"   空答案: {sum(1 for r in rows if not r[1])}")
    print(f"   总token: prompt={sum_p} completion={sum_c} total={sum_t}")
    print(f"   TokenScore≈{tscore:.4f}")
    print(f"   各领域读到的文档总字数: {domain_doc_chars}")
    print("=" * 44)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

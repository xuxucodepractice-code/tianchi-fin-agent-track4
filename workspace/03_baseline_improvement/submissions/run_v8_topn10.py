"""
v8 调参 —— 检索 TOP_N 8→10（唯一变量：每份文档喂几段）。

对照基线：v6（run_v6_retrieval.py，TOP_N=8，线上 61.4601）。
本版唯一改动：TOP_N 8→10，多喂2段相关证据，赌"v6可能喂少了漏证据"。
模型、检索逻辑、prompt、后处理、其余全部与 v6 相同 → 分数变化可干净归因到"喂8段 vs 喂10段"。
"""

import os
import re
import csv
import json
import time
import math
from pathlib import Path

import pypdf
from bs4 import BeautifulSoup
import dashscope

MODEL = "qwen-max"   # 与 v6 同款
OUT_CSV = "answer_v8.csv"
DATA_ROOT = Path(__file__).parent / "official_data" / "public_dataset_upload"

# --- 检索参数（见文件头说明） ---
SEG_CHARS = 500          # 每段长度
OVERLAP = 100            # 段间重叠，防关键句被切断
TOP_N = 10               # ← v8：8→10，每份文档多喂2段相关证据（唯一变量）
FALLBACK_CHARS = 4000    # 零命中兜底喂开头字数

_STOP = set("的了在与和或及为是对于按之其此该等被把从向到由于至因而则若如以下哪些哪个哪项"
            "说法正确错误关于根据属于包括或者以及并且对于其中无论均不可以不得应当如果但是"
            "所以因此这个那个什么怎样如何选项题目下列本题均为都是不是没有允许一个进行以及")


def load_all_questions() -> list[dict]:
    qdir = DATA_ROOT / "questions" / "group_a"
    questions = []
    for jp in sorted(qdir.glob("*.json")):
        questions.extend(json.load(jp.open(encoding="utf-8")))
    return questions


_doc_cache: dict = {}


def find_doc_file(domain: str, doc_id: str):
    root = DATA_ROOT / "raw" / domain
    for p in root.rglob(doc_id + ".*"):
        if p.is_file():
            return p
    return None


def extract_text(path: Path) -> str:
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


# ------------------------------------------------------------ 检索四步

def split_segments(text: str) -> list[str]:
    """第1步：切成 SEG_CHARS 字的段，带 OVERLAP 重叠。"""
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) <= SEG_CHARS:
        return [text] if text else []
    step = SEG_CHARS - OVERLAP
    return [text[i:i + SEG_CHARS] for i in range(0, len(text), step) if text[i:i + SEG_CHARS].strip()]


def extract_keywords(question: dict) -> list[str]:
    """第2步：从题干+选项抽关键词（中文2-4gram + 数字/比例/条款号），扔停用词。"""
    parts = [question.get("question", "")]
    parts.extend(str(v) for v in question.get("options", {}).values())
    text = " ".join(parts)

    terms: set[str] = set()
    # 数字/百分比/年份/金额/条款号（这些后面加权）
    terms.update(re.findall(r"\d+(?:\.\d+)?%|\d{4}年?|\d+(?:\.\d+)?(?:亿元|万元|亿|万|元|个月|周岁|日|天|年|月|倍|次|期)|第[一二三四五六七八九十百千0-9]+[章节条款项]", text))
    # 中文 2-4 字片段
    for run in re.findall(r"[一-鿿]+", text):
        for n in (4, 3, 2):
            for i in range(len(run) - n + 1):
                g = run[i:i + n]
                if g not in _STOP and not all(ch in _STOP for ch in g):
                    terms.add(g)
    # 英文词/长数字
    terms.update(re.findall(r"[a-zA-Z][a-zA-Z0-9]{2,}", text))
    return [t for t in terms if len(t) >= 2]


def is_numeric(term: str) -> bool:
    return bool(re.search(r"\d|第[一二三四五六七八九十百千]+[章节条款项]", term))


def retrieve_segments(segments: list[str], keywords: list[str]) -> str:
    """第3+4步：每段按 BM25 风格打分，取 top-N 段拼成一份文本。"""
    if not segments:
        return ""
    n = len(segments)
    norm_segs = [s.lower() for s in segments]
    # df: 每个词出现在多少段里（稀有词 idf 高）
    df = {}
    for kw in keywords:
        k = kw.lower()
        df[k] = sum(1 for s in norm_segs if k in s)

    scored = []
    for idx, seg in enumerate(norm_segs):
        score = 0.0
        for kw in keywords:
            k = kw.lower()
            tf = seg.count(k)
            if tf == 0 or df[k] == 0:
                continue
            idf = math.log(1 + (n - df[k] + 0.5) / (df[k] + 0.5))
            w = min(len(kw), 6)                 # 长词更值钱
            if is_numeric(kw):
                w *= 3.0                          # 数字/条款号加权
            score += w * idf * (tf * 2.2 / (tf + 1.2))   # tf 饱和
        if score > 0:
            scored.append((score, idx))
    if not scored:
        return ""
    scored.sort(key=lambda x: (-x[0], x[1]))
    picked = sorted(idx for _, idx in scored[:TOP_N])   # 按原文顺序拼回
    return "\n...\n".join(segments[i] for i in picked)


def build_doc_text_for_question(question: dict, doc_id: str, full_text: str) -> str:
    """把一份文档处理成"喂给Qwen的文本"：检索命中则喂相关段，否则兜底喂开头。"""
    segments = split_segments(full_text)
    keywords = extract_keywords(question)
    retrieved = retrieve_segments(segments, keywords)
    if retrieved:
        return retrieved
    return full_text[:FALLBACK_CHARS]   # 零命中兜底


# ------------------------------------------------------------ prompt / 调用（与 v5 一致）

def build_prompt(question: dict, docs_text: dict) -> str:
    fmt_rule = {
        "mcq": "这是单选题，只回复一个大写字母，如 A。",
        "multi": "这是多选题，回复所有正确选项的大写字母，按字母升序、无分隔符，如 BC。",
        "tf": "这是判断题，只回复一个大写字母 A 或 B。",
    }.get(question.get("answer_format"), "只回复选项大写字母。")

    parts = ["以下是从参考文档中检索出的相关段落：\n"]
    for doc_id, text in docs_text.items():
        parts.append(f"【文档{doc_id}】\n{text}\n")
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
    print(f"共加载 {len(questions)} 题（v6 检索版，SEG={SEG_CHARS} TOP_N={TOP_N}），模型 {MODEL}\n")

    rows, sum_p, sum_c, sum_t = [], 0, 0, 0
    fallback_count = 0

    for i, q in enumerate(questions, 1):
        qid, domain, fmt = q["qid"], q["domain"], q.get("answer_format")
        try:
            docs_text = {}
            for d in q.get("doc_ids", []):
                full = read_doc_text(domain, d)
                docs_text[d] = build_doc_text_for_question(q, d, full)
            answer_raw, ptok, ctok = ask_qwen(api_key, build_prompt(q, docs_text))
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
    print("=" * 44)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

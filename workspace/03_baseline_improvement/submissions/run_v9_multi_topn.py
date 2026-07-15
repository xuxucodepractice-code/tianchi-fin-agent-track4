"""
v9 —— 按题型分治 TOP_N：multi 多选题用高 TOP_N(证据多、治漏选)，mcq/tf 保持 TOP_N=8。
本地验证版：跑全量100题 → 和 reference_claude.csv 比 → 看"只给多选题多喂证据"能把准确率抬到多少。

对照基线：v6（全题型 TOP_N=8，本地一致率67%，线上61.46）。
本版唯一设计改动：multi 题的 TOP_N 8→MULTI_TOP_N；mcq/tf 不变。

⚠️ 运行说明：本地验证用百度网关(deepseek-v4-pro)跑（Qwen额度不够高TOP_N全量）。
   因此这是"方向/天花板"的本地估计，不是纯Qwen单变量对照；
   正式提交仍须用 Qwen。答案写 answer_v9.csv，token列记网关真实用量。
"""
import os
import csv
from pathlib import Path

import anthropic
import run_v6_retrieval as v6

MULTI_TOP_N = 24     # 多选题：高 TOP_N（探针证明 top24 治漏选最好）
BASE_TOP_N = 8       # mcq/tf：保持 v6 基线
MODEL = "deepseek-v4-pro"
MAX_TOKENS = 2048    # 推理模型难题思考长，给足防被截断返回空
OUT_CSV = "answer_v9.csv"


def make_client():
    return anthropic.Anthropic(
        base_url=os.environ["ANTHROPIC_BASE_URL"],
        auth_token=os.environ.get("ANTHROPIC_AUTH_TOKEN") or os.environ["ANTHROPIC_API_KEY"],
    )


def ask_gw(client, prompt: str):
    r = client.messages.create(
        model=MODEL, max_tokens=MAX_TOKENS,
        messages=[{"role": "user", "content": prompt}],
    )
    txt = "".join(b.text for b in r.content if b.type == "text").strip()
    return txt, r.usage.input_tokens, r.usage.output_tokens


def build_docs(q: dict, top_n: int) -> dict:
    old = v6.TOP_N
    v6.TOP_N = top_n
    try:
        docs = {}
        for d in q.get("doc_ids", []):
            full = v6.read_doc_text(q["domain"], d)
            docs[d] = v6.build_doc_text_for_question(q, d, full)
        return docs
    finally:
        v6.TOP_N = old


def main() -> int:
    if not (os.environ.get("ANTHROPIC_AUTH_TOKEN") or os.environ.get("ANTHROPIC_API_KEY")):
        print("❌ 没读到网关 key"); return 1
    client = make_client()
    questions = v6.load_all_questions()
    print(f"v9 分治TOP_N | multi={MULTI_TOP_N} mcq/tf={BASE_TOP_N} | 网关 {MODEL}\n")

    rows, sum_i, sum_o = [], 0, 0
    for i, q in enumerate(questions, 1):
        qid, domain, fmt = q["qid"], q["domain"], q.get("answer_format")
        top_n = MULTI_TOP_N if fmt == "multi" else BASE_TOP_N
        try:
            docs = build_docs(q, top_n)
            raw, itok, otok = ask_gw(client, v6.build_prompt(q, docs))
            ans = v6.normalize_answer(raw, fmt)
        except Exception as e:
            print(f"  [{i}/100] {qid} ❌ {e}")
            ans, itok, otok = "", 0, 0
        rows.append((qid, ans, itok, otok, itok + otok))
        sum_i += itok; sum_o += otok
        print(f"  [{i}/100] {qid} ({fmt},top{top_n}) -> {ans or '空'} | tok {itok}+{otok}")

    out = Path(__file__).parent / OUT_CSV
    with out.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["qid", "answer", "prompt_tokens", "completion_tokens", "total_tokens"])
        w.writerow(["summary", "", sum_i, sum_o, sum_i + sum_o])
        for r in rows:
            w.writerow(r)

    print("\n" + "=" * 44)
    print(f"✅ 已写出 {out}")
    print(f"   空答案: {sum(1 for r in rows if not r[1])}")
    print(f"   总token: in={sum_i} out={sum_o} total={sum_i + sum_o}")
    print(f"   下一步: ./.venv/bin/python compare_to_reference.py answer_v9.csv")
    print("=" * 44)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

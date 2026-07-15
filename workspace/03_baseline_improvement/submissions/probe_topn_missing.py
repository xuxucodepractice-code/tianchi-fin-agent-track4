"""
第1步本地验证 —— "多喂证据能不能治多选漏选"（不提交、只花小额度）。

背景：v6a 线上 72 实锤了 v6 的病=多选漏选（Qwen比Claude少选一项）。
本脚本拿几道典型"漏选"题，用 Qwen 在不同 TOP_N 下各答一次，和 Claude 参考答案比：
  TOP_N 越大 = 喂越多检索证据 → 看 Qwen 能不能自己把漏掉的 B/D 补上。
只跑这几道题、只调 TOP_N 一个量，其余（模型/prompt/检索逻辑）全用 v6 原样。
"""
import os
import csv
from pathlib import Path

import run_v6_retrieval as v6

# 典型漏选题（Qwen 比 Claude 少选一项）——从 33 道分歧里挑
SAMPLE_QIDS = ["fc_a_009", "fc_a_017", "fin_a_002", "fin_a_007", "fin_a_009", "fin_a_016"]
TOPN_GRID = [8, 16, 24]   # v6基线8 → 翻倍 → 三倍，看喂更多证据的效果


def load_ref() -> dict:
    ref = {}
    p = Path(__file__).parent / "reference_claude.csv"
    for r in csv.reader(p.open(encoding="utf-8")):
        if r and r[0] not in ("qid",):
            ref[r[0]] = r[1]
    return ref


def answer_at_topn(api_key: str, q: dict, top_n: int):
    """用指定 TOP_N 检索并让 Qwen 答一次，返回 (answer, tok)。"""
    old = v6.TOP_N
    v6.TOP_N = top_n
    try:
        docs_text = {}
        for d in q.get("doc_ids", []):
            full = v6.read_doc_text(q["domain"], d)
            docs_text[d] = v6.build_doc_text_for_question(q, d, full)
        raw, p, c = v6.ask_qwen(api_key, v6.build_prompt(q, docs_text))
        return v6.normalize_answer(raw, q.get("answer_format")), p + c
    finally:
        v6.TOP_N = old


def main() -> int:
    api_key = os.environ.get("DASHSCOPE_API_KEY")
    if not api_key:
        print("❌ 没读到 DASHSCOPE_API_KEY"); return 1

    ref = load_ref()
    all_q = {q["qid"]: q for q in v6.load_all_questions()}

    print(f"模型 {v6.MODEL} | 验证 {len(SAMPLE_QIDS)} 道典型漏选题 | TOP_N={TOPN_GRID}\n")
    header = f"{'qid':<11}{'v6(top8)':<10}" + "".join(f"top{n:<7}" for n in TOPN_GRID) + "Claude参考"
    print(header); print("-" * len(header))

    total_tok = 0
    match_count = {n: 0 for n in TOPN_GRID}
    for qid in SAMPLE_QIDS:
        q = all_q[qid]
        cells, row_toks = [], 0
        for n in TOPN_GRID:
            ans, tok = answer_at_topn(api_key, q, n)
            cells.append(ans or "空")
            row_toks += tok
            if ans == ref.get(qid):
                match_count[n] += 1
        total_tok += row_toks
        v6_base = cells[0]   # top8 就是 v6 基线
        line = f"{qid:<11}{v6_base:<10}" + "".join(f"{c:<10}" for c in cells) + f"{ref.get(qid,'?')}"
        print(line)

    print("-" * len(header))
    print("各 TOP_N 命中 Claude 参考的题数：")
    for n in TOPN_GRID:
        print(f"  top{n}: {match_count[n]}/{len(SAMPLE_QIDS)}")
    print(f"\n本次总 token ≈ {total_tok}")
    print("解读：若 top16/24 比 top8 命中更多，说明'多喂证据治漏选'成立 → 值得做全量高TOP_N版")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

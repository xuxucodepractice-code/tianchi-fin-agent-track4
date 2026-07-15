"""
v13c —— 抽取式 + question-aware 结合（旋钮A、B 同时开）。

2×2 实验里的 (摘原句, 逐选项宁多勿漏) 角：把 v13a 的"逐字摘原句"和 v13b 的"逐个选项宁多勿漏"
合到一个压缩 prompt 里。这就是 改进策略.md 第13.3 节的 v13 目标形态。
目的：测两个旋钮一起开，能不能把 v12 丢的多选证据完全救回来、并稳住其他题型。

- 检索：复用 v9（multi top24 / 其余 top8）。
- 压缩：本文件唯一改动 —— 抽取式 + 逐选项 + 宁多勿漏，三者合一。
- 答题：复用 v12 的 build_answer_from_notes_prompt。
- 模型：deepseek-v4-pro（开发期网关）。
"""
import os
import csv
from pathlib import Path

import run_v6_retrieval as v6
import run_v9_multi_topn as v9
import run_v12_compress as v12

MULTI_TOP_N = 24
BASE_TOP_N = 8
MAX_TOKENS = 8192
OUT_CSV = "answer_v13c.csv"


def build_compress_prompt(question: dict, docs_text: dict) -> str:
    """旋钮A+B 合一：逐个选项、逐字摘原句、宁多勿漏、不改写。"""
    parts = ["你是金融文档分析助手。下面是从参考文档中检索出的候选段落，可能含大量与本题无关的内容。\n"]
    parts.append("请围绕本题的【每一个选项】，从原文中【逐字摘录】能支持或反驳该选项的句子，组成一份摘录笔记。\n")
    parts.append("硬性要求：")
    parts.append("1. 【逐个选项】过一遍，为每个选项摘出与它相关的原文句子（哪怕只有一点线索也要摘）。")
    parts.append("2. 只能【逐字复制原文】，不得改写、转述、总结、下结论。")
    parts.append("3. 宁多勿漏：只要可能和某个选项有关就摘，不要因为「看起来次要」而丢掉。")
    parts.append("4. 含数字/比例/金额/日期/期限/条款号的句子务必原样摘录，一字不改。\n")
    parts.append("笔记格式（按选项分栏，无相关原句的写“无”）：")
    for k in question.get("options", {}):
        parts.append(f"【选项{k}相关原句】：…")
    parts.append("")
    parts.append(f"问题：{question['question']}")
    parts.append("选项：")
    for k, val in question.get("options", {}).items():
        parts.append(f"{k}. {val}")
    parts.append("\n候选段落：")
    for doc_id, text in docs_text.items():
        parts.append(f"【文档{doc_id}】\n{text}\n")
    parts.append("\n请直接输出按选项分栏的摘录原句，不要回答题目本身，不要加解释。")
    return "\n".join(parts)


def main() -> int:
    if not (os.environ.get("ANTHROPIC_AUTH_TOKEN") or os.environ.get("ANTHROPIC_API_KEY")):
        print("❌ 没读到网关 key"); return 1
    client = v9.make_client()
    v9.MAX_TOKENS = MAX_TOKENS
    questions = v6.load_all_questions()
    print(f"v13c 抽取式+question-aware | 候选 multi={MULTI_TOP_N} 其余={BASE_TOP_N} | 网关 {v9.MODEL}\n")

    rows = []
    sum_ci = sum_co = sum_ai = sum_ao = 0
    for i, q in enumerate(questions, 1):
        qid, fmt = q["qid"], q.get("answer_format")
        top_n = MULTI_TOP_N if fmt == "multi" else BASE_TOP_N
        try:
            docs = v9.build_docs(q, top_n)
            notes, ci, co = v9.ask_gw(client, build_compress_prompt(q, docs))
            if len(notes.strip()) < 10:
                notes = "\n".join(f"【文档{d}】\n{t}" for d, t in docs.items())
                print(f"      ⚠️ {qid} 压缩为空，退回原候选段答题")
            raw, ai, ao = v9.ask_gw(client, v12.build_answer_from_notes_prompt(q, notes))
            ans = v6.normalize_answer(raw, fmt)
        except Exception as e:
            print(f"  [{i}/100] {qid} ❌ {e}")
            ans, ci, co, ai, ao = "", 0, 0, 0, 0
        itok, otok = ci + ai, co + ao
        rows.append((qid, ans, itok, otok, itok + otok))
        sum_ci += ci; sum_co += co; sum_ai += ai; sum_ao += ao
        print(f"  [{i}/100] {qid} ({fmt},top{top_n}) -> {ans or '空'} | 压缩 {ci}+{co} 答题 {ai}+{ao}")

    out = Path(__file__).parent / OUT_CSV
    with out.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["qid", "answer", "prompt_tokens", "completion_tokens", "total_tokens"])
        tot_i, tot_o = sum_ci + sum_ai, sum_co + sum_ao
        w.writerow(["summary", "", tot_i, tot_o, tot_i + tot_o])
        for r in rows:
            w.writerow(r)

    total = sum_ci + sum_co + sum_ai + sum_ao
    print("\n" + "=" * 52)
    print(f"✅ 已写出 {out}")
    print(f"   空答案: {sum(1 for r in rows if not r[1])}")
    print(f"   压缩阶段 token: in={sum_ci} out={sum_co}")
    print(f"   答题阶段 token: in={sum_ai} out={sum_ao}")
    print(f"   总 token: {total}  (对比 v12≈140万)")
    print(f"   下一步: ./.venv/bin/python my_benchmark.py {OUT_CSV}")
    print("=" * 52)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

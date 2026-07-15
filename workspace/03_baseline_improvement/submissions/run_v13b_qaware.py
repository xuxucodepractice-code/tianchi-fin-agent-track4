"""
v13b —— question-aware 压缩（只改"旋钮B：留什么+目标"）。

2×2 实验里的 (改写, 逐选项宁多勿漏) 角：相对 v12 只把压缩目标从【泛化尽量短】换成
【逐个选项分别保留支持/反驳证据、宁多勿漏】，压缩方式仍是 v12 的"改写重述"（旋钮A 不动）。
目的：单独测"强化盯选项、宁多勿漏"能救回多少 v12 丢的多选证据。

- 检索：复用 v9（multi top24 / 其余 top8），与 v12 同一批候选段。
- 压缩：本文件唯一改动 —— build_compress_prompt 逐选项组织、要求宁多勿漏。
- 答题：复用 v12 的 build_answer_from_notes_prompt。
- 模型：deepseek-v4-pro（开发期网关）。

★干净归因★：v13b vs v12 唯一差别 = 压缩目标是"逐选项宁多勿漏" 还是 "泛化求短"。
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
OUT_CSV = "answer_v13b.csv"


def build_compress_prompt(question: dict, docs_text: dict) -> str:
    """旋钮B=question-aware：逐个选项找证据、宁多勿漏（旋钮A 仍是 v12 的改写重述）。"""
    parts = ["你是金融文档分析助手。下面是从参考文档中检索出的候选段落，可能含大量与本题无关的内容。\n"]
    parts.append("请围绕本题的【每一个选项】，分别整理出能支持或反驳该选项的关键信息，压成一份要点笔记。\n")
    parts.append("硬性要求：")
    parts.append("1. 【逐个选项】过一遍，为每个选项单独列出与它相关的数据/条款/事实（哪怕只有一点线索也要保留）。")
    parts.append("2. 宁多勿漏：只要可能和某个选项有关，就保留，不要因为「看起来次要」而删掉。")
    parts.append("3. 数字/比例/金额/日期/期限/条款号务必原样保留，不得改动。\n")
    parts.append("笔记格式（按选项分栏，无相关内容的写“无”）：")
    for k in question.get("options", {}):
        parts.append(f"【选项{k}相关证据】：…")
    parts.append("")
    parts.append(f"问题：{question['question']}")
    parts.append("选项：")
    for k, val in question.get("options", {}).items():
        parts.append(f"{k}. {val}")
    parts.append("\n候选段落：")
    for doc_id, text in docs_text.items():
        parts.append(f"【文档{doc_id}】\n{text}\n")
    parts.append("\n请直接输出按选项分栏的要点笔记，不要回答题目本身。")
    return "\n".join(parts)


def main() -> int:
    if not (os.environ.get("ANTHROPIC_AUTH_TOKEN") or os.environ.get("ANTHROPIC_API_KEY")):
        print("❌ 没读到网关 key"); return 1
    client = v9.make_client()
    v9.MAX_TOKENS = MAX_TOKENS
    questions = v6.load_all_questions()
    print(f"v13b question-aware压缩 | 候选 multi={MULTI_TOP_N} 其余={BASE_TOP_N} | 网关 {v9.MODEL}\n")

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

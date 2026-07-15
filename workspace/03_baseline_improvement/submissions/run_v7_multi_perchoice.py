"""
v7 —— 只对 multi 多选题改成"逐选项审"，其余题型保持 v6 不变（唯一变量：多选题怎么问）。

对照基线：v6（run_v6_retrieval.py，检索版整题一次问，线上 61.4601）。
本版唯一改动：mcq/tf 仍整题一次问；仅 multi 题改成"每个选项单独判 支持/否定/不确定 → 只选支持的合成答案"。
检索证据完全复用 v6（同一批 top-8 段）——不重新检索，保证"喂什么"不变，只变"怎么问"。
模型、检索、其余题型全部与 v6 相同 → 分数变化可干净归因到"多选题：整题一次问 vs 逐选项审"。

借鉴队友 a榜v0 的"逐项判断"，但只用在多选题（漏选/多选痛点最集中处），
不全题型铺开——避免 token 翻倍拖垮 TokenScore（v6 的甜点=简单+省token）。
"""
import os
import re
import csv
import time
from pathlib import Path

import run_v6_retrieval as v6   # 复用 v6 的检索/解析/调用/后处理，不改动它

OUT_CSV = "answer_v7.csv"


def judge_one_option(api_key: str, question: dict, docs_text: dict, key: str, opt_text: str):
    """对单个选项问一次 Qwen：这个选项被文档支持吗？返回 (裁决, ptok, ctok)。
    裁决 ∈ {'support','refute','insufficient'}。"""
    parts = ["以下是从参考文档中检索出的相关段落：\n"]
    for doc_id, text in docs_text.items():
        parts.append(f"【文档{doc_id}】\n{text}\n")
    parts.append(f"\n问题背景：{question['question']}\n")
    parts.append(f"现在只判断下面这一个选项是否成立：\n{key}. {opt_text}\n")
    parts.append('要求：只回复一个词——"支持"（文档支持该选项成立）、'
                 '"否定"（文档表明该选项不成立）、或"不确定"（文档没给出足够信息）。不要解释。')
    prompt = "\n".join(parts)

    raw, ptok, ctok = v6.ask_qwen(api_key, prompt)
    if "支持" in raw:
        verdict = "support"
    elif "否定" in raw:
        verdict = "refute"
    else:
        verdict = "insufficient"   # 含"不确定"或任何模糊回答
    return verdict, ptok, ctok


def answer_multi_perchoice(api_key: str, question: dict, docs_text: dict):
    """多选题：逐选项审，只选判为 support 的。零 support 时回退 v6 整题一次问兜底。
    返回 (answer, ptok_sum, ctok_sum, n_calls)。"""
    options = question.get("options", {})
    picked, pt, ct, calls = [], 0, 0, 0
    for key, opt_text in options.items():
        verdict, p, c = judge_one_option(api_key, question, docs_text, key, str(opt_text))
        pt += p; ct += c; calls += 1
        if verdict == "support":
            picked.append(key)
        time.sleep(0.3)

    if picked:
        answer = "".join(sorted(set(picked)))
        return answer, pt, ct, calls

    # 零 support 兜底：回退 v6 整题一次问，避免空答案
    raw, p, c = v6.ask_qwen(api_key, v6.build_prompt(question, docs_text))
    pt += p; ct += c; calls += 1
    return v6.normalize_answer(raw, "multi"), pt, ct, calls


def main() -> int:
    api_key = os.environ.get("DASHSCOPE_API_KEY")
    if not api_key:
        print("❌ 没读到 DASHSCOPE_API_KEY"); return 1
    if not v6.DATA_ROOT.exists():
        print(f"❌ 数据目录不存在: {v6.DATA_ROOT}"); return 1

    questions = v6.load_all_questions()
    print(f"共加载 {len(questions)} 题（v7：仅multi逐选项审），模型 {v6.MODEL}\n")

    rows, sum_p, sum_c, sum_t = [], 0, 0, 0
    multi_calls = 0

    for i, q in enumerate(questions, 1):
        qid, domain, fmt = q["qid"], q["domain"], q.get("answer_format")
        try:
            docs_text = {}
            for d in q.get("doc_ids", []):
                full = v6.read_doc_text(domain, d)
                docs_text[d] = v6.build_doc_text_for_question(q, d, full)

            if fmt == "multi":
                answer, ptok, ctok, calls = answer_multi_perchoice(api_key, q, docs_text)
                multi_calls += calls
                tag = f"逐项×{calls}"
            else:
                raw, ptok, ctok = v6.ask_qwen(api_key, v6.build_prompt(q, docs_text))
                answer = v6.normalize_answer(raw, fmt)
                tag = "一次问"
        except Exception as e:
            print(f"  [{i}/100] {qid} ❌ {e}")
            answer, ptok, ctok, tag = "", 0, 0, "错误"

        ttok = ptok + ctok
        rows.append((qid, answer, ptok, ctok, ttok))
        sum_p += ptok; sum_c += ctok; sum_t += ttok
        print(f"  [{i}/100] {qid} ({domain}/{fmt}) [{tag}] -> {answer or '空'} | tok {ttok}")
        time.sleep(0.3)

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
    print(f"   多选题总调用次数: {multi_calls}")
    print(f"   总token: prompt={sum_p} completion={sum_c} total={sum_t}")
    print(f"   TokenScore≈{tscore:.4f}  （v6=0.8677）")
    print("=" * 44)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""
probe_multi_logprobs.py —— 验证：multi 多选题答题时，logprobs 能不能暴露「漏选处的犹豫」？

背景：判断题/单选答单字母、概率≈1.0，logprobs 无区分度(已测)。但 multi 答 AB/ABD 是多 token，
若模型在「要不要加上某个选项」上犹豫，可能在某位置露出低概率。若能，logprobs 就是比「模型自报missing」
更客观的怀疑信号(FLARE/DRAGIN 思路)，可用于 v16 触发定向补查。

做法：用 qwen-plus-2025-07-28(有免费额度且支持logprobs)，跑几道【已知漏选】的 multi 题
     (probe_omission_bm25 里 v15 漏选的题：reg_a_005/fc_a_014/reg_a_011/res_a_002/fc_a_005...)。
     对比：模型答了什么、每个输出 token 的概率、以及【它没选但该选的那个字母】在候选里的概率。

关键看：漏选的字母(如该选D却没选)，在生成过程中是不是以「次高概率候选」出现过?
  - 若是 → 低概率/次高候选=漏选信号，logprobs 可用。
  - 若漏选字母概率极低、从不出现 → 模型是「真没意识到」，logprobs 也救不了，此路否。

零风险小额度验证(约10题×一次调用)。
"""
import os, csv, math
from pathlib import Path
from openai import OpenAI

import run_v6_retrieval as v6
import run_v9_multi_topn as v9

HERE = Path(__file__).parent
MODEL = "qwen-plus-2025-07-28"
BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"

# probe_omission_bm25 输出里 v15 漏选的 multi 题(取分布不同的几道)
OMIT_CASES = {
    "reg_a_005": "A", "fc_a_014": "C", "reg_a_011": "D", "res_a_002": "B",
    "fc_a_005": "C", "fc_a_004": "C", "res_a_001": "B", "ins_a_009": "B",
    "fc_a_017": "B", "fin_a_012": "C",
}


def load_answers(path):
    d = {}
    with path.open(encoding="utf-8") as f:
        for r in csv.reader(f):
            if not r or r[0] in ("qid", "summary"):
                continue
            d[r[0]] = r[1] if len(r) > 1 else ""
    return d


def main():
    if not os.environ.get("DASHSCOPE_API_KEY"):
        print("❌ 没读到 DASHSCOPE_API_KEY"); return 1
    client = OpenAI(api_key=os.environ["DASHSCOPE_API_KEY"], base_url=BASE_URL)
    ref = load_answers(HERE / "reference_claude.csv")
    v15 = load_answers(HERE / "answer_v15.csv")
    questions = {q["qid"]: q for q in v6.load_all_questions()}

    print(f"验证 multi 漏选处 logprobs 犹豫痕迹 | {MODEL}\n")
    hit = 0  # 漏选字母在候选里露过面的题数
    for qid, miss_letter in OMIT_CASES.items():
        q = questions.get(qid)
        if not q:
            continue
        docs = v9.build_docs(q, 24)
        prompt = v6.build_prompt(q, docs)
        try:
            r = client.chat.completions.create(
                model=MODEL, max_tokens=20,
                messages=[{"role": "user", "content": prompt}],
                logprobs=True, top_logprobs=5,
            )
        except Exception as e:
            print(f"  {qid} ❌ {type(e).__name__} {str(e)[:100]}")
            continue
        ans = (r.choices[0].message.content or "").strip()
        lp = r.choices[0].logprobs
        # 在所有输出位置的 top候选里，找漏选字母出现的最高概率
        best_p = 0.0
        for tokinfo in (lp.content or []):
            for cand in tokinfo.top_logprobs:
                if miss_letter in cand.token:
                    best_p = max(best_p, math.exp(cand.logprob))
        appeared = best_p > 0.01
        hit += int(appeared)
        mark = f"✅露面(概率≈{best_p:.3f})" if appeared else "❌从未出现"
        print(f"  {qid}: v15答{v15.get(qid,''):<4} Claude{ref.get(qid,''):<5} 漏[{miss_letter}] | 模型这次答{ans:<5} | 漏选字母{mark}")

    print("\n" + "=" * 56)
    print(f"  漏选字母在 logprobs 候选里露过面: {hit}/{len(OMIT_CASES)} 题")
    if hit >= len(OMIT_CASES) * 0.6:
        print("  → ✅ logprobs 能捕捉漏选犹豫，可当客观怀疑信号(v16可用)")
    else:
        print("  → ❌ 漏选字母多数从不出现，模型'真没意识到'，logprobs 救不了此病")
    print("=" * 56)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

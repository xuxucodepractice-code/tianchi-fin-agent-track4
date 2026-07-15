"""
run_v10c_qwen3_32b.py —— 诊断版：把 v10 的方法(直接喂检索段·无循环·无压缩)搬到 qwen3-32b。

目的(承接 probe_multi_logprobs 的意外发现)：
  logprobs 验证时发现，v15(网关deepseek)漏选的 10 道 multi 题里，有 6 道换 qwen-plus-2025-07-28
  直接就答对了(补上漏的字母、且概率≈1.0)。这暗示：v15 的"漏选病"可能很大程度是【网关模型弱】造成的，
  换个新鲜 Qwen 就自愈——而不是必须靠 agent 循环去治。

本版验证这个假设：用纯 v10 方法(无循环、无压缩、无自检)，只把模型换成 qwen3-32b，看裸准确率多少。
  - 若裸奔逼近/超过 v10 的 77% → 漏选主要是模型问题，v16 方向应是"好模型+轻量循环只补真硬漏选"
  - 若裸奔仍 ~70% → 漏选是真结构病，循环该保留

模型选择说明：qwen-plus-2025-07-28 只剩13.8万免费额度(跑不完132万的全量)，qwen-max/qwen3.7-plus 免费额度已耗尽；
  qwen3-32b 尚有满额100万免费额度，是唯一能跑完全量的通用 Qwen。它比 qwen-plus 略小，但足以回答核心问题。
  qwen3-32b 是推理模型 → enable_thinking=False 关思考，out≈几个字母，避免思考吃 token。

相对 v10 只改一处：模型 qwen3.7-plus → qwen3-32b。方法(multi top24/其余top8、检索、prompt、后处理)全部原样。
"""
import os
import csv
from pathlib import Path

from openai import OpenAI
import run_v6_retrieval as v6

MULTI_TOP_N = 24
BASE_TOP_N = 8
MODEL = "qwen3-32b"
BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
MAX_TOKENS = 512
OUT_CSV = "answer_v10c.csv"


def make_client() -> OpenAI:
    return OpenAI(api_key=os.environ["DASHSCOPE_API_KEY"], base_url=BASE_URL)


def ask(client: OpenAI, prompt: str):
    r = client.chat.completions.create(
        model=MODEL, max_tokens=MAX_TOKENS,
        messages=[{"role": "user", "content": prompt}],
        extra_body={"enable_thinking": False},
    )
    txt = (r.choices[0].message.content or "").strip()
    return txt, r.usage.prompt_tokens, r.usage.completion_tokens


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
    if not os.environ.get("DASHSCOPE_API_KEY"):
        print("❌ 没读到 DASHSCOPE_API_KEY"); return 1
    client = make_client()
    questions = v6.load_all_questions()
    print(f"v10c 诊断 | 直接喂·无循环 | multi={MULTI_TOP_N} 其余={BASE_TOP_N} | {MODEL}(关思考)\n")

    rows, sum_i, sum_o = [], 0, 0
    for i, q in enumerate(questions, 1):
        qid, fmt = q["qid"], q.get("answer_format")
        top_n = MULTI_TOP_N if fmt == "multi" else BASE_TOP_N
        try:
            docs = build_docs(q, top_n)
            raw, itok, otok = ask(client, v6.build_prompt(q, docs))
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

    budget = 5_000_000
    tscore = max(0, min(1, (budget - (sum_i + sum_o)) / budget))
    print("\n" + "=" * 48)
    print(f"✅ 已写出 {out}")
    print(f"   空答案: {sum(1 for r in rows if not r[1])}")
    print(f"   总token: in={sum_i} out={sum_o} total={sum_i + sum_o}  TokenScore≈{tscore:.4f}")
    print(f"   下一步: ./.venv/bin/python my_benchmark.py {OUT_CSV}")
    print("=" * 48)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

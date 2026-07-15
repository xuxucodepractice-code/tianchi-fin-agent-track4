"""
v11 —— v10 基础上【打开思考】，追回 v9 靠"敢多选治漏选"多拿的那 5.5 分。

对照基线：v10（run_v10_qwen37.py，qwen3.7-plus 关思考，线上 70.9071）。
本版相对 v10 **只改一个变量：思考开/关**。
  - v10: enable_thinking=False → out≈1、保守、多选题滑回漏选
  - v11: enable_thinking=True  → 模型"想一想再答"，敢把漏掉的选项补回（冒烟已验证 fc_a_009 补回D、fin_a_014 补回A）
方法本身不变：multi TOP_N=24、mcq/tf TOP_N=8，检索/prompt/后处理全沿用 v6/v9/v10。

模型：qwen3.6-plus（Qwen系列、合规、可正式提交；qwen3.7-plus 免费额度已耗尽故换此）。
思考模型 out 会涨（冒烟 out≈1400~2300/multi题），给足 max_tokens 防截断。
额度耗尽的题由 fill_empty_v11.py 用 qwen-plus（同样开思考）补空。
"""
import os
import csv
from pathlib import Path

from openai import OpenAI
import run_v6_retrieval as v6
import run_v10_qwen37 as v10   # 复用 build_docs / MULTI_TOP_N / BASE_TOP_N

MODEL = "qwen3.6-plus"        # 思考模型，Qwen系列合规
BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
MAX_TOKENS = 8192             # 开思考后 out 大：给足防截断（冒烟最高 out≈2300）
OUT_CSV = "answer_v11.csv"


def make_client() -> OpenAI:
    return OpenAI(api_key=os.environ["DASHSCOPE_API_KEY"], base_url=BASE_URL)


def ask_thinking(client: OpenAI, prompt: str):
    """qwen3.6-plus，开思考（enable_thinking=True），返回 (答案文本, in_tok, out_tok)。"""
    r = client.chat.completions.create(
        model=MODEL, max_tokens=MAX_TOKENS,
        messages=[{"role": "user", "content": prompt}],
        extra_body={"enable_thinking": True},
    )
    txt = (r.choices[0].message.content or "").strip()
    return txt, r.usage.prompt_tokens, r.usage.completion_tokens


def main() -> int:
    if not os.environ.get("DASHSCOPE_API_KEY"):
        print("❌ 没读到 DASHSCOPE_API_KEY"); return 1
    client = make_client()
    questions = v6.load_all_questions()
    print(f"v11 开思考 | multi={v10.MULTI_TOP_N} mcq/tf={v10.BASE_TOP_N} | {MODEL}(思考ON)\n")

    rows, sum_i, sum_o = [], 0, 0
    for i, q in enumerate(questions, 1):
        qid, fmt = q["qid"], q.get("answer_format")
        top_n = v10.MULTI_TOP_N if fmt == "multi" else v10.BASE_TOP_N
        try:
            docs = v10.build_docs(q, top_n)
            raw, itok, otok = ask_thinking(client, v6.build_prompt(q, docs))
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
    print("\n" + "=" * 44)
    print(f"✅ 已写出 {out}")
    print(f"   空答案: {sum(1 for r in rows if not r[1])}")
    print(f"   总token: in={sum_i} out={sum_o} total={sum_i + sum_o}  TokenScore≈{tscore:.4f}")
    print(f"   下一步: 若有空→ ./.venv/bin/python fill_empty_v11.py ；否则 compare_to_reference.py {OUT_CSV}")
    print("=" * 44)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

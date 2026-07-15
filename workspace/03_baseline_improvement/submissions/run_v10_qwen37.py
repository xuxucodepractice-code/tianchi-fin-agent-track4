"""
v10 —— 把 v9 验证成功的"多选题多喂证据"方案，落地成【可正式提交的 Qwen 版】。

背景：v9(网关 deepseek-v4-pro, multi top24) 线上 76.45，验证了"多选题高TOP_N治漏选"方向，
      但 deepseek 非 Qwen，不能正式提交。本版换成 qwen3.7-plus（Qwen系列、合规、100万免费额度未动过）复现该方案。

相对 v9 的改动【只有一处】：模型/接口 deepseek-v4-pro(百度网关) → qwen3.7-plus（阿里百炼 OpenAI 兼容接口）。
方法本身原样复现 v9：multi TOP_N=24（治漏选，v9 的核心改进点），mcq/tf TOP_N=8，检索/prompt/后处理全沿用。
—— 目的就是"只换 API"，把 v9 验证过的方案落地成可正式提交的 Qwen 版，不动方法。

额度说明：top24 全量约 126万 input，超 qwen3.7-plus 免费额度(100万)约 26万（超出部分走付费）。
         但打分 token 预算是 500万，126万仅占 25%，分数无碍；且"用 token 换准确率"是本项目铁律，
         不为省额度削弱方法（那会削掉 v9 相对 v6 的改进本身）。

关键点：qwen3.7-plus 是推理模型，但 extra_body={'enable_thinking': False} 可关思考，
       关掉后 out token≈1、直接吐答案 → 没有 v9 那种"思考吃光 max_tokens 导致空答案"的坑。
"""
import os
import csv
from pathlib import Path

from openai import OpenAI
import run_v6_retrieval as v6

MULTI_TOP_N = 24          # 多选题：高 TOP_N 治漏选（原样复现 v9，不动方法）
BASE_TOP_N = 8            # mcq/tf：保持 v6/v9 基线
MODEL = "qwen3.7-plus"    # Qwen 系列，合规，可正式提交
BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
MAX_TOKENS = 512          # 关思考后 out≈1，512 绰绰有余
OUT_CSV = "answer_v10.csv"


def make_client() -> OpenAI:
    return OpenAI(api_key=os.environ["DASHSCOPE_API_KEY"], base_url=BASE_URL)


def ask_qwen37(client: OpenAI, prompt: str):
    """qwen3.7-plus，关思考（enable_thinking=False），返回 (答案文本, in_tok, out_tok)。"""
    r = client.chat.completions.create(
        model=MODEL, max_tokens=MAX_TOKENS,
        messages=[{"role": "user", "content": prompt}],
        extra_body={"enable_thinking": False},
    )
    txt = (r.choices[0].message.content or "").strip()
    return txt, r.usage.prompt_tokens, r.usage.completion_tokens


def build_docs(q: dict, top_n: int) -> dict:
    """按题型指定的 top_n 检索每份文档（临时改 v6.TOP_N，与 v9 同法）。"""
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
    print(f"v10 分治TOP_N | multi={MULTI_TOP_N} mcq/tf={BASE_TOP_N} | {MODEL}(关思考)\n")

    rows, sum_i, sum_o = [], 0, 0
    for i, q in enumerate(questions, 1):
        qid, fmt = q["qid"], q.get("answer_format")
        top_n = MULTI_TOP_N if fmt == "multi" else BASE_TOP_N
        try:
            docs = build_docs(q, top_n)
            raw, itok, otok = ask_qwen37(client, v6.build_prompt(q, docs))
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
    print(f"   下一步: ./.venv/bin/python compare_to_reference.py {OUT_CSV}")
    print("=" * 44)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

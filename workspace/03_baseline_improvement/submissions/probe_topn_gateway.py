"""
TOP_N 验证 · 百度网关(deepseek-v4-pro)版 —— 主要目的：拿真实 token 用量做参考。

逻辑同 probe_topn_missing.py（那版用 Qwen），本版改成走百度 comate 网关调 deepseek-v4-pro。
跑同一批典型"漏选"题、同样 TOP_N=[8,16,24]，和 Claude 参考答案比，
额外重点：打印每题/每档的真实 token（in/out），因为网关模型是推理模型，out 会偏高。

注意：本脚本仅用于本地验证方向 + 看 token，deepseek 答案不作为正式提交（提交用 Qwen）。
"""
import os
import csv
from pathlib import Path

import anthropic
import run_v6_retrieval as v6

SAMPLE_QIDS = ["fc_a_009", "fc_a_017", "fin_a_002", "fin_a_007", "fin_a_009", "fin_a_016"]
TOPN_GRID = [8, 16, 24]
MODEL = "deepseek-v4-pro"
MAX_TOKENS = 512   # 推理模型：给小了会被思考吃光返回空


def make_client():
    return anthropic.Anthropic(
        base_url=os.environ["ANTHROPIC_BASE_URL"],
        auth_token=os.environ.get("ANTHROPIC_AUTH_TOKEN") or os.environ["ANTHROPIC_API_KEY"],
    )


def load_ref() -> dict:
    ref = {}
    p = Path(__file__).parent / "reference_claude.csv"
    for r in csv.reader(p.open(encoding="utf-8")):
        if r and r[0] not in ("qid",):
            ref[r[0]] = r[1]
    return ref


def ask_gw(client, prompt: str):
    r = client.messages.create(
        model=MODEL, max_tokens=MAX_TOKENS,
        messages=[{"role": "user", "content": prompt}],
    )
    txt = "".join(b.text for b in r.content if b.type == "text").strip()
    return txt, r.usage.input_tokens, r.usage.output_tokens


def answer_at_topn(client, q: dict, top_n: int):
    old = v6.TOP_N
    v6.TOP_N = top_n
    try:
        docs_text = {}
        for d in q.get("doc_ids", []):
            full = v6.read_doc_text(q["domain"], d)
            docs_text[d] = v6.build_doc_text_for_question(q, d, full)
        raw, itok, otok = ask_gw(client, v6.build_prompt(q, docs_text))
        return v6.normalize_answer(raw, q.get("answer_format")), itok, otok
    finally:
        v6.TOP_N = old


def main() -> int:
    if not (os.environ.get("ANTHROPIC_AUTH_TOKEN") or os.environ.get("ANTHROPIC_API_KEY")):
        print("❌ 没读到网关 key"); return 1
    client = make_client()
    ref = load_ref()
    all_q = {q["qid"]: q for q in v6.load_all_questions()}

    print(f"网关模型 {MODEL} | {len(SAMPLE_QIDS)} 道漏选题 | TOP_N={TOPN_GRID}\n")
    header = f"{'qid':<11}" + "".join(f"top{n:<9}" for n in TOPN_GRID) + "Claude"
    print(header); print("-" * len(header))

    sum_in, sum_out = 0, 0
    match = {n: 0 for n in TOPN_GRID}
    tok_by_topn = {n: [0, 0] for n in TOPN_GRID}   # n -> [in, out]
    for qid in SAMPLE_QIDS:
        q = all_q[qid]
        cells = []
        for n in TOPN_GRID:
            ans, itok, otok = answer_at_topn(client, q, n)
            cells.append(f"{ans or '空'}({itok}+{otok})")
            sum_in += itok; sum_out += otok
            tok_by_topn[n][0] += itok; tok_by_topn[n][1] += otok
            if ans == ref.get(qid):
                match[n] += 1
        print(f"{qid:<11}" + "".join(f"{c:<12}" for c in cells) + f"{ref.get(qid,'?')}")

    print("-" * len(header))
    print("各 TOP_N 命中 Claude 参考题数 + 该档总token：")
    for n in TOPN_GRID:
        i, o = tok_by_topn[n]
        print(f"  top{n:<3}: 命中 {match[n]}/{len(SAMPLE_QIDS)}  |  6题 in={i} out={o} (单题均≈{(i+o)//len(SAMPLE_QIDS)})")
    print(f"\n全部总 token：in={sum_in} out={sum_out} total={sum_in+sum_out}")
    print("解读：命中随TOP_N升→'多喂证据治漏选'再验证；token列供你判断网关模型单题成本")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

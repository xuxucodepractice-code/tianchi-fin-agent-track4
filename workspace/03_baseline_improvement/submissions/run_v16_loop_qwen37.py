"""
v16 —— 把 v15 的 agent 循环(直接喂检索段 + 自检 + 定向补查)原样搬到【合规可提交的 qwen3.7-plus】。

背景链条：
  - v15(网关 deepseek·直接喂+循环) 本地 73%(tf治到85%)，唯一硬伤 = 370万 token。
  - 一路验证掉了 BM25置信度门控/BM25反向漏选(信号太弱)、logprobs(qwen-plus额度不够+单字母场景受限)。
  - 实测 qwen3.7-plus 现可调用(账户余额生效)，它正是 v10 跑出 77%/70.91 的强模型，多选能力强。

本版定位：**先只换模型这一个变量**(网关 deepseek-v4-pro → qwen3.7-plus)，方法(直接喂+自检+补查+MAX_ROUNDS=2)
  原样复用 v15，暂不做增量喂。目的 = 拿到「强模型 + agent循环」的干净基线分，再在其上加增量喂省 token(v17)。

相对 v15 只改一处：模型/接口。
  - v15: v9.ask_gw(anthropic SDK, deepseek-v4-pro 网关)
  - v16: ask_qwen37(openai SDK, qwen3.7-plus, enable_thinking=False 关思考→out极小无空答案坑)
  自检 prompt(v14.build_selfcheck_prompt)、解析(v14.parse_selfcheck)、定向补查(v14.supplementary_retrieve,纯BM25)、
  循环骨架(v15.agent_solve 的结构)全部照搬。

合规：纯 Qwen 答题 + 纯 BM25 检索/补查，无 embedding、无小模型、不联网。可正式提交。
"""
import os
import csv
from pathlib import Path

from openai import OpenAI
import run_v6_retrieval as v6
import run_v9_multi_topn as v9        # build_docs
import run_v14_agent_loop as v14      # build_selfcheck_prompt / parse_selfcheck / supplementary_retrieve

MULTI_TOP_N = 24
BASE_TOP_N = 8
MODEL = "qwen3.7-plus"                # Qwen系列，合规可提交，v10验证过的强模型
BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
MAX_TOKENS = 512                      # 关思考后 out≈1~几字母，512 足够
MAX_ROUNDS = 2
OUT_CSV = "answer_v16.csv"


def make_client() -> OpenAI:
    return OpenAI(api_key=os.environ["DASHSCOPE_API_KEY"], base_url=BASE_URL)


def ask_qwen37(client: OpenAI, prompt: str):
    """qwen3.7-plus 关思考。返回 (答案文本, in_tok, out_tok)。替代 v15 里的 v9.ask_gw。"""
    r = client.chat.completions.create(
        model=MODEL, max_tokens=MAX_TOKENS,
        messages=[{"role": "user", "content": prompt}],
        extra_body={"enable_thinking": False},
    )
    txt = (r.choices[0].message.content or "").strip()
    return txt, r.usage.prompt_tokens, r.usage.completion_tokens


def agent_solve(client, q: dict):
    """单题 agent 循环(直接喂地基版，同 v15，唯一区别=模型调用换成 ask_qwen37)。
    直接喂检索段答 → 自检 → (缺则补查→再答) × MAX_ROUNDS。返回 (答案, in累加, out累加, 补查轮数)。"""
    fmt = q.get("answer_format")
    top_n = MULTI_TOP_N if fmt == "multi" else BASE_TOP_N
    itok = otok = 0

    # --- 初答：检索(天然抽取式压缩) → 直接喂检索段答(v10式，无LLM压缩层) ---
    docs = v9.build_docs(q, top_n)
    raw, ai, ao = ask_qwen37(client, v6.build_prompt(q, docs))
    itok += ai; otok += ao
    ans = v6.normalize_answer(raw, fmt)

    evidence = "\n".join(f"【文档{d}】\n{t}" for d, t in docs.items())

    rounds = 0
    for _ in range(MAX_ROUNDS):
        # --- 自检(复用v14)：多选查漏选 / tf查复合句每半 / mcq查区分度 → {ok, missing} ---
        sc_raw, si, so = ask_qwen37(client, v14.build_selfcheck_prompt(q, evidence, ans))
        itok += si; otok += so
        ok, missing = v14.parse_selfcheck(sc_raw)
        if ok or not missing:
            break
        # --- 定向补查(复用v14，纯BM25)：缺口词在本题文档内再检索 → 追加证据 → 再答 ---
        supp = v14.supplementary_retrieve(q, missing)
        if not supp:
            break
        docs = {**docs, f"补查{rounds + 1}": supp}
        evidence = evidence + "\n\n【补查到的额外证据】\n" + supp
        raw, ai, ao = ask_qwen37(client, v6.build_prompt(q, docs))
        itok += ai; otok += ao
        ans = v6.normalize_answer(raw, fmt)
        rounds += 1

    return ans, itok, otok, rounds


def load_existing(path: Path) -> dict:
    """断点续跑：读已有 CSV 里【非空】的答案，重跑时跳过它们（防欠费中断后从头烧余额）。
    只跳过已答出字母的题；空题(上次欠费失败的)会重答。返回 qid->(ans,itok,otok)。"""
    done = {}
    if not path.exists():
        return done
    with path.open(encoding="utf-8") as f:
        for r in csv.reader(f):
            if not r or r[0] in ("qid", "summary"):
                continue
            if len(r) >= 5 and r[1].strip():   # 有非空答案
                try:
                    done[r[0]] = (r[1], int(r[2]), int(r[3]))
                except ValueError:
                    pass
    return done


def main() -> int:
    if not os.environ.get("DASHSCOPE_API_KEY"):
        print("❌ 没读到 DASHSCOPE_API_KEY"); return 1
    client = make_client()
    questions = v6.load_all_questions()
    out = Path(__file__).parent / OUT_CSV
    done = load_existing(out)
    if done:
        print(f"🔁 断点续跑：已有 {len(done)} 题答案，本次只跑剩下 {len(questions) - len(done)} 题\n")
    print(f"v16 强模型+agent循环 | 直接喂 | multi={MULTI_TOP_N} 其余={BASE_TOP_N} | 最多补{MAX_ROUNDS}轮 | {MODEL}(关思考)\n")

    rows = []
    sum_i = sum_o = 0
    total_rounds = 0
    for i, q in enumerate(questions, 1):
        qid, fmt = q["qid"], q.get("answer_format")
        if qid in done:                                  # 断点续跑：跳过已答题
            ans, itok, otok = done[qid]
            rows.append((qid, ans, itok, otok, itok + otok))
            sum_i += itok; sum_o += otok
            print(f"  [{i}/100] {qid} ({fmt}) -> {ans} | 已有(跳过)")
            continue
        try:
            ans, itok, otok, rounds = agent_solve(client, q)
        except Exception as e:
            print(f"  [{i}/100] {qid} ❌ {e}")
            ans, itok, otok, rounds = "", 0, 0, 0
        rows.append((qid, ans, itok, otok, itok + otok))
        sum_i += itok; sum_o += otok; total_rounds += rounds
        flag = f" [补{rounds}轮]" if rounds else ""
        print(f"  [{i}/100] {qid} ({fmt}) -> {ans or '空'} | tok {itok}+{otok}{flag}")

    with out.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["qid", "answer", "prompt_tokens", "completion_tokens", "total_tokens"])
        w.writerow(["summary", "", sum_i, sum_o, sum_i + sum_o])
        for r in rows:
            w.writerow(r)

    budget = 5_000_000
    tscore = max(0, min(1, (budget - (sum_i + sum_o)) / budget))
    print("\n" + "=" * 52)
    print(f"✅ 已写出 {out}")
    print(f"   空答案: {sum(1 for r in rows if not r[1])}")
    print(f"   触发补查总轮数: {total_rounds}")
    print(f"   总token: in={sum_i} out={sum_o} total={sum_i + sum_o}  TokenScore≈{tscore:.4f}  (对比 v15≈370万)")
    print(f"   下一步: ./.venv/bin/python my_benchmark.py {OUT_CSV}")
    print("=" * 52)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

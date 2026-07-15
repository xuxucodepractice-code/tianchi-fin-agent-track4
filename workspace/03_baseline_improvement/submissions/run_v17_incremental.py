"""
v17 —— v16 + 增量喂（治 v16 的 token 522万超预算，方法/模型全不变，只改"每步喂多少字"）。

v16 证明了：qwen3.7-plus + 自检补查循环 → 准确率 77%(multi 80%，全场最高、追平v10天花板)。
唯一硬伤：循环里【全段证据被重复喂 2~3 次】(初答喂全段 + 自检又喂全段 + 补查再答又喂全段+新段)，
token 顶到 522万超500万预算、TokenScore=0、系数触底0.70 → 估分反比v10低16分。

★关键前提★：比赛 TokenScore 按"喂进去的token总量"算，API缓存省钱但token照计、TokenScore不变。
  所以必须【真正少喂】。而"自检"若单独发一次调用就必须重喂证据(模型跨调用无记忆)→ 唯一省法=合并。

增量喂两刀(都不改循环决策/补查逻辑，只改喂什么，理论零准确率风险；merge自检有小偏差风险，靠benchmark验)：
  ① 【答题+自检合并成一次调用】：喂全段证据一次 → 同时输出 {答案, 缺口missing}。
     —— 全段证据只喂这一次(v16是初答+自检各喂一次=两次)。
  ② 【补查再答只喂增量】：只喂 "上一轮答案 + 新补的那几段"，不重喂旧全段。
     —— v16再答喂"全段+新段"，v17只喂"结论+新段"。

循环骨架、MAX_ROUNDS=2、定向补查(v14.supplementary_retrieve 纯BM25)、检索(multi top24)全部不变。
模型 qwen3.7-plus(同v16，合规可提交)。带断点续跑(同v16，防欠费)。

相对 v16 唯一变量：喂给模型的文本量(合并答题+自检、再答只喂增量)。准确率应≈v16的77%，token应↓到~130万量级。
"""
import os
import re
import csv
import json
from pathlib import Path

from openai import OpenAI
import run_v6_retrieval as v6
import run_v9_multi_topn as v9        # build_docs
import run_v14_agent_loop as v14      # supplementary_retrieve（纯BM25定向补查）

MULTI_TOP_N = 24
BASE_TOP_N = 8
MODEL = "qwen3.7-plus"
BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
MAX_TOKENS = 512
MAX_ROUNDS = 2
OUT_CSV = "answer_v17.csv"


def make_client() -> OpenAI:
    return OpenAI(api_key=os.environ["DASHSCOPE_API_KEY"], base_url=BASE_URL)


def ask_qwen37(client: OpenAI, prompt: str):
    r = client.chat.completions.create(
        model=MODEL, max_tokens=MAX_TOKENS,
        messages=[{"role": "user", "content": prompt}],
        extra_body={"enable_thinking": False},
    )
    txt = (r.choices[0].message.content or "").strip()
    return txt, r.usage.prompt_tokens, r.usage.completion_tokens


def _fmt_rule(fmt: str) -> str:
    return {
        "mcq": "单选题，answer 填一个大写字母，如 A。",
        "multi": "多选题，answer 填所有正确选项大写字母、升序无分隔，如 BC。",
        "tf": "判断题，answer 填一个大写字母 A 或 B。",
    }.get(fmt, "answer 填选项大写字母。")


def build_answer_selfcheck_prompt(q: dict, evidence: str) -> str:
    """刀①：答题+自检【合并一次调用】——喂全段证据(仅此一次)，同时输出答案和证据缺口。"""
    fmt = q.get("answer_format")
    parts = ["以下是从参考文档检索出的相关段落：\n", evidence]
    parts.append(f"\n问题：{q['question']}\n选项：")
    for k, val in q.get("options", {}).items():
        parts.append(f"{k}. {val}")
    parts.append(f"\n请分两步：\n第一步 作答：{_fmt_rule(fmt)}")
    parts.append("第二步 自检证据缺口：")
    if fmt == "multi":
        parts.append("- 逐个【未选选项】检查：它是不是因为上面段落里根本没提到（证据被漏），而非真的错？")
        parts.append("  找不到任何相关信息的未选选项，很可能是「证据被漏」，把它的关键词列入 missing 该去补查。")
    elif fmt == "tf":
        parts.append("- 若题干由多个子事实用「且/而/同时/并」连接，每个子事实都必须在段落里有证据；")
        parts.append("  某个子事实段落里没提到的，把它的关键词列入 missing 该去补查。")
    else:
        parts.append("- 若几个选项都缺明确证据、难以区分，把难区分选项的关键词列入 missing 该去补查。")
    parts.append("\n严格输出 JSON（不要多余文字）：")
    parts.append('{"answer": "选项字母", "missing": ["证据充分则空数组；否则列该去原文补查的关键词/实体2-5个"]}')
    return "\n".join(parts)


def build_reanswer_incremental_prompt(q: dict, prev_ans: str, supp: str) -> str:
    """刀②：补查再答【只喂增量】——只喂 上一轮答案 + 新补的段，不重喂旧全段。"""
    fmt = q.get("answer_format")
    parts = [f"你上一轮对下面这道题的答案是：{prev_ans or '(空)'}"]
    parts.append("现在补查到一批【新的额外证据】，请结合它复查并给出最终答案（可补充/修正上一轮答案）：\n")
    parts.append(supp)
    parts.append(f"\n问题：{q['question']}\n选项：")
    for k, val in q.get("options", {}).items():
        parts.append(f"{k}. {val}")
    parts.append(f"\n请分两步：\n第一步 作答：{_fmt_rule(fmt)}")
    parts.append("第二步 自检：若仍有未选选项/子事实缺证据，把其关键词列入 missing；否则 missing 空数组。")
    parts.append("\n严格输出 JSON（不要多余文字）：")
    parts.append('{"answer": "选项字母", "missing": ["仍缺证据的关键词，充分则空"]}')
    return "\n".join(parts)


def parse_ans_missing(raw: str, fmt: str):
    """解析合并调用返回的 {answer, missing}。解析失败退回：从原文抽字母当答案、missing空(不补查)。"""
    m = re.search(r"\{.*\}", raw, re.DOTALL)
    if m:
        try:
            obj = json.loads(m.group(0))
            ans = v6.normalize_answer(str(obj.get("answer", "")), fmt)
            missing = [str(x) for x in obj.get("missing", []) if str(x).strip()]
            return ans, missing
        except Exception:
            pass
    return v6.normalize_answer(raw, fmt), []


def agent_solve(client, q: dict):
    """v17 单题循环：答题+自检合并(全段喂1次) → 缺则补查 → 再答只喂增量。返回(答案,in,out,轮数)。"""
    fmt = q.get("answer_format")
    top_n = MULTI_TOP_N if fmt == "multi" else BASE_TOP_N
    itok = otok = 0

    docs = v9.build_docs(q, top_n)
    evidence = "\n".join(f"【文档{d}】\n{t}" for d, t in docs.items())

    # 刀①：答题+自检合并一次（全段证据仅此一次）
    raw, i0, o0 = ask_qwen37(client, build_answer_selfcheck_prompt(q, evidence))
    itok += i0; otok += o0
    ans, missing = parse_ans_missing(raw, fmt)

    rounds = 0
    for _ in range(MAX_ROUNDS):
        if not missing:
            break
        supp = v14.supplementary_retrieve(q, missing)
        if not supp:
            break
        # 刀②：再答只喂增量（上一轮答案 + 新补段，不重喂旧全段）
        raw, ai, ao = ask_qwen37(client, build_reanswer_incremental_prompt(q, ans, supp))
        itok += ai; otok += ao
        ans, missing = parse_ans_missing(raw, fmt)
        rounds += 1

    return ans, itok, otok, rounds


def load_existing(path: Path) -> dict:
    """断点续跑（同 v16）：读已有 CSV 非空答案，重跑时跳过；空题重答。"""
    done = {}
    if not path.exists():
        return done
    with path.open(encoding="utf-8") as f:
        for r in csv.reader(f):
            if not r or r[0] in ("qid", "summary"):
                continue
            if len(r) >= 5 and r[1].strip():
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
        print(f"🔁 断点续跑：已有 {len(done)} 题，本次只跑 {len(questions) - len(done)} 题\n")
    print(f"v17 增量喂 | 答题+自检合并·再答喂增量 | multi={MULTI_TOP_N} 其余={BASE_TOP_N} | 最多补{MAX_ROUNDS}轮 | {MODEL}\n")

    rows, sum_i, sum_o, total_rounds = [], 0, 0, 0
    for i, q in enumerate(questions, 1):
        qid, fmt = q["qid"], q.get("answer_format")
        if qid in done:
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
    print(f"   总token: in={sum_i} out={sum_o} total={sum_i + sum_o}  TokenScore≈{tscore:.4f}  (对比 v16=522万)")
    print(f"   下一步: ./.venv/bin/python my_benchmark.py {OUT_CSV}")
    print("=" * 52)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

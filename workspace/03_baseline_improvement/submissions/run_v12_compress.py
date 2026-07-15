"""
v12 —— 压缩 Agent 第一版（定位 → 压缩 → 答题，三步）。

这是路线转向后的新方向：主攻比赛核心"动态记忆压缩"（队友做逐选项判断，我做压缩，不重复）。
相对 v9/v10 的根本区别：不再把检索到的段落【直接】喂给模型答题，而是中间insert一层"压缩"：
  第1步 定位：BM25 检索出候选段（复用 v6，不烧 token）
  第2步 压缩：让模型把候选段读成一份【结构化要点笔记】（相关数据/关键条款/关键结论），几千字→几百字
  第3步 答题：只基于这份短笔记推理作答（不再看原始长段）

★实验设计（干净归因）★：v12 和 v9 从【同一批检索段】出发（multi top24 / 其余 top8），
  唯一差别 = 中间多了"压缩"这一层。于是能直接对比：
    - 准确率：压缩后有没有掉/涨（压缩会不会丢关键信息）
    - token：压缩烧的 token（第2步）vs 答题省下的 token（第3步喂得少），净赚还是净亏

⚠️ 官方计分规则：压缩这步的 token 也【计入】总量（scoring 文档明列"上下文压缩"）。
   所以 v12 记录 compress_tok + answer_tok 全部，评判"压缩是否划算"要看净 token。

模型：deepseek-v4-pro（百度网关，开发验证用；最终落地再切 Qwen）。是推理模型，给足 max_tokens。
"""
import os
import csv
from pathlib import Path

import run_v6_retrieval as v6
import run_v9_multi_topn as v9   # 复用 make_client / ask_gw / build_docs / TOP_N 分治

MULTI_TOP_N = 24     # 候选段深度：和 v9 一致（同一批证据出发，才好归因）
BASE_TOP_N = 8
MAX_TOKENS = 8192    # 推理模型，压缩和答题都给足防截断（冒烟发现给4096时压缩会被思考吃光→空笔记）
OUT_CSV = "answer_v12.csv"


def build_compress_prompt(question: dict, docs_text: dict) -> str:
    """第2步：让模型把候选段压成结构化要点笔记（query-aware：围绕本题压）。"""
    parts = ["你是金融文档分析助手。下面是从参考文档中检索出的候选段落，可能含大量与本题无关的内容。\n"]
    parts.append("请【只保留与回答本题相关的信息】，压缩成一份简短的结构化要点笔记，丢弃无关内容。\n")
    parts.append("笔记格式（无相关内容的栏目写“无”）：")
    parts.append("【相关数据】：与题目/选项相关的数字、比例、金额、日期、期限等（务必原样保留数字，不得改动）")
    parts.append("【关键条款/规则】：相关的条款号、规定、定义、条件")
    parts.append("【关键结论/事实】：与判断选项正误直接相关的事实陈述\n")
    parts.append(f"问题：{question['question']}")
    parts.append("选项：")
    for k, val in question.get("options", {}).items():
        parts.append(f"{k}. {val}")
    parts.append("\n候选段落：")
    for doc_id, text in docs_text.items():
        parts.append(f"【文档{doc_id}】\n{text}\n")
    parts.append("\n请直接输出要点笔记，尽量简短，不要复述原文，不要回答题目本身。")
    return "\n".join(parts)


def build_answer_from_notes_prompt(question: dict, notes: str) -> str:
    """第3步：只基于压缩笔记答题（不再看原文）。答题格式与 v6 一致。"""
    fmt_rule = {
        "mcq": "这是单选题，只回复一个大写字母，如 A。",
        "multi": "这是多选题，回复所有正确选项的大写字母，按字母升序、无分隔符，如 BC。",
        "tf": "这是判断题，只回复一个大写字母 A 或 B。",
    }.get(question.get("answer_format"), "只回复选项大写字母。")

    parts = ["以下是从参考文档压缩出的要点笔记：\n"]
    parts.append(notes)
    parts.append(f"\n问题：{question['question']}\n选项：")
    for k, val in question.get("options", {}).items():
        parts.append(f"{k}. {val}")
    parts.append(f"\n要求：{fmt_rule} 只输出答案本身，不要解释。")
    return "\n".join(parts)


def main() -> int:
    if not (os.environ.get("ANTHROPIC_AUTH_TOKEN") or os.environ.get("ANTHROPIC_API_KEY")):
        print("❌ 没读到网关 key"); return 1
    client = v9.make_client()
    v9.MAX_TOKENS = MAX_TOKENS   # 关键：ask_gw 内部用 v9.MAX_TOKENS，覆盖成 v12 的 8192 防压缩被思考截断
    questions = v6.load_all_questions()
    print(f"v12 压缩Agent | 候选 multi={MULTI_TOP_N} 其余={BASE_TOP_N} | 网关 {v9.MODEL}\n")

    rows = []
    sum_ci = sum_co = sum_ai = sum_ao = 0
    for i, q in enumerate(questions, 1):
        qid, fmt = q["qid"], q.get("answer_format")
        top_n = MULTI_TOP_N if fmt == "multi" else BASE_TOP_N
        try:
            docs = v9.build_docs(q, top_n)                       # 第1步 定位
            notes, ci, co = v9.ask_gw(client, build_compress_prompt(q, docs))   # 第2步 压缩
            # 兜底：压缩返回空（推理模型思考吃光/无相关内容）→ 退回用原候选段答，不让笔记为空导致瞎猜
            if len(notes.strip()) < 10:
                notes = "\n".join(f"【文档{d}】\n{t}" for d, t in docs.items())
                print(f"      ⚠️ {qid} 压缩为空，退回原候选段答题")
            raw, ai, ao = v9.ask_gw(client, build_answer_from_notes_prompt(q, notes))  # 第3步 答题
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
    print(f"   总 token: {total}  (对比 v9≈131万 / v10≈132万)")
    print(f"   下一步: ./.venv/bin/python my_benchmark.py {OUT_CSV}")
    print("=" * 52)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

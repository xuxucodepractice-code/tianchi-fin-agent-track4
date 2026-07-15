"""
v14 —— 真正的 agent 推理循环（Self-RAG 自检 + CRAG 定向补查）。

路线转折：v12/v13 全在"调压缩prompt"，流程始终是单步直线，没有 agent 推理。v14 第一次给流程
加"自检→补查→修正"循环，让它成为会回头检查、发现证据不足会自己再查的 agent。这既治压缩丢证据
的病（多选漏选 / tf复合句翻错=同一个病：分散证据被删），又是 B榜换题也能泛化的通用推理能力。

理论支撑（改进策略.md 第14节）：
  - Self-RAG(arXiv:2310.11511)：模型边答边自检 relevance/support，retrieve-on-demand。
  - CRAG(arXiv:2401.15884)：检索评估器判信心，不合格触发纠错式补查。
  合规实现：不训练模型、不用小模型、不联网、无 embedding —— 纯 prompt 让 Qwen 自检 + 在给定文档内 BM25 补查。

相对 v13b（question-aware 压缩，multi 治漏选最好那版）唯一新增：答完后的【自检→定向补查→再答】循环。

agent 循环（每题）：
  1. 检索(BM25, v6) → question-aware 压缩(v13b 式笔记) → 答一次        [初答]
  2. 自检：让模型审自己的答案——多选是否可能漏选？tf复合句每一半都有证据吗？→ 输出 OK / 缺口关键词
  3. 若有缺口：把缺口关键词在同一批文档里 BM25 再查 → 补进笔记 → 再答     [修正]
  4. 最多 MAX_ROUNDS 轮，收敛(自检说OK)或到上限即定答

模型：deepseek-v4-pro（开发期网关）。token 会因多轮上升，现阶段先不管（用户已确认）。
"""
import os
import re
import csv
import json
from pathlib import Path

import run_v6_retrieval as v6
import run_v9_multi_topn as v9      # make_client / ask_gw / build_docs / TOP_N 分治
import run_v12_compress as v12      # build_answer_from_notes_prompt（基于笔记答）
import run_v13b_qaware as v13b      # build_compress_prompt（question-aware 压缩）

MULTI_TOP_N = 24
BASE_TOP_N = 8
MAX_TOKENS = 8192
MAX_ROUNDS = 2        # 自检→补查最多补 2 轮（防死循环；0轮=退回v13b）
SUPP_TOP_N = 6        # 每次定向补查，为缺口关键词额外检索的段数
OUT_CSV = "answer_v14.csv"


def build_selfcheck_prompt(question: dict, notes: str, cur_ans: str) -> str:
    """自检：让模型审自己的初答，找证据缺口（Self-RAG 的 support 批判 + 题型专项）。

    输出严格 JSON：{"ok": bool, "missing": ["缺口关键词", ...]}
      ok=true  → 证据充分、答案可信，停止补查
      ok=false → 有选项/子事实缺证据，missing 列出该去补查的关键词
    """
    fmt = question.get("answer_format")
    parts = ["你是严谨的金融答案审查员。下面是某道题、已有的证据笔记、以及初步答案。"]
    parts.append("请审查：**初步答案是否有「证据不足」的风险**，需要回原文补查更多证据。\n")
    if fmt == "multi":
        parts.append("这是【多选题】，重点审查【漏选】：逐个选项检查——")
        parts.append("- 已选的选项，笔记里是否真有支持证据？")
        parts.append("- **未选的选项，是不是因为笔记里根本没提到它（证据被漏掉），而非真的错？**")
        parts.append("  若某个未选选项在笔记里找不到任何相关信息，它很可能是「证据被漏」，应补查。")
    elif fmt == "tf":
        parts.append("这是【判断题】，重点审查【复合陈述】：题干若由多个子事实用「且/而/同时/并」连接，")
        parts.append("**每一个子事实都必须在笔记里有对应证据**。若某个子事实笔记里没提到，不能凭空判错，应补查。")
    else:
        parts.append("这是【单选题】：检查所选选项是否有明确证据支持；若几个选项都缺证据难以区分，应补查。")
    parts.append("\n【问题】" + question["question"])
    parts.append("【选项】")
    for k, val in question.get("options", {}).items():
        parts.append(f"{k}. {val}")
    parts.append("\n【已有证据笔记】\n" + notes)
    parts.append(f"\n【初步答案】{cur_ans or '(空)'}")
    parts.append("\n请严格输出 JSON（不要多余文字）：")
    parts.append('{"ok": true 或 false, "missing": ["若ok=false，列出该去原文补查的关键词/实体/子事实，2-5个；ok=true则空数组"]}')
    parts.append("判断标准：证据确实足以支撑答案→ok=true；有选项/子事实明显缺证据→ok=false并给missing。")
    return "\n".join(parts)


def parse_selfcheck(raw: str):
    """从自检返回里解析 {ok, missing}。解析失败→保守当作 ok=true(不补查，避免乱补)。"""
    m = re.search(r"\{.*\}", raw, re.DOTALL)
    if not m:
        return True, []
    try:
        obj = json.loads(m.group(0))
        return bool(obj.get("ok", True)), [str(x) for x in obj.get("missing", []) if str(x).strip()]
    except Exception:
        return True, []


def supplementary_retrieve(question: dict, missing: list[str]) -> str:
    """定向补查：把缺口关键词当查询，在本题文档里 BM25 再检索 SUPP_TOP_N 段（CRAG 纠错式补证据）。

    合规：纯 BM25 关键词检索，无 embedding、无模型、不联网。只在本题给定 doc_ids 内查。
    """
    if not missing:
        return ""
    # 用缺口词作为关键词（加上题干抽的词一起，缺口词优先）
    kw = list(dict.fromkeys(missing + v6.extract_keywords(question)))
    old = v6.TOP_N
    v6.TOP_N = SUPP_TOP_N
    try:
        chunks = []
        for d in question.get("doc_ids", []):
            full = v6.read_doc_text(question["domain"], d)
            segs = v6.split_segments(full)
            hit = v6.retrieve_segments(segs, kw)
            if hit:
                chunks.append(f"【文档{d}·补查】\n{hit}")
        return "\n".join(chunks)
    finally:
        v6.TOP_N = old


def agent_solve(client, q: dict):
    """单题 agent 循环：初答 → 自检 → (缺则补查→再答) × MAX_ROUNDS。返回 (答案, 各阶段token累加, 轮数)。"""
    fmt = q.get("answer_format")
    top_n = MULTI_TOP_N if fmt == "multi" else BASE_TOP_N
    itok = otok = 0

    # --- 初答：检索 → question-aware 压缩 → 答 ---
    docs = v9.build_docs(q, top_n)
    notes, ci, co = v9.ask_gw(client, v13b.build_compress_prompt(q, docs))
    itok += ci; otok += co
    if len(notes.strip()) < 10:
        notes = "\n".join(f"【文档{d}】\n{t}" for d, t in docs.items())
    raw, ai, ao = v9.ask_gw(client, v12.build_answer_from_notes_prompt(q, notes))
    itok += ai; otok += ao
    ans = v6.normalize_answer(raw, fmt)

    rounds = 0
    for _ in range(MAX_ROUNDS):
        # --- 自检 ---
        sc_raw, si, so = v9.ask_gw(client, build_selfcheck_prompt(q, notes, ans))
        itok += si; otok += so
        ok, missing = parse_selfcheck(sc_raw)
        if ok or not missing:
            break
        # --- 定向补查 → 补进笔记 → 再答 ---
        supp = supplementary_retrieve(q, missing)
        if not supp:
            break
        notes = notes + "\n\n【补查到的额外证据】\n" + supp
        raw, ai, ao = v9.ask_gw(client, v12.build_answer_from_notes_prompt(q, notes))
        itok += ai; otok += ao
        ans = v6.normalize_answer(raw, fmt)
        rounds += 1

    return ans, itok, otok, rounds


def main() -> int:
    if not (os.environ.get("ANTHROPIC_AUTH_TOKEN") or os.environ.get("ANTHROPIC_API_KEY")):
        print("❌ 没读到网关 key"); return 1
    client = v9.make_client()
    v9.MAX_TOKENS = MAX_TOKENS
    questions = v6.load_all_questions()
    print(f"v14 agent循环(自检+补查) | multi={MULTI_TOP_N} 其余={BASE_TOP_N} | 最多补{MAX_ROUNDS}轮 | 网关 {v9.MODEL}\n")

    rows = []
    sum_i = sum_o = 0
    total_rounds = 0
    for i, q in enumerate(questions, 1):
        qid, fmt = q["qid"], q.get("answer_format")
        try:
            ans, itok, otok, rounds = agent_solve(client, q)
        except Exception as e:
            print(f"  [{i}/100] {qid} ❌ {e}")
            ans, itok, otok, rounds = "", 0, 0, 0
        rows.append((qid, ans, itok, otok, itok + otok))
        sum_i += itok; sum_o += otok; total_rounds += rounds
        flag = f" [补{rounds}轮]" if rounds else ""
        print(f"  [{i}/100] {qid} ({fmt}) -> {ans or '空'} | tok {itok}+{otok}{flag}")

    out = Path(__file__).parent / OUT_CSV
    with out.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["qid", "answer", "prompt_tokens", "completion_tokens", "total_tokens"])
        w.writerow(["summary", "", sum_i, sum_o, sum_i + sum_o])
        for r in rows:
            w.writerow(r)

    print("\n" + "=" * 52)
    print(f"✅ 已写出 {out}")
    print(f"   空答案: {sum(1 for r in rows if not r[1])}")
    print(f"   触发补查的总轮数: {total_rounds}（越多说明agent越常发现证据不足去补）")
    print(f"   总token: in={sum_i} out={sum_o} total={sum_i + sum_o}  (对比 v13c≈150万)")
    print(f"   下一步: ./.venv/bin/python my_benchmark.py {OUT_CSV}")
    print("=" * 52)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

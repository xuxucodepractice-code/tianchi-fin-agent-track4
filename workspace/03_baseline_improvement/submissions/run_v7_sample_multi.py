"""
v7 采样探底 —— 只测前 N 道 multi 多选题的"逐选项审"，看两件事：
  1. 质量：每个选项判成 支持/否定/不确定 到底合不合理（人肉眼看）
  2. token：多选题逐项审的单题真实 token（验证全量额度够不够）
复用 run_v7_multi_perchoice 的逐选项逻辑，不改它；只打印，不写 csv、不碰 answer_v7.csv。
"""
import os, time
import run_v6_retrieval as v6
import run_v7_multi_perchoice as v7

SAMPLE_MULTI = 5


def main() -> int:
    api_key = os.environ.get("DASHSCOPE_API_KEY")
    if not api_key:
        print("❌ 没读到 DASHSCOPE_API_KEY"); return 1

    # v6 的答案，用来和 v7 逐项审的结果对照
    v6_ans = {}
    csv_path = v6.Path(__file__).parent / "answer_v6.csv"
    if csv_path.exists():
        import csv as _csv
        for r in _csv.reader(csv_path.open(encoding="utf-8")):
            if len(r) >= 2 and r[0] not in ("qid", "summary"):
                v6_ans[r[0]] = r[1]

    all_q = v6.load_all_questions()
    multi_q = [q for q in all_q if q.get("answer_format") == "multi"][:SAMPLE_MULTI]
    print(f"采样测 {len(multi_q)} 道 multi 多选题（v7 逐选项审），模型 {v6.MODEL}\n")

    sum_t, sum_calls = 0, 0
    for i, q in enumerate(multi_q, 1):
        qid, domain = q["qid"], q["domain"]
        docs_text = {}
        for d in q.get("doc_ids", []):
            full = v6.read_doc_text(domain, d)
            docs_text[d] = v6.build_doc_text_for_question(q, d, full)

        print(f"[{i}/{len(multi_q)}] {qid} ({domain})")
        print(f"    题干：{q['question'][:60]}...")
        picked, qtok, qcalls = [], 0, 0
        for key, opt_text in q.get("options", {}).items():
            verdict, p, c = v7.judge_one_option(api_key, q, docs_text, key, str(opt_text))
            qtok += p + c; qcalls += 1
            mark = "✅选" if verdict == "support" else "  "
            print(f"      {mark} {key}. {str(opt_text)[:32]:<34} -> {verdict}")
            if verdict == "support":
                picked.append(key)
            time.sleep(0.3)
        v7_answer = "".join(sorted(set(picked))) or "(零支持→兜底)"
        print(f"    v7逐项审 -> {v7_answer:<8} | v6一次问 -> {v6_ans.get(qid,'?')} | 本题tok {qtok} ({qcalls}次)\n")
        sum_t += qtok; sum_calls += qcalls

    avg = sum_t / len(multi_q) if multi_q else 0
    print("=" * 52)
    print(f"  {len(multi_q)}道多选题：总tok={sum_t} 总调用={sum_calls} 单题均值≈{avg:.0f}")
    print(f"  外推 65 道 multi ≈ {avg*65:.0f} token")
    print(f"  加 mcq/tf(约24万) ≈ 全量 {avg*65 + 240000:.0f} token")
    print(f"  单模型上限 100万 → {'✅ 够' if avg*65 + 240000 < 1_000_000 else '❌ 超额，需改一次调用逐项裁决'}")
    print("=" * 52)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

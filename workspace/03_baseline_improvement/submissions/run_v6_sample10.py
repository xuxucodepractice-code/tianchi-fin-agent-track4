"""
v6 采样探底 —— 只跑前 10 题，估算单题平均 token，判断 19万免费额度够不够跑满100题。
复用 run_v6_retrieval.py 的全部逻辑，不改动它；输出写到 answer_v6_sample10.csv，不碰 answer_v6.csv。
"""
import os, csv, time
from pathlib import Path
import run_v6_retrieval as v6

SAMPLE_N = 10
OUT = "answer_v6_sample10.csv"


def main() -> int:
    api_key = os.environ.get("DASHSCOPE_API_KEY")
    if not api_key:
        print("❌ 没读到 DASHSCOPE_API_KEY"); return 1

    questions = v6.load_all_questions()[:SAMPLE_N]
    print(f"采样跑前 {len(questions)} 题（v6 检索版），模型 {v6.MODEL}\n")

    rows, sum_t = [], 0
    for i, q in enumerate(questions, 1):
        qid, domain, fmt = q["qid"], q["domain"], q.get("answer_format")
        try:
            docs_text = {}
            for d in q.get("doc_ids", []):
                full = v6.read_doc_text(domain, d)
                docs_text[d] = v6.build_doc_text_for_question(q, d, full)
            answer_raw, ptok, ctok = v6.ask_qwen(api_key, v6.build_prompt(q, docs_text))
            answer = v6.normalize_answer(answer_raw, fmt)
        except Exception as e:
            print(f"  [{i}/{SAMPLE_N}] {qid} ❌ {e}"); answer, ptok, ctok = "", 0, 0
        ttok = ptok + ctok
        rows.append((qid, answer, ptok, ctok, ttok)); sum_t += ttok
        print(f"  [{i}/{SAMPLE_N}] {qid} ({domain}/{fmt}) -> {answer or '空'} | tok {ttok}")
        time.sleep(0.5)

    with (Path(__file__).parent / OUT).open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f); w.writerow(["qid","answer","prompt_tokens","completion_tokens","total_tokens"])
        for r in rows: w.writerow(r)

    avg = sum_t / len(rows) if rows else 0
    print("\n" + "="*44)
    print(f"  10题总token={sum_t}  单题均值≈{avg:.0f}")
    print(f"  外推100题≈{avg*100:.0f}  （免费额度剩约19万）")
    print(f"  结论：{'✅ 够跑满100题' if avg*100 < 190000 else '⚠️ 可能不够，需下调TOP_N或分批'}")
    print("="*44)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

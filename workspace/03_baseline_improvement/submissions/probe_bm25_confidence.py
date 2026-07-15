"""
probe_bm25_confidence.py —— 零成本验证：BM25 检索置信度 能不能当"要不要进循环"的路由信号？

不跑模型、不烧 token。只用 answer_v15.csv（已跑完的答案）+ reference_claude.csv（尺子）+ 现成检索代码。

思路：
  1. 对每题算一个"BM25 证据置信度分"——关键词在检索段里命中得越准越多，分越高（证据越充分）。
  2. 用这个分把 100 题排序，分成【高置信度批】和【低置信度批】。
  3. 看两批各自对 Claude 尺子的准确率：
     - 若 高置信度批准确率 >> 低置信度批 → BM25 分是好的路由信号，门控成立（高分题可跳过循环省token）。
     - 若 两批差不多 → BM25 分不是好信号，得换路由（如按题型）。
  4. 顺带看：v15 触发补查的题，是不是集中在低置信度批（那才说明循环用在了刀刃上）。

置信度分定义（纯 BM25，无 embedding、无模型）：
  对每题，取其所有 doc 的检索命中，算 top 段的 BM25 分之和 / 命中关键词覆盖率。
  为可比，做两种：cover=命中关键词占比；topscore=最高段BM25分。
"""
import csv
from pathlib import Path

import run_v6_retrieval as v6

HERE = Path(__file__).parent


def load_answers(path: Path) -> dict:
    ans = {}
    with path.open(encoding="utf-8") as f:
        for r in csv.reader(f):
            if not r or r[0] in ("qid", "summary"):
                continue
            ans[r[0]] = r[1] if len(r) > 1 else ""
    return ans


def bm25_confidence(q: dict, top_n: int):
    """算一题的 BM25 置信度：返回 (最高段分, 命中关键词覆盖率)。纯关键词，零 token。"""
    import math, re
    keywords = v6.extract_keywords(q)
    if not keywords:
        return 0.0, 0.0
    all_scores = []
    hit_kw = set()
    old = v6.TOP_N
    v6.TOP_N = top_n
    try:
        for d in q.get("doc_ids", []):
            full = v6.read_doc_text(q["domain"], d)
            segs = v6.split_segments(full)
            if not segs:
                continue
            norm = [s.lower() for s in segs]
            n = len(norm)
            df = {kw.lower(): sum(1 for s in norm if kw.lower() in s) for kw in keywords}
            for seg in norm:
                score = 0.0
                for kw in keywords:
                    k = kw.lower()
                    tf = seg.count(k)
                    if tf == 0 or df[k] == 0:
                        continue
                    hit_kw.add(k)
                    idf = math.log(1 + (n - df[k] + 0.5) / (df[k] + 0.5))
                    w = min(len(kw), 6)
                    if v6.is_numeric(kw):
                        w *= 3.0
                    score += w * idf * (tf * 2.2 / (tf + 1.2))
                if score > 0:
                    all_scores.append(score)
    finally:
        v6.TOP_N = old
    top_score = max(all_scores) if all_scores else 0.0
    cover = len(hit_kw) / len(set(k.lower() for k in keywords)) if keywords else 0.0
    return top_score, cover


def main():
    v15 = load_answers(HERE / "answer_v15.csv")
    ref = load_answers(HERE / "reference_claude.csv")
    questions = {q["qid"]: q for q in v6.load_all_questions()}
    fmt = {qid: q.get("answer_format") for qid, q in questions.items()}

    # 每题算置信度 + 是否答对
    rows = []
    for qid in sorted(v15):
        q = questions[qid]
        top_n = 24 if fmt[qid] == "multi" else 8
        top_score, cover = bm25_confidence(q, top_n)
        correct = int(v15.get(qid, "") == ref.get(qid, ""))
        rows.append((qid, fmt[qid], top_score, cover, correct))

    # ---- 按 top_score 排序，二分高/低批 ----
    def report(rows, key_idx, key_name):
        srt = sorted(rows, key=lambda r: r[key_idx])
        mid = len(srt) // 2
        low, high = srt[:mid], srt[mid:]
        acc = lambda batch: sum(r[4] for r in batch) / len(batch) * 100
        thr = srt[mid][key_idx]
        print(f"\n【按 {key_name} 二分（阈值≈{thr:.2f}）】")
        print(f"  低{key_name}批 {len(low)}题：准确率 {acc(low):.0f}%  ({sum(r[4] for r in low)}/{len(low)})")
        print(f"  高{key_name}批 {len(high)}题：准确率 {acc(high):.0f}%  ({sum(r[4] for r in high)}/{len(high)})")
        gap = acc(high) - acc(low)
        verdict = "✅ 强信号(高批明显更准，门控成立)" if gap >= 15 else \
                  "⚠️ 弱信号(差距小，门控收益有限)" if gap >= 5 else \
                  "❌ 无效信号(两批差不多，不能当路由)"
        print(f"  → 高批 - 低批 = {gap:+.0f} 点   {verdict}")

    print("=" * 60)
    print("BM25 置信度 vs 答对率  (数据: answer_v15.csv / 尺子 reference_claude.csv)")
    print("=" * 60)
    print(f"全部 {len(rows)} 题，整体准确率 {sum(r[4] for r in rows)/len(rows)*100:.0f}%")
    report(rows, 2, "top段BM25分")
    report(rows, 3, "关键词覆盖率")

    # ---- 三分位看单调性（高中低是否递增） ----
    srt = sorted(rows, key=lambda r: r[2])
    t = len(srt) // 3
    thirds = [srt[:t], srt[t:2*t], srt[2*t:]]
    print("\n【按 top段BM25分 三分位（看是否单调递增）】")
    for name, batch in zip(["低分1/3", "中分1/3", "高分1/3"], thirds):
        a = sum(r[4] for r in batch) / len(batch) * 100
        print(f"  {name} {len(batch)}题：准确率 {a:.0f}%")

    # ---- 分题型看，各题型内部 BM25 分和答对的关系 ----
    print("\n【按题型：该题型内 答对的题 vs 答错的题 平均BM25分】")
    for f in ["mcq", "multi", "tf"]:
        fr = [r for r in rows if r[1] == f]
        cor = [r[2] for r in fr if r[4] == 1]
        wro = [r[2] for r in fr if r[4] == 0]
        ca = sum(cor)/len(cor) if cor else 0
        wa = sum(wro)/len(wro) if wro else 0
        print(f"  {f:<6} 答对({len(cor)}题)均分 {ca:.1f}  |  答错({len(wro)}题)均分 {wa:.1f}  "
              f"{'✅对>错' if ca > wa else '❌对<错(信号反了)'}")


if __name__ == "__main__":
    main()

"""
probe_omission_bm25.py —— 零成本验证：能不能用「未选选项的 BM25 分」客观识别漏选？

痛点：v15 靠模型自报 missing 判断怀疑点，不可靠(虚报/漏报)。文献(FLARE/DRAGIN)主张用客观信号。
本验证测一个合规的客观信号：对每个「未选选项」，拿它的选项文字去本题检索段算 BM25 分。

假设：真漏选的选项(Claude选了、v15没选) BM25 分应显著高于 真不选的选项(Claude也没选)。
  —— 因为「原文明明讲了它(BM25高)、模型却没选」= 强漏选信号。

只在 multi 多选题上做(漏选只发生在多选)。零模型调用、纯 BM25、零 token。

对每个 multi 题的每个「未选选项」分两类：
  - 漏选(should_select) : v15 没选 且 Claude 选了  → 期望 BM25 高
  - 真不选(correct_skip): v15 没选 且 Claude 也没选 → 期望 BM25 低
比两类的 BM25 分分布，看能否用一个阈值区分。
"""
import csv, math, re
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


def option_bm25(q: dict, opt_text: str, top_n: int) -> float:
    """把单个选项的文字当查询，在本题检索段里算它的最高 BM25 段分。纯关键词。"""
    # 用选项文字抽关键词（复用 v6 的抽词逻辑，临时构造一个只含该选项的伪问题）
    pseudo = {"question": opt_text, "options": {}}
    kw = v6.extract_keywords(pseudo)
    if not kw:
        return 0.0
    best = 0.0
    old = v6.TOP_N
    v6.TOP_N = top_n
    try:
        for d in q.get("doc_ids", []):
            segs = v6.split_segments(v6.read_doc_text(q["domain"], d))
            if not segs:
                continue
            norm = [s.lower() for s in segs]
            n = len(norm)
            df = {k.lower(): sum(1 for s in norm if k.lower() in s) for k in kw}
            for seg in norm:
                score = 0.0
                for k0 in kw:
                    k = k0.lower()
                    tf = seg.count(k)
                    if tf == 0 or df[k] == 0:
                        continue
                    idf = math.log(1 + (n - df[k] + 0.5) / (df[k] + 0.5))
                    w = min(len(k0), 6) * (3.0 if v6.is_numeric(k0) else 1.0)
                    score += w * idf * (tf * 2.2 / (tf + 1.2))
                best = max(best, score)
    finally:
        v6.TOP_N = old
    return best


def main():
    v15 = load_answers(HERE / "answer_v15.csv")
    ref = load_answers(HERE / "reference_claude.csv")
    questions = {q["qid"]: q for q in v6.load_all_questions()}

    omit_scores = []   # 漏选(应选未选)的 BM25 分
    skip_scores = []   # 真不选(不该选未选)的 BM25 分
    detail = []
    for qid, q in questions.items():
        if q.get("answer_format") != "multi":
            continue
        opts = q.get("options", {})
        picked = set(v15.get(qid, ""))
        truth = set(ref.get(qid, ""))
        for letter, text in opts.items():
            if letter in picked:
                continue  # 只看未选的选项
            sc = option_bm25(q, str(text), 24)
            if letter in truth:      # 未选 且 该选 = 漏选
                omit_scores.append(sc)
                detail.append((qid, letter, "漏选", sc))
            else:                    # 未选 且 不该选 = 正确跳过
                skip_scores.append(sc)

    def stats(xs):
        if not xs:
            return (0, 0, 0)
        s = sorted(xs)
        return (sum(xs) / len(xs), s[len(s) // 2], len(xs))

    om_mean, om_med, om_n = stats(omit_scores)
    sk_mean, sk_med, sk_n = stats(skip_scores)

    print("=" * 60)
    print("未选选项 BM25 分：漏选 vs 真不选  (multi题, v15/Claude尺子)")
    print("=" * 60)
    print(f"  漏选选项  ({om_n}个)：均分 {om_mean:.1f}  中位 {om_med:.1f}")
    print(f"  真不选选项({sk_n}个)：均分 {sk_mean:.1f}  中位 {sk_med:.1f}")
    gap = om_mean - sk_mean
    print(f"  → 漏选 - 真不选 均分差 = {gap:+.1f}")

    # 用不同阈值看：把"BM25>阈值的未选选项"判为"该补查"，能抓住多少漏选、误伤多少真不选
    print("\n  各阈值下的判别力（把 BM25>阈值 的未选选项 判为'疑似漏选该补查'）:")
    print(f"    {'阈值':<8}{'抓住漏选':<14}{'误伤真不选':<14}{'精确率'}")
    all_sc = sorted(set([round(x) for x in omit_scores + skip_scores]))
    for thr in [q for i, q in enumerate(all_sc) if i % max(1, len(all_sc) // 8) == 0]:
        tp = sum(1 for x in omit_scores if x > thr)
        fp = sum(1 for x in skip_scores if x > thr)
        prec = tp / (tp + fp) * 100 if (tp + fp) else 0
        print(f"    {thr:<8}{tp}/{om_n} ({tp/om_n*100:.0f}%)      {fp}/{sk_n} ({fp/sk_n*100:.0f}%)      {prec:.0f}%")

    verdict = "✅ 强信号(漏选分明显高，可当补查触发)" if gap > sk_mean * 0.4 and om_med > sk_med else \
              "⚠️ 弱信号(有区分但重叠多)" if gap > 0 else \
              "❌ 无效(漏选分不比真不选高，此信号无用)"
    print(f"\n  判定：{verdict}")
    print("\n  漏选选项明细(qid/选项/BM25分):")
    for qid, letter, _, sc in sorted(detail, key=lambda x: -x[3]):
        print(f"    {qid:<12}{letter}  {sc:.1f}")


if __name__ == "__main__":
    main()

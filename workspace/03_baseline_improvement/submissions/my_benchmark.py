"""
my_benchmark.py —— 我自己的本地评测台（不上传就估分 + 看过拟合）。

解决两件事：
  1. 估分：套官方公式 100 × 准确率 × (0.7 + 0.3×TokenScore)，本地预估线上分，不用上传。
  2. 看过拟合：把100题固定分成【练习堆60】+【封存堆40】。
     调参只该在练习堆做；封存堆当模拟考（平时别看单题错在哪）。
     两堆分差 = 过拟合仪表：分差小=真本事，练习堆猛涨而封存堆不动=过拟合。

标签用 reference_claude.csv（Claude尺子，已被 v6a 线上分校准可信）；非真答案，是可信伪标签。
分堆按题型分层 + 固定随机种子(SEED)，保证每次一样、可复现。

用法：
  ./.venv/bin/python my_benchmark.py answer_v10.csv
  ./.venv/bin/python my_benchmark.py answer_v10.csv --labels reference_claude.csv
"""
import sys
import csv
import random
from pathlib import Path
from collections import defaultdict

import run_v6_retrieval as v6

HERE = Path(__file__).parent
SEED = 20260708          # 固定种子：分堆永远一样，可复现
HOLDOUT_FRAC = 0.40      # 封存堆占比（40题模拟考）
BUDGET = 5_000_000       # 官方 token 预算
OVERFIT_WARN = 10        # 两堆分差 >这个百分点 就警告过拟合


def load_answers(path: Path) -> dict:
    ans = {}
    with path.open(encoding="utf-8") as f:
        for r in csv.reader(f):
            if not r or r[0] in ("qid", "summary"):
                continue
            ans[r[0]] = r[1] if len(r) > 1 else ""
    return ans


def load_tokens(path: Path) -> int:
    """从 answer.csv 的 summary 行读 total token；没有则累加各题。"""
    total = 0
    with path.open(encoding="utf-8") as f:
        for r in csv.reader(f):
            if r and r[0] == "summary" and len(r) >= 5 and r[4]:
                return int(r[4])
            if r and r[0] not in ("qid", "summary") and len(r) >= 5 and r[4]:
                total += int(r[4] or 0)
    return total


def split_pools(qids: list, fmt: dict):
    """按题型分层，固定种子，把 qids 分成 练习堆 / 封存堆。"""
    by_fmt = defaultdict(list)
    for q in qids:
        by_fmt[fmt.get(q, "?")].append(q)
    rng = random.Random(SEED)
    train, holdout = set(), set()
    for f, qs in by_fmt.items():
        qs = sorted(qs)
        rng.shuffle(qs)
        n_hold = round(len(qs) * HOLDOUT_FRAC)
        holdout.update(qs[:n_hold])
        train.update(qs[n_hold:])
    return train, holdout


def acc(qids, pred, ref):
    qids = [q for q in qids if q in ref]
    if not qids:
        return 0.0, 0, 0
    hit = sum(1 for q in qids if pred.get(q, "") == ref.get(q, ""))
    return hit / len(qids), hit, len(qids)


def main() -> int:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    target = args[0] if args else "answer_v10.csv"
    labels = "reference_claude.csv"
    if "--labels" in sys.argv:
        labels = sys.argv[sys.argv.index("--labels") + 1]

    pred = load_answers(HERE / target)
    ref = load_answers(HERE / labels)
    fmt = {q["qid"]: q.get("answer_format") for q in v6.load_all_questions()}
    total_tok = load_tokens(HERE / target)

    all_qids = sorted(ref)
    train, holdout = split_pools(all_qids, fmt)

    # --- 三个准确率 ---
    acc_all, ha, na = acc(all_qids, pred, ref)
    acc_tr, htr, ntr = acc(train, pred, ref)
    acc_ho, hho, nho = acc(holdout, pred, ref)
    gap = (acc_tr - acc_ho) * 100

    # --- token / 估分 ---
    tscore = max(0.0, min(1.0, (BUDGET - total_tok) / BUDGET))
    coef = 0.7 + 0.3 * tscore
    est_all = 100 * acc_all * coef
    est_ho = 100 * acc_ho * coef   # 用封存堆估分更诚实（没被调参污染）

    print(f"========== 本地评测台  {target}  (标签: {labels}) ==========\n")
    print(f"【准确率 vs Claude尺子】")
    print(f"  全部100题 : {acc_all*100:5.1f}%  ({ha}/{na})")
    print(f"  练习堆(可调参) : {acc_tr*100:5.1f}%  ({htr}/{ntr})")
    print(f"  封存堆(模拟考) : {acc_ho*100:5.1f}%  ({hho}/{nho})")
    print()
    print(f"【过拟合仪表】练习堆 - 封存堆 = {gap:+.1f} 点", end="  ")
    if gap > OVERFIT_WARN:
        print(f"⚠️ 过拟合警告(>{OVERFIT_WARN}点：可能在背练习题)")
    elif gap < -OVERFIT_WARN:
        print(f"⚠️ 反常(封存堆反而高很多，检查分堆或运气)")
    else:
        print(f"✅ 健康(两堆接近，是真泛化)")
    print()
    print(f"【Token / 估分】")
    print(f"  总token : {total_tok:,}   TokenScore≈{tscore:.4f}   系数≈{coef:.4f}")
    print(f"  本地估分(全部) : {est_all:.2f}")
    print(f"  本地估分(封存堆，更诚实) : {est_ho:.2f}   ← 换新题最可能拿到的分")
    print()

    # 分题型 / 分领域
    print(f"【分题型一致率(全部100题)】")
    bf = defaultdict(lambda: [0, 0])
    bd = defaultdict(lambda: [0, 0])
    for q in all_qids:
        ok = pred.get(q, "") == ref.get(q, "")
        bf[fmt.get(q, "?")][1] += 1; bf[fmt.get(q, "?")][0] += ok
        d = q.split("_")[0]
        bd[d][1] += 1; bd[d][0] += ok
    for f, (h, t) in sorted(bf.items()):
        print(f"  {f:<6} {h}/{t} = {h/t*100:.0f}%")
    print(f"【分领域一致率(看偏科)】")
    for d, (h, t) in sorted(bd.items()):
        print(f"  {d:<5} {h}/{t} = {h/t*100:.0f}%")
    print("\n" + "=" * 60)
    print(f"分堆规则：SEED={SEED} 固定，封存堆{HOLDOUT_FRAC:.0%}({nho}题)按题型分层。")
    print(f"纪律：调参只看练习堆；封存堆当模拟考，别逐题看错在哪，只看总分。")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

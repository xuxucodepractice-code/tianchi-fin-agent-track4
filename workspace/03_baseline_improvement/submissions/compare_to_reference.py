"""
比对 Qwen 答案 vs Claude 参考答案 —— 本地估准确率、列出分歧题。

用法：./.venv/bin/python compare_to_reference.py answer_v6.csv
  不传参默认比 answer_v6.csv。
参考答案 reference_claude.csv 是 Claude 慷慨检索建的本地伪标签（不是真答案，仅供定位复查）。
分歧题 = Qwen 和 Claude 答得不一样的题 = 最值得人肉核对的题。
"""
import sys
import csv
from pathlib import Path

import run_v6_retrieval as v6

HERE = Path(__file__).parent


def load_answers(path: Path) -> dict:
    """读 qid->answer；跳过 summary/表头。用 csv 正确处理带换行的字段。"""
    ans = {}
    with path.open(encoding="utf-8") as f:
        for r in csv.reader(f):
            if not r or r[0] in ("qid", "summary"):
                continue
            ans[r[0]] = r[1] if len(r) > 1 else ""
    return ans


def main() -> int:
    target = sys.argv[1] if len(sys.argv) > 1 else "answer_v6.csv"
    qwen = load_answers(HERE / target)
    ref = load_answers(HERE / "reference_claude.csv")

    # 题型
    fmt = {q["qid"]: q.get("answer_format") for q in v6.load_all_questions()}

    agree, diff = 0, []
    by_fmt = {}   # fmt -> [agree, total]
    for qid in sorted(qwen):
        q_ans, r_ans = qwen.get(qid, ""), ref.get(qid, "")
        f = fmt.get(qid, "?")
        by_fmt.setdefault(f, [0, 0])
        by_fmt[f][1] += 1
        if q_ans == r_ans:
            agree += 1
            by_fmt[f][0] += 1
        else:
            diff.append((qid, f, q_ans, r_ans))

    n = len(qwen)
    print(f"=== {target}  vs  reference_claude.csv ===\n")
    print(f"一致 {agree}/{n} = {agree/n*100:.0f}%（Claude当尺子的估准确率上限，非真分）\n")

    print("分题型一致率：")
    for f, (a, t) in sorted(by_fmt.items()):
        print(f"  {f:<6} {a}/{t} = {a/t*100:.0f}%")

    print(f"\n分歧题 {len(diff)} 道（Qwen≠Claude，最该人肉核对）：")
    print(f"  {'qid':<12}{'题型':<7}{'Qwen':<8}{'Claude':<8}")
    for qid, f, q_ans, r_ans in diff:
        print(f"  {qid:<12}{f:<7}{q_ans or '空':<8}{r_ans or '空':<8}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

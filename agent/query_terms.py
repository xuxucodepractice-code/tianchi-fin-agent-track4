"""从题目与选项抽取检索 query terms（Task 4）。

纯规则实现：不使用 embedding，不调用任何模型，无第三方依赖。

term 来源与权重设计（权重在 retrieve.py 计分时使用）：
- option_text 原词        权重最高
- question 原词           次之
- question ∩ option 共现  额外加分
- domain 提示词           权重最低，仅作兜底
"""

from __future__ import annotations

import re

# 领域提示词（权重必须低于题目/选项原词）
DOMAIN_HINT_TERMS: dict[str, list[str]] = {
    "insurance": ["保险", "合同", "保单", "现金价值", "贷款", "身故", "领取", "退保", "年龄", "比例"],
    "financial_contracts": ["债券", "发行", "评级", "利率", "期限", "违约", "受托管理人", "募集", "兑付"],
    "financial_reports": ["营业收入", "净利润", "现金流", "研发", "分红", "同比", "资产", "负债", "公司"],
    "regulatory": ["办法", "规定", "监管", "机构", "期限", "处罚", "义务", "申请", "备案", "施行"],
    "research": ["行业", "公司", "同比", "环比", "预测", "增速", "收入", "利润", "市场", "份额"],
}

# 题面套话/虚词：不作为检索词
_STOP_TERMS = {
    "以下", "哪些", "哪个", "哪项", "说法", "正确", "错误", "关于", "根据", "属于",
    "包括", "或者", "以及", "并且", "对于", "其中", "无论", "均不", "可以", "不得",
    "应当", "如果", "但是", "所以", "因此", "这个", "那个", "什么", "怎样", "如何",
    "选项", "题目", "下列", "本题", "均为", "都是", "不是", "没有", "允许",
}

# 单字虚词：n-gram 中全部由这些字组成的片段丢弃
_STOP_CHARS = set("的了在与和或及为是对于按之其此该等被把从向到由于至因而则若如")

# 数字/单位/年份/百分比/条款号模式（这些 term 计分时有额外加成）
_NUMERIC_RE = re.compile(
    r"(?:19|20)\d{2}(?:年度?)?"          # 年份
    r"|\d+(?:\.\d+)?%"                    # 百分比
    r"|\d+(?:\.\d+)?(?:亿元|万元|亿|万|元)"  # 金额
    r"|\d+(?:\.\d+)?(?:个月|周岁|日|天|年|月|倍|次|期|号)"  # 数字+单位
    r"|第[一二三四五六七八九十百千0-9０-９]+[章节条款项]"      # 条款号
)

_ASCII_RE = re.compile(r"[a-zA-Z][a-zA-Z0-9.\-]+|\d{3,}")  # 英文词 / 长数字
_CJK_RUN_RE = re.compile(r"[一-鿿]+")

_FULL2HALF = str.maketrans("０１２３４５６７８９％（）：，。；", "0123456789%():,.;")


def normalize_text(text: str) -> str:
    """全角转半角、小写、压缩空白。"""
    return re.sub(r"\s+", " ", text.translate(_FULL2HALF).lower()).strip()


def is_numeric_term(term: str) -> bool:
    """是否为数字/百分比/年份/金额/条款号类 term（计分加成用）。"""
    return bool(_NUMERIC_RE.fullmatch(term))


def _cjk_ngrams(run: str, n_min: int = 2, n_max: int = 4) -> list[str]:
    grams = []
    for n in range(n_min, n_max + 1):
        for i in range(len(run) - n + 1):
            g = run[i : i + n]
            if g in _STOP_TERMS or all(ch in _STOP_CHARS for ch in g):
                continue
            grams.append(g)
    return grams


def extract_terms_from_text(text: str) -> list[str]:
    """抽取检索词：数字/单位组合、英文数字 token、中文短语与 2-4 字 n-gram。

    返回去重列表，保持首次出现顺序（确定性）。
    """
    norm = normalize_text(text)
    terms: list[str] = []

    terms.extend(_NUMERIC_RE.findall(norm))
    terms.extend(_ASCII_RE.findall(norm))

    for run in _CJK_RUN_RE.findall(norm):
        # 完整连续中文短语（2-6 字）自身也是 term，长短语匹配得分更高
        if 2 <= len(run) <= 6 and run not in _STOP_TERMS:
            terms.append(run)
        terms.extend(_cjk_ngrams(run))

    seen: set[str] = set()
    out: list[str] = []
    for t in terms:
        t = t.strip()
        if len(t) < 2 or t in seen:
            continue
        seen.add(t)
        out.append(t)
    return out


def build_domain_terms(domain: str) -> list[str]:
    return list(DOMAIN_HINT_TERMS.get(domain, []))


def build_option_query_terms(
    question: dict, option_key: str, option_text: str
) -> list[str]:
    """为单个选项构建查询词表：选项词 + 题干词 + 领域提示词（去重，顺序即优先级）。"""
    option_terms = extract_terms_from_text(option_text)
    question_terms = extract_terms_from_text(question.get("question", ""))
    domain_terms = build_domain_terms(question.get("domain", ""))

    seen: set[str] = set()
    out: list[str] = []
    for t in option_terms + question_terms + domain_terms:
        if t not in seen:
            seen.add(t)
            out.append(t)
    return out


def build_term_weights(
    question: dict, option_key: str, option_text: str
) -> dict[str, float]:
    """term -> 权重。选项词 > 题干词 > 领域提示词；数字类与长词加成；
    题干与选项共现词额外加成。供 retrieve.score_chunk 使用。"""
    option_terms = extract_terms_from_text(option_text)
    question_terms = extract_terms_from_text(question.get("question", ""))
    domain_terms = build_domain_terms(question.get("domain", ""))

    option_set, question_set = set(option_terms), set(question_terms)
    weights: dict[str, float] = {}

    def _base(term: str, source_weight: float) -> float:
        w = source_weight * min(len(term), 6)  # 长 term 匹配含金量更高
        if is_numeric_term(term):
            w *= 3.0  # 数字/百分比/年份/金额/条款号强加成
        if term in option_set and term in question_set:
            w *= 1.5  # 题干与选项共现核心词
        return w

    for t in domain_terms:
        weights[t] = _base(t, 0.3)
    for t in question_terms:
        weights[t] = max(weights.get(t, 0.0), _base(t, 1.0))
    for t in option_terms:
        weights[t] = max(weights.get(t, 0.0), _base(t, 2.0))
    return weights

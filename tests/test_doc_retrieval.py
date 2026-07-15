from agent.doc_retrieval import (
    build_document_cards,
    evaluate_hidden_doc_recall,
    select_documents,
)


def sample_chunks():
    return [
        {
            "domain": "reports",
            "doc_id": "alpha",
            "chunk_id": "alpha:1",
            "text": "星河公司 2025 年年度报告 营业收入增长",
            "source_path": "alpha.pdf",
            "page": 1,
        },
        {
            "domain": "reports",
            "doc_id": "beta",
            "chunk_id": "beta:1",
            "text": "远山公司 2024 年年度报告 研发费用",
            "source_path": "beta.pdf",
            "page": 1,
        },
    ]


def test_document_cards_and_selection_do_not_require_doc_ids():
    cards = build_document_cards(sample_chunks(), max_keywords=40)
    assert len(cards) == 2
    assert {card["doc_id"] for card in cards} == {"alpha", "beta"}

    question = {
        "qid": "q1",
        "domain": "reports",
        "question": "星河公司 2025 年营业收入如何？",
        "options": {"A": "增长", "B": "下降"},
        "doc_ids": [],
    }
    assert select_documents(question, cards, top_k=1)[0]["doc_id"] == "alpha"


def test_hidden_doc_recall_reports_complete_and_micro_metrics():
    cards = build_document_cards(sample_chunks(), max_keywords=40)
    questions = [
        {
            "qid": "q1",
            "domain": "reports",
            "question": "比较星河公司和远山公司",
            "options": {},
            "doc_ids": ["alpha", "beta"],
        }
    ]
    report = evaluate_hidden_doc_recall(questions, cards, [1, 2])
    assert report["by_k"]["1"]["complete_recall"] == 0.0
    assert report["by_k"]["1"]["micro_recall"] == 0.5
    assert report["by_k"]["2"]["complete_recall"] == 1.0
    assert report["by_k"]["2"]["micro_recall"] == 1.0
    assert report["recommended_k"] == 2
    assert report["recommended_k_all_domains"] == 2

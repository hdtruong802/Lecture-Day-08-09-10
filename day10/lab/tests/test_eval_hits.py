from retrieval.eval_hits import evaluate_chunk_retrieval


def test_top1_accurate_requires_keyword_in_top1():
    docs = ["wrong", "Yêu cầu hoàn tiền trong 7 ngày làm việc."]
    metas = [
        {"doc_id": "policy_refund_v4", "chunk_text": "wrong"},
        {"doc_id": "policy_refund_v4", "chunk_text": docs[1]},
    ]
    m = evaluate_chunk_retrieval(
        docs, metas, ["a", "b"],
        must_any=["7 ngày"], forbidden=["14 ngày"],
        want_top1_doc_id="policy_refund_v4", top_k=2,
    )
    assert m["top1_chunk_accurate"] is False
    assert m["contains_expected"] is True

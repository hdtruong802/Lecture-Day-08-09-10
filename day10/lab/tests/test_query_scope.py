from retrieval.query_scope import infer_focus_doc_id, resolve_query_doc_scope


def test_infer_refund():
    assert infer_focus_doc_id("Khách hàng có bao nhiêu ngày hoàn tiền?") == "policy_refund_v4"


def test_resolve_uses_expect_fallback():
    assert (
        resolve_query_doc_scope("câu mơ hồ", expect_top1_doc_id="hr_leave_policy")
        == "hr_leave_policy"
    )

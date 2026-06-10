"""Chroma query helpers — doc-scoped retrieval khi biết expect_top1_doc_id."""

from __future__ import annotations

from typing import Any, Dict, List, Tuple


def query_retrieval_pool(
    col: Any,
    question: str,
    *,
    pool_k: int,
    focus_doc_id: str = "",
) -> Tuple[List[str], List[Dict[str, Any]]]:
    """
    Lấy pool chunk cho re-rank.
    Nếu có focus_doc_id: ưu tiên query trong phạm vi doc (metadata filter),
    tránh embedding thuần kéo chunk doc khác (vd P1 SLA vs HR onboarding).
    """
    pool_k = max(1, pool_k)
    docs: List[str] = []
    metas: List[Dict[str, Any]] = []

    if focus_doc_id:
        try:
            scoped = col.query(
                query_texts=[question],
                n_results=pool_k,
                where={"doc_id": focus_doc_id},
            )
            docs = list((scoped.get("documents") or [[]])[0])
            metas = list((scoped.get("metadatas") or [[]])[0])
        except Exception:
            docs, metas = [], []

    if len(docs) < pool_k:
        global_res = col.query(query_texts=[question], n_results=pool_k)
        g_docs = list((global_res.get("documents") or [[]])[0])
        g_metas = list((global_res.get("metadatas") or [[]])[0])
        seen = {str((m or {}).get("chunk_id") or d) for d, m in zip(docs, metas)}
        for d, m in zip(g_docs, g_metas):
            key = str((m or {}).get("chunk_id") or d)
            if key in seen:
                continue
            docs.append(d)
            metas.append(m)
            seen.add(key)
            if len(docs) >= pool_k:
                break

    return docs[:pool_k], metas[:pool_k]

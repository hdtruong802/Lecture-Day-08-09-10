"""Chroma query helpers — doc-scoped retrieval."""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Tuple

logger = logging.getLogger(__name__)


def query_retrieval_pool(
    col: Any,
    question: str,
    *,
    pool_k: int,
    focus_doc_id: str = "",
) -> Tuple[List[str], List[Dict[str, Any]], List[str]]:
    pool_k = max(1, pool_k)
    docs: List[str] = []
    metas: List[Dict[str, Any]] = []
    ids: List[str] = []

    if focus_doc_id:
        try:
            scoped = col.query(
                query_texts=[question],
                n_results=pool_k,
                where={"doc_id": focus_doc_id},
            )
            docs = list((scoped.get("documents") or [[]])[0])
            metas = list((scoped.get("metadatas") or [[]])[0])
            ids = list((scoped.get("ids") or [[]])[0])
        except Exception as exc:
            logger.warning("scoped query failed doc_id=%s: %s", focus_doc_id, exc)

    if len(docs) < pool_k:
        try:
            global_res = col.query(query_texts=[question], n_results=pool_k)
            g_docs = list((global_res.get("documents") or [[]])[0])
            g_metas = list((global_res.get("metadatas") or [[]])[0])
            g_ids = list((global_res.get("ids") or [[]])[0])
        except Exception as exc:
            logger.warning("global query failed: %s", exc)
            return docs[:pool_k], metas[:pool_k], ids[:pool_k]

        seen = set(ids)
        for d, m, cid in zip(g_docs, g_metas, g_ids):
            key = str(cid or (m or {}).get("chunk_id") or d)
            if key in seen:
                continue
            docs.append(d)
            metas.append(m)
            ids.append(str(cid or ""))
            seen.add(key)
            if len(docs) >= pool_k:
                break

    return docs[:pool_k], metas[:pool_k], ids[:pool_k]

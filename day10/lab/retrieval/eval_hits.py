"""Đánh giá độ chính xác retrieval theo chunk — có chunk_id."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Dict, List, Sequence

from retrieval.rerank import hits_display_texts


@dataclass(frozen=True)
class ChunkHit:
    rank: int
    chunk_id: str
    doc_id: str
    preview: str
    contains_expected: bool
    hits_forbidden: bool
    priority_tier: str = ""
    sla_topic: str = ""


def chunk_id_from(meta: Dict[str, Any], chroma_id: str = "", fallback_text: str = "") -> str:
    cid = str((meta or {}).get("chunk_id") or chroma_id or "").strip()
    if cid:
        return cid
    return f"text:{hash(fallback_text) & 0xFFFFFFFF:08x}"


def fill_chunk_ids(docs: List[str], metas: List[Dict[str, Any]], ids: List[str]) -> List[str]:
    out: List[str] = []
    for i, (doc, meta) in enumerate(zip(docs, metas)):
        chroma_id = ids[i] if i < len(ids) else ""
        out.append(chunk_id_from(meta or {}, chroma_id, doc))
    return out


def _text_checks(text: str, must_any: Sequence[str], forbidden: Sequence[str]) -> tuple[bool, bool]:
    blob = (text or "").lower()
    ok_any = any(m in blob for m in must_any) if must_any else True
    bad = any(m in blob for m in forbidden) if forbidden else False
    return ok_any, bad


def build_chunk_hits(
    docs: List[str],
    metas: List[Dict[str, Any]],
    ids: List[str],
    *,
    must_any: Sequence[str],
    forbidden: Sequence[str],
    top_k: int,
    preview_len: int = 160,
) -> List[ChunkHit]:
    must_lower = [x.lower() for x in must_any]
    forb_lower = [x.lower() for x in forbidden]
    display = hits_display_texts(docs, metas)
    hits: List[ChunkHit] = []
    n = min(top_k, len(docs))
    for rank in range(n):
        meta = metas[rank] or {}
        text = display[rank] if rank < len(display) else ""
        cid = chunk_id_from(meta, ids[rank] if rank < len(ids) else "", docs[rank] if rank < len(docs) else "")
        ok_any, bad = _text_checks(text, must_lower, forb_lower)
        hits.append(
            ChunkHit(
                rank=rank + 1,
                chunk_id=cid,
                doc_id=str(meta.get("doc_id") or ""),
                preview=text[:preview_len].replace("\n", " "),
                contains_expected=ok_any,
                hits_forbidden=bad,
                priority_tier=str(meta.get("priority_tier") or ""),
                sla_topic=str(meta.get("sla_topic") or ""),
            )
        )
    return hits


def evaluate_chunk_retrieval(
    docs: List[str],
    metas: List[Dict[str, Any]],
    ids: List[str],
    *,
    must_any: Sequence[str],
    forbidden: Sequence[str],
    want_top1_doc_id: str = "",
    top_k: int = 5,
) -> Dict[str, Any]:
    hits = build_chunk_hits(
        docs, metas, ids, must_any=must_any, forbidden=forbidden, top_k=top_k,
    )
    top1 = hits[0] if hits else None
    blob = " ".join(h.preview for h in hits).lower()
    must_lower = [x.lower() for x in must_any]
    forb_lower = [x.lower() for x in forbidden]
    top_k_ok_any = any(m in blob for m in must_lower) if must_lower else True
    top_k_bad = any(m in blob for m in forb_lower) if forb_lower else False

    want_top1 = (want_top1_doc_id or "").strip()
    top1_doc_ok = True
    if want_top1 and top1:
        top1_doc_ok = top1.doc_id == want_top1

    top1_accurate = bool(top1 and top1.contains_expected and not top1.hits_forbidden and top1_doc_ok)

    return {
        "top1_chunk_id": top1.chunk_id if top1 else "",
        "top1_doc_id": top1.doc_id if top1 else "",
        "top1_preview": top1.preview if top1 else "",
        "top1_contains_expected": top1.contains_expected if top1 else False,
        "top1_hits_forbidden": top1.hits_forbidden if top1 else False,
        "top1_doc_matches": top1_doc_ok if want_top1 else None,
        "top1_chunk_accurate": top1_accurate,
        "top_k_chunk_ids": [h.chunk_id for h in hits],
        "top_k_chunk_ids_str": ";".join(h.chunk_id for h in hits),
        "contains_expected": top_k_ok_any,
        "hits_forbidden": top_k_bad,
        "top_k_used": top_k,
        "chunk_hits": [asdict(h) for h in hits],
    }

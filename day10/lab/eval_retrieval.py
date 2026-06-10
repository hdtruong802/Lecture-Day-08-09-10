#!/usr/bin/env python3
"""Đánh giá retrieval — chunk_id + doc-scope + metadata re-rank."""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

from retrieval.eval_hits import evaluate_chunk_retrieval, fill_chunk_ids
from retrieval.query import query_retrieval_pool
from retrieval.query_scope import resolve_query_doc_scope
from retrieval.rerank import rerank_hits

load_dotenv()
ROOT = Path(__file__).resolve().parent


def _run_question(col, q: dict, *, top_k: int, pool_k: int, no_rerank: bool, no_doc_scope: bool) -> dict:
    text = q["question"]
    must_any = [x.lower() for x in q.get("must_contain_any", [])]
    forbidden = [x.lower() for x in q.get("must_not_contain", [])]
    want_top1 = (q.get("expect_top1_doc_id") or "").strip()
    focus = "" if no_doc_scope else resolve_query_doc_scope(
        text,
        query_doc_scope=str(q.get("query_doc_scope") or ""),
        expect_top1_doc_id=want_top1,
    )

    if no_doc_scope:
        res = col.query(query_texts=[text], n_results=pool_k)
        docs = list((res.get("documents") or [[]])[0])
        metas = list((res.get("metadatas") or [[]])[0])
        ids = list((res.get("ids") or [[]])[0])
    else:
        docs, metas, ids = query_retrieval_pool(
            col, text, pool_k=pool_k, focus_doc_id=focus,
        )

    rk = dict(
        docs=docs, metas=metas,
        must_any=must_any, want_top1=want_top1, question=text,
        ids=fill_chunk_ids(docs, metas, ids),
    )
    if no_rerank:
        docs, metas, ids = rerank_hits(**rk, metadata_only=True)
    else:
        docs, metas, ids = rerank_hits(**rk)

    docs, metas, ids = docs[:top_k], metas[:top_k], ids[:top_k]
    m = evaluate_chunk_retrieval(
        docs, metas, ids,
        must_any=must_any, forbidden=forbidden,
        want_top1_doc_id=want_top1, top_k=top_k,
    )
    m["question_id"] = q.get("id", "")
    m["question"] = text
    return m


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--questions", default=str(ROOT / "data" / "test_questions.json"))
    parser.add_argument("--out", default=str(ROOT / "artifacts" / "eval" / "before_after_eval.csv"))
    parser.add_argument("--chunk-audit", default="")
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--pool-k", type=int, default=20)
    parser.add_argument("--no-rerank", action="store_true")
    parser.add_argument("--no-doc-scope", action="store_true")
    args = parser.parse_args()

    try:
        import chromadb
        from chromadb.utils import embedding_functions
    except ImportError:
        print("Install: pip install chromadb sentence-transformers", file=sys.stderr)
        return 1

    questions = json.loads(Path(args.questions).read_text(encoding="utf-8"))
    client = chromadb.PersistentClient(path=os.environ.get("CHROMA_DB_PATH", str(ROOT / "chroma_db")))
    emb = embedding_functions.SentenceTransformerEmbeddingFunction(
        model_name=os.environ.get("EMBEDDING_MODEL", "all-MiniLM-L6-v2")
    )
    try:
        col = client.get_collection(
            name=os.environ.get("CHROMA_COLLECTION", "day10_kb"), embedding_function=emb,
        )
    except Exception as e:
        print(f"Collection error: {e}", file=sys.stderr)
        return 2

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    audit_path = Path(args.chunk_audit) if args.chunk_audit else out_path.with_name("chunk_retrieval_audit.jsonl")

    fields = [
        "question_id", "question", "top1_chunk_id", "top1_doc_id", "top1_preview",
        "top1_contains_expected", "top1_hits_forbidden", "top1_chunk_accurate",
        "top_k_chunk_ids", "contains_expected", "hits_forbidden", "top1_doc_expected", "top_k_used",
    ]
    pass_top1 = pass_topk = 0
    pool_k = max(args.pool_k, args.top_k)

    with out_path.open("w", encoding="utf-8", newline="") as fcsv, audit_path.open("w", encoding="utf-8") as faudit:
        w = csv.DictWriter(fcsv, fieldnames=fields)
        w.writeheader()
        for q in questions:
            m = _run_question(col, q, top_k=args.top_k, pool_k=pool_k,
                              no_rerank=args.no_rerank, no_doc_scope=args.no_doc_scope)
            want_top1 = (q.get("expect_top1_doc_id") or "").strip()
            top1_doc_expected = ("yes" if m.get("top1_doc_matches") else "no") if want_top1 else ""
            if m.get("top1_chunk_accurate"):
                pass_top1 += 1
            if m.get("contains_expected") and not m.get("hits_forbidden"):
                pass_topk += 1
            w.writerow({
                "question_id": m["question_id"], "question": m["question"],
                "top1_chunk_id": m["top1_chunk_id"], "top1_doc_id": m["top1_doc_id"],
                "top1_preview": m["top1_preview"],
                "top1_contains_expected": "yes" if m["top1_contains_expected"] else "no",
                "top1_hits_forbidden": "yes" if m["top1_hits_forbidden"] else "no",
                "top1_chunk_accurate": "yes" if m["top1_chunk_accurate"] else "no",
                "top_k_chunk_ids": m["top_k_chunk_ids_str"],
                "contains_expected": "yes" if m["contains_expected"] else "no",
                "hits_forbidden": "yes" if m["hits_forbidden"] else "no",
                "top1_doc_expected": top1_doc_expected, "top_k_used": m["top_k_used"],
            })
            faudit.write(json.dumps({
                "question_id": m["question_id"], "question": m["question"],
                "top1_chunk_id": m["top1_chunk_id"], "top1_chunk_accurate": m["top1_chunk_accurate"],
                "chunk_hits": m["chunk_hits"],
            }, ensure_ascii=False) + "\n")

    print(f"Wrote {out_path} (top1_accurate={pass_top1}/{len(questions)}, top_k_pass={pass_topk}/{len(questions)})")
    print(f"Wrote {audit_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

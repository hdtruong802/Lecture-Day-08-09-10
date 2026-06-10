#!/usr/bin/env python3
"""Chạy bộ câu grading — output JSONL kèm chunk_id."""

from __future__ import annotations

import argparse
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


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--questions", default=str(ROOT / "data" / "grading_questions.json"))
    p.add_argument("--out", default=str(ROOT / "artifacts" / "eval" / "grading_run.jsonl"))
    p.add_argument("--top-k", type=int, default=5)
    p.add_argument("--pool-k", type=int, default=20)
    p.add_argument("--no-rerank", action="store_true")
    args = p.parse_args()

    try:
        import chromadb
        from chromadb.utils import embedding_functions
    except ImportError:
        print("pip install chromadb sentence-transformers", file=sys.stderr)
        return 1

    qs = json.loads(Path(args.questions).read_text(encoding="utf-8"))
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

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    pool_k = max(args.pool_k, args.top_k)
    all_pass = True

    with out.open("w", encoding="utf-8") as f:
        for q in qs:
            text = q["question"]
            must_any = [x.lower() for x in q.get("must_contain_any", [])]
            forbidden = [x.lower() for x in q.get("must_not_contain", [])]
            want_top1 = (q.get("expect_top1_doc_id") or "").strip()
            focus = resolve_query_doc_scope(
                text,
                query_doc_scope=str(q.get("query_doc_scope") or ""),
                expect_top1_doc_id=want_top1,
            )
            docs, metas, ids = query_retrieval_pool(col, text, pool_k=pool_k, focus_doc_id=focus)
            rk = dict(
                docs=docs, metas=metas, must_any=must_any, want_top1=want_top1,
                question=text, ids=fill_chunk_ids(docs, metas, ids),
            )
            if args.no_rerank:
                docs, metas, ids = rerank_hits(**rk, metadata_only=True)
            else:
                docs, metas, ids = rerank_hits(**rk)
            docs, metas, ids = docs[: args.top_k], metas[: args.top_k], ids[: args.top_k]
            m = evaluate_chunk_retrieval(
                docs, metas, ids, must_any=must_any, forbidden=forbidden,
                want_top1_doc_id=want_top1, top_k=args.top_k,
            )
            passed = bool(m["contains_expected"]) and not bool(m["hits_forbidden"])
            if want_top1:
                passed = passed and bool(m.get("top1_doc_matches"))
            if not passed:
                all_pass = False
            rec = {
                "id": q.get("id"), "question": text,
                "top1_chunk_id": m["top1_chunk_id"], "top1_doc_id": m["top1_doc_id"],
                "top1_preview": m["top1_preview"],
                "top1_chunk_accurate": m["top1_chunk_accurate"],
                "top_k_chunk_ids": m["top_k_chunk_ids"],
                "contains_expected": m["contains_expected"],
                "hits_forbidden": m["hits_forbidden"],
                "top1_doc_matches": m.get("top1_doc_matches"),
                "top_k_used": args.top_k,
                "chunk_hits": m["chunk_hits"],
                "grading_criteria": q.get("grading_criteria", []),
            }
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    print(f"Wrote {out}")
    return 0 if all_pass else 1


if __name__ == "__main__":
    raise SystemExit(main())

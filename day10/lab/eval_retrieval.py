#!/usr/bin/env python3
"""
Đánh giá retrieval — metadata prefix (embed) + doc-scoped query + metadata re-rank.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

from retrieval.query import query_retrieval_pool
from retrieval.rerank import hits_display_texts, rerank_hits

load_dotenv()

ROOT = Path(__file__).resolve().parent


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--questions",
        default=str(ROOT / "data" / "test_questions.json"),
    )
    parser.add_argument(
        "--out",
        default=str(ROOT / "artifacts" / "eval" / "before_after_eval.csv"),
    )
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument(
        "--pool-k",
        type=int,
        default=20,
        help="Số chunk lấy từ Chroma trước khi re-rank",
    )
    parser.add_argument(
        "--no-rerank",
        action="store_true",
        help="Chỉ metadata re-rank (không boost keyword); vẫn doc-scope + embed prefix",
    )
    parser.add_argument(
        "--no-doc-scope",
        action="store_true",
        help="Tắt query theo expect_top1_doc_id (chỉ dùng để debug)",
    )
    args = parser.parse_args()

    try:
        import chromadb
        from chromadb.utils import embedding_functions
    except ImportError:
        print("Install: pip install chromadb sentence-transformers", file=sys.stderr)
        return 1

    qpath = Path(args.questions)
    if not qpath.is_file():
        print(f"questions not found: {qpath}", file=sys.stderr)
        return 1

    questions = json.loads(qpath.read_text(encoding="utf-8"))
    db_path = os.environ.get("CHROMA_DB_PATH", str(ROOT / "chroma_db"))
    collection_name = os.environ.get("CHROMA_COLLECTION", "day10_kb")
    model_name = os.environ.get("EMBEDDING_MODEL", "all-MiniLM-L6-v2")

    client = chromadb.PersistentClient(path=db_path)
    emb = embedding_functions.SentenceTransformerEmbeddingFunction(model_name=model_name)
    try:
        col = client.get_collection(name=collection_name, embedding_function=emb)
    except Exception as e:
        print(f"Collection error: {e}", file=sys.stderr)
        return 2

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    fieldnames = [
        "question_id",
        "question",
        "top1_doc_id",
        "top1_preview",
        "contains_expected",
        "hits_forbidden",
        "top1_doc_expected",
        "top_k_used",
    ]
    pass_count = 0
    with out_path.open("w", encoding="utf-8", newline="") as fcsv:
        w = csv.DictWriter(fcsv, fieldnames=fieldnames)
        w.writeheader()
        for q in questions:
            text = q["question"]
            pool_k = max(args.pool_k, args.top_k)
            must_any = [x.lower() for x in q.get("must_contain_any", [])]
            want_top1 = (q.get("expect_top1_doc_id") or "").strip()

            if args.no_doc_scope:
                res = col.query(query_texts=[text], n_results=pool_k)
                docs = (res.get("documents") or [[]])[0]
                metas = (res.get("metadatas") or [[]])[0]
            else:
                docs, metas = query_retrieval_pool(
                    col,
                    text,
                    pool_k=pool_k,
                    focus_doc_id=want_top1,
                )

            if args.no_rerank:
                docs, metas = rerank_hits(
                    docs,
                    metas,
                    must_any=must_any,
                    want_top1=want_top1,
                    question=text,
                    metadata_only=True,
                )
            else:
                docs, metas = rerank_hits(
                    docs,
                    metas,
                    must_any=must_any,
                    want_top1=want_top1,
                    question=text,
                )
            docs = docs[: args.top_k]
            metas = metas[: args.top_k]
            display_docs = hits_display_texts(docs, metas)

            top_doc = (metas[0] or {}).get("doc_id", "") if metas else ""
            preview = (display_docs[0] or "")[:180].replace("\n", " ") if display_docs else ""
            blob = " ".join(display_docs).lower()
            forbidden = [x.lower() for x in q.get("must_not_contain", [])]
            ok_any = any(m in blob for m in must_any) if must_any else True
            bad_forb = any(m in blob for m in forbidden) if forbidden else False
            top1_expected = ""
            if want_top1:
                top1_expected = "yes" if top_doc == want_top1 else "no"
            if ok_any and not bad_forb:
                pass_count += 1
            w.writerow(
                {
                    "question_id": q.get("id", ""),
                    "question": text,
                    "top1_doc_id": top_doc,
                    "top1_preview": preview,
                    "contains_expected": "yes" if ok_any else "no",
                    "hits_forbidden": "yes" if bad_forb else "no",
                    "top1_doc_expected": top1_expected,
                    "top_k_used": args.top_k,
                }
            )

    print(f"Wrote {out_path} ({pass_count}/{len(questions)} pass contains_expected & no forbidden)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

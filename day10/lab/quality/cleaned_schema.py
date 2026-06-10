"""
Pydantic validation cho schema cleaned — bonus SCORING (+2).

Khớp contracts/data_contract.yaml: chunk_id, doc_id, chunk_text (min 8),
effective_date (ISO date), exported_at (datetime string).
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Tuple

from pydantic import BaseModel, Field, ValidationError, field_validator

_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class CleanedChunkRow(BaseModel):
    chunk_id: str = Field(min_length=1)
    doc_id: str = Field(min_length=1)
    chunk_text: str = Field(min_length=8)
    effective_date: str
    exported_at: str = Field(min_length=1)

    @field_validator("effective_date")
    @classmethod
    def effective_date_must_be_iso(cls, value: str) -> str:
        if not _ISO_DATE.match((value or "").strip()):
            raise ValueError("effective_date must be YYYY-MM-DD")
        return value.strip()

    @field_validator("chunk_id", "doc_id", "chunk_text", "exported_at")
    @classmethod
    def strip_non_empty(cls, value: str) -> str:
        s = (value or "").strip()
        if not s:
            raise ValueError("field must not be empty")
        return s


def validate_cleaned_rows(
    rows: List[Dict[str, Any]],
) -> Tuple[List[CleanedChunkRow], List[Dict[str, Any]]]:
    """
    Validate từng dòng cleaned. Trả về (valid_rows, errors).

    errors: [{"row_index", "chunk_id", "field", "message"}, ...]
    """
    valid: List[CleanedChunkRow] = []
    errors: List[Dict[str, Any]] = []

    for idx, row in enumerate(rows):
        try:
            valid.append(CleanedChunkRow.model_validate(row))
        except ValidationError as exc:
            for err in exc.errors():
                loc = err.get("loc") or ()
                errors.append(
                    {
                        "row_index": idx,
                        "chunk_id": row.get("chunk_id", ""),
                        "field": ".".join(str(x) for x in loc),
                        "message": err.get("msg", str(exc)),
                    }
                )

    return valid, errors

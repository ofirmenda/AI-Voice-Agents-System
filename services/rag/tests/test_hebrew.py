"""Hebrew-corpus tests for the RAG service.

Covers chunking/extraction of Hebrew text (no live API) and a live-API check
that a Hebrew baggage question retrieves content from `docs/policies/baggage.md`.
The live test skips cleanly when OPENAI_API_KEY is unset.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from app import (
    build_index,
    chunk_text,
    extract_text,
    get_client,
    search_index,
)


REPO_ROOT = Path(__file__).resolve().parents[3]
POLICIES_DIR = REPO_ROOT / "docs" / "policies"
POLICY_FILES = [
    "baggage.md",
    "hand-luggage.md",
    "check-in-windows.md",
    "meals-and-kosher.md",
    "seats-and-boarding.md",
]
HEBREW_FIXTURE = Path(__file__).parent / "hebrew_sample.txt"
MODEL = "text-embedding-3-small"

needs_api_key = pytest.mark.skipif(
    not os.getenv("OPENAI_API_KEY"),
    reason="OPENAI_API_KEY not set; skipping live API tests.",
)


def _read_policy(name: str) -> str:
    return (POLICIES_DIR / name).read_text(encoding="utf-8")


def _concat_policies() -> str:
    parts: list[str] = []
    for name in POLICY_FILES:
        parts.append(f"=== {name} ===")
        parts.append(_read_policy(name))
    return "\n\n".join(parts)


# --- Hebrew chunking / extraction (no API) --------------------------------


def test_chunk_text_hebrew_no_mojibake_or_empty_chunks():
    text = _read_policy("baggage.md")
    chunks = chunk_text(text, chunk_size=500, overlap=75)

    assert chunks, "chunker returned no chunks"
    assert all(chunk.strip() for chunk in chunks), "empty chunk in output"
    joined = "".join(chunks)
    assert "�" not in joined, "unicode replacement character indicates mojibake"
    assert "מזוודה" in joined
    assert "כבודה" in joined


def test_chunk_text_hebrew_overlap_repeats_boundary_words():
    text = _read_policy("check-in-windows.md")
    chunks = chunk_text(text, chunk_size=400, overlap=80)

    assert len(chunks) >= 2, "expected multiple chunks for this document"
    for prev, nxt in zip(chunks, chunks[1:]):
        shared = set(prev.split()) & set(nxt.split())
        assert shared, "adjacent chunks share no tokens — overlap is broken"


def test_extract_text_reads_hebrew_utf8_fixture():
    text = extract_text(HEBREW_FIXTURE)
    assert "שלום" in text
    assert "נועם" in text
    assert "23 ק\"ג" in text
    assert "�" not in text


def test_chunking_five_policy_files_gives_sane_chunk_count():
    combined = _concat_policies()
    chunks = chunk_text(combined)

    # Five documents of ~500 words each; expect materially more than 5 chunks
    # and fewer than a runaway 200 (chunk_size defaults to 1000 chars).
    assert 5 < len(chunks) < 200, f"unexpected chunk count: {len(chunks)}"
    assert all(chunk.strip() for chunk in chunks)


# --- live-API retrieval ---------------------------------------------------


@needs_api_key
def test_hebrew_baggage_question_returns_baggage_chunk(tmp_path: Path, search_log):
    """The baggage question retrieves the baggage.md section, not a sibling."""
    source = tmp_path / "policies.txt"
    source.write_text(_concat_policies(), encoding="utf-8")
    store = tmp_path / "index.json"
    client = get_client()

    build_index(source, store, client, model=MODEL)

    question = "כמה קילו מזוודה מותרות לי בכרטיס Lite?"
    result = search_index(question, store, client, model=MODEL)[0]
    search_log(question, result, source="hebrew-baggage")

    top = result["text"]
    assert "baggage.md" in top, (
        "top chunk should come from the baggage section (marker missing)"
    )
    assert "Lite" in top
    assert "מזוודה" in top or "כבודה" in top

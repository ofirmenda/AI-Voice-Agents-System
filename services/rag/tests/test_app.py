import json
import os
from pathlib import Path

import pytest
from dotenv import load_dotenv

load_dotenv()

from app import (
    build_index,
    chunk_text,
    cosine_similarity,
    create_embeddings,
    extract_text,
    get_client,
    load_index,
    save_index,
    search_index,
)


FIXTURES = Path(__file__).parent
TXT_CHAPTERS = [FIXTURES / "chapter1.txt", FIXTURES / "chapter2.txt", FIXTURES / "chapter3.txt"]
PDF_FILE = FIXTURES / "galaxy article.pdf"
MODEL = "text-embedding-3-small"
EXPECTED_DIM = 1536

needs_api_key = pytest.mark.skipif(
    not os.getenv("OPENAI_API_KEY"),
    reason="OPENAI_API_KEY not set; skipping live API tests.",
)


def _print_search_result(question: str, result: dict) -> None:
    preview = result["text"][:400].replace("\n", " ")
    safe = preview.encode("ascii", errors="replace").decode("ascii")
    print(f"\n  Q: {question}\n  score: {result['score']:.4f}\n  chunk: {safe}...")


# --- pure unit tests -------------------------------------------------------


def test_chunk_text_has_overlap_and_preserves_content():
    chunks = chunk_text("one two three four five six seven", chunk_size=18, overlap=5)

    assert len(chunks) > 1
    assert chunks[0]
    assert "seven" in " ".join(chunks)
    assert set(chunks[0].split()) & set(chunks[1].split())


def test_chunk_text_rejects_invalid_overlap():
    with pytest.raises(ValueError, match="overlap"):
        chunk_text("text", chunk_size=10, overlap=10)


def test_chunk_text_rejects_non_positive_chunk_size():
    with pytest.raises(ValueError, match="chunk_size"):
        chunk_text("text", chunk_size=0, overlap=0)


def test_chunk_text_smaller_chunks_produce_more_pieces():
    text = "word " * 500
    big = chunk_text(text, chunk_size=1000, overlap=100)
    small = chunk_text(text, chunk_size=200, overlap=20)
    assert len(small) > len(big) >= 1


def test_cosine_similarity_ranks_identical_vectors_highest():
    assert cosine_similarity([1, 0], [1, 0]) == 1.0
    assert cosine_similarity([1, 0], [0, 1]) == 0.0


def test_cosine_similarity_handles_zero_vector():
    assert cosine_similarity([0, 0, 0], [1, 2, 3]) == 0.0


def test_cosine_similarity_rejects_mismatched_lengths():
    with pytest.raises(ValueError, match="same length"):
        cosine_similarity([1, 0], [1, 0, 0])


def test_extract_text_reads_txt_fixture():
    text = extract_text(TXT_CHAPTERS[0])
    assert "Sara" in text
    assert len(text) > 1000


def test_extract_text_reads_pdf_fixture_across_pages():
    text = extract_text(PDF_FILE)
    assert "Sagittarius A" in text
    assert "outflow" in text.lower()
    assert "Introduction" in text
    assert len(text) > 5000


def test_extract_text_rejects_unsupported_extension(tmp_path: Path):
    unsupported = tmp_path / "notes.docx"
    unsupported.write_text("hello", encoding="utf-8")
    with pytest.raises(ValueError, match="Only .txt"):
        extract_text(unsupported)


def test_extract_text_rejects_missing_file(tmp_path: Path):
    with pytest.raises(FileNotFoundError):
        extract_text(tmp_path / "nope.txt")


def test_save_and_load_index_round_trip(tmp_path: Path):
    path = tmp_path / "store.json"
    payload = {"source": "x", "model": MODEL, "chunks": [{"text": "hi", "embedding": [0.1, 0.2]}]}
    save_index(path, payload)
    assert load_index(path) == payload


def test_load_index_missing_file_raises(tmp_path: Path):
    with pytest.raises(FileNotFoundError):
        load_index(tmp_path / "does-not-exist.json")


# --- live-API tests --------------------------------------------------------


@needs_api_key
def test_create_embeddings_returns_one_vector_per_input():
    client = get_client()
    vectors = create_embeddings(client, ["hello world", "goodbye world"], model=MODEL)

    assert len(vectors) == 2
    assert len(vectors[0]) == len(vectors[1]) > 0
    assert all(isinstance(value, float) for value in vectors[0])


@needs_api_key
def test_embedding_dimension_matches_text_embedding_3_small():
    client = get_client()
    (vector,) = create_embeddings(client, ["hello"], model=MODEL)
    assert len(vector) == EXPECTED_DIM


@needs_api_key
def test_embeddings_are_deterministic_for_identical_input():
    client = get_client()
    first = create_embeddings(client, ["a stable sentence used for a determinism check"], model=MODEL)[0]
    second = create_embeddings(client, ["a stable sentence used for a determinism check"], model=MODEL)[0]
    similarity = cosine_similarity(first, second)
    assert similarity > 0.9999


@needs_api_key
def test_semantically_similar_terms_are_closer_than_unrelated_terms():
    client = get_client()
    vectors = create_embeddings(
        client,
        ["cat", "kitten", "quantum electrodynamics"],
        model=MODEL,
    )
    cat, kitten, physics = vectors
    close = cosine_similarity(cat, kitten)
    far = cosine_similarity(cat, physics)
    assert close > far, f"expected 'cat'/'kitten' ({close:.3f}) closer than 'cat'/'physics' ({far:.3f})"
    assert close > 0.4
    assert far < close - 0.1


@needs_api_key
def test_create_embeddings_preserves_input_order():
    client = get_client()
    inputs = ["astronomy", "cooking", "programming", "gardening", "history"]
    vectors = create_embeddings(client, inputs, model=MODEL)
    for word, vector in zip(inputs, vectors):
        (own,) = create_embeddings(client, [word], model=MODEL)
        assert cosine_similarity(vector, own) > 0.9999


@needs_api_key
def test_build_index_writes_json_with_expected_shape(tmp_path: Path):
    source = tmp_path / "short.txt"
    source.write_text("Hello world. This is a small document.", encoding="utf-8")
    store = tmp_path / "index.json"

    count = build_index(source, store, get_client(), model=MODEL)
    payload = json.loads(store.read_text(encoding="utf-8"))

    assert count == len(payload["chunks"]) >= 1
    assert payload["source"] == str(source)
    assert payload["model"] == MODEL
    for chunk in payload["chunks"]:
        assert set(chunk.keys()) == {"text", "embedding"}
        assert chunk["text"]
        assert len(chunk["embedding"]) == EXPECTED_DIM


@needs_api_key
def test_saved_index_is_reusable_by_search_without_rebuilding(tmp_path: Path, search_log):
    source = tmp_path / "notes.txt"
    source.write_text(
        (FIXTURES / "chapter1.txt").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    store = tmp_path / "index.json"
    client = get_client()

    build_index(source, store, client, model=MODEL)

    result = search_index("Who is Milly to Arnold?", store, client, model=MODEL)[0]
    _print_search_result("Who is Milly to Arnold?", result)
    search_log("Who is Milly to Arnold?", result, source="reuse-txt")
    assert "Milly" in result["text"]
    assert 0 <= result["score"] <= 1


@needs_api_key
def test_search_across_txt_chapters_returns_the_right_chapter(tmp_path: Path, search_log):
    combined = "\n\n".join(chapter.read_text(encoding="utf-8") for chapter in TXT_CHAPTERS)
    source = tmp_path / "book.txt"
    source.write_text(combined, encoding="utf-8")
    store = tmp_path / "index.json"
    client = get_client()

    chunk_count = build_index(source, store, client, model=MODEL)
    assert chunk_count >= 3
    print(f"\n[TXT] Indexed {chunk_count} chunks from 3 chapters.")

    cases = [
        ("Who did Sara's brother Arnold marry?", "Milly"),
        ("How did Sara travel from the railway station in the dark?", "dog-cart"),
        ("What did Mrs. Laird think about the young woman Graham had hired?", "Laird"),
    ]

    for question, must_contain in cases:
        result = search_index(question, store, client, model=MODEL)[0]
        _print_search_result(question, result)
        search_log(question, result, source="3-chapters")
        assert must_contain.lower() in result["text"].lower(), (
            f"Expected {must_contain!r} in the top chunk for {question!r}"
        )


@needs_api_key
def test_relevant_query_scores_higher_than_off_topic_query(tmp_path: Path, search_log):
    source = tmp_path / "book.txt"
    source.write_text(TXT_CHAPTERS[1].read_text(encoding="utf-8"), encoding="utf-8")
    store = tmp_path / "index.json"
    client = get_client()
    build_index(source, store, client, model=MODEL)

    on_topic = search_index("Sara arrived by train at a lonely station in the North.", store, client, model=MODEL)[0]
    off_topic = search_index("How do I center a div in CSS?", store, client, model=MODEL)[0]
    _print_search_result("[on-topic] Sara arrived by train ...", on_topic)
    _print_search_result("[off-topic] center a div in CSS", off_topic)
    search_log("Sara arrived by train ...", on_topic, source="on-topic")
    search_log("How do I center a div in CSS?", off_topic, source="off-topic")

    assert on_topic["score"] > off_topic["score"] + 0.15


@needs_api_key
def test_same_question_returns_the_same_top_chunk(tmp_path: Path):
    source = tmp_path / "book.txt"
    source.write_text(TXT_CHAPTERS[0].read_text(encoding="utf-8"), encoding="utf-8")
    store = tmp_path / "index.json"
    client = get_client()
    build_index(source, store, client, model=MODEL)

    first = search_index("Who is engaged to Arnold?", store, client, model=MODEL)[0]
    second = search_index("Who is engaged to Arnold?", store, client, model=MODEL)[0]
    assert first["text"] == second["text"]
    assert abs(first["score"] - second["score"]) < 1e-6


@needs_api_key
def test_unique_marker_paragraph_is_returned_for_its_query(tmp_path: Path, search_log):
    marker = "The quokka named Zephyr sails a purple sloop across Lake Windermere every third Tuesday."
    body = (TXT_CHAPTERS[0].read_text(encoding="utf-8") + "\n\n" + marker + "\n\n" +
            TXT_CHAPTERS[1].read_text(encoding="utf-8"))
    source = tmp_path / "book.txt"
    source.write_text(body, encoding="utf-8")
    store = tmp_path / "index.json"
    client = get_client()
    build_index(source, store, client, model=MODEL)

    question = "Tell me about the purple sloop that a quokka named Zephyr sails."
    result = search_index(question, store, client, model=MODEL)[0]
    _print_search_result(question, result)
    search_log(question, result, source="unique-marker")
    assert "Zephyr" in result["text"]
    assert "quokka" in result["text"].lower()


@needs_api_key
def test_search_over_pdf_finds_relevant_chunk(tmp_path: Path, search_log):
    store = tmp_path / "galaxy.json"
    client = get_client()

    chunk_count = build_index(PDF_FILE, store, client, model=MODEL)
    assert chunk_count >= 3
    print(f"\n[PDF] Indexed {chunk_count} chunks from {PDF_FILE.name}.")

    question = "What method was used to measure the spin of Sagittarius A*?"
    result = search_index(question, store, client, model=MODEL)[0]
    _print_search_result(question, result)
    search_log(question, result, source="pdf")

    text = result["text"].lower()
    assert "outflow" in text
    assert "sgr a" in text or "sagittarius" in text
    assert result["score"] > 0.2


@needs_api_key
def test_multiple_pdf_questions_each_hit_a_relevant_chunk(tmp_path: Path, search_log):
    store = tmp_path / "galaxy.json"
    client = get_client()
    build_index(PDF_FILE, store, client, model=MODEL)

    pdf_cases = [
        ("What is the dimensionless spin angular momentum of Sgr A*?", ["spin", "a*"]),
        ("What is the total dynamical mass of Sagittarius A*?", ["mass"]),
        ("Which method is used to derive the spin function F?", ["outflow"]),
    ]
    for question, must_contain_any in pdf_cases:
        result = search_index(question, store, client, model=MODEL)[0]
        _print_search_result(question, result)
        search_log(question, result, source="pdf")
        lowered = result["text"].lower()
        assert any(token in lowered for token in must_contain_any), (
            f"None of {must_contain_any} in top chunk for {question!r}"
        )
        assert result["score"] > 0.25


@needs_api_key
def test_search_returns_top_k_chunks_in_ranked_order(tmp_path: Path, search_log):
    combined = "\n\n".join(chapter.read_text(encoding="utf-8") for chapter in TXT_CHAPTERS)
    source = tmp_path / "book.txt"
    source.write_text(combined, encoding="utf-8")
    store = tmp_path / "index.json"
    client = get_client()
    build_index(source, store, client, model=MODEL)

    question = "How did Sara reach her destination after the train ride in the dark?"
    results = search_index(question, store, client, model=MODEL, top_k=3)

    assert len(results) == 3
    scores = [r["score"] for r in results]
    assert scores == sorted(scores, reverse=True), f"results not ranked: {scores}"
    assert len({r["text"] for r in results}) == 3

    print(f"\n[TOP-3] Q: {question}")
    for rank, item in enumerate(results, start=1):
        preview = item["text"][:120].replace("\n", " ").encode("ascii", errors="replace").decode("ascii")
        print(f"  [{rank}] score={item['score']:.4f}  {preview}...")
    search_log(question, results[0], source="top-k-1")
    search_log(question, results[1], source="top-k-2")
    search_log(question, results[2], source="top-k-3")


def test_search_index_rejects_zero_top_k(tmp_path: Path):
    payload = {"source": "x", "model": MODEL, "chunks": [{"text": "hi", "embedding": [0.1] * EXPECTED_DIM}]}
    store = tmp_path / "store.json"
    save_index(store, payload)
    with pytest.raises(ValueError, match="top_k"):
        search_index("anything", store, client=None, model=MODEL, top_k=0)

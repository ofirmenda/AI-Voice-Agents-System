"""API tests for the RAG service.

Uses fastapi.testclient with a stubbed embedding client so retrieval is
deterministic and no OpenAI credentials are required in CI.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from api import create_app


REPO_ROOT = Path(__file__).resolve().parents[3]
BAGGAGE_POLICY = REPO_ROOT / "docs" / "policies" / "baggage.md"
HEBREW_FIXTURE = Path(__file__).parent / "hebrew_sample.txt"

# A tiny fixed vocabulary is enough to make retrieval deterministic for the
# tests. Cosine similarity on these word-count vectors mirrors the shape of a
# real embedding-based ranking without needing an API call.
KEYWORDS = [
    "מזוודה",
    "כבודה",
    "Lite",
    "Classic",
    "Flex",
    "ק\"ג",
    "לאונג",
    "ארוחה",
    "כשר",
    "מושב",
    "צ'ק",
    "אין",
    "טיסה",
]


def _embed(text: str) -> list[float]:
    return [float(text.count(word)) for word in KEYWORDS]


class _StubEmbedding:
    def __init__(self, index: int, embedding: list[float]) -> None:
        self.index = index
        self.embedding = embedding


class _StubResponse:
    def __init__(self, data: list[_StubEmbedding]) -> None:
        self.data = data


class _StubEmbeddings:
    def create(self, input: list[str], model: str) -> _StubResponse:  # noqa: A002
        return _StubResponse([_StubEmbedding(i, _embed(t)) for i, t in enumerate(input)])


class StubClient:
    def __init__(self) -> None:
        self.embeddings = _StubEmbeddings()


@pytest.fixture
def api_client(tmp_path: Path):
    store = tmp_path / "index.json"
    app = create_app(client=StubClient(), store_path=store, model="stub-model")
    with TestClient(app) as client:
        yield client, store


def test_health_returns_zero_chunks_before_ingest(api_client):
    client, _ = api_client
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["chunks"] == 0
    assert body["source"] == ""


def test_search_returns_503_when_no_index_loaded(api_client):
    client, _ = api_client
    response = client.post("/search", json={"question": "כמה קילו מזוודה?"})
    assert response.status_code == 503


def test_search_empty_question_is_422(api_client):
    client, _ = api_client
    # ingest something so the 422 branch is reached rather than the 503 one.
    client.post("/ingest", json={"path": str(HEBREW_FIXTURE)})
    response = client.post("/search", json={"question": "   "})
    assert response.status_code == 422


def test_ingest_then_health_reports_chunks(api_client):
    client, store = api_client
    response = client.post("/ingest", json={"path": str(HEBREW_FIXTURE)})
    assert response.status_code == 200
    chunks_returned = response.json()["chunks"]
    assert chunks_returned >= 1

    health = client.get("/health").json()
    assert health["chunks"] == chunks_returned
    assert HEBREW_FIXTURE.name in health["source"] or str(HEBREW_FIXTURE) in health["source"]
    assert store.is_file()


def test_ingest_missing_file_is_422(api_client, tmp_path: Path):
    client, _ = api_client
    response = client.post("/ingest", json={"path": str(tmp_path / "nope.txt")})
    assert response.status_code == 422


def test_search_hebrew_baggage_question_returns_baggage_chunk(api_client):
    client, _ = api_client
    ingest = client.post("/ingest", json={"path": str(BAGGAGE_POLICY)})
    assert ingest.status_code == 200

    response = client.post(
        "/search",
        json={"question": "כמה קילו מזוודה מותרות לי בכרטיס Lite?", "top_k": 3},
    )
    assert response.status_code == 200

    results = response.json()["results"]
    assert len(results) == 3
    top = results[0]
    assert "text" in top and "score" in top

    # Chunk must be from baggage.md and touch on both the ticket type and the
    # bag concept the question asked about.
    assert "Lite" in top["text"]
    assert "מזוודה" in top["text"] or "כבודה" in top["text"]

    # Ranking is monotonic non-increasing.
    scores = [r["score"] for r in results]
    assert scores == sorted(scores, reverse=True)


def test_search_top_k_validation(api_client):
    client, _ = api_client
    client.post("/ingest", json={"path": str(HEBREW_FIXTURE)})
    response = client.post("/search", json={"question": "שלום", "top_k": 0})
    assert response.status_code == 422

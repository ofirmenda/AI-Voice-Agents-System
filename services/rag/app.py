"""Index TXT/PDF files and search their contents with OpenAI embeddings."""

from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from openai import OpenAI


DEFAULT_MODEL = "text-embedding-3-small"
DEFAULT_STORE = Path("data/index.json")


def extract_text(file_path: str | Path) -> str:
    """Extract UTF-8 text from a TXT file or text from every page of a PDF."""
    path = Path(file_path)
    if not path.is_file():
        raise FileNotFoundError(f"File not found: {path}")

    suffix = path.suffix.lower()
    if suffix in {".txt", ".md"}:
        text = path.read_text(encoding="utf-8")
    elif suffix == ".pdf":
        try:
            import pymupdf
        except ImportError as error:
            raise RuntimeError("Install project dependencies before reading PDFs.") from error

        with pymupdf.open(path) as document:
            text = "\n\n".join(page.get_text() for page in document)
    else:
        raise ValueError("Only .txt, .md and .pdf files are supported.")

    text = text.strip()
    if not text:
        raise ValueError(f"No text could be extracted from {path}.")
    return text


def chunk_text(text: str, chunk_size: int = 1000, overlap: int = 150) -> list[str]:
    """Split text into overlapping character chunks without creating empty chunks."""
    if chunk_size <= 0:
        raise ValueError("chunk_size must be greater than zero.")
    if overlap < 0 or overlap >= chunk_size:
        raise ValueError("overlap must be non-negative and smaller than chunk_size.")

    normalized = " ".join(text.split())
    if not normalized:
        return []

    chunks: list[str] = []
    start = 0
    step = chunk_size - overlap
    while start < len(normalized):
        end = min(start + chunk_size, len(normalized))
        chunks.append(normalized[start:end])
        if end == len(normalized):
            break
        start += step
    return chunks


def create_embeddings(client: OpenAI, texts: list[str], model: str = DEFAULT_MODEL) -> list[list[float]]:
    """Create one embedding vector for each input string."""
    if not texts:
        return []
    response = client.embeddings.create(input=texts, model=model)
    ordered = sorted(response.data, key=lambda item: item.index)
    return [item.embedding for item in ordered]


def cosine_similarity(left: list[float], right: list[float]) -> float:
    """Return cosine similarity for two vectors."""
    if len(left) != len(right):
        raise ValueError("Vectors must have the same length.")
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    if left_norm == 0 or right_norm == 0:
        return 0.0
    return sum(a * b for a, b in zip(left, right)) / (left_norm * right_norm)


def save_index(store_path: str | Path, index: dict[str, Any]) -> None:
    path = Path(store_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(index, indent=2), encoding="utf-8")


def load_index(store_path: str | Path) -> dict[str, Any]:
    path = Path(store_path)
    if not path.is_file():
        raise FileNotFoundError(f"Index not found: {path}. Run the index command first.")
    return json.loads(path.read_text(encoding="utf-8"))


def build_index(file_path: str | Path, store_path: str | Path, client: OpenAI, model: str) -> int:
    text = extract_text(file_path)
    chunks = chunk_text(text)
    embeddings = create_embeddings(client, chunks, model)
    save_index(
        store_path,
        {
            "source": str(Path(file_path)),
            "model": model,
            "chunks": [
                {"text": chunk, "embedding": embedding}
                for chunk, embedding in zip(chunks, embeddings)
            ],
        },
    )
    return len(chunks)


def rank_index(
    question: str,
    index: dict[str, Any],
    client: OpenAI,
    model: str,
    top_k: int = 3,
) -> list[dict[str, Any]]:
    """Rank an already-loaded index for a question. Used by the HTTP service."""
    if top_k < 1:
        raise ValueError("top_k must be at least 1.")
    question_embedding = create_embeddings(client, [question], model)[0]
    ranked = sorted(
        (
            {
                "text": item["text"],
                "score": cosine_similarity(question_embedding, item["embedding"]),
            }
            for item in index["chunks"]
        ),
        key=lambda item: item["score"],
        reverse=True,
    )
    if not ranked:
        raise ValueError("The index contains no chunks.")
    return ranked[:top_k]


def search_index(
    question: str,
    store_path: str | Path,
    client: OpenAI,
    model: str,
    top_k: int = 3,
) -> list[dict[str, Any]]:
    if top_k < 1:
        raise ValueError("top_k must be at least 1.")
    index = load_index(store_path)
    return rank_index(question, index, client, model, top_k)


def get_client() -> OpenAI:
    load_dotenv()
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is missing. Add it to a .env file.")
    return OpenAI(api_key=api_key)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Search TXT and PDF files with embeddings.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    index_parser = subparsers.add_parser("index", help="Extract, chunk, embed, and store a file.")
    index_parser.add_argument("file", type=Path)
    index_parser.add_argument("--store", type=Path, default=DEFAULT_STORE)
    index_parser.add_argument("--model", default=DEFAULT_MODEL)

    search_parser = subparsers.add_parser("search", help="Find the most relevant stored chunks.")
    search_parser.add_argument("question")
    search_parser.add_argument("--store", type=Path, default=DEFAULT_STORE)
    search_parser.add_argument("--model", default=DEFAULT_MODEL)
    search_parser.add_argument("--top-k", type=int, default=3, help="Number of chunks to return.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    client = get_client()
    if args.command == "index":
        count = build_index(args.file, args.store, client, args.model)
        print(f"Indexed {count} chunks from {args.file} into {args.store}.")
    else:
        results = search_index(args.question, args.store, client, args.model, args.top_k)
        for rank, result in enumerate(results, start=1):
            print(f"[{rank}] Score: {result['score']:.4f}\n{result['text']}\n")


if __name__ == "__main__":
    main()

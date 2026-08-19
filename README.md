# File Embedding Search

![tests](https://github.com/ofirmenda/part-2-home-assesment/actions/workflows/tests.yml/badge.svg)

A small Python CLI that extracts text from `.txt` and `.pdf` files, splits it into overlapping chunks, creates OpenAI embeddings, stores them in a local JSON file, and returns the most relevant chunks for a question.

## Setup

1. Create and activate a virtual environment:

   ```powershell
   py -m venv .venv
   .\.venv\Scripts\Activate.ps1
   ```

2. Install dependencies:

   ```powershell
   pip install -r requirements.txt
   ```

3. Copy `.env.example` to `.env` and add your OpenAI API key. Never commit `.env`.

## Usage

Index a text or PDF file:

```powershell
python app.py index path\to\document.pdf
```

This writes the embeddings to `data/index.json`, which is ignored by Git.

Search the indexed document (returns the top 3 chunks by default):

```powershell
python app.py search "What is the main topic?"
```

Change how many chunks come back with `--top-k`:

```powershell
python app.py search "What is the main topic?" --top-k 5
```

Use a different index location or embedding model with `--store` and `--model`:

```powershell
python app.py index notes.txt --store data/notes.json --model text-embedding-3-small
python app.py search "Explain the conclusion" --store data/notes.json
```

Search uses cosine similarity between the question embedding and each stored chunk embedding. The JSON index is intentionally simple and local; it can later be replaced with a vector database without changing text extraction or chunking.

## Tests

```powershell
pytest -v
```

28 tests in total. Live-API tests (embeddings, end-to-end search over the TXT and PDF fixtures under `tests/`) auto-skip when `OPENAI_API_KEY` is not set. After each run, a full report — pass/fail per test and the questions/scores/top chunks for every live search — is written to `test_results.txt` (gitignored).

## CI

GitHub Actions runs the suite on every push and pull request to `main`, installing dependencies and running `pytest`. Live-API tests are skipped there (no key configured), so CI validates the pure logic and the file-extraction path.

## Upload To GitHub

Create an empty repository on GitHub, then run:

```powershell
git add .
git commit -m "Build file embedding search CLI"
git branch -M main
git remote add origin https://github.com/YOUR-USERNAME/YOUR-REPOSITORY.git
git push -u origin main
```

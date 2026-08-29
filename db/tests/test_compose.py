"""Sanity checks on the deployment plumbing.

Not a substitute for actually running `docker compose up`, but catches things
like renamed services, missing env keys, or broken image references before
they hit a machine that has Docker installed.
"""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
COMPOSE = REPO_ROOT / "docker-compose.yml"
ENV_EXAMPLE = REPO_ROOT / ".env.example"
RAG_DOCKERFILE = REPO_ROOT / "services" / "rag" / "Dockerfile"
WEBHOOK_DOCKERFILE = REPO_ROOT / "services" / "webhook" / "Dockerfile"


def test_compose_defines_required_services():
    text = COMPOSE.read_text(encoding="utf-8")
    for service in ("postgres:", "rag:", "webhook:", "langflow:"):
        assert service in text, f"missing service: {service}"


def test_compose_mounts_init_sql_into_postgres_entrypoint():
    text = COMPOSE.read_text(encoding="utf-8")
    assert "./db/init.sql:/docker-entrypoint-initdb.d/" in text


def test_compose_has_postgres_healthcheck_and_dependents_wait_for_it():
    text = COMPOSE.read_text(encoding="utf-8")
    assert "pg_isready" in text
    # webhook and langflow both wait on postgres being healthy.
    assert text.count("condition: service_healthy") >= 3  # db-seed, webhook, langflow


def test_compose_uses_named_volume_for_postgres_data():
    text = COMPOSE.read_text(encoding="utf-8")
    assert "postgres-data:/var/lib/postgresql/data" in text
    assert "\nvolumes:" in text
    assert "  postgres-data:" in text


def test_env_example_lists_required_keys():
    text = ENV_EXAMPLE.read_text(encoding="utf-8")
    for key in (
        "POSTGRES_USER",
        "POSTGRES_PASSWORD",
        "POSTGRES_DB",
        "DATABASE_URL",
        "OPENAI_API_KEY",
        "WEBHOOK_SECRET",
    ):
        assert f"{key}=" in text, f"missing env key: {key}"


def test_env_file_is_gitignored():
    gitignore = (REPO_ROOT / ".gitignore").read_text(encoding="utf-8")
    assert ".env" in gitignore.splitlines()


def test_dockerfiles_exist_and_expose_uvicorn():
    for path in (RAG_DOCKERFILE, WEBHOOK_DOCKERFILE):
        text = path.read_text(encoding="utf-8")
        assert "FROM python:" in text
        assert "uvicorn" in text
        assert "EXPOSE 8000" in text

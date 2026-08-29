FROM python:3.12-slim

WORKDIR /app

COPY services/rag/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY services/rag/app.py services/rag/api.py ./
# Bundle the Hebrew corpus so a fresh container can be ingested without an
# extra volume mount; docker-compose still mounts docs/policies read-only.
COPY docs/policies /app/docs/policies

EXPOSE 8000
CMD ["uvicorn", "api:app", "--host", "0.0.0.0", "--port", "8000"]

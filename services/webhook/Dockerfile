FROM python:3.12-slim

WORKDIR /app

COPY services/webhook/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY services/webhook/main.py services/webhook/repository.py ./

EXPOSE 8000
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]

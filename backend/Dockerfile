FROM python:3.12-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY alembic ./alembic
COPY alembic.ini .
COPY scripts ./scripts

EXPOSE 8000
# Render (and similar platforms) inject PORT at runtime and expect the
# container to bind to it; default to 8000 for local `docker run`.
# Migrations deliberately do NOT run here (see README.md -- avoids races
# against production replicas); render.yaml runs them as a pre-deploy step.
ENV PORT=8000
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT}"]

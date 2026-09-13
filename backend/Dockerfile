FROM python:3.12-slim

WORKDIR /app

# Install curl for healthchecks (optional but good practice)
RUN apt-get update && apt-get install -y curl && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Run uvicorn on 0.0.0.0:8000 (and run migrations / seed first)
CMD sh -c "alembic upgrade head && python add_admin.py && uvicorn app.main:app --host 0.0.0.0 --port 8000"

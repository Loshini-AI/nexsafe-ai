FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends libgl1 libglib2.0-0 && rm -rf /var/lib/apt/lists/*
COPY requirements.txt vision-requirements.txt ./
RUN pip install --no-cache-dir -r vision-requirements.txt
COPY app ./app
COPY training ./training
COPY datasets ./datasets
COPY configs ./configs
COPY alembic.ini .
COPY migrations ./migrations
EXPOSE 8000
CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000"]

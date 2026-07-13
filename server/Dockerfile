FROM python:3.12-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app ./app

ENV DATABASE_PATH=/data/songdrop.db
# Create the data dir so the image runs standalone; mount a volume here to persist.
RUN mkdir -p /data
VOLUME /data
EXPOSE 8585
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8585"]

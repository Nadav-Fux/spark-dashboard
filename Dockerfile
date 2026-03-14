FROM python:3.11-slim

WORKDIR /app

RUN pip install --no-cache-dir fastapi uvicorn psutil httpx python-dotenv

COPY backend/app.py .
COPY frontend/index.html /root/spark-dashboard/frontend/index.html

RUN mkdir -p /root/spark-dashboard/data
COPY data/jobs.json /root/spark-dashboard/data/jobs.json

EXPOSE 8888

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8888"]

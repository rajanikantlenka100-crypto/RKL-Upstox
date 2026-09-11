FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 TZ=Asia/Kolkata
WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
RUN mkdir -p /app/logs /app/reports /app/data

HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 CMD python healthcheck.py

CMD ["python", "main.py"]

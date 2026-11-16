FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY validation.py ingestion.py ./
USER 1000
CMD ["python", "-u", "ingestion.py"]
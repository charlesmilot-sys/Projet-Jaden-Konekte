# Conteneur de tests : le dépôt est monté en lecture seule dans /depot (voir compose.yaml)
FROM python:3.12-slim
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
ENV PYTHONDONTWRITEBYTECODE=1
WORKDIR /depot
CMD ["pytest", "-v", "-p", "no:cacheprovider", "tests"]

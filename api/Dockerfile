FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app ./app
COPY static ./static
# Dossier des photos de diagnostic, appartenant à l'utilisateur 1000 (le volume en hérite)
RUN mkdir -p /donnees/images && chown 1000:1000 /donnees/images
USER 1000
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
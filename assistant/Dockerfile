# Contexte de construction : la racine du dépôt (voir compose.yaml et .dockerignore)
FROM python:3.12-slim
WORKDIR /app
COPY assistant/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
# Le modèle d'embeddings (~220 Mo) est téléchargé UNE FOIS, à la construction de l'image :
# le conteneur démarre ensuite sans dépendre d'Internet pour les embeddings.
ENV DOSSIER_EMBEDDINGS=/modele-embeddings
RUN python -c "from fastembed import TextEmbedding; TextEmbedding('sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2', cache_dir='/modele-embeddings')" \
 && chown -R 1000:1000 /modele-embeddings
ENV HF_HUB_OFFLINE=1
COPY assistant/*.py ./
COPY ia/rag/questions_reference.json ./
COPY ia/rag/fiches /fiches
USER 1000
EXPOSE 8002
CMD ["uvicorn", "service:app", "--host", "0.0.0.0", "--port", "8002"]

# Contexte de construction : la racine du dépôt (voir compose.yaml et .dockerignore)
FROM python:3.12-slim
WORKDIR /app
COPY inference/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY inference/service.py ia/cnn/pretraitement.py ./
COPY ia/cnn/classes_fr.json ia/cnn/modele/classes.json /modele/
COPY ia/cnn/modele/tomate_mobilenetv3.onnx ia/cnn/modele/tomate_mobilenetv3.onnx.data /modele/
USER 1000
EXPOSE 8001
CMD ["uvicorn", "service:app", "--host", "0.0.0.0", "--port", "8001"]

# Corpus pour l'assistant agronome (RAG)

- `fiches/` : six fiches techniques simplifiées (Markdown), à indexer.
  Découpez-les par section (titres `##`) : chaque passage garde le nom du fichier et le titre de section, pour citer les sources.
- `questions_reference.json` : 20 questions de référence pour **évaluer** votre assistant
  (source attendue + éléments attendus). La question 20 est volontairement hors corpus :
  l'assistant doit le dire au lieu d'inventer.

Pistes techniques :
- Embeddings multilingues (par exemple un modèle sentence-transformers multilingue de dimension 384,
  à adapter à la colonne `passage.embedding` de `infra/sql/schema.sql`).
- Recherche vectorielle avec pgvector : `ORDER BY embedding <=> :q LIMIT 5`.
- LLM via l'API d'un fournisseur ou en local (Ollama, vLLM). La clé d'API reste côté serveur.
- Réponse en streaming (SSE) et liste des sources citées.

Ces fiches sont pédagogiques : elles ne constituent pas des recommandations agronomiques officielles.

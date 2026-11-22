FROM node:22-slim AS ui
WORKDIR /ui
COPY ui/package*.json ./
RUN npm ci
COPY ui/ ./
RUN npm run build

FROM python:3.12-slim
WORKDIR /app
ENV SG_ROOT=/app PIP_NO_CACHE_DIR=1
COPY pyproject.toml ./
COPY src ./src
# Editable install: ontology/, shapes/, mappings/, sparql/ and config/ are resolved relative to SG_ROOT.
RUN pip install -e ".[etl,llm]" && pip install torch --index-url https://download.pytorch.org/whl/cpu
COPY ontology ontology
COPY shapes shapes
COPY mappings mappings
COPY sparql sparql
COPY config config
COPY --from=ui /ui/dist ui/dist
RUN mkdir -p data models
EXPOSE 8000
CMD ["uvicorn", "suppliergraph.api.main:app_factory", "--factory", "--host", "0.0.0.0", "--port", "8000"]

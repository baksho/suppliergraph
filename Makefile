.PHONY: install test lint ui pipeline serve docker
install:
	pip install -e ".[etl,ml,llm,dev]" && cd ui && npm install
test:
	pytest
lint:
	ruff check src tests
ui:
	cd ui && npm run build
pipeline:            # needs real files in data/raw, see docs/data_sources.md
	sg init-db && sg ingest && sg resolve && sg extract && sg build-kg && sg validate && sg er-eval
serve:
	sg serve
docker:
	docker compose up --build

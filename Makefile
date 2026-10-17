# IncuBrix Long-Tail Distribution — Makefile
# All commands work with zero API keys (SIMULATION_MODE=true, LLM_PROVIDER=mock)

.PHONY: up down test test-docker logs shell migrate openapi-check clean

# ── Local dev ────────────────────────────────────────────────
up:
	docker compose up --build -d
	@echo "✅ All services started. API at http://localhost:8000/docs"

down:
	docker compose down -v

logs:
	docker compose logs -f api

shell:
	docker compose exec api bash

# ── Tests (no API keys required) ────────────────────────────
test:
	SIMULATION_MODE=true LLM_PROVIDER=mock \
	DATABASE_URL=sqlite+aiosqlite:///./test.db \
	REDIS_URL=redis://localhost:6379/99 \
	MINIO_ENDPOINT=localhost:9000 \
	pytest tests/ -v --tb=short --cov=api --cov=connectors --cov-report=term-missing

# Run tests in Docker (full integration, all services)
test-docker:
	docker compose --profile test up --build --abort-on-container-exit test-runner

# ── Batch runner (Integration Standard #10) ──────────────────
batch:
	python batch_runner.py --input tests/batch_inputs/ --output tests/batch_results/ --base-url http://localhost:8000

batch-docker:
	docker compose exec api python batch_runner.py --input /app/tests/batch_inputs/ --output /app/tests/batch_results/

# ── Catalogue import ─────────────────────────────────────────
import-catalogue:
	curl -F "file=@catalogue/real_destinations.csv" http://localhost:8000/api/v1/catalogue/import

# ── Recommender eval ─────────────────────────────────────────
eval-recommender:
	python catalogue/recommender_eval.py

# ── Database migrations ──────────────────────────────────────
migrate:
	docker compose exec api alembic upgrade head

migration:
	docker compose exec api alembic revision --autogenerate -m "$(MSG)"

# ── OpenAPI spec validation ──────────────────────────────────
openapi-check:
	@echo "Checking openapi.yaml matches running service..."
	curl -sf http://localhost:8000/openapi.json | python -c "import sys,json,yaml; \
		spec=json.load(sys.stdin); \
		local=yaml.safe_load(open('openapi.yaml')); \
		sys.exit(0 if spec.get('info',{}).get('version')==local.get('info',{}).get('version') else 1)" \
	&& echo "✅ openapi.yaml matches" || echo "❌ openapi.yaml mismatch — regenerate it"

openapi-generate:
	curl -sf http://localhost:8000/openapi.json | python -m json.tool --json-decoder json > /tmp/openapi.json
	python -c "import json,yaml; d=json.load(open('/tmp/openapi.json')); yaml.dump(d,open('openapi.yaml','w'),allow_unicode=True)"
	@echo "✅ openapi.yaml regenerated"

# ── Cleanup ──────────────────────────────────────────────────
clean:
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -name "*.pyc" -delete 2>/dev/null || true
	rm -f test.db

.PHONY: format lint test test-infra test-coverage makemigrations

format:
	uv run ruff check . --fix
	uv run ruff format .
	@sh scripts/check-format-excludes.sh

lint:
	uv run mypy src tests
	uv run flake8 src tests

test:
	uv run pytest -m "not infrastructure"

test-coverage:
	uv run pytest -m "not infrastructure" --cov=src --cov-branch --cov-report=term-missing --cov-report=html:artifacts/coverage/html --cov-report=json:artifacts/coverage/coverage.json --cov-fail-under=95 -ra

test-infra:
	@uv run pytest -m infrastructure; status=$$?; \
	if [ $$status -eq 5 ]; then echo "Infrastructure-тесты отсутствуют."; exit 0; fi; \
	exit $$status

makemigrations:
	docker exec \
	-u "$$(id -u):$$(id -g)" \
	-e UV_CACHE_DIR="/tmp/uv-cache-$$(id -u)" \
	-w /app/src \
	eqsitecms-yandex-service \
	uv run --no-sync alembic revision --autogenerate -m "$(msg)"

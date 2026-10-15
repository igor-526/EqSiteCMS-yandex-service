# FastAPI Template

Пустой шаблон FastAPI с Clean Architecture, PostgreSQL и эндпоинтом проверки состояния.

## Стек

- Python 3.14.6
- FastAPI
- SQLAlchemy Core + asyncpg
- PostgreSQL 17
- Alembic
- Sentry (опционально)

## Архитектура

```text
src/
├── api/             # HTTP-контракты
├── core/            # сущности, схемы, протоколы и бизнес-логика
├── depends/         # сборка зависимостей FastAPI
├── models/          # SQLAlchemy Core tables
├── repositories/    # реализации repository protocols
├── migration/       # Alembic
├── utils/           # База данных и инфраструктурные утилиты
├── main.py
└── settings.py
```

## Запуск в Docker

```bash
cp .env.example .env
docker compose up --build
```

Compose дождётся PostgreSQL, применит миграции и запустит API на `http://localhost:8000`.
Swagger доступен на `http://localhost:8000/docs`.
Контейнеры объединяются в Compose-проект `fastapi-template`. Каталог `src` подключён как bind mount,
а Uvicorn автоматически перезапускает приложение при изменении исходного кода.

## Локальная разработка

```bash
cp .env.example .env
uv sync
docker compose up -d db
uv run alembic -c src/alembic.ini upgrade head
uv run uvicorn main:app --app-dir src --reload
```

```bash
make format
make lint
make test
```

## API

| Метод | Путь | Назначение |
|---|---|---|
| GET | `/health` | Healthcheck |

Пакеты `api`, `core`, `depends`, `models` и `repositories` оставлены как точки расширения для новых бизнес-фич.

Sentry включается через `SENTRY_ENABLED=true` и `SENTRY_DSN`. Prometheus в шаблон не входит.

## Тесты сервиса Яндекса

```bash
uv sync --group dev
uv run pytest --collect-only -q
make test
make test-coverage
```

`make test` запускает автономные unit/component/API тесты без PostgreSQL и внешних
сервисов. `tests/conftest.py` задаёт фиктивные ENV до runtime imports, блокирует
DNS/TCP и восстанавливает provider/dependency overrides. Для настроек создавайте
экземпляры с `_env_file=None`. Не используйте runtime credentials или `.env` в тестах.
HTTP-клиенты проверяются через `tests.helpers.mock_http_transport`, API — через
`httpx.ASGITransport`; `override_providers` очищает scoped overrides даже при ошибке.

`make test-coverage` измеряет `src` с ветвями (исключены только миграции), выводит
пропуски в терминале и сохраняет HTML/JSON в `artifacts/coverage/`. Gate combined
coverage — 95%; отдельно проверяется отношение `covered_branches / num_branches`
в JSON (не менее 90%). Добавление harness само по себе не означает достижения gate.

Реальные PostgreSQL тесты помечены `infrastructure`; задайте `TEST_DATABASE_URL`
для выделенной тестовой БД и выполните `make test-infra`. Они не используют runtime
DB URL. Если URL отсутствует, результат — явный skip, PostgreSQL не проверен.
Этот маркер разрешает инфраструктурным тестам TCP/DNS.

Baseline harness (2026-10-14): 32 collected / 32 passed; combined coverage 71.375%,
branches 12/66 (18.182%). Исходный TestClient зависает в ограниченном sandbox
на AnyIO blocking portal; тот же suite вне sandbox проходит. Runtime-код для
обхода этого ограничения не изменялся.

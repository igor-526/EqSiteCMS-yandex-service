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

## Внутренний peer-контракт Y5

| ID | Метод | Путь | Access class | Роли | Без авторизации | С Cookie/Bearer |
|---|---|---|---|---|---|---|
| Y5 | GET | `/api/servicing/access-token/{account_id}` | Sensitive Private Peer Read exception | доверенный внутренний сервис ya-metrica | `200 {"enc_access_token": "<ciphertext>"}`; malformed/отсутствующий аккаунт → `400` | то же |

Y5 возвращает сохранённый `enc_access_token` **без расшифровки**. Поле `access_token`
и открытый OAuth-токен в ответе отсутствуют. Это breaking change внутреннего контракта;
потребитель `ya-metrica-service` расшифровывает ciphertext общим `ENCRYPTION_SERVICE_KEY`.
Cookie/Bearer не проверяются и не дают дополнительных прав: в доверенном peer-контуре
валидный аккаунт другого tenant имеет тот же контракт, неизвестный — `400`.

Ciphertext остаётся чувствительным: Y5 не является Public Read для сайтов/CMS.
Исключение сохраняется только в согласованном dev-окружении; production deployment
блокируется без подтверждённой защиты чувствительных peer APIs от внешних anonymous
callers. Этот change не добавляет сервисную аутентификацию и не доказывает сетевую изоляцию.

Регрессия: `UT-YS-01..04` в `tests/unit/test_service_authorization.py` и
`tests/api/test_servicing.py` (ciphertext, отсутствие decrypt/plaintext, безопасные ошибки,
anonymous/Cookie/Bearer, чужой tenant).

## Список привязок Метрики (Y10)

`GET /api/connections/metrica?limit=100&offset=0` возвращает внутренний реестр
привязок для ежедневного расписания seo-service. `limit` — 1..500 (по умолчанию
100), `offset` — целое ≥0 (по умолчанию 0). Сортировка стабильная по
`equestrian_id`, `total` — количество всех привязок независимо от страницы.

```json
{"total": 1, "items": [{"equestrian_id": "22222222-2222-4222-8222-222222222222", "counter_id": "42"}]}
```

Нет привязок → `{"total": 0, "items": []}`; offset за пределами списка → пустые
`items` с общим `total`. Каждый элемент содержит ровно два поля: `equestrian_id`
(UUID) и `counter_id` (строка), без токенов и данных аккаунта. Невалидные или
нечисловые параметры пагинации → `400` без отражения входных значений.
Существующий `GET /api/connections/metrica/{equestrian_id}` не меняется.

| ID | Метод | Путь | Access class | Роли | Без авторизации | С Cookie/Bearer |
|---|---|---|---|---|---|---|
| Y10 | GET | `/api/connections/metrica` | Private Peer Read exception | доверенный внутренний caller (seo-service scheduler) | `200 {total, items}`; invalid `limit`/`offset` → `400` | то же; Cookie/Authorization игнорируются |

Причина исключения из Public Read: это внутренний операционный реестр, не API
публичных `site-*`. Контракт credential-less: peer credentials не добавляются,
пользовательские cookie/Bearer не дают прав. Сохраняется dev-допущение Q2;
production deployment/release блокируется до подтверждения защиты чувствительных
peer APIs от внешних anonymous callers. Этот endpoint не доказывает production
изоляцию и не меняет существующие auth/network boundaries.

Проверки: `UT-YB-01` — `tests/api/test_yandex_connections.py`; `IT-YB-01` —
`tests/integration/test_counter_repository_postgres.py`. Для последней нужен
`TEST_DATABASE_URL` (`postgresql+asyncpg://...`): fixture создаёт уникальную
тестовую схему и удаляет только её, не затрагивая существующие данные.

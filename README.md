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

## Lifecycle и атомарные мутации (106–107)

Additive Alembic head `9e106a107001` следует за `61c3a74f4ba9`.
`metrica_tenant_lifecycle` хранит независимые от FK привязки generation и requested/completed
watermarks; существующие non-null binding tenant получают generation=1, seq=0.
`metrica_cleanup_operations` — ledger с unique `(equestrian_id, cleanup_seq)`;
`metrica_lifecycle_outbox` — pending/published, retry/claim lease и сохранённый message ID;
`metrica_lifecycle_inbox` — dedup `(consumer, message_id)` и hash для проверки повтора.
Связи outbox/inbox с ledger tenant-qualified; binding_id — snapshot без FK/cascade.

Storage primitives `MetricaLifecycleRepository` не коммитят: все tenant locks берутся
в отсортированном UUID порядке **до** account/binding locks в той же сессии.
DELETE реальной привязки под tenant lock увеличивает requested_seq, сохраняет ledger
и outbox перед удалением. Повторный DELETE по старому UUID — no-op. Account DELETE
собирает FK-контекст, повторно проверяет его после account lock и создаёт ту же cleanup
операцию для каждой реально связанной конюшни до cascade. Если concurrent rebind
расширил набор tenants, savepoint откатывает locks и discovery повторяется в UUID порядке.
Несвязанный аккаунт не создаёт cleanup. Всё использует одну request session через DI;
ошибка commit/outbox откатывает binding/account и ledger вместе.

Rebind под тем же tenant lock увеличивает generation только при реальном изменении,
сохраняет requested/completed watermarks; identical POST — no-op.
Outbox хранит безопасный envelope v1 без credentials/PII, subject
`events.yandex.metrica.cleanup.requested`, стабильный message_id UUIDv5 с suffix
`requested`. HTTP успех означает сохранённое намерение, не завершённую очистку.
**Producer transport, relay и completed consumer включены в lifespan**.
Relay публикует pending outbox; completed consumer снимает barrier только после
commit inbox/ledger и продвижения непрерывного completed prefix.

Развёртывание требует maintenance window без старых parse workers/admissions.
Rollback до активации producers: оставить additive таблицы предпочтительнее downgrade.
Downgrade явно запрещён при **любой** истории cleanup/outbox/inbox или requested_seq>0,
включая completed: поздняя доставка не должна встретить сброшенный watermark.
После активации — остановить admissions, сохранить ledger/сообщения, использовать
forward-fix либо согласованный backup, не удалять таблицы вручную.

Targeted schema tests: `uv run pytest tests/unit/test_metrica_lifecycle.py`.
PG fixtures IT-D-01 (schema, rollback, cascade, concurrent DELETE/rebind): `uv run pytest tests/integration/test_metrica_lifecycle_postgres.py`.
Нужна выделенная `TEST_DATABASE_URL` (не runtime DB); её отсутствие — FAIL, не PASS/skip.
Тесты создают и удаляют только уникальную тестовую schema; не запускать на production.
IT-D-01 также проверяет атомарность DELETE/rebind/FK cascade; outbox lease-тесты
проверяют concurrent claim, expiry/reclaim, fencing и published mark после PubAck.

### Private binding snapshot (Y-2, DTO slice)

`GET /api/connections/metrica/{equestrian_id}` — Private Peer Read exception:
доверенная внутренняя сеть, без user auth; Cookie/Bearer не меняют результат.
Malformed UUID остаётся безопасным 400 до storage; валидный UUID возвращает 200.
Рядом с `counter` всегда присутствуют обязательные неотрицательные
`binding_generation`, `cleanup_requested_seq`, `cleanup_completed_seq`, в том числе
при `counter=null`. Для pristine tenant все три равны 0; после DELETE watermark
сохраняется при null и при rebind. Binding и lifecycle читаются одним SQL statement
(MVCC snapshot), без создания tenant/lock на GET. Binding без lifecycle — безопасный
отказ 400, а не generation=0. Ошибка storage/commit не превращается в пустой 200.
Никакие OAuth tokens не возвращаются; вложенный account DTO остаётся прежним.
CMS gateway обязан явно проецировать прежний безопасный DTO, не проксировать lifecycle.
Внешние сервисы в этом slice не изменены. Production network isolation остаётся gate.

Проверки UT-D-02/04/07: `tests/api/test_yandex_connections.py`,
`tests/unit/test_metrica_lifecycle.py`, `tests/unit/test_yandex_metrica_counter_service.py`.
PG snapshot: `tests/integration/test_metrica_lifecycle_postgres.py` (только выделенная
`TEST_DATABASE_URL`, её отсутствие — blocker). Transport/settings/recovery документация
producer и consumer результата подключены к lifespan (Y-2c).

### Maintenance producer: контракт и outbox relay (Y-2b)

Канонический wire-контракт: `docs/asyncapi.yaml`. Owner yandex создаёт только
`YANDEX_LIFECYCLE`, точный subject `events.yandex.metrica.cleanup.requested`.
FILE/LIMITS, max_age=0, без вытеснения старых команд; overflow оставляет pending
outbox. Result stream `METRICA_MAINTENANCE_RESULTS` принадлежит Метрике:
yandex выполняет только lookup, durable `yandex-metrica-cleanup-completed`
(consumer и ledger-prefix включены в Y-2c). Msg-Id детерминирован из subject/operation/
`requested`, payload сохранён DELETE-транзакцией; повтор не генерирует новый ID.

`CleanupOutboxRepository` забирает одну due pending строку через SKIP LOCKED,
фиксирует claim token/lease и attempts отдельной короткой транзакцией.
`CleanupOutboxRelay` публикует вне транзакции через `CleanupPublisherProtocol`;
адаптер обязан дождаться PubAck и передать duplicate flag. Duplicate логируется
warning и считается доставленным повтором. Отметка published проверяет token,
status и неистёкший lease. Ошибка publish оставляет pending с задержкой
1,2,4,8,16,32,60 секунд, без cap удаления. Ошибка mark/commit и отмена процесса
восстанавливаются по истёкшему lease при следующем claim. Это at-least-once:
consumer inbox обязателен также после broker duplicate window. Диагностика не
содержит payload, текст исключений, адреса соединений или OAuth данные.

**Runtime Y-2b2:** `nats-py` закреплён в сервисном `uv.lock`. Модульный
`containers.container` (`ApplicationContainer`) собирает singleton NATS client,
publisher и outbox repository с независимыми короткими DB sessions через
`AsyncSessionLocal`; relay создаётся на каждый lifespan. Порядок запуска:
bounded connect → owner stream setup/проверка совместимости → foreign stream
lookup и completed durable → task `cleanup-outbox-relay` → HTTP serving. Несовместимый stream не переписывается:
startup завершается ошибкой, требуется проверка оператора, не удаление stream.
Первичное подключение ограничено общим connect timeout (не только timeout
одного адреса); setup/connect повторяется до `NATS_SETUP_MAX_ATTEMPTS`, backoff
`NATS_SETUP_BACKOFF_SECONDS × номер попытки`. После подключения reconnect
не ограничен числом попыток; publish error оставляет намерение в outbox.

При shutdown relay отменяется и дожидается остановки до drain/close NATS,
затем dispose DB. Отмена publish/mark оставляет claim для восстановления после
lease expiry; рестарт публикует тот же сохранённый envelope/Msg-Id. Drain во
время reconnect безопасно переходит в close. HTTP startup невозможен при
исчерпании NATS startup retries. `/health` по-прежнему не является ongoing
JetStream readiness probe. Дополнительный Redis DB, отдельный процесс и
compose-правки не нужны. Completed consumer и foreign stream lookup работают
в том же lifespan; HTTP startup ждёт готовности обоих направлений.

Рабочие knobs (`NatsSettings`, отдельный класс с `NATS_` aliases):

| Переменная | Default | Назначение |
|---|---|---|
| `NATS_SERVERS` | `nats://localhost:4222` | Адреса через запятую, непустой список |
| `NATS_SETUP_MAX_ATTEMPTS` | 10 | Bounded startup/foreign stream lookup retry |
| `NATS_SETUP_BACKOFF_SECONDS` | 2 | Линейный startup backoff |
| `NATS_CONNECT_TIMEOUT_SECONDS` | 5 | Timeout подключения |
| `NATS_PUBLISH_TIMEOUT_SECONDS` | 5 | Timeout ожидания PubAck |
| `NATS_RELAY_POLL_SECONDS` | 1 | Пауза пустой очереди/ошибки storage |
| `NATS_RELAY_CLAIM_SECONDS` | 30 | Lease, строго больше publish timeout |
| `NATS_ERROR_REPORT_AFTER_ATTEMPTS` | 5 | Порог безопасной эскалации |

При потере брокерного storage оператор восстанавливает команды из producer
ledger/outbox после проверки корреляции; не поднимать completed watermark вручную
и не удалять pending строки ради снятия barrier. После штатного рестарта pending
и expired claims должны доставляться автоматически подключённым relay.
NATS — Internal Trusted Network Write, без user roles; development plaintext не
является production security approval. Production требует изоляции сети/ACL и
контроля дискового бюджета. `/health` не доказывает готовность JetStream.
Unit tests используют fake publisher/storage и НЕ заменяют real PG/NATS gates.


Scoped producer/runtime verification:
```bash
uv lock --check
uv pip check
uv run pytest tests/unit/test_cleanup_outbox_relay.py tests/unit/test_nats_cleanup_runtime.py tests/api/test_lifespan.py
# Только выделенный JetStream test broker; отсутствие TEST_NATS_URL — FAIL, не skip.
uv run pytest tests/integration/test_cleanup_nats_transport.py -m infrastructure
```
Real-broker fixture использует UUID-named stream/subject, проверяет owner setup,
restart и duplicate PubAck, очищает только свои ресурсы. Он не заменяет real-PG
lease/transaction и consumer inbox/result gate IT-D-01. После длительного
простоя pending/expired claims восстанавливаются без ручной смены message_id.
После потери broker storage оператор сверяет producer ledger/outbox и возвращает
проверенные операции к повторной публикации с прежними ID; published строки сами
не реплеятся. Нельзя удалять volumes/ledger или вручную повышать completed seq.


### Completed consumer и восстановление watermark (Y-2c)

После owner setup выполняется lookup `METRICA_MAINTENANCE_RESULTS` и bind
pull durable `yandex-metrica-cleanup-completed`, filter
`events.metrica.cleanup.completed`, ALL / explicit ACK / ack_wait=30s /
max_deliver=-1. Чужой stream никогда не создаётся и не переписывается сервисом;
`NotFound` повторяется до 10 раз с линейным шагом 2s (те же NATS_SETUP knobs).
Несовместимая конфигурация или BadRequest завершают startup сразу. Поэтому при
развёртывании сначала нужен owner Метрика; production requires его readiness.
При рестарте используется прежний durable с retained backlog, не DeliverNew.

Envelope v1 строго проверяет UUID, UTC, positive bigint cleanup_seq,
status=completed, отсутствие лишних полей и header `Nats-Msg-Id`. Его UUIDv5:
`uuid5(NAMESPACE_URL, "eqcms:maintenance:v1:events.metrica.cleanup.completed:<operation_id>:completed")`.
В inbox сохраняется SHA-256 канонического типизированного JSON (порядок полей и
пробелы wire JSON не влияют на hash). Один message_id с изменённым содержимым —
TERM, не новый эффект. Invalid schema/header/tenant/operation/seq — TERM и безопасная
диагностика без payload/секретов. Ошибка DB/commit — NAK с 1..60s backoff без cap;
после 5 доставок эскалация. Обработка ограничена 25s, меньше ack_wait; fetch batch=1.

Короткая транзакция берёт существующий tenant row lock (как DELETE/rebind),
сверяет собственный ledger, записывает inbox unique(consumer,message_id), отмечает
operation completed и повышает watermark только по непрерывному completed-префиксу
после текущего значения. seq=2 до seq=1 не повышает watermark; поздний seq=1 не
разрешает seq=3. Неизвестные операции и пропуски ledger не превращаются в max(seq).
Binding и generation обработчик результата никогда не меняет.
ACK отправляется только после commit, включая повтор. Crash до commit откатывает
все три эффекта; после commit до ACK сообщение переигрывается идемпотентно.

Shutdown: consumer cancel/await → unsubscribe (durable сохраняется) → relay
cancel/await → NATS drain/close → DB dispose. Незавершённая доставка остаётся
для redelivery. При TERM оператор сверяет корреляцию с producer ledger, устраняет
причину и повторяет исходное корректное событие; не поднимает watermark вручную.
Потеря broker storage требует восстановления обеих сторон из ledger/outbox с
прежними envelope/ID. Ручной сброс volumes, inbox или barrier не является recovery.

Финальные gates: `make lint test test-infra`. Выделенные `TEST_DATABASE_URL` и
`TEST_NATS_URL` обязательны; их отсутствие — FAIL/BLOCKED, не PASS по skipped.
Consumer broker fixture проверяет настоящий JetStream (durable, NAK/redelivery,
ACK, TERM, restart); атомарный inbox/prefix/rollback проверяется отдельно на PostgreSQL.
Никаких изменений SEO-only HTTP access matrix или прав ADMIN этот transport не вносит.

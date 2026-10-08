# Yandex Service

Foundation infrastructure для интеграции с Яндекс.Метрика и Яндекс.Вебмастер.

## Overview

Yandex Service — микросервис для хранения и управления OAuth credentials для интеграций с сервисами Яндекса (Метрика, Вебмастер). Реализует:

- **Encryption foundation:** Fernet-шифрование для хранения токенов
- **Database schema:** PostgreSQL с таблицей `yandex_accounts`
- **Health check endpoint:** Мониторинг состояния сервиса и БД

## Current Status

**Foundation only (BE-2):** Базовая структура сервиса готова. OAuth, счётчики, хосты — в следующих tasks.

## Setup

### Requirements

- Python 3.13+
- PostgreSQL 16+
- Docker & Docker Compose

### Quick Start (Recommended)

Используй Makefile из корня монорепозитория для управления сервисом:

```bash
# 1. Запустить PostgreSQL инфраструктуру
make infra

# 2. Применить миграции
make yandex-migrate

# 3. Запустить сервис (development с hot reload)
make yandex
```

Сервис доступен на `http://localhost:8006`

### Encryption Key Generation

Перед первым запуском сгенерируй encryption key:

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Скопируй полученный ключ в `services/yandex-service/.env`:

```env
YANDEX_ENCRYPTION_KEY=<your-generated-key>
```

**⚠️ ВАЖНО:** Сохрани ключ в безопасном месте! Если ключ утрачен, все зашифрованные токены станут недоступны.

### Manual Setup (Alternative)

Если нужна ручная настройка:

#### 1. Database Setup

Убедись, что PostgreSQL БД `yandex_service` запущена:

```bash
# В корне монорепозитория
make infra
```

Проверь доступность БД:

```bash
psql -h localhost -U eqsitecmsyandex -d yandex_service -p 5438 -c "SELECT 1"
```

#### 2. Install Dependencies

```bash
cd services/yandex-service
uv sync
```

#### 3. Run Migrations

```bash
uv run alembic -c src/alembic.ini upgrade head
```

#### 4. Run Service

**Development (with hot reload):**

```bash
docker compose up --build
```

Сервис доступен на `http://localhost:8006`

**Production:**

```bash
docker compose -f docker-compose.prod.yml up -d
```

## Environment Variables

| Variable | Description | Example |
|----------|-------------|---------|
| `ENVIRONMENT` | Окружение (development/production) | `development` |
| `DEBUG` | Debug mode | `true` |
| `APP_TITLE` | Название приложения | `Yandex Service` |
| `POSTGRES_USER` | PostgreSQL user | `eqsitecmsyandex` |
| `POSTGRES_PASSWORD` | PostgreSQL password | `eqsitecmsyandex` |
| `POSTGRES_HOST` | PostgreSQL host | `db-yandex` |
| `POSTGRES_PORT` | PostgreSQL port | `5432` |
| `POSTGRES_DB` | PostgreSQL database | `yandex_service` |
| `YANDEX_ENCRYPTION_KEY` | Fernet encryption key (32 bytes base64) | `<generate-fernet-key>` |

## API Endpoints

### Health Check

**GET /health**

Проверка состояния сервиса и доступности БД.

**Response (200 OK):**

```json
{
  "status": "healthy",
  "timestamp": "2024-01-01T12:00:00Z"
}
```

**Response (503 Service Unavailable):**

```json
{
  "status": "unhealthy",
  "error": "Database connection failed",
  "timestamp": "2024-01-01T12:00:00Z"
}
```

**Access:** Public (anonymous и authenticated доступ разрешён)

## Testing

### Run All Tests

```bash
# В корне монорепозитория
make test

# Или локально в сервисе
cd services/yandex-service
uv run pytest
```

**Test Coverage:**
- ✅ Unit tests: Encryption utilities (10 tests)
- ✅ Integration tests: Health check endpoint (4 tests)

**Total:** 14 tests

### Unit Tests Only

```bash
cd services/yandex-service
uv run pytest tests/unit/
```

### Integration Tests Only

```bash
cd services/yandex-service
uv run pytest tests/integration/
```

### Lint & Type Check

```bash
make lint
```

### Format Code

```bash
make format
```

## Database Schema

### Table: `yandex_accounts`

Хранит OAuth credentials для Яндекс аккаунтов (токены зашифрованы).

| Column | Type | Description |
|--------|------|-------------|
| `id` | UUID | Primary key |
| `user_id` | UUID | Связь с пользователем CMS |
| `encrypted_access_token` | TEXT | Зашифрованный access token |
| `encrypted_refresh_token` | TEXT | Зашифрованный refresh token |
| `expires_at` | TIMESTAMP | Время истечения access token |
| `requires_reauth` | BOOLEAN | Требуется повторная авторизация |
| `deleted_at` | TIMESTAMP | Soft delete |
| `created_at` | TIMESTAMP | Время создания записи |

## Future Work

Следующие этапы (не в этом foundation):

### Phase 1: OAuth & Accounts Management
- OAuth 2.0 authorization flow для Яндекс.Метрика/Вебмастер
- Token refresh mechanism (автоматическое обновление истёкших токенов)
- Accounts API: создание, чтение, обновление, удаление OAuth аккаунтов
- Reauth flow для истёкших/отозванных токенов

### Phase 2: Яндекс.Метрика Integration
- Counters CRUD (управление счётчиками Метрики)
- Counters permissions (связь счётчиков с yandex_accounts)
- Internal API для получения credentials парсерами (аутентифицированный доступ)

### Phase 3: Яндекс.Вебмастер Integration
- Hosts CRUD (управление хостами Вебмастера)
- Hosts permissions (связь хостов с yandex_accounts)

### Phase 4: Events & Integration
- NATS integration: обработка событий удаления аккаунтов из `backend-service`
- Cascade deletion: автоматическое удаление всех связанных данных при `accounts.deleted` event

### Phase 5: UI Integration
- OAuth flow UI в CMS (redirect, authorization code handling)
- Counters/Hosts management UI
- Token status monitoring (requires_reauth indicator)

## Encryption

### Encryption Key Setup

Yandex Service использует Fernet (AES-128 CBC + HMAC-SHA256) для шифрования чувствительных данных (OAuth токены, client secrets).

**Генерация ключа:**

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

**Пример ключа:**

```
ZvJ8Q8X6KqF9nZ5j2rXkM7tYwL3pHbNcRdVsG4aUoE8=
```

**⚠️ ВАЖНО:**

- Ключ должен быть **32 байта** в формате base64 (44 символа)
- Сохрани ключ в безопасном месте! Если ключ утрачен, все зашифрованные токены станут недоступны
- В production используй secrets manager (Vault, AWS Secrets Manager)
- Никогда не коммить реальные ключи в Git

### Using Encryption in Code

```python
from src.core.encryption import FernetEncryption
from src.settings import yandex_settings

# Initialize encryptor
encryptor = FernetEncryption(yandex_settings.encryption_key)

# Encrypt sensitive data
access_token = "ya29.a0AfH6SMC..."
encrypted_token = encryptor.encrypt(access_token)
# → "gAAAAABhX..."

# Decrypt when needed
decrypted_token = encryptor.decrypt(encrypted_token)
# → "ya29.a0AfH6SMC..."
```

**Error Handling:**

```python
from cryptography.fernet import InvalidToken

try:
    plaintext = encryptor.decrypt(corrupted_ciphertext)
except InvalidToken:
    # Wrong key, corrupted data, or expired token
    logger.error("Decryption failed - token may be corrupted")
```

## Architecture

Сервис следует Clean Architecture с разделением:

- **core/entities:** Бизнес-сущности (Pydantic)
- **core/protocols:** Protocol-интерфейсы репозиториев
- **core/schemas:** DTO для API
- **core/services:** Use cases и бизнес-логика
- **core/encryption:** Fernet encryption utilities
- **models:** SQLAlchemy Core tables
- **repositories:** Реализации репозиториев
- **api:** FastAPI routes
- **depends:** DI factories
- **utils:** Инфраструктурные утилиты

## License

Part of EqSiteCMS project.

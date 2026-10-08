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

### 1. Generate Encryption Key

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Скопируй полученный ключ в `.env`:

```env
YANDEX_ENCRYPTION_KEY=<your-generated-key>
```

**⚠️ ВАЖНО:** Сохрани ключ в безопасном месте! Если ключ утрачен, все зашифрованные токены станут недоступны.

### 2. Database Setup

Убедись, что PostgreSQL БД `yandex_service` запущена (через infrastructure docker-compose):

```bash
# В корне монорепозитория
make infra-up
```

Проверь доступность БД:

```bash
psql -h localhost -U eqsitecmsyandex -d yandex_service -p 5438 -c "SELECT 1"
```

### 3. Install Dependencies

```bash
uv sync
```

### 4. Run Migrations

```bash
uv run alembic -c src/alembic.ini upgrade head
```

### 5. Run Service

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

### Unit Tests

```bash
make test
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

- OAuth 2.0 implementation (authorization flow, token refresh)
- Счётчики Яндекс.Метрика (counters CRUD)
- Хосты Яндекс.Вебмастер (hosts CRUD)
- Internal credentials API для парсеров
- NATS интеграция для событий
- UI для OAuth flow в CMS

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

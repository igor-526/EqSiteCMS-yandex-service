from uuid import UUID

from sqlalchemy import Boolean, ColumnDefault, DateTime, DefaultClause
from sqlalchemy.dialects.postgresql import UUID as PG_UUID

from utils.basemodel import soft_delete_columns, timestamp_columns, uuid_pk


def test_uuid_primary_key_default_and_fresh_columns() -> None:
    column = uuid_pk()
    assert column.name == "id" and column.primary_key and not column.nullable
    assert isinstance(column.type, PG_UUID) and column.type.as_uuid
    assert isinstance(column.default, ColumnDefault)
    first = column.default.arg(None)
    second = column.default.arg(None)
    assert isinstance(first, UUID) and first.version == 4 and first != second
    assert uuid_pk() is not column


def test_timestamp_columns_timezone_defaults_and_update() -> None:
    created, updated = timestamp_columns()
    assert (created.name, updated.name) == ("created_at", "updated_at")
    assert isinstance(created.type, DateTime) and created.type.timezone
    assert isinstance(updated.type, DateTime) and updated.type.timezone
    assert not created.nullable and updated.nullable
    assert isinstance(created.server_default, DefaultClause) and str(created.server_default.arg) == "now()"
    assert isinstance(updated.onupdate, ColumnDefault) and str(updated.onupdate.arg) == "now()"
    assert updated.server_default is None


def test_soft_delete_columns_defaults_and_nullable_timestamp() -> None:
    deleted, timestamp = soft_delete_columns()
    assert (deleted.name, timestamp.name) == ("is_deleted", "deleted_at")
    assert isinstance(deleted.type, Boolean) and not deleted.nullable
    assert isinstance(deleted.default, ColumnDefault) and deleted.default.arg is False
    assert isinstance(deleted.server_default, DefaultClause) and str(deleted.server_default.arg) == "false"
    assert isinstance(timestamp.type, DateTime) and timestamp.type.timezone and timestamp.nullable
    assert timestamp.default is None and timestamp.server_default is None

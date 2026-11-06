import importlib.util
import io
from pathlib import Path
from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from pydantic import ValidationError
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.schema import CreateColumn

from core.entities.metrica_lifecycle import MetricaTenantLifecycle
from models import yandex_metrica_counters
from models.metrica_lifecycle import (
    metrica_cleanup_operations,
    metrica_lifecycle_inbox,
    metrica_lifecycle_outbox,
    metrica_tenant_lifecycle,
)
from repositories.metrica_lifecycle_repository import MetricaLifecycleRepository

TABLES = (metrica_tenant_lifecycle, metrica_cleanup_operations, metrica_lifecycle_outbox, metrica_lifecycle_inbox)
MIGRATION = Path(__file__).parents[2] / "src/migration/versions/9e106a107001_metrica_lifecycle.py"


def load_migration():
    spec = importlib.util.spec_from_file_location("lifecycle_revision", MIGRATION)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def migration_sql(direction: str) -> str:
    output = io.StringIO()
    context = MigrationContext.configure(dialect_name="postgresql", opts={"as_sql": True, "output_buffer": output})
    with Operations.context(context):
        getattr(load_migration(), direction)()
    return " ".join(output.getvalue().split())


def test_lifecycle_migration_columns_constraints_indexes_match_metadata() -> None:
    sql = migration_sql("upgrade")
    assert load_migration().down_revision == "61c3a74f4ba9"
    for table in TABLES:
        assert f"CREATE TABLE {table.name}" in sql
        for column in table.columns:
            expected = str(CreateColumn(column).compile(dialect=postgresql.dialect()))
            assert " ".join(expected.split()) in sql
        for constraint in table.constraints:
            if constraint.name:
                assert f"CONSTRAINT {constraint.name}" in sql
        for index in table.indexes:
            assert f"CREATE INDEX {index.name}" in sql
    assert "SELECT equestrian_id, 1, 0, 0 FROM yandex_metrica_counters" in sql
    assert "WHERE equestrian_id IS NOT NULL ON CONFLICT (equestrian_id) DO NOTHING" in sql


def test_lifecycle_storage_survives_binding_cascade_and_downgrade_is_guarded() -> None:
    for table in TABLES:
        for fk in table.foreign_keys:
            assert fk.column.table in TABLES
            assert fk.ondelete != "CASCADE"
    assert list(metrica_lifecycle_inbox.primary_key.columns.keys()) == ["consumer", "message_id"]
    sql = migration_sql("downgrade")
    assert sql.index("RAISE EXCEPTION") < sql.index("DROP TABLE")
    for table in TABLES:
        assert f"EXISTS (SELECT 1 FROM {table.name}" in sql


@pytest.mark.parametrize(
    "values",
    [
        {"binding_generation": -1},
        {"cleanup_requested_seq": -1},
        {"cleanup_completed_seq": 1},
        {"cleanup_completed_seq": -1},
    ],
)
def test_lifecycle_entity_rejects_invalid_watermarks(values: dict[str, int]) -> None:
    with pytest.raises(ValidationError):
        MetricaTenantLifecycle(equestrian_id=uuid4(), **values)


async def test_lifecycle_lock_tenants_deduplicates_and_sorts_inserts_and_locks() -> None:
    session = AsyncMock(spec=AsyncSession)
    repository = MetricaLifecycleRepository(session)
    await repository.lock_tenants(equestrian_ids=[UUID(int=3), UUID(int=1), UUID(int=3)])
    calls = session.execute.call_args_list
    assert len(calls) == 4
    for i, expected in enumerate([UUID(int=1), UUID(int=3)]):
        insert = calls[i * 2].args[0].compile(dialect=postgresql.dialect())
        lock = calls[i * 2 + 1].args[0].compile(dialect=postgresql.dialect())
        assert insert.params["equestrian_id"] == expected
        assert "ON CONFLICT (equestrian_id) DO NOTHING" in str(insert)
        assert expected in lock.params.values() and "FOR UPDATE" in str(lock)
    session.commit.assert_not_called()


async def test_lifecycle_missing_read_does_not_create_state() -> None:
    session = AsyncMock(spec=AsyncSession)
    result = MagicMock()
    result.mappings.return_value.first.return_value = None
    session.execute.return_value = result
    tenant = uuid4()
    assert await MetricaLifecycleRepository(session).get(equestrian_id=tenant) == MetricaTenantLifecycle(
        equestrian_id=tenant
    )
    session.execute.assert_awaited_once()


async def test_lifecycle_generation_increment_never_resets_watermarks() -> None:
    session = AsyncMock(spec=AsyncSession)
    result = MagicMock()
    tenant = uuid4()
    result.mappings.return_value.one.return_value = dict(
        equestrian_id=tenant, binding_generation=3, cleanup_requested_seq=2, cleanup_completed_seq=1
    )
    session.execute.return_value = result
    repository = MetricaLifecycleRepository(session)
    state = await repository.advance_generation(equestrian_id=tenant)
    assert (state.binding_generation, state.cleanup_requested_seq, state.cleanup_completed_seq) == (3, 2, 1)
    stmt = session.execute.call_args_list[-1].args[0].compile(dialect=postgresql.dialect())
    assignment = str(stmt).split(" SET ", 1)[1].split(" WHERE ", 1)[0]
    assert "binding_generation=(metrica_tenant_lifecycle.binding_generation +" in assignment
    assert "cleanup_requested_seq" not in assignment and "cleanup_completed_seq" not in assignment
    session.commit.assert_not_called()


def query_result(*, first=None, scalar=None, rows=()):
    result = MagicMock()
    result.mappings.return_value.first.return_value = first
    result.mappings.return_value.all.return_value = rows
    result.first.return_value = first
    result.scalar_one_or_none.return_value = scalar
    return result


@pytest.fixture
def binding():
    from core.entities import YandexMetricaCounter

    return YandexMetricaCounter(equestrian_id=uuid4(), yandex_user_id=uuid4(), counter_id="42")


async def test_cleanup_delete_rechecks_after_tenant_lock_and_repeat_is_noop(binding) -> None:
    session = AsyncMock(spec=AsyncSession)
    repository = cast(Any, MetricaLifecycleRepository(session))
    repository.lock_tenants = AsyncMock()
    repository._request_cleanup = AsyncMock()
    session.execute.side_effect = [
        query_result(scalar=binding.equestrian_id),
        query_result(first=binding.model_dump()),
        query_result(),
        query_result(scalar=None),
        # Another DELETE won after our discovery, before we acquired tenant lock.
        query_result(scalar=binding.equestrian_id),
        query_result(first=None),
    ]
    for _ in range(3):
        await repository.delete_binding(counter_id=binding.id)
    repository._request_cleanup.assert_awaited_once_with(counter=binding, reason="counter_unlinked")
    assert repository.lock_tenants.await_count == 2
    delete_stmt = session.execute.call_args_list[2].args[0]
    assert str(delete_stmt).startswith("DELETE FROM yandex_metrica_counters")
    session.commit.assert_not_called()


async def test_cleanup_intention_advances_only_requested_and_persists_safe_envelope(binding) -> None:
    from uuid import NAMESPACE_URL, uuid5

    session = AsyncMock(spec=AsyncSession)
    repository = cast(Any, MetricaLifecycleRepository(session))
    repository.get = AsyncMock(
        return_value=MetricaTenantLifecycle(
            equestrian_id=binding.equestrian_id, binding_generation=3, cleanup_requested_seq=2, cleanup_completed_seq=1
        )
    )
    await repository._request_cleanup(counter=binding, reason="account_deleted")
    statements = [call.args[0].compile(dialect=postgresql.dialect()) for call in session.execute.call_args_list]
    assert statements[0].params["cleanup_requested_seq"] == 3
    assert "binding_generation" not in str(statements[0]).split(" SET ")[1]
    operation, outbox = statements[1].params, statements[2].params
    assert (operation["binding_generation"], operation["cleanup_seq"], operation["binding_id"]) == (3, 3, binding.id)
    assert operation["reason"] == "account_deleted"
    payload = outbox["payload"]
    assert set(payload) == {
        "schema_version",
        "message_id",
        "operation_id",
        "equestrian_id",
        "occurred_at",
        "cleanup_seq",
        "binding_generation",
        "reason",
    }
    assert outbox["operation_id"] == operation["id"]
    assert outbox["message_id"] == uuid5(
        NAMESPACE_URL, f"eqcms:maintenance:v1:{outbox['subject']}:{operation['id']}:requested"
    )
    assert payload["message_id"] == str(outbox["message_id"])
    assert payload["cleanup_seq"] == 3
    session.commit.assert_not_called()


@pytest.mark.parametrize("mode", ["create", "same", "change"])
async def test_lifecycle_rebind_uses_locked_snapshot_and_generation_only_on_change(binding, mode) -> None:
    session = AsyncMock(spec=AsyncSession)
    repository = cast(Any, MetricaLifecycleRepository(session))
    repository.lock_tenants = AsyncMock()
    repository.advance_generation = AsyncMock()
    existing = None if mode == "create" else binding.model_dump()
    proposed = binding.model_copy(update={"id": uuid4(), "counter_id": "43" if mode == "change" else "42"})
    session.execute.side_effect = [
        query_result(first=(binding.yandex_user_id,)),
        query_result(first=existing),
        query_result(),
    ]
    actual = await repository.set_binding(counter=proposed)
    assert actual.id == (proposed.id if mode == "create" else binding.id)
    assert actual.counter_id == proposed.counter_id
    if mode == "same":
        repository.advance_generation.assert_not_awaited()
        assert session.execute.await_count == 2
    else:
        repository.advance_generation.assert_awaited_once_with(equestrian_id=binding.equestrian_id)
    repository.lock_tenants.assert_awaited_once_with(equestrian_ids=[binding.equestrian_id])
    session.commit.assert_not_called()


async def test_lifecycle_rebind_missing_locked_account_fails_before_writing(binding) -> None:
    from core.exceptions import ClientError

    session = AsyncMock(spec=AsyncSession)
    repository = cast(Any, MetricaLifecycleRepository(session))
    repository.lock_tenants = AsyncMock()
    session.execute.return_value = query_result(first=None)
    with pytest.raises(ClientError, match="Аккаунт не найден"):
        await repository.set_binding(counter=binding)
    assert session.execute.await_count == 1


@pytest.mark.parametrize("linked", [False, True])
async def test_cleanup_account_collects_context_before_cascade_and_unrelated_is_noop(binding, linked) -> None:
    session = AsyncMock(spec=AsyncSession)
    repository = cast(Any, MetricaLifecycleRepository(session))
    repository._account_bindings = AsyncMock(return_value=[binding] if linked else [])
    repository.lock_tenants = AsyncMock()
    repository._request_cleanup = AsyncMock()
    session.execute.side_effect = [query_result(first=(binding.yandex_user_id,)), query_result()]
    await repository.delete_account(account_id=binding.yandex_user_id)
    assert repository._account_bindings.await_count == 2
    repository.lock_tenants.assert_awaited_once_with(equestrian_ids=[binding.equestrian_id] if linked else [])
    if linked:
        repository._request_cleanup.assert_awaited_once_with(counter=binding, reason="account_deleted")
    else:
        repository._request_cleanup.assert_not_awaited()
    assert str(session.execute.call_args_list[-1].args[0]).startswith("DELETE FROM yandex_user")
    session.commit.assert_not_called()


async def test_cleanup_account_retries_discovery_if_concurrent_rebind_expands_tenants(binding) -> None:
    session = AsyncMock(spec=AsyncSession)
    repository = cast(Any, MetricaLifecycleRepository(session))
    repository._account_bindings = AsyncMock(side_effect=[[], [binding], [binding], [binding]])
    repository.lock_tenants = AsyncMock()
    repository._request_cleanup = AsyncMock()
    session.execute.side_effect = [query_result(first=(binding.yandex_user_id,))] * 2 + [query_result()]
    await repository.delete_account(account_id=binding.yandex_user_id)
    assert session.begin_nested.call_count == 2
    session.begin_nested.return_value.__aenter__.return_value.rollback.assert_awaited_once()
    repository._request_cleanup.assert_awaited_once_with(counter=binding, reason="account_deleted")


async def test_lifecycle_di_uses_same_request_session_for_both_services() -> None:
    from containers.repositories import RepositoriesContainer
    from containers.services import ServicesContainer

    repositories = RepositoriesContainer()
    session = AsyncMock(spec=AsyncSession)
    with repositories.session.override(session):
        services = ServicesContainer(repositories_container=repositories)
        counters = cast(Any, services.yandex_metrica_counter_service())
        accounts = cast(Any, services.yandex_accounts_service())
        assert counters._lifecycle.session is accounts._lifecycle.session is session
        assert counters.yandex_metrica_counter_repository.session is session
        assert accounts._yandex_user_repository.session is session


@pytest.mark.parametrize("found", [False, True])
@pytest.mark.parametrize("numbers", [None, (3, 2, 1), (4, 2, 2)])
async def test_binding_snapshot_is_one_read_without_locks_or_mutations(binding, found, numbers) -> None:
    from core.exceptions import ClientError

    session = AsyncMock(spec=AsyncSession)
    row = dict.fromkeys([column.name for column in yandex_metrica_counters.c])
    if found:
        row.update(binding.model_dump())
    row.update(
        dict(
            zip(
                ("binding_generation", "cleanup_requested_seq", "cleanup_completed_seq"),
                numbers or (None,) * 3,
                strict=True,
            )
        )
    )
    result = MagicMock()
    result.mappings.return_value.one.return_value = row
    session.execute.return_value = result
    repository = MetricaLifecycleRepository(session)
    if found and numbers is None:
        # Never issue a generation-zero snapshot for a binding missing lifecycle.
        with pytest.raises(ClientError, match="Состояние привязки недоступно"):
            await repository.get_binding_snapshot(equestrian_id=binding.equestrian_id)
    else:
        snapshot = await repository.get_binding_snapshot(equestrian_id=binding.equestrian_id)
        assert snapshot.counter == (binding if found else None)
        assert snapshot.lifecycle.equestrian_id == binding.equestrian_id
        assert (
            snapshot.lifecycle.binding_generation,
            snapshot.lifecycle.cleanup_requested_seq,
            snapshot.lifecycle.cleanup_completed_seq,
        ) == (numbers or (0, 0, 0))
    session.execute.assert_awaited_once()
    statement = session.execute.call_args.args[0].compile(dialect=postgresql.dialect())
    sql = str(statement)
    assert sql.startswith("SELECT") and sql.count("LEFT OUTER JOIN") == 2
    assert "FOR UPDATE" not in sql and "INSERT" not in sql
    assert binding.equestrian_id in statement.params.values()
    session.commit.assert_not_called()


def test_private_binding_dto_requires_explicit_lifecycle_and_keeps_set_dto_unchanged() -> None:
    from core.schemas.api import YandexMetricaConnectedCounterOutDto, YandexMetricaSetCounterOutDto

    with pytest.raises(ValidationError):
        YandexMetricaConnectedCounterOutDto.model_validate({"counter": None})
    lifecycle_fields = {"binding_generation", "cleanup_requested_seq", "cleanup_completed_seq"}
    assert lifecycle_fields.isdisjoint(YandexMetricaSetCounterOutDto.model_fields)
    assert lifecycle_fields <= set(YandexMetricaConnectedCounterOutDto.model_json_schema()["required"])

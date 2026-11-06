from collections.abc import Sequence
from typing import Protocol
from uuid import UUID

from core.entities import YandexMetricaCounter
from core.entities.metrica_lifecycle import MetricaBindingSnapshot, MetricaTenantLifecycle


class MetricaLifecycleRepositoryProtocol(Protocol):
    """All mutations share the caller's transaction; never commit here.

    Acquire all tenant locks in UUID order before any account/binding locks.
    Watermarks live independently of binding and account records.
    """

    async def get_binding_snapshot(self, *, equestrian_id: UUID) -> MetricaBindingSnapshot: ...

    async def get(self, *, equestrian_id: UUID) -> MetricaTenantLifecycle: ...

    async def lock_tenants(self, *, equestrian_ids: Sequence[UUID]) -> None: ...

    async def advance_generation(self, *, equestrian_id: UUID) -> MetricaTenantLifecycle: ...

    async def set_binding(self, *, counter: YandexMetricaCounter) -> YandexMetricaCounter: ...

    async def delete_binding(self, *, counter_id: UUID) -> None: ...

    async def delete_account(self, *, account_id: UUID) -> None: ...

import uuid

from sqlalchemy import (
    Column,
    ForeignKey,
    String,
    Table,
)
from sqlalchemy.dialects.postgresql import UUID as PG_UUID

from utils.basemodel import metadata, timestamp_columns, uuid_pk

yandex_metrica_counters = Table(
    "yandex_metrica_counters",
    metadata,
    uuid_pk(),
    *timestamp_columns(),
    Column(
        "equestrian_id",
        PG_UUID(as_uuid=True),
        default=uuid.uuid4,
    ),
    Column("yandex_user_id", ForeignKey("yandex_user.id", ondelete="CASCADE"), nullable=False),
    Column("counter_id", String(31), nullable=False),
)

import uuid

from sqlalchemy import (
    Column,
    DateTime,
    Index,
    String,
    Table,
    func,
)
from sqlalchemy.dialects.postgresql import UUID as PG_UUID

from utils.basemodel import metadata, timestamp_columns, uuid_pk

yandex_user = Table(
    "yandex_user",
    metadata,
    uuid_pk(),
    *timestamp_columns(),
    Column(
        "equestrian_id",
        PG_UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    ),
    Column("yandex_id", String(63), nullable=False),
    Column("yandex_login", String(127), nullable=False),
    Column("display_name", String(127), nullable=False),
    Column("email", String(320), nullable=True),
    Column("yandex_avatar_id", String(63), nullable=True),
    Column("yandex_phone", String(31), nullable=True),
    Column("enc_access_token", String(511), nullable=False),
    Column("enc_refresh_token", String(511), nullable=False),
    Column(
        "token_expires_at",
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    ),
    Index(
        "ux_yandex_user_equestrian_id_yandex_id",
        "equestrian_id",
        "yandex_id",
        unique=True,
    ),
    Index(
        "ix_yandex_user_equestrian_id_yandex_login",
        "equestrian_id",
        "yandex_login",
    ),
    Index(
        "ix_yandex_user_equestrian_id_email",
        "equestrian_id",
        "email",
    ),
    Index(
        "ix_yandex_user_equestrian_id_display_name",
        "equestrian_id",
        "display_name",
    ),
)

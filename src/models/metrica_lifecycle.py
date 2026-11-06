"""Durable tenant state; deliberately independent of account/binding cascades."""

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Table,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID

from utils.basemodel import metadata, timestamp_columns, uuid_pk

metrica_tenant_lifecycle = Table(
    "metrica_tenant_lifecycle",
    metadata,
    Column("equestrian_id", PG_UUID(as_uuid=True), primary_key=True),
    Column("binding_generation", BigInteger, nullable=False, server_default=text("0")),
    Column("cleanup_requested_seq", BigInteger, nullable=False, server_default=text("0")),
    Column("cleanup_completed_seq", BigInteger, nullable=False, server_default=text("0")),
    CheckConstraint("binding_generation >= 0", name="ck_metrica_lifecycle_generation"),
    CheckConstraint(
        "cleanup_completed_seq >= 0 AND cleanup_requested_seq >= cleanup_completed_seq",
        name="ck_metrica_lifecycle_watermarks",
    ),
)

metrica_cleanup_operations = Table(
    "metrica_cleanup_operations",
    metadata,
    uuid_pk(),
    *timestamp_columns(),
    Column("equestrian_id", PG_UUID(as_uuid=True), nullable=False),
    # Snapshots, not FKs: these identifiers must survive the original cascade.
    Column("binding_id", PG_UUID(as_uuid=True), nullable=False),
    Column("binding_generation", BigInteger, nullable=False),
    Column("cleanup_seq", BigInteger, nullable=False),
    Column("reason", String(31), nullable=False),
    Column("status", String(31), nullable=False, server_default=text("'pending'")),
    Column("completed_at", DateTime(timezone=True)),
    ForeignKeyConstraint(
        ["equestrian_id"], ["metrica_tenant_lifecycle.equestrian_id"], name="fk_metrica_cleanup_tenant"
    ),
    UniqueConstraint("equestrian_id", "cleanup_seq", name="uq_metrica_cleanup_tenant_seq"),
    UniqueConstraint("equestrian_id", "id", name="uq_metrica_cleanup_tenant_operation"),
    CheckConstraint("cleanup_seq > 0 AND binding_generation >= 0", name="ck_metrica_cleanup_numbers"),
    CheckConstraint("reason IN ('counter_unlinked', 'account_deleted')", name="ck_metrica_cleanup_reason"),
    CheckConstraint("status IN ('pending', 'completed')", name="ck_metrica_cleanup_status"),
    CheckConstraint("(status = 'completed') = (completed_at IS NOT NULL)", name="ck_metrica_cleanup_completed"),
    Index("ix_metrica_cleanup_tenant_status", "equestrian_id", "status"),
)

metrica_lifecycle_outbox = Table(
    "metrica_lifecycle_outbox",
    metadata,
    Column("message_id", PG_UUID(as_uuid=True), primary_key=True),
    *timestamp_columns(),
    Column("equestrian_id", PG_UUID(as_uuid=True), nullable=False),
    Column("operation_id", PG_UUID(as_uuid=True), nullable=False),
    Column("subject", String(127), nullable=False),
    Column("payload", JSONB, nullable=False),
    Column("status", String(15), nullable=False, server_default=text("'pending'")),
    Column("attempts", Integer, nullable=False, server_default=text("0")),
    Column("next_attempt_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("claim_token", PG_UUID(as_uuid=True)),
    Column("claim_expires_at", DateTime(timezone=True)),
    Column("published_at", DateTime(timezone=True)),
    ForeignKeyConstraint(
        ["equestrian_id", "operation_id"],
        ["metrica_cleanup_operations.equestrian_id", "metrica_cleanup_operations.id"],
        name="fk_metrica_outbox_tenant_operation",
    ),
    UniqueConstraint("operation_id", "subject", name="uq_metrica_outbox_operation_subject"),
    CheckConstraint("status IN ('pending', 'published')", name="ck_metrica_outbox_status"),
    CheckConstraint("attempts >= 0", name="ck_metrica_outbox_attempts"),
    CheckConstraint("(claim_token IS NULL) = (claim_expires_at IS NULL)", name="ck_metrica_outbox_claim"),
    CheckConstraint("(status = 'published') = (published_at IS NOT NULL)", name="ck_metrica_outbox_published"),
    Index("ix_metrica_outbox_ready", "status", "next_attempt_at"),
)

metrica_lifecycle_inbox = Table(
    "metrica_lifecycle_inbox",
    metadata,
    Column("consumer", String(127), primary_key=True),
    Column("message_id", PG_UUID(as_uuid=True), primary_key=True),
    Column("equestrian_id", PG_UUID(as_uuid=True), nullable=False),
    Column("operation_id", PG_UUID(as_uuid=True), nullable=False),
    Column("payload_hash", String(64), nullable=False),
    Column("processed_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    ForeignKeyConstraint(
        ["equestrian_id", "operation_id"],
        ["metrica_cleanup_operations.equestrian_id", "metrica_cleanup_operations.id"],
        name="fk_metrica_inbox_tenant_operation",
    ),
    CheckConstraint("length(payload_hash) = 64", name="ck_metrica_inbox_hash"),
)

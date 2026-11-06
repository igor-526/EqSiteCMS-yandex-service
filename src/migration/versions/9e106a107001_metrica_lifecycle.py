"""Add durable Metrica lifecycle storage.

Revision ID: 9e106a107001
Revises: 61c3a74f4ba9
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "9e106a107001"
down_revision = "61c3a74f4ba9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "metrica_tenant_lifecycle",
        sa.Column("equestrian_id", sa.UUID(), nullable=False),
        sa.Column("binding_generation", sa.BigInteger(), server_default=sa.text("0"), nullable=False),
        sa.Column("cleanup_requested_seq", sa.BigInteger(), server_default=sa.text("0"), nullable=False),
        sa.Column("cleanup_completed_seq", sa.BigInteger(), server_default=sa.text("0"), nullable=False),
        sa.CheckConstraint("binding_generation >= 0", name="ck_metrica_lifecycle_generation"),
        sa.CheckConstraint(
            "cleanup_completed_seq >= 0 AND cleanup_requested_seq >= cleanup_completed_seq",
            name="ck_metrica_lifecycle_watermarks",
        ),
        sa.PrimaryKeyConstraint("equestrian_id"),
    )
    op.create_table(
        "metrica_cleanup_operations",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("equestrian_id", sa.UUID(), nullable=False),
        sa.Column("binding_id", sa.UUID(), nullable=False),
        sa.Column("binding_generation", sa.BigInteger(), nullable=False),
        sa.Column("cleanup_seq", sa.BigInteger(), nullable=False),
        sa.Column("reason", sa.String(length=31), nullable=False),
        sa.Column("status", sa.String(length=31), server_default=sa.text("'pending'"), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("(status = 'completed') = (completed_at IS NOT NULL)", name="ck_metrica_cleanup_completed"),
        sa.CheckConstraint("reason IN ('counter_unlinked', 'account_deleted')", name="ck_metrica_cleanup_reason"),
        sa.CheckConstraint("status IN ('pending', 'completed')", name="ck_metrica_cleanup_status"),
        sa.CheckConstraint("cleanup_seq > 0 AND binding_generation >= 0", name="ck_metrica_cleanup_numbers"),
        sa.ForeignKeyConstraint(
            ["equestrian_id"], ["metrica_tenant_lifecycle.equestrian_id"], name="fk_metrica_cleanup_tenant"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("equestrian_id", "cleanup_seq", name="uq_metrica_cleanup_tenant_seq"),
        sa.UniqueConstraint("equestrian_id", "id", name="uq_metrica_cleanup_tenant_operation"),
    )
    op.create_index(
        "ix_metrica_cleanup_tenant_status", "metrica_cleanup_operations", ["equestrian_id", "status"], unique=False
    )
    op.create_table(
        "metrica_lifecycle_outbox",
        sa.Column("message_id", sa.UUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("equestrian_id", sa.UUID(), nullable=False),
        sa.Column("operation_id", sa.UUID(), nullable=False),
        sa.Column("subject", sa.String(length=127), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("status", sa.String(length=15), server_default=sa.text("'pending'"), nullable=False),
        sa.Column("attempts", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("claim_token", sa.UUID(), nullable=True),
        sa.Column("claim_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("(status = 'published') = (published_at IS NOT NULL)", name="ck_metrica_outbox_published"),
        sa.CheckConstraint("status IN ('pending', 'published')", name="ck_metrica_outbox_status"),
        sa.CheckConstraint("(claim_token IS NULL) = (claim_expires_at IS NULL)", name="ck_metrica_outbox_claim"),
        sa.CheckConstraint("attempts >= 0", name="ck_metrica_outbox_attempts"),
        sa.ForeignKeyConstraint(
            ["equestrian_id", "operation_id"],
            ["metrica_cleanup_operations.equestrian_id", "metrica_cleanup_operations.id"],
            name="fk_metrica_outbox_tenant_operation",
        ),
        sa.PrimaryKeyConstraint("message_id"),
        sa.UniqueConstraint("operation_id", "subject", name="uq_metrica_outbox_operation_subject"),
    )
    op.create_index("ix_metrica_outbox_ready", "metrica_lifecycle_outbox", ["status", "next_attempt_at"], unique=False)
    op.create_table(
        "metrica_lifecycle_inbox",
        sa.Column("consumer", sa.String(length=127), nullable=False),
        sa.Column("message_id", sa.UUID(), nullable=False),
        sa.Column("equestrian_id", sa.UUID(), nullable=False),
        sa.Column("operation_id", sa.UUID(), nullable=False),
        sa.Column("payload_hash", sa.String(length=64), nullable=False),
        sa.Column("processed_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("length(payload_hash) = 64", name="ck_metrica_inbox_hash"),
        sa.ForeignKeyConstraint(
            ["equestrian_id", "operation_id"],
            ["metrica_cleanup_operations.equestrian_id", "metrica_cleanup_operations.id"],
            name="fk_metrica_inbox_tenant_operation",
        ),
        sa.PrimaryKeyConstraint("consumer", "message_id"),
    )

    op.execute("""
        INSERT INTO metrica_tenant_lifecycle
            (equestrian_id, binding_generation, cleanup_requested_seq, cleanup_completed_seq)
        SELECT equestrian_id, 1, 0, 0 FROM yandex_metrica_counters
        WHERE equestrian_id IS NOT NULL
        ON CONFLICT (equestrian_id) DO NOTHING
    """)


def downgrade() -> None:
    # Refuse even completed history: dropping it can allow delayed replay or
    # reset a cleanup watermark. Recovery is an explicit operator procedure.
    op.execute("""
        DO $$ BEGIN
            IF EXISTS (SELECT 1 FROM metrica_cleanup_operations)
                OR EXISTS (SELECT 1 FROM metrica_lifecycle_outbox)
                OR EXISTS (SELECT 1 FROM metrica_lifecycle_inbox)
                OR EXISTS (SELECT 1 FROM metrica_tenant_lifecycle WHERE cleanup_requested_seq > 0)
            THEN
                RAISE EXCEPTION 'Metrica lifecycle history exists; use forward-fix, not downgrade';
            END IF;
        END $$
    """)
    op.drop_table("metrica_lifecycle_inbox")
    op.drop_table("metrica_lifecycle_outbox")
    op.drop_table("metrica_cleanup_operations")
    op.drop_table("metrica_tenant_lifecycle")

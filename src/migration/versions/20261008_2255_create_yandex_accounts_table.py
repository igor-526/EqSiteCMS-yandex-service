"""Create yandex_accounts table

Revision ID: 9810155968b5
Revises: 
Create Date: 2026-10-08 22:55:29.332262

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '9810155968b5'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'yandex_accounts',
        sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('user_id', sa.UUID(), nullable=False),
        sa.Column('encrypted_access_token', sa.Text(), nullable=True),
        sa.Column('encrypted_refresh_token', sa.Text(), nullable=True),
        sa.Column('expires_at', sa.TIMESTAMP(), nullable=True),
        sa.Column('requires_reauth', sa.Boolean(), server_default=sa.text('false'), nullable=False),
        sa.Column('deleted_at', sa.TIMESTAMP(), nullable=True),
        sa.Column('created_at', sa.TIMESTAMP(), server_default=sa.text('NOW()'), nullable=False),
        sa.PrimaryKeyConstraint('id')
    )


def downgrade() -> None:
    op.drop_table('yandex_accounts')

"""Durable worker heartbeat for queue diagnostics."""
from alembic import op
import sqlalchemy as sa
revision = '0003'
down_revision = '0002'
branch_labels = None
depends_on = None

def upgrade():
    op.create_table('pi_worker_heartbeats',
        sa.Column('worker_id',sa.String(100),primary_key=True),
        sa.Column('updated_at',sa.DateTime(timezone=True),nullable=False))

def downgrade():
    op.drop_table('pi_worker_heartbeats')

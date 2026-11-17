"""Initial schema: students, users, tuitions, payments.

Revision ID: 0001
Revises:
Create Date: 2026-11-17
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

MONEY = sa.Numeric(12, 2)


def upgrade() -> None:
    op.create_table(
        "students",
        sa.Column("student_no", sa.String(16), nullable=False),
        sa.Column("full_name", sa.String(120), nullable=False),
        sa.Column("email", sa.String(255), nullable=True),
        sa.PrimaryKeyConstraint("student_no", name="pk_students"),
    )

    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), sa.Identity(), nullable=False),
        sa.Column("username", sa.String(64), nullable=False),
        sa.Column("password_hash", sa.String(100), nullable=False),
        sa.Column("role", sa.String(16), nullable=False),
        sa.Column("student_no", sa.String(16), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_users"),
        sa.UniqueConstraint("username", name="uq_users_username"),
        sa.ForeignKeyConstraint(["student_no"], ["students.student_no"], name="fk_users_student_no_students", ondelete="RESTRICT"),
        sa.CheckConstraint("role IN ('student', 'bank', 'admin')", name="ck_users_role_valid"),
        sa.CheckConstraint("(role = 'student') = (student_no IS NOT NULL)", name="ck_users_student_no_matches_role"),
    )

    op.create_table(
        "tuitions",
        sa.Column("id", sa.Integer(), sa.Identity(), nullable=False),
        sa.Column("student_no", sa.String(16), nullable=False),
        sa.Column("term", sa.String(16), nullable=False),
        sa.Column("amount", MONEY, nullable=False),
        sa.Column("currency", sa.String(3), server_default="USD", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_tuitions"),
        sa.ForeignKeyConstraint(["student_no"], ["students.student_no"], name="fk_tuitions_student_no_students", ondelete="RESTRICT"),
        sa.UniqueConstraint("student_no", "term", name="uq_tuitions_student_term"),
        sa.CheckConstraint("amount > 0", name="ck_tuitions_amount_positive"),
        sa.CheckConstraint("term ~ '^[0-9]{4}-(FALL|SPRING)$'", name="ck_tuitions_term_format"),
        sa.CheckConstraint("currency ~ '^[A-Z]{3}$'", name="ck_tuitions_currency_iso4217"),
    )
    op.create_index("ix_tuitions_student_no", "tuitions", ["student_no"])

    op.create_table(
        "payments",
        sa.Column("id", sa.Integer(), sa.Identity(), nullable=False),
        sa.Column("transaction_id", sa.String(64), nullable=False),
        sa.Column("tuition_id", sa.Integer(), nullable=False),
        sa.Column("amount", MONEY, nullable=False),
        sa.Column("channel", sa.String(16), nullable=False),
        sa.Column("created_by", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_payments"),
        sa.UniqueConstraint("transaction_id", name="uq_payments_transaction_id"),
        sa.ForeignKeyConstraint(["tuition_id"], ["tuitions.id"], name="fk_payments_tuition_id_tuitions", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], name="fk_payments_created_by_users", ondelete="RESTRICT"),
        sa.CheckConstraint("amount > 0", name="ck_payments_amount_positive"),
        sa.CheckConstraint("channel IN ('bank', 'agent')", name="ck_payments_channel_valid"),
    )
    op.create_index("ix_payments_tuition_id", "payments", ["tuition_id"])


def downgrade() -> None:
    op.drop_index("ix_payments_tuition_id", table_name="payments")
    op.drop_table("payments")
    op.drop_index("ix_tuitions_student_no", table_name="tuitions")
    op.drop_table("tuitions")
    op.drop_table("users")
    op.drop_table("students")

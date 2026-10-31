# SPDX-FileCopyrightText: 2026 Siddharth Majhi
# SPDX-License-Identifier: MIT
"""Core domain schema: tenants, calendar, synthetic scenarios, conversations, intake, bookings.

Revision ID: 293745f95565
Revises:
Create Date: 2026-10-31 10:55:36.631474+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "293745f95565"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Exclusion constraints combine a uuid equality with a range overlap in one GiST index.
    op.execute("CREATE EXTENSION IF NOT EXISTS btree_gist")
    op.create_table(
        "clinics",
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("slug", sa.String(length=64), nullable=False),
        sa.Column("timezone", sa.String(length=64), nullable=False),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "slug ~ '^[a-z0-9]+(-[a-z0-9]+)*$'", name=op.f("ck_clinics_slug_format")
        ),
        sa.CheckConstraint("length(name) BETWEEN 1 AND 120", name=op.f("ck_clinics_name_length")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_clinics")),
        sa.UniqueConstraint("slug", name=op.f("uq_clinics_slug")),
    )
    op.create_table(
        "users",
        sa.Column("email", sa.String(length=254), nullable=False),
        sa.Column("display_name", sa.String(length=120), nullable=False),
        sa.Column("password_hash", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "email ~* '^[a-z0-9._%+-]+@example\\.(com|org|net)$'",
            name=op.f("ck_users_email_reserved"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_users")),
        sa.UniqueConstraint("email", name=op.f("uq_users_email")),
    )
    op.create_table(
        "appointment_types",
        sa.Column("clinic_id", sa.UUID(), nullable=False),
        sa.Column("code", sa.String(length=40), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("duration_minutes", sa.SmallInteger(), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "code ~ '^[a-z][a-z0-9_]*$'", name=op.f("ck_appointment_types_code_format")
        ),
        sa.CheckConstraint(
            "duration_minutes > 0 AND duration_minutes % 15 = 0",
            name=op.f("ck_appointment_types_duration"),
        ),
        sa.ForeignKeyConstraint(
            ["clinic_id"],
            ["clinics.id"],
            name=op.f("fk_appointment_types_clinic_id_clinics"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_appointment_types")),
        sa.UniqueConstraint("clinic_id", "code", name=op.f("uq_appointment_types_clinic_id_code")),
        sa.UniqueConstraint("clinic_id", "id", name=op.f("uq_appointment_types_clinic_id_id")),
    )
    op.create_table(
        "audit_events",
        sa.Column("clinic_id", sa.UUID(), nullable=True),
        sa.Column("actor_user_id", sa.UUID(), nullable=True),
        sa.Column("action", sa.String(length=64), nullable=False),
        sa.Column("resource_type", sa.String(length=48), nullable=True),
        sa.Column("resource_id", sa.UUID(), nullable=True),
        sa.Column("request_id", sa.String(length=64), nullable=True),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "action ~ '^[a-z][a-z_.]*$'", name=op.f("ck_audit_events_action_format")
        ),
        sa.ForeignKeyConstraint(
            ["actor_user_id"],
            ["users.id"],
            name=op.f("fk_audit_events_actor_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["clinic_id"],
            ["clinics.id"],
            name=op.f("fk_audit_events_clinic_id_clinics"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_audit_events")),
    )
    op.create_index(
        "ix_audit_events_clinic_created_at",
        "audit_events",
        ["clinic_id", "created_at"],
        unique=False,
    )
    op.create_table(
        "clinic_users",
        sa.Column("clinic_id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column(
            "role",
            sa.Enum("admin", "staff", "viewer", name="clinicrole", native_enum=False, length=16),
            nullable=False,
        ),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "role IN ('admin', 'staff', 'viewer')", name=op.f("ck_clinic_users_role_valid")
        ),
        sa.ForeignKeyConstraint(
            ["clinic_id"],
            ["clinics.id"],
            name=op.f("fk_clinic_users_clinic_id_clinics"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_clinic_users_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_clinic_users")),
        sa.UniqueConstraint("clinic_id", "user_id", name=op.f("uq_clinic_users_clinic_id_user_id")),
    )
    op.create_index(op.f("ix_clinic_users_user_id"), "clinic_users", ["user_id"], unique=False)
    op.create_table(
        "dentists",
        sa.Column("clinic_id", sa.UUID(), nullable=False),
        sa.Column("display_name", sa.String(length=120), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["clinic_id"],
            ["clinics.id"],
            name=op.f("fk_dentists_clinic_id_clinics"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_dentists")),
        sa.UniqueConstraint("clinic_id", "id", name=op.f("uq_dentists_clinic_id_id")),
    )
    op.create_index(op.f("ix_dentists_clinic_id"), "dentists", ["clinic_id"], unique=False)
    op.create_table(
        "synthetic_personas",
        sa.Column("clinic_id", sa.UUID(), nullable=False),
        sa.Column("first_name", sa.String(length=80), nullable=False),
        sa.Column("last_name", sa.String(length=80), nullable=False),
        sa.Column("email", sa.String(length=254), nullable=True),
        sa.Column("phone", sa.String(length=16), nullable=True),
        sa.Column(
            "preferred_contact_channel",
            sa.Enum("email", "phone", name="contactchannel", native_enum=False, length=8),
            nullable=False,
        ),
        sa.Column(
            "patient_type",
            sa.Enum("new", "returning", name="patienttype", native_enum=False, length=16),
            nullable=False,
        ),
        sa.Column("background", sa.Text(), nullable=False),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "email IS NULL OR email ~* '^[a-z0-9._%+-]+@example\\.(com|org|net)$'",
            name=op.f("ck_synthetic_personas_email_reserved"),
        ),
        sa.CheckConstraint(
            "patient_type IN ('new', 'returning')",
            name=op.f("ck_synthetic_personas_patient_type_valid"),
        ),
        sa.CheckConstraint(
            "phone IS NULL OR phone ~ '^\\+1-555-01[0-9]{2}$'",
            name=op.f("ck_synthetic_personas_phone_reserved"),
        ),
        sa.CheckConstraint(
            "preferred_contact_channel IN ('email', 'phone')",
            name=op.f("ck_synthetic_personas_preferred_contact_channel_valid"),
        ),
        sa.ForeignKeyConstraint(
            ["clinic_id"],
            ["clinics.id"],
            name=op.f("fk_synthetic_personas_clinic_id_clinics"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_synthetic_personas")),
        sa.UniqueConstraint("clinic_id", "id", name=op.f("uq_synthetic_personas_clinic_id_id")),
    )
    op.create_table(
        "appointment_slots",
        sa.Column("clinic_id", sa.UUID(), nullable=False),
        sa.Column("dentist_id", sa.UUID(), nullable=False),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "status",
            sa.Enum("open", "blocked", name="slotstatus", native_enum=False, length=16),
            server_default="open",
            nullable=False,
        ),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        postgresql.ExcludeConstraint(
            (sa.column("dentist_id"), "="),
            (sa.text("tstzrange(starts_at, ends_at, '[)')"), "&&"),
            using="gist",
            name="ex_appointment_slots_dentist_no_overlap",
        ),
        sa.CheckConstraint(
            "status IN ('open', 'blocked')", name=op.f("ck_appointment_slots_status_valid")
        ),
        sa.CheckConstraint(
            "starts_at < ends_at", name=op.f("ck_appointment_slots_start_before_end")
        ),
        sa.ForeignKeyConstraint(
            ["clinic_id", "dentist_id"],
            ["dentists.clinic_id", "dentists.id"],
            name=op.f("fk_appointment_slots_clinic_id_dentist_id_dentists"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_appointment_slots")),
    )
    op.create_index(
        "ix_appointment_slots_clinic_starts_at",
        "appointment_slots",
        ["clinic_id", "starts_at"],
        unique=False,
    )
    op.create_table(
        "dentist_schedules",
        sa.Column("clinic_id", sa.UUID(), nullable=False),
        sa.Column("dentist_id", sa.UUID(), nullable=False),
        sa.Column("weekday", sa.SmallInteger(), nullable=False),
        sa.Column("start_local", sa.Time(), nullable=False),
        sa.Column("end_local", sa.Time(), nullable=False),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "start_local < end_local", name=op.f("ck_dentist_schedules_start_before_end")
        ),
        sa.CheckConstraint(
            "weekday BETWEEN 0 AND 6", name=op.f("ck_dentist_schedules_weekday_range")
        ),
        sa.ForeignKeyConstraint(
            ["clinic_id", "dentist_id"],
            ["dentists.clinic_id", "dentists.id"],
            name=op.f("fk_dentist_schedules_clinic_id_dentist_id_dentists"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_dentist_schedules")),
    )
    op.create_index(
        "ix_dentist_schedules_clinic_dentist",
        "dentist_schedules",
        ["clinic_id", "dentist_id"],
        unique=False,
    )
    op.create_table(
        "patients",
        sa.Column("clinic_id", sa.UUID(), nullable=False),
        sa.Column("persona_id", sa.UUID(), nullable=True),
        sa.Column("first_name", sa.String(length=80), nullable=False),
        sa.Column("last_name", sa.String(length=80), nullable=False),
        sa.Column("email", sa.String(length=254), nullable=True),
        sa.Column("phone", sa.String(length=16), nullable=True),
        sa.Column(
            "preferred_contact_channel",
            sa.Enum("email", "phone", name="contactchannel", native_enum=False, length=8),
            nullable=True,
        ),
        sa.Column(
            "patient_type",
            sa.Enum("new", "returning", name="patienttype", native_enum=False, length=16),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.Enum(
                "prospective",
                "registered",
                "archived",
                name="patientstatus",
                native_enum=False,
                length=16,
            ),
            server_default="prospective",
            nullable=False,
        ),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "email IS NULL OR email ~* '^[a-z0-9._%+-]+@example\\.(com|org|net)$'",
            name=op.f("ck_patients_email_reserved"),
        ),
        sa.CheckConstraint(
            "patient_type IN ('new', 'returning')", name=op.f("ck_patients_patient_type_valid")
        ),
        sa.CheckConstraint(
            "phone IS NULL OR phone ~ '^\\+1-555-01[0-9]{2}$'",
            name=op.f("ck_patients_phone_reserved"),
        ),
        sa.CheckConstraint(
            "preferred_contact_channel IN ('email', 'phone')",
            name=op.f("ck_patients_preferred_contact_channel_valid"),
        ),
        sa.CheckConstraint(
            "status IN ('prospective', 'registered', 'archived')",
            name=op.f("ck_patients_status_valid"),
        ),
        sa.CheckConstraint(
            "email IS NOT NULL OR phone IS NOT NULL", name=op.f("ck_patients_has_contact")
        ),
        sa.ForeignKeyConstraint(
            ["clinic_id", "persona_id"],
            ["synthetic_personas.clinic_id", "synthetic_personas.id"],
            name=op.f("fk_patients_clinic_id_persona_id_synthetic_personas"),
        ),
        sa.ForeignKeyConstraint(
            ["clinic_id"],
            ["clinics.id"],
            name=op.f("fk_patients_clinic_id_clinics"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_patients")),
        sa.UniqueConstraint("clinic_id", "id", name=op.f("uq_patients_clinic_id_id")),
    )
    op.create_index(
        "ix_patients_clinic_last_name", "patients", ["clinic_id", "last_name"], unique=False
    )
    op.create_index(
        "uq_patients_clinic_email",
        "patients",
        ["clinic_id", sa.literal_column("lower(email)")],
        unique=True,
        postgresql_where=sa.text("email IS NOT NULL"),
    )
    op.create_index(
        "uq_patients_clinic_phone",
        "patients",
        ["clinic_id", "phone"],
        unique=True,
        postgresql_where=sa.text("phone IS NOT NULL"),
    )
    op.create_table(
        "synthetic_scenarios",
        sa.Column("clinic_id", sa.UUID(), nullable=False),
        sa.Column("persona_id", sa.UUID(), nullable=False),
        sa.Column("code", sa.String(length=1), nullable=False),
        sa.Column("title", sa.String(length=120), nullable=False),
        sa.Column("objective", sa.Text(), nullable=False),
        sa.Column("clips", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("expected", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("code ~ '^[A-Z]$'", name=op.f("ck_synthetic_scenarios_code_format")),
        sa.CheckConstraint(
            "jsonb_typeof(clips) = 'array'", name=op.f("ck_synthetic_scenarios_clips_is_array")
        ),
        sa.CheckConstraint(
            "jsonb_typeof(expected) = 'object'",
            name=op.f("ck_synthetic_scenarios_expected_is_object"),
        ),
        sa.ForeignKeyConstraint(
            ["clinic_id", "persona_id"],
            ["synthetic_personas.clinic_id", "synthetic_personas.id"],
            name=op.f("fk_synthetic_scenarios_clinic_id_persona_id_synthetic_personas"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_synthetic_scenarios")),
        sa.UniqueConstraint(
            "clinic_id", "code", name=op.f("uq_synthetic_scenarios_clinic_id_code")
        ),
        sa.UniqueConstraint("clinic_id", "id", name=op.f("uq_synthetic_scenarios_clinic_id_id")),
    )
    op.create_table(
        "conversations",
        sa.Column("clinic_id", sa.UUID(), nullable=False),
        sa.Column("scenario_id", sa.UUID(), nullable=False),
        sa.Column("patient_id", sa.UUID(), nullable=True),
        sa.Column("started_by_user_id", sa.UUID(), nullable=True),
        sa.Column(
            "state",
            sa.Enum(
                "CREATED",
                "GREETING",
                "INTRODUCTION",
                "IDENTITY_COLLECTION",
                "CONTACT_DETAILS",
                "VISIT_REASON",
                "APPOINTMENT_PREFERENCES",
                "INFORMATION_REVIEW",
                "CONFIRMATION_PENDING",
                "COMPLETED",
                "ESCALATED",
                "ABANDONED",
                name="conversationstate",
                native_enum=False,
                length=32,
            ),
            server_default="CREATED",
            nullable=False,
        ),
        sa.Column("state_version", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column(
            "provider_mode",
            sa.Enum("mock", "live", name="providermode", native_enum=False, length=8),
            nullable=False,
        ),
        sa.Column("turn_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "(state IN ('COMPLETED', 'ESCALATED', 'ABANDONED')) = (ended_at IS NOT NULL)",
            name=op.f("ck_conversations_ended_iff_terminal"),
        ),
        sa.CheckConstraint(
            "provider_mode IN ('mock', 'live')", name=op.f("ck_conversations_provider_mode_valid")
        ),
        sa.CheckConstraint(
            "state IN ('CREATED', 'GREETING', 'INTRODUCTION', 'IDENTITY_COLLECTION', 'CONTACT_DETAILS', 'VISIT_REASON', 'APPOINTMENT_PREFERENCES', 'INFORMATION_REVIEW', 'CONFIRMATION_PENDING', 'COMPLETED', 'ESCALATED', 'ABANDONED')",
            name=op.f("ck_conversations_state_valid"),
        ),
        sa.CheckConstraint(
            "state_version >= 1", name=op.f("ck_conversations_state_version_positive")
        ),
        sa.CheckConstraint(
            "turn_count >= 0", name=op.f("ck_conversations_turn_count_non_negative")
        ),
        sa.ForeignKeyConstraint(
            ["clinic_id", "patient_id"],
            ["patients.clinic_id", "patients.id"],
            name=op.f("fk_conversations_clinic_id_patient_id_patients"),
        ),
        sa.ForeignKeyConstraint(
            ["clinic_id", "scenario_id"],
            ["synthetic_scenarios.clinic_id", "synthetic_scenarios.id"],
            name=op.f("fk_conversations_clinic_id_scenario_id_synthetic_scenarios"),
        ),
        sa.ForeignKeyConstraint(
            ["clinic_id"],
            ["clinics.id"],
            name=op.f("fk_conversations_clinic_id_clinics"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["started_by_user_id"],
            ["users.id"],
            name=op.f("fk_conversations_started_by_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_conversations")),
        sa.UniqueConstraint("clinic_id", "id", name=op.f("uq_conversations_clinic_id_id")),
    )
    op.create_index(
        "ix_conversations_clinic_created_at",
        "conversations",
        ["clinic_id", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_conversations_clinic_state", "conversations", ["clinic_id", "state"], unique=False
    )
    op.create_table(
        "appointments",
        sa.Column("clinic_id", sa.UUID(), nullable=False),
        sa.Column("patient_id", sa.UUID(), nullable=False),
        sa.Column("dentist_id", sa.UUID(), nullable=False),
        sa.Column("appointment_type_id", sa.UUID(), nullable=False),
        sa.Column("conversation_id", sa.UUID(), nullable=True),
        sa.Column("rescheduled_from_id", sa.UUID(), nullable=True),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "requested",
                "confirmed",
                "cancelled",
                "rescheduled",
                name="appointmentstatus",
                native_enum=False,
                length=16,
            ),
            nullable=False,
        ),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("request_hash", sa.String(length=64), nullable=False),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        postgresql.ExcludeConstraint(
            (sa.column("dentist_id"), "="),
            (sa.text("tstzrange(starts_at, ends_at, '[)')"), "&&"),
            where=sa.text("status IN ('confirmed', 'requested')"),
            using="gist",
            name="ex_appointments_dentist_no_overlap",
        ),
        sa.CheckConstraint(
            "status IN ('requested', 'confirmed', 'cancelled', 'rescheduled')",
            name=op.f("ck_appointments_status_valid"),
        ),
        sa.CheckConstraint(
            "length(idempotency_key) BETWEEN 8 AND 128",
            name=op.f("ck_appointments_idempotency_key_length"),
        ),
        sa.CheckConstraint("starts_at < ends_at", name=op.f("ck_appointments_start_before_end")),
        sa.ForeignKeyConstraint(
            ["clinic_id", "appointment_type_id"],
            ["appointment_types.clinic_id", "appointment_types.id"],
            name=op.f("fk_appointments_clinic_id_appointment_type_id_appointment_types"),
        ),
        sa.ForeignKeyConstraint(
            ["clinic_id", "conversation_id"],
            ["conversations.clinic_id", "conversations.id"],
            name=op.f("fk_appointments_clinic_id_conversation_id_conversations"),
        ),
        sa.ForeignKeyConstraint(
            ["clinic_id", "dentist_id"],
            ["dentists.clinic_id", "dentists.id"],
            name=op.f("fk_appointments_clinic_id_dentist_id_dentists"),
        ),
        sa.ForeignKeyConstraint(
            ["clinic_id", "patient_id"],
            ["patients.clinic_id", "patients.id"],
            name=op.f("fk_appointments_clinic_id_patient_id_patients"),
        ),
        sa.ForeignKeyConstraint(
            ["clinic_id", "rescheduled_from_id"],
            ["appointments.clinic_id", "appointments.id"],
            name=op.f("fk_appointments_clinic_id_rescheduled_from_id_appointments"),
        ),
        sa.ForeignKeyConstraint(
            ["clinic_id"],
            ["clinics.id"],
            name=op.f("fk_appointments_clinic_id_clinics"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_appointments")),
        sa.UniqueConstraint("clinic_id", "id", name=op.f("uq_appointments_clinic_id_id")),
        sa.UniqueConstraint(
            "clinic_id", "idempotency_key", name=op.f("uq_appointments_clinic_id_idempotency_key")
        ),
    )
    op.create_index(
        "ix_appointments_clinic_patient", "appointments", ["clinic_id", "patient_id"], unique=False
    )
    op.create_index(
        "ix_appointments_clinic_starts_at", "appointments", ["clinic_id", "starts_at"], unique=False
    )
    op.create_table(
        "conversation_events",
        sa.Column("clinic_id", sa.UUID(), nullable=False),
        sa.Column("conversation_id", sa.UUID(), nullable=False),
        sa.Column("type", sa.String(length=48), nullable=False),
        sa.Column(
            "payload",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "jsonb_typeof(payload) = 'object'",
            name=op.f("ck_conversation_events_payload_is_object"),
        ),
        sa.CheckConstraint(
            "type ~ '^[a-z][a-z_.]*$'", name=op.f("ck_conversation_events_type_format")
        ),
        sa.ForeignKeyConstraint(
            ["clinic_id", "conversation_id"],
            ["conversations.clinic_id", "conversations.id"],
            name=op.f("fk_conversation_events_clinic_id_conversation_id_conversations"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_conversation_events")),
    )
    op.create_index(
        "ix_conversation_events_conversation_created",
        "conversation_events",
        ["conversation_id", "created_at"],
        unique=False,
    )
    op.create_table(
        "conversation_turns",
        sa.Column("clinic_id", sa.UUID(), nullable=False),
        sa.Column("conversation_id", sa.UUID(), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column(
            "speaker",
            sa.Enum("caller", "receptionist", name="speaker", native_enum=False, length=16),
            nullable=False,
        ),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("clip_id", sa.String(length=64), nullable=True),
        sa.Column("stt_ms", sa.Integer(), nullable=True),
        sa.Column("llm_ms", sa.Integer(), nullable=True),
        sa.Column("tts_ms", sa.Integer(), nullable=True),
        sa.Column("total_ms", sa.Integer(), nullable=True),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "speaker IN ('caller', 'receptionist')",
            name=op.f("ck_conversation_turns_speaker_valid"),
        ),
        sa.CheckConstraint(
            "coalesce(stt_ms, 0) >= 0 AND coalesce(llm_ms, 0) >= 0 AND coalesce(tts_ms, 0) >= 0 AND coalesce(total_ms, 0) >= 0",
            name=op.f("ck_conversation_turns_latency_non_negative"),
        ),
        sa.CheckConstraint("seq >= 1", name=op.f("ck_conversation_turns_seq_positive")),
        sa.ForeignKeyConstraint(
            ["clinic_id", "conversation_id"],
            ["conversations.clinic_id", "conversations.id"],
            name=op.f("fk_conversation_turns_clinic_id_conversation_id_conversations"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_conversation_turns")),
        sa.UniqueConstraint("clinic_id", "id", name=op.f("uq_conversation_turns_clinic_id_id")),
        sa.UniqueConstraint(
            "conversation_id", "seq", name=op.f("uq_conversation_turns_conversation_id_seq")
        ),
    )
    op.create_table(
        "intake_snapshots",
        sa.Column("clinic_id", sa.UUID(), nullable=False),
        sa.Column("conversation_id", sa.UUID(), nullable=False),
        sa.Column("data", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "jsonb_typeof(data) = 'object'", name=op.f("ck_intake_snapshots_data_is_object")
        ),
        sa.ForeignKeyConstraint(
            ["clinic_id", "conversation_id"],
            ["conversations.clinic_id", "conversations.id"],
            name=op.f("fk_intake_snapshots_clinic_id_conversation_id_conversations"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_intake_snapshots")),
        sa.UniqueConstraint("conversation_id", name=op.f("uq_intake_snapshots_conversation_id")),
    )
    op.create_table(
        "intake_drafts",
        sa.Column("clinic_id", sa.UUID(), nullable=False),
        sa.Column("conversation_id", sa.UUID(), nullable=False),
        sa.Column(
            "field",
            sa.Enum(
                "first_name",
                "last_name",
                "patient_type",
                "preferred_contact_channel",
                "email",
                "phone",
                "visit_reason",
                "requested_service",
                "preferred_date",
                "preferred_time",
                name="intakefield",
                native_enum=False,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("value", sa.Text(), nullable=True),
        sa.Column(
            "status",
            sa.Enum(
                "provided",
                "needs_confirmation",
                "confirmed",
                "rejected",
                "superseded",
                name="intakefieldstatus",
                native_enum=False,
                length=24,
            ),
            nullable=False,
        ),
        sa.Column("source_turn_id", sa.UUID(), nullable=True),
        sa.Column("confidence", sa.Numeric(precision=4, scale=3), nullable=True),
        sa.Column("rejection_reason", sa.String(length=200), nullable=True),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "(status = 'rejected') = (rejection_reason IS NOT NULL)",
            name=op.f("ck_intake_drafts_rejection_has_reason"),
        ),
        sa.CheckConstraint(
            "field IN ('first_name', 'last_name', 'patient_type', 'preferred_contact_channel', 'email', 'phone', 'visit_reason', 'requested_service', 'preferred_date', 'preferred_time')",
            name=op.f("ck_intake_drafts_field_valid"),
        ),
        sa.CheckConstraint(
            "status IN ('provided', 'needs_confirmation', 'confirmed', 'rejected', 'superseded')",
            name=op.f("ck_intake_drafts_status_valid"),
        ),
        sa.CheckConstraint(
            "confidence IS NULL OR confidence BETWEEN 0 AND 1",
            name=op.f("ck_intake_drafts_confidence_range"),
        ),
        sa.ForeignKeyConstraint(
            ["clinic_id", "conversation_id"],
            ["conversations.clinic_id", "conversations.id"],
            name=op.f("fk_intake_drafts_clinic_id_conversation_id_conversations"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["clinic_id", "source_turn_id"],
            ["conversation_turns.clinic_id", "conversation_turns.id"],
            name=op.f("fk_intake_drafts_clinic_id_source_turn_id_conversation_turns"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_intake_drafts")),
    )
    op.create_index(
        "uq_intake_drafts_live_field",
        "intake_drafts",
        ["conversation_id", "field"],
        unique=True,
        postgresql_where=sa.text("status IN ('provided', 'needs_confirmation', 'confirmed')"),
    )


def downgrade() -> None:
    op.drop_index(
        "uq_intake_drafts_live_field",
        table_name="intake_drafts",
        postgresql_where=sa.text("status IN ('provided', 'needs_confirmation', 'confirmed')"),
    )
    op.drop_table("intake_drafts")
    op.drop_table("intake_snapshots")
    op.drop_table("conversation_turns")
    op.drop_index("ix_conversation_events_conversation_created", table_name="conversation_events")
    op.drop_table("conversation_events")
    op.drop_index("ix_appointments_clinic_starts_at", table_name="appointments")
    op.drop_index("ix_appointments_clinic_patient", table_name="appointments")
    op.drop_table("appointments")
    op.drop_index("ix_conversations_clinic_state", table_name="conversations")
    op.drop_index("ix_conversations_clinic_created_at", table_name="conversations")
    op.drop_table("conversations")
    op.drop_table("synthetic_scenarios")
    op.drop_index(
        "uq_patients_clinic_phone",
        table_name="patients",
        postgresql_where=sa.text("phone IS NOT NULL"),
    )
    op.drop_index(
        "uq_patients_clinic_email",
        table_name="patients",
        postgresql_where=sa.text("email IS NOT NULL"),
    )
    op.drop_index("ix_patients_clinic_last_name", table_name="patients")
    op.drop_table("patients")
    op.drop_index("ix_dentist_schedules_clinic_dentist", table_name="dentist_schedules")
    op.drop_table("dentist_schedules")
    op.drop_index("ix_appointment_slots_clinic_starts_at", table_name="appointment_slots")
    op.drop_table("appointment_slots")
    op.drop_table("synthetic_personas")
    op.drop_index(op.f("ix_dentists_clinic_id"), table_name="dentists")
    op.drop_table("dentists")
    op.drop_index(op.f("ix_clinic_users_user_id"), table_name="clinic_users")
    op.drop_table("clinic_users")
    op.drop_index("ix_audit_events_clinic_created_at", table_name="audit_events")
    op.drop_table("audit_events")
    op.drop_table("appointment_types")
    op.drop_table("users")
    op.drop_table("clinics")
    op.execute("DROP EXTENSION IF EXISTS btree_gist")

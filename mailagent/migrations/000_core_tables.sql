-- Core mailagent tables must exist before 001_full_schema.sql creates tables
-- that reference them. These definitions mirror mailagent/src/mailagent/models.py.

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

CREATE TABLE IF NOT EXISTS mailagent_providers (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name VARCHAR(100) NOT NULL,
    provider_type VARCHAR(50) NOT NULL,
    credentials JSONB NOT NULL DEFAULT '{}'::jsonb,
    status VARCHAR(20) NOT NULL DEFAULT 'setup',
    is_default BOOLEAN NOT NULL DEFAULT FALSE,
    priority INTEGER NOT NULL DEFAULT 100,
    rate_limit_per_minute INTEGER,
    rate_limit_per_day INTEGER,
    last_health_check TIMESTAMPTZ,
    error_count INTEGER NOT NULL DEFAULT 0,
    last_error TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS mailagent_domains (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    domain VARCHAR(255) NOT NULL UNIQUE,
    status VARCHAR(20) NOT NULL DEFAULT 'pending',
    dns_records JSONB NOT NULL DEFAULT '{}'::jsonb,
    warming_schedule VARCHAR(20),
    warming_day INTEGER NOT NULL DEFAULT 0,
    warming_started_at TIMESTAMPTZ,
    daily_limit INTEGER,
    health_score INTEGER NOT NULL DEFAULT 0,
    emails_sent_today INTEGER NOT NULL DEFAULT 0,
    last_email_sent_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS mailagent_inboxes (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    email VARCHAR(255) NOT NULL UNIQUE,
    display_name VARCHAR(255),
    domain_id UUID REFERENCES mailagent_domains(id),
    is_verified BOOLEAN NOT NULL DEFAULT FALSE,
    verification_token VARCHAR(64),
    verified_at TIMESTAMPTZ,
    emails_sent INTEGER NOT NULL DEFAULT 0,
    last_email_sent_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

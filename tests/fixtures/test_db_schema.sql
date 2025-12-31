-- Test database schema for db_introspect testing
-- Creates sample tables, functions, triggers, views, etc.

-- Create test schema
CREATE SCHEMA IF NOT EXISTS test_schema;

-- Create extensions
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- Tables
CREATE TABLE IF NOT EXISTS test_schema.users (
    id SERIAL PRIMARY KEY,
    username VARCHAR(100) NOT NULL UNIQUE,
    email VARCHAR(255) NOT NULL,
    password_hash TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS test_schema.orders (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id INTEGER NOT NULL REFERENCES test_schema.users(id) ON DELETE CASCADE,
    total_amount DECIMAL(10, 2) NOT NULL,
    status VARCHAR(50) NOT NULL DEFAULT 'pending',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT check_positive_amount CHECK (total_amount > 0)
);

CREATE TABLE IF NOT EXISTS test_schema.order_items (
    id SERIAL PRIMARY KEY,
    order_id UUID NOT NULL REFERENCES test_schema.orders(id) ON DELETE CASCADE,
    product_name VARCHAR(200) NOT NULL,
    quantity INTEGER NOT NULL,
    price DECIMAL(10, 2) NOT NULL,
    CONSTRAINT check_positive_quantity CHECK (quantity > 0)
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_users_email ON test_schema.users(email);
CREATE INDEX IF NOT EXISTS idx_orders_user_id ON test_schema.orders(user_id);
CREATE INDEX IF NOT EXISTS idx_orders_status ON test_schema.orders(status);
CREATE INDEX IF NOT EXISTS idx_order_items_order_id ON test_schema.order_items(order_id);

-- Simple function
CREATE OR REPLACE FUNCTION test_schema.get_user_order_count(p_user_id INTEGER)
RETURNS INTEGER
LANGUAGE plpgsql
STABLE
AS $$
BEGIN
    RETURN (SELECT COUNT(*) FROM test_schema.orders WHERE user_id = p_user_id);
END;
$$;

-- Function with dynamic SQL (risk: SQL injection)
CREATE OR REPLACE FUNCTION test_schema.search_users_dynamic(search_term TEXT)
RETURNS TABLE(id INTEGER, username VARCHAR, email VARCHAR)
LANGUAGE plpgsql
VOLATILE
AS $$
DECLARE
    query TEXT;
BEGIN
    -- UNSAFE: Dynamic SQL with string concatenation
    query := 'SELECT id, username, email FROM test_schema.users WHERE username LIKE ''%' || search_term || '%''';
    RETURN QUERY EXECUTE query;
END;
$$;

-- Function with SECURITY DEFINER without search_path (risk: injection)
CREATE OR REPLACE FUNCTION test_schema.elevate_user_role(p_user_id INTEGER)
RETURNS VOID
LANGUAGE plpgsql
SECURITY DEFINER
AS $$
BEGIN
    -- RISKY: SECURITY DEFINER without explicit search_path
    UPDATE test_schema.users SET updated_at = now() WHERE id = p_user_id;
    -- Simulate privilege escalation
    PERFORM pg_sleep(0.1);
END;
$$;

-- Function with SECURITY DEFINER and proper search_path (safe)
CREATE OR REPLACE FUNCTION test_schema.safe_get_user(p_user_id INTEGER)
RETURNS TABLE(id INTEGER, username VARCHAR, email VARCHAR)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = test_schema, pg_temp
AS $$
BEGIN
    RETURN QUERY SELECT u.id, u.username, u.email FROM test_schema.users u WHERE u.id = p_user_id;
END;
$$;

-- Complex function with high cyclomatic complexity
CREATE OR REPLACE FUNCTION test_schema.calculate_order_discount(
    p_order_id UUID,
    p_user_tier VARCHAR
)
RETURNS DECIMAL(10, 2)
LANGUAGE plpgsql
VOLATILE
AS $$
DECLARE
    v_total DECIMAL(10, 2);
    v_discount DECIMAL(10, 2) := 0;
    v_order_count INTEGER;
BEGIN
    SELECT total_amount INTO v_total FROM test_schema.orders WHERE id = p_order_id;

    IF v_total IS NULL THEN
        RETURN 0;
    END IF;

    -- High complexity with many branches
    IF p_user_tier = 'gold' THEN
        IF v_total > 1000 THEN
            v_discount := v_total * 0.20;
        ELSIF v_total > 500 THEN
            v_discount := v_total * 0.15;
        ELSIF v_total > 100 THEN
            v_discount := v_total * 0.10;
        ELSE
            v_discount := v_total * 0.05;
        END IF;
    ELSIF p_user_tier = 'silver' THEN
        IF v_total > 1000 THEN
            v_discount := v_total * 0.15;
        ELSIF v_total > 500 THEN
            v_discount := v_total * 0.10;
        ELSIF v_total > 100 THEN
            v_discount := v_total * 0.05;
        END IF;
    ELSIF p_user_tier = 'bronze' THEN
        IF v_total > 1000 THEN
            v_discount := v_total * 0.10;
        ELSIF v_total > 500 THEN
            v_discount := v_total * 0.05;
        END IF;
    END IF;

    -- Additional complexity
    SELECT COUNT(*) INTO v_order_count FROM test_schema.orders WHERE user_id = (
        SELECT user_id FROM test_schema.orders WHERE id = p_order_id
    );

    IF v_order_count > 100 THEN
        v_discount := v_discount * 1.5;
    ELSIF v_order_count > 50 THEN
        v_discount := v_discount * 1.25;
    ELSIF v_order_count > 10 THEN
        v_discount := v_discount * 1.1;
    END IF;

    RETURN LEAST(v_discount, v_total * 0.5); -- Cap at 50%
END;
$$;

-- Trigger function
CREATE OR REPLACE FUNCTION test_schema.update_user_timestamp()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$;

-- Trigger
CREATE TRIGGER trg_users_update
    BEFORE UPDATE ON test_schema.users
    FOR EACH ROW
    EXECUTE FUNCTION test_schema.update_user_timestamp();

-- View
CREATE OR REPLACE VIEW test_schema.user_order_summary AS
SELECT
    u.id,
    u.username,
    u.email,
    COUNT(o.id) AS order_count,
    COALESCE(SUM(o.total_amount), 0) AS total_spent
FROM test_schema.users u
LEFT JOIN test_schema.orders o ON o.user_id = u.id
GROUP BY u.id, u.username, u.email;

-- Materialized view
CREATE MATERIALIZED VIEW IF NOT EXISTS test_schema.daily_order_stats AS
SELECT
    DATE(created_at) AS order_date,
    COUNT(*) AS order_count,
    SUM(total_amount) AS total_revenue,
    AVG(total_amount) AS avg_order_value
FROM test_schema.orders
GROUP BY DATE(created_at)
WITH DATA;

CREATE INDEX IF NOT EXISTS idx_daily_stats_date ON test_schema.daily_order_stats(order_date);

-- Enum type
CREATE TYPE test_schema.order_status_enum AS ENUM ('pending', 'processing', 'shipped', 'delivered', 'cancelled');

-- Custom domain
CREATE DOMAIN test_schema.email_address AS TEXT
CHECK (VALUE ~ '^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$');

-- Sequence
CREATE SEQUENCE IF NOT EXISTS test_schema.invoice_number_seq
    START WITH 1000
    INCREMENT BY 1
    NO MAXVALUE
    CACHE 10;

-- Function using deprecated features (for testing)
CREATE OR REPLACE FUNCTION test_schema.deprecated_user_check()
RETURNS BOOLEAN
LANGUAGE plpgsql
AS $$
DECLARE
    v_count INTEGER;
BEGIN
    -- Using deprecated pg_user
    SELECT COUNT(*) INTO v_count FROM pg_user WHERE usename = current_user;
    RETURN v_count > 0;
END;
$$;

-- Function with SET ROLE (risky)
CREATE OR REPLACE FUNCTION test_schema.risky_admin_operation()
RETURNS VOID
LANGUAGE plpgsql
SECURITY DEFINER
AS $$
BEGIN
    SET ROLE postgres;
    -- Risky operation
    PERFORM pg_sleep(0.1);
END;
$$;

-- Migration tracking table (Alembic-style)
CREATE TABLE IF NOT EXISTS public.alembic_version (
    version_num VARCHAR(32) NOT NULL PRIMARY KEY
);

-- Insert sample data
INSERT INTO test_schema.users (username, email, password_hash) VALUES
    ('alice', 'alice@example.com', '$2b$12$KIXxKj4tX.DummyHash1'),
    ('bob', 'bob@example.com', '$2b$12$KIXxKj4tX.DummyHash2'),
    ('charlie', 'charlie@example.com', '$2b$12$KIXxKj4tX.DummyHash3')
ON CONFLICT (username) DO NOTHING;

INSERT INTO test_schema.orders (user_id, total_amount, status)
SELECT
    u.id,
    (RANDOM() * 500 + 50)::DECIMAL(10,2),
    (ARRAY['pending', 'processing', 'shipped', 'delivered'])[FLOOR(RANDOM() * 4 + 1)::INTEGER]
FROM test_schema.users u
CROSS JOIN generate_series(1, 3)
ON CONFLICT DO NOTHING;

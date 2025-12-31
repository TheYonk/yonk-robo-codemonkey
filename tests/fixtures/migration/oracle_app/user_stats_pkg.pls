CREATE OR REPLACE PACKAGE user_stats_pkg AS
    -- Package specification for user statistics

    PROCEDURE calculate_monthly_stats;
    PROCEDURE calculate_daily_active_users(p_date IN DATE);
    FUNCTION get_user_count RETURN NUMBER;
    FUNCTION get_revenue_by_user(p_user_id IN NUMBER) RETURN NUMBER;

END user_stats_pkg;
/

CREATE OR REPLACE PACKAGE BODY user_stats_pkg AS

    -- Calculate monthly statistics
    PROCEDURE calculate_monthly_stats IS
        v_month_start DATE;
        v_month_end DATE;
        v_user_count NUMBER;
        v_revenue NUMBER;
    BEGIN
        -- Get current month boundaries
        v_month_start := TRUNC(SYSDATE, 'MM');
        v_month_end := LAST_DAY(SYSDATE);

        -- Calculate user count using ROWNUM and subquery
        SELECT COUNT(*)
        INTO v_user_count
        FROM (
            SELECT user_id
            FROM users
            WHERE created_at BETWEEN v_month_start AND v_month_end
            AND ROWNUM <= 10000
        );

        -- Calculate revenue with NVL
        SELECT NVL(SUM(amount), 0)
        INTO v_revenue
        FROM orders
        WHERE order_date BETWEEN v_month_start AND v_month_end;

        -- Insert stats using DECODE for status mapping
        INSERT INTO monthly_stats (
            stat_month,
            user_count,
            revenue,
            status
        ) VALUES (
            v_month_start,
            v_user_count,
            v_revenue,
            DECODE(v_user_count, 0, 'INACTIVE', 'ACTIVE')
        );

        COMMIT;

    EXCEPTION
        WHEN OTHERS THEN
            ROLLBACK;
            RAISE;
    END calculate_monthly_stats;

    -- Calculate daily active users
    PROCEDURE calculate_daily_active_users(p_date IN DATE) IS
        v_dau_count NUMBER;
    BEGIN
        -- Hierarchical query with CONNECT BY
        SELECT COUNT(DISTINCT user_id)
        INTO v_dau_count
        FROM user_sessions
        WHERE TRUNC(session_start) = TRUNC(p_date)
        START WITH session_id IS NOT NULL
        CONNECT BY PRIOR session_id = parent_session_id;

        -- Update using MERGE (Oracle-specific)
        MERGE INTO daily_stats d
        USING (SELECT p_date as stat_date, v_dau_count as dau FROM DUAL) s
        ON (d.stat_date = s.stat_date)
        WHEN MATCHED THEN
            UPDATE SET d.daily_active_users = s.dau
        WHEN NOT MATCHED THEN
            INSERT (stat_date, daily_active_users)
            VALUES (s.stat_date, s.dau);

        COMMIT;
    END calculate_daily_active_users;

    -- Get total user count
    FUNCTION get_user_count RETURN NUMBER IS
        v_count NUMBER;
    BEGIN
        SELECT COUNT(*) INTO v_count FROM users;
        RETURN v_count;
    END get_user_count;

    -- Get revenue by user with Oracle-specific functions
    FUNCTION get_revenue_by_user(p_user_id IN NUMBER) RETURN NUMBER IS
        v_revenue NUMBER;
    BEGIN
        SELECT NVL(SUM(amount), 0)
        INTO v_revenue
        FROM orders
        WHERE user_id = p_user_id
        AND order_date >= ADD_MONTHS(SYSDATE, -12);

        RETURN v_revenue;
    END get_revenue_by_user;

END user_stats_pkg;
/

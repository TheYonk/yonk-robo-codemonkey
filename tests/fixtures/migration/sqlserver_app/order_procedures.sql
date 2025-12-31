-- SQL Server stored procedures for order processing

-- Procedure to process pending orders
CREATE OR ALTER PROCEDURE process_pending_orders
AS
BEGIN
    SET NOCOUNT ON;

    DECLARE @order_id INT;
    DECLARE @user_id INT;
    DECLARE @total_amount DECIMAL(10,2);

    -- Use TOP with variable
    DECLARE order_cursor CURSOR FOR
        SELECT TOP 1000 order_id, user_id, total_amount
        FROM orders WITH (NOLOCK)
        WHERE status = 'pending'
        ORDER BY order_date ASC;

    OPEN order_cursor;

    FETCH NEXT FROM order_cursor INTO @order_id, @user_id, @total_amount;

    WHILE @@FETCH_STATUS = 0
    BEGIN
        BEGIN TRY
            BEGIN TRAN

            -- Update order status using GETDATE()
            UPDATE orders WITH (ROWLOCK)
            SET status = 'processed',
                processed_at = GETDATE()
            WHERE order_id = @order_id;

            -- Update user stats with ISNULL
            UPDATE user_stats
            SET total_orders = ISNULL(total_orders, 0) + 1,
                total_spent = ISNULL(total_spent, 0.0) + @total_amount
            WHERE user_id = @user_id;

            COMMIT TRAN

        END TRY
        BEGIN CATCH
            ROLLBACK TRAN
            -- Log error (SQL Server error handling)
            INSERT INTO error_log (error_message, error_date)
            VALUES (ERROR_MESSAGE(), GETDATE());
        END CATCH

        FETCH NEXT FROM order_cursor INTO @order_id, @user_id, @total_amount;
    END

    CLOSE order_cursor;
    DEALLOCATE order_cursor;

END
GO

-- Procedure to calculate order metrics
CREATE OR ALTER PROCEDURE calculate_order_metrics
    @start_date DATE,
    @end_date DATE
AS
BEGIN
    SET NOCOUNT ON;

    -- Temporary table (SQL Server specific)
    CREATE TABLE #temp_metrics (
        metric_date DATE,
        order_count INT,
        revenue DECIMAL(12,2),
        avg_order_value DECIMAL(10,2)
    );

    -- Insert metrics using SQL Server date functions
    INSERT INTO #temp_metrics
    SELECT
        CAST(order_date AS DATE) as metric_date,
        COUNT(*) as order_count,
        ISNULL(SUM(total_amount), 0.0) as revenue,
        ISNULL(AVG(total_amount), 0.0) as avg_order_value
    FROM orders WITH (NOLOCK)
    WHERE order_date BETWEEN @start_date AND @end_date
    GROUP BY CAST(order_date AS DATE);

    -- Merge into permanent table using SQL Server MERGE
    MERGE INTO daily_metrics AS target
    USING #temp_metrics AS source
    ON target.metric_date = source.metric_date
    WHEN MATCHED THEN
        UPDATE SET
            target.order_count = source.order_count,
            target.revenue = source.revenue,
            target.avg_order_value = source.avg_order_value,
            target.updated_at = GETDATE()
    WHEN NOT MATCHED THEN
        INSERT (metric_date, order_count, revenue, avg_order_value, created_at)
        VALUES (source.metric_date, source.order_count, source.revenue,
                source.avg_order_value, GETDATE());

    DROP TABLE #temp_metrics;

    -- Return results using OUTPUT clause
    SELECT metric_date, order_count, revenue
    FROM daily_metrics WITH (NOLOCK)
    WHERE metric_date BETWEEN @start_date AND @end_date
    ORDER BY metric_date DESC;

END
GO

-- Function with SQL Server syntax
CREATE OR ALTER FUNCTION dbo.get_user_tier(@user_id INT)
RETURNS VARCHAR(20)
AS
BEGIN
    DECLARE @tier VARCHAR(20);
    DECLARE @total_spent DECIMAL(12,2);

    -- Get total spent using ISNULL
    SELECT @total_spent = ISNULL(SUM(total_amount), 0.0)
    FROM orders WITH (NOLOCK)
    WHERE user_id = @user_id;

    -- Determine tier using CASE
    SET @tier = CASE
        WHEN @total_spent >= 10000 THEN 'platinum'
        WHEN @total_spent >= 5000 THEN 'gold'
        WHEN @total_spent >= 1000 THEN 'silver'
        ELSE 'bronze'
    END;

    RETURN @tier;
END
GO

-- Indexed view (SQL Server specific feature)
CREATE VIEW dbo.vw_order_summary
WITH SCHEMABINDING
AS
SELECT
    user_id,
    COUNT_BIG(*) as order_count,
    SUM(ISNULL(total_amount, 0.0)) as total_revenue
FROM dbo.orders
WHERE status = 'completed'
GROUP BY user_id
GO

-- Create unique clustered index on the view
CREATE UNIQUE CLUSTERED INDEX IX_vw_order_summary
ON dbo.vw_order_summary(user_id)
GO

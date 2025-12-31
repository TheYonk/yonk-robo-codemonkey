"""
Order service with SQL Server database access patterns.
"""
import pyodbc
from datetime import datetime


class OrderService:
    def __init__(self, connection_string: str):
        self.connection = pyodbc.connect(connection_string)

    def get_recent_orders(self, count: int = 100):
        """Get recent orders using SQL Server TOP clause."""
        cursor = self.connection.cursor()
        # SQL Server TOP syntax
        query = """
            SELECT TOP (?) order_id, user_id, total_amount, order_date
            FROM orders WITH (NOLOCK)
            ORDER BY order_date DESC
        """
        cursor.execute(query, count)
        return cursor.fetchall()

    def get_orders_with_items(self, order_id: int):
        """Get order with items using NOLOCK hint."""
        cursor = self.connection.cursor()
        # SQL Server NOLOCK table hint
        query = """
            SELECT
                o.order_id,
                o.order_date,
                o.status,
                oi.item_id,
                oi.quantity,
                oi.price
            FROM orders o WITH (NOLOCK)
            INNER JOIN order_items oi WITH (NOLOCK)
                ON o.order_id = oi.order_id
            WHERE o.order_id = ?
        """
        cursor.execute(query, order_id)
        return cursor.fetchall()

    def create_order(self, user_id: int, items: list):
        """Create order and return identity value."""
        cursor = self.connection.cursor()
        # SQL Server IDENTITY column
        query = """
            INSERT INTO orders (user_id, order_date, status)
            VALUES (?, GETDATE(), 'pending');
            SELECT SCOPE_IDENTITY() as order_id;
        """
        cursor.execute(query, user_id)
        order_id = cursor.fetchone()[0]

        # Bulk insert items
        for item in items:
            item_query = """
                INSERT INTO order_items (order_id, item_id, quantity, price)
                VALUES (?, ?, ?, ?)
            """
            cursor.execute(item_query, order_id, item['item_id'], item['quantity'], item['price'])

        self.connection.commit()
        return int(order_id)

    def get_order_stats(self, start_date: datetime, end_date: datetime):
        """Get order statistics using SQL Server window functions."""
        cursor = self.connection.cursor()
        # SQL Server specific syntax with OVER clause
        query = """
            SELECT
                order_date,
                COUNT(*) as order_count,
                SUM(total_amount) as revenue,
                ROW_NUMBER() OVER (ORDER BY order_date DESC) as row_num
            FROM orders WITH (NOLOCK)
            WHERE order_date BETWEEN ? AND ?
            GROUP BY order_date
            ORDER BY order_date DESC
        """
        cursor.execute(query, start_date, end_date)
        return cursor.fetchall()

    def process_pending_orders(self):
        """Call SQL Server stored procedure."""
        cursor = self.connection.cursor()
        # Execute T-SQL stored procedure
        cursor.execute("EXEC process_pending_orders")
        self.connection.commit()

    def get_user_order_summary(self, user_id: int):
        """Get user order summary with ISNULL."""
        cursor = self.connection.cursor()
        # SQL Server ISNULL function
        query = """
            SELECT
                u.user_id,
                u.username,
                ISNULL(COUNT(o.order_id), 0) as order_count,
                ISNULL(SUM(o.total_amount), 0.0) as total_spent,
                ISNULL(MAX(o.order_date), '1900-01-01') as last_order_date
            FROM users u WITH (NOLOCK)
            LEFT JOIN orders o WITH (NOLOCK) ON u.user_id = o.user_id
            WHERE u.user_id = ?
            GROUP BY u.user_id, u.username
        """
        cursor.execute(query, user_id)
        return cursor.fetchone()

    def archive_old_orders(self):
        """Archive old orders using SQL Server transaction syntax."""
        cursor = self.connection.cursor()
        # SQL Server BEGIN TRAN / COMMIT TRAN syntax
        cursor.execute("""
            BEGIN TRAN

            INSERT INTO orders_archive
            SELECT * FROM orders WITH (TABLOCKX)
            WHERE order_date < DATEADD(year, -2, GETDATE())

            DELETE FROM orders
            WHERE order_date < DATEADD(year, -2, GETDATE())

            COMMIT TRAN
        """)

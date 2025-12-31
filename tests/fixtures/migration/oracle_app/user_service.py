"""
User service with Oracle database access patterns.
"""
import cx_Oracle
from datetime import datetime


class UserService:
    def __init__(self, dsn: str):
        self.connection = cx_Oracle.connect(dsn)

    def get_top_users(self, limit: int = 10):
        """Get top N users using Oracle ROWNUM pagination."""
        cursor = self.connection.cursor()
        # Oracle-specific ROWNUM pattern
        query = """
            SELECT user_id, username, email, created_at
            FROM users
            WHERE ROWNUM <= :limit
            ORDER BY created_at DESC
        """
        cursor.execute(query, limit=limit)
        return cursor.fetchall()

    def get_user_with_fallback(self, user_id: int):
        """Get user with NVL for null handling."""
        cursor = self.connection.cursor()
        # Oracle NVL function
        query = """
            SELECT
                user_id,
                username,
                NVL(email, 'no-email@example.com') as email,
                NVL(phone, 'N/A') as phone,
                DECODE(status, 1, 'active', 0, 'inactive', 'unknown') as status_text
            FROM users
            WHERE user_id = :user_id
        """
        cursor.execute(query, user_id=user_id)
        return cursor.fetchone()

    def get_user_hierarchy(self, root_user_id: int):
        """Get user referral hierarchy using CONNECT BY."""
        cursor = self.connection.cursor()
        # Oracle hierarchical query
        query = """
            SELECT user_id, username, referred_by, LEVEL as hierarchy_level
            FROM users
            START WITH user_id = :root_user_id
            CONNECT BY PRIOR user_id = referred_by
            ORDER BY LEVEL
        """
        cursor.execute(query, root_user_id=root_user_id)
        return cursor.fetchall()

    def get_current_timestamp(self):
        """Get current database timestamp using SYSDATE."""
        cursor = self.connection.cursor()
        # Oracle SYSDATE and DUAL
        query = "SELECT SYSDATE FROM DUAL"
        cursor.execute(query)
        return cursor.fetchone()[0]

    def bulk_insert_users(self, users: list):
        """Bulk insert with Oracle hints."""
        cursor = self.connection.cursor()
        # Oracle hint syntax
        query = """
            INSERT /*+ APPEND */ INTO users (user_id, username, email, created_at)
            VALUES (:user_id, :username, :email, :created_at)
        """
        cursor.executemany(query, users)
        self.connection.commit()

    def analyze_user_stats(self):
        """Call Oracle stored procedure."""
        cursor = self.connection.cursor()
        # Calling PL/SQL package
        cursor.callproc('user_stats_pkg.calculate_monthly_stats')
        self.connection.commit()

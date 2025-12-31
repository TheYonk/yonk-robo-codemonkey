"""Sample Python database client using various libraries."""

import asyncpg
import psycopg2
from sqlalchemy import create_engine, Column, Integer, String, select
from sqlalchemy.orm import sessionmaker, declarative_base

# asyncpg example
async def get_user_asyncpg(user_id: int):
    """Fetch user using asyncpg."""
    conn = await asyncpg.connect(dsn="postgresql://user:pass@localhost/mydb")
    try:
        result = await conn.fetchrow(
            "SELECT id, username, email FROM test_schema.users WHERE id = $1",
            user_id
        )
        return result
    finally:
        await conn.close()


# psycopg2 example
def get_orders_psycopg2(user_id: int):
    """Fetch orders using psycopg2."""
    conn = psycopg2.connect("dbname=mydb user=postgres password=secret")
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT o.id, o.total_amount, o.status
            FROM test_schema.orders o
            WHERE o.user_id = %s
            ORDER BY o.created_at DESC
            """,
            (user_id,)
        )
        return cur.fetchall()
    finally:
        conn.close()


# SQLAlchemy ORM example
Base = declarative_base()

class User(Base):
    __tablename__ = 'users'
    __table_args__ = {'schema': 'test_schema'}

    id = Column(Integer, primary_key=True)
    username = Column(String(100))
    email = Column(String(255))


def get_user_sqlalchemy(user_id: int):
    """Fetch user using SQLAlchemy ORM."""
    engine = create_engine("postgresql://user:pass@localhost/mydb")
    Session = sessionmaker(bind=engine)
    session = Session()

    try:
        user = session.query(User).filter(User.id == user_id).first()
        return user
    finally:
        session.close()


# SQLAlchemy Core example with raw SQL
def search_users_sqlalchemy_raw(search_term: str):
    """Search users using SQLAlchemy Core with raw SQL."""
    engine = create_engine("postgresql://user:pass@localhost/mydb")
    with engine.connect() as conn:
        result = conn.execute(
            """
            SELECT id, username, email
            FROM test_schema.users
            WHERE username ILIKE :search_term
            """,
            {"search_term": f"%{search_term}%"}
        )
        return result.fetchall()


# Transaction example
def create_order_with_items(user_id: int, items: list):
    """Create order with items in a transaction."""
    conn = psycopg2.connect("dbname=mydb user=postgres")
    try:
        conn.autocommit = False
        cur = conn.cursor()

        # Insert order
        cur.execute(
            """
            INSERT INTO test_schema.orders (user_id, total_amount, status)
            VALUES (%s, %s, 'pending')
            RETURNING id
            """,
            (user_id, sum(item['price'] * item['qty'] for item in items))
        )
        order_id = cur.fetchone()[0]

        # Insert order items
        for item in items:
            cur.execute(
                """
                INSERT INTO test_schema.order_items (order_id, product_name, quantity, price)
                VALUES (%s, %s, %s, %s)
                """,
                (order_id, item['name'], item['qty'], item['price'])
            )

        conn.commit()
        return order_id
    except Exception as e:
        conn.rollback()
        raise
    finally:
        conn.close()


# DDL operation
def create_audit_table():
    """Create audit table."""
    conn = psycopg2.connect("dbname=mydb user=postgres")
    try:
        cur = conn.cursor()
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS test_schema.audit_log (
                id SERIAL PRIMARY KEY,
                user_id INTEGER REFERENCES test_schema.users(id),
                action VARCHAR(100),
                timestamp TIMESTAMPTZ DEFAULT now()
            )
            """
        )
        conn.commit()
    finally:
        conn.close()


# Locking example
def lock_user_for_update(user_id: int):
    """Lock user row for update."""
    conn = psycopg2.connect("dbname=mydb user=postgres")
    try:
        conn.autocommit = False
        cur = conn.cursor()
        cur.execute(
            """
            SELECT id, username, email
            FROM test_schema.users
            WHERE id = %s
            FOR UPDATE NOWAIT
            """,
            (user_id,)
        )
        user = cur.fetchone()
        # Do something with locked row
        conn.commit()
        return user
    except Exception as e:
        conn.rollback()
        raise
    finally:
        conn.close()

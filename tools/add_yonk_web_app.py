#!/usr/bin/env python3
"""Add yonk-web-app repository to RoboMonkey."""
import asyncio
import asyncpg
from pathlib import Path

async def main():
    conn = await asyncpg.connect(dsn='postgresql://postgres:postgres@localhost:5433/robomonkey')

    try:
        # Check if repo already exists
        existing = await conn.fetchrow(
            'SELECT name, schema_name FROM robomonkey_control.repo_registry WHERE name = $1',
            'yonk-web-app'
        )

        if existing:
            print(f'✓ Repo already exists: {existing["name"]} -> {existing["schema_name"]}')
            schema_name = existing['schema_name']
        else:
            # Add repo to registry
            await conn.execute('''
                INSERT INTO robomonkey_control.repo_registry
                (name, schema_name, root_path, auto_embed)
                VALUES ($1, $2, $3, $4)
            ''', 'yonk-web-app', 'robomonkey_yonk_web_app', '/home/yonk/yonk-web-app', True)

            print('✓ Added repo: yonk-web-app')
            schema_name = 'robomonkey_yonk_web_app'

        # Create schema if not exists
        await conn.execute(f'CREATE SCHEMA IF NOT EXISTS {schema_name}')
        print(f'✓ Schema exists: {schema_name}')

        # Initialize schema tables from DDL
        from yonk_code_robomonkey.db.schema_manager import init_schema_tables
        await init_schema_tables(conn, schema_name)
        print('✓ Schema tables initialized')

        # Enqueue FULL_INDEX job
        job_id = await conn.fetchval('''
            INSERT INTO robomonkey_control.job_queue
            (repo_name, schema_name, job_type, payload, priority, status)
            VALUES ($1, $2, 'FULL_INDEX', $3, 10, 'PENDING')
            RETURNING id
        ''', 'yonk-web-app', schema_name, '{}')

        print(f'✓ Enqueued FULL_INDEX job: {job_id}')
        print('\nThe daemon will pick up this job and index the repository.')

    finally:
        await conn.close()

if __name__ == '__main__':
    asyncio.run(main())

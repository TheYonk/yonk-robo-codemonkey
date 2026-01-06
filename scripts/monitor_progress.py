#!/usr/bin/env python3
"""Monitor embedding and indexing progress with ETA calculations."""

import asyncio
import asyncpg
import time
from datetime import datetime, timedelta
from dataclasses import dataclass
import argparse
import os

@dataclass
class ProgressSnapshot:
    timestamp: datetime
    chunks_total: int
    chunks_embedded: int
    docs_total: int
    docs_embedded: int
    file_summaries: int
    symbol_summaries: int
    symbols_total: int
    files_total: int

class ProgressMonitor:
    def __init__(self, database_url: str, schema_name: str, repo_name: str):
        self.database_url = database_url
        self.schema_name = schema_name
        self.repo_name = repo_name
        self.history: list[ProgressSnapshot] = []
        self.start_time: datetime | None = None

    async def get_snapshot(self, conn: asyncpg.Connection) -> ProgressSnapshot:
        """Get current progress counts."""
        await conn.execute(f'SET search_path TO "{self.schema_name}", public')

        counts = await conn.fetchrow("""
            SELECT
                (SELECT COUNT(*) FROM chunk) as chunks_total,
                (SELECT COUNT(*) FROM chunk_embedding) as chunks_embedded,
                (SELECT COUNT(*) FROM document) as docs_total,
                (SELECT COUNT(*) FROM document_embedding) as docs_embedded,
                (SELECT COUNT(*) FROM file_summary) as file_summaries,
                (SELECT COUNT(*) FROM symbol_summary) as symbol_summaries,
                (SELECT COUNT(*) FROM symbol) as symbols_total,
                (SELECT COUNT(*) FROM file) as files_total
        """)

        return ProgressSnapshot(
            timestamp=datetime.now(),
            chunks_total=counts['chunks_total'],
            chunks_embedded=counts['chunks_embedded'],
            docs_total=counts['docs_total'],
            docs_embedded=counts['docs_embedded'],
            file_summaries=counts['file_summaries'],
            symbol_summaries=counts['symbol_summaries'],
            symbols_total=counts['symbols_total'],
            files_total=counts['files_total']
        )

    def calculate_rate(self, metric: str, window_minutes: int = 5) -> float:
        """Calculate rate per minute over the window."""
        if len(self.history) < 2:
            return 0.0

        now = datetime.now()
        window_start = now - timedelta(minutes=window_minutes)

        # Find snapshots within window
        recent = [s for s in self.history if s.timestamp >= window_start]
        if len(recent) < 2:
            recent = self.history[-2:]  # Use last two if not enough in window

        first = recent[0]
        last = recent[-1]

        elapsed_minutes = (last.timestamp - first.timestamp).total_seconds() / 60
        if elapsed_minutes < 0.1:
            return 0.0

        delta = getattr(last, metric) - getattr(first, metric)
        return delta / elapsed_minutes

    def calculate_eta(self, current: int, total: int, rate: float) -> str:
        """Calculate ETA string."""
        if rate <= 0 or current >= total:
            return "N/A" if current < total else "Complete"

        remaining = total - current
        minutes = remaining / rate

        if minutes < 60:
            return f"{int(minutes)}m"
        elif minutes < 1440:
            hours = minutes / 60
            return f"{hours:.1f}h"
        else:
            days = minutes / 1440
            return f"{days:.1f}d"

    def format_progress_bar(self, current: int, total: int, width: int = 30) -> str:
        """Create ASCII progress bar."""
        if total == 0:
            return "[" + "-" * width + "]"

        pct = min(current / total, 1.0)
        filled = int(width * pct)
        empty = width - filled
        return "[" + "█" * filled + "░" * empty + "]"

    def print_status(self, snapshot: ProgressSnapshot, clear: bool = True):
        """Print formatted status."""
        if clear:
            # Clear screen (ANSI escape)
            print("\033[2J\033[H", end="")

        print("=" * 70)
        print(f"  ROBOMONKEY PROGRESS MONITOR - {self.repo_name}")
        print(f"  Started: {self.start_time.strftime('%Y-%m-%d %H:%M:%S') if self.start_time else 'N/A'}")
        print(f"  Current: {snapshot.timestamp.strftime('%Y-%m-%d %H:%M:%S')}")
        if self.start_time:
            elapsed = snapshot.timestamp - self.start_time
            print(f"  Elapsed: {str(elapsed).split('.')[0]}")
        print("=" * 70)
        print()

        # Chunk embeddings
        chunk_rate = self.calculate_rate('chunks_embedded')
        chunk_eta = self.calculate_eta(snapshot.chunks_embedded, snapshot.chunks_total, chunk_rate)
        chunk_pct = (snapshot.chunks_embedded / snapshot.chunks_total * 100) if snapshot.chunks_total > 0 else 0
        print(f"  CHUNK EMBEDDINGS")
        print(f"    {self.format_progress_bar(snapshot.chunks_embedded, snapshot.chunks_total)}")
        print(f"    {snapshot.chunks_embedded:,} / {snapshot.chunks_total:,} ({chunk_pct:.1f}%)")
        print(f"    Rate: {chunk_rate:.1f}/min | ETA: {chunk_eta}")
        print()

        # Document embeddings
        doc_rate = self.calculate_rate('docs_embedded')
        doc_eta = self.calculate_eta(snapshot.docs_embedded, snapshot.docs_total, doc_rate)
        doc_pct = (snapshot.docs_embedded / snapshot.docs_total * 100) if snapshot.docs_total > 0 else 0
        print(f"  DOCUMENT EMBEDDINGS")
        print(f"    {self.format_progress_bar(snapshot.docs_embedded, snapshot.docs_total)}")
        print(f"    {snapshot.docs_embedded:,} / {snapshot.docs_total:,} ({doc_pct:.1f}%)")
        print(f"    Rate: {doc_rate:.1f}/min | ETA: {doc_eta}")
        print()

        # File summaries
        fs_rate = self.calculate_rate('file_summaries')
        fs_eta = self.calculate_eta(snapshot.file_summaries, snapshot.files_total, fs_rate)
        fs_pct = (snapshot.file_summaries / snapshot.files_total * 100) if snapshot.files_total > 0 else 0
        print(f"  FILE SUMMARIES")
        print(f"    {self.format_progress_bar(snapshot.file_summaries, snapshot.files_total)}")
        print(f"    {snapshot.file_summaries:,} / {snapshot.files_total:,} ({fs_pct:.1f}%)")
        print(f"    Rate: {fs_rate:.1f}/min | ETA: {fs_eta}")
        print()

        # Symbol summaries
        ss_rate = self.calculate_rate('symbol_summaries')
        ss_eta = self.calculate_eta(snapshot.symbol_summaries, snapshot.symbols_total, ss_rate)
        ss_pct = (snapshot.symbol_summaries / snapshot.symbols_total * 100) if snapshot.symbols_total > 0 else 0
        print(f"  SYMBOL SUMMARIES")
        print(f"    {self.format_progress_bar(snapshot.symbol_summaries, snapshot.symbols_total)}")
        print(f"    {snapshot.symbol_summaries:,} / {snapshot.symbols_total:,} ({ss_pct:.1f}%)")
        print(f"    Rate: {ss_rate:.1f}/min | ETA: {ss_eta}")
        print()

        print("=" * 70)
        print("  Press Ctrl+C to exit")
        print("=" * 70)

    async def run(self, interval_seconds: int = 10):
        """Run the monitor loop."""
        conn = await asyncpg.connect(dsn=self.database_url)
        self.start_time = datetime.now()

        try:
            while True:
                snapshot = await self.get_snapshot(conn)
                self.history.append(snapshot)

                # Keep only last 100 snapshots
                if len(self.history) > 100:
                    self.history = self.history[-100:]

                self.print_status(snapshot)
                await asyncio.sleep(interval_seconds)

        except KeyboardInterrupt:
            print("\n\nMonitor stopped.")
        finally:
            await conn.close()


async def list_repos(database_url: str) -> list[dict]:
    """List available repos."""
    conn = await asyncpg.connect(dsn=database_url)
    try:
        # Get all robomonkey schemas
        schemas = await conn.fetch("""
            SELECT schema_name
            FROM information_schema.schemata
            WHERE schema_name LIKE 'robomonkey_%'
            ORDER BY schema_name
        """)

        repos = []
        for row in schemas:
            schema = row['schema_name']
            repo_name = schema.replace('robomonkey_', '').replace('_', '-')

            # Get counts from this schema
            await conn.execute(f'SET search_path TO "{schema}", public')
            counts = await conn.fetchrow("""
                SELECT
                    (SELECT COUNT(*) FROM chunk) as chunks,
                    (SELECT COUNT(*) FROM chunk_embedding) as embeds
            """)

            repos.append({
                'name': repo_name,
                'schema': schema,
                'chunks': counts['chunks'],
                'embeds': counts['embeds']
            })

        return repos
    finally:
        await conn.close()


async def main():
    parser = argparse.ArgumentParser(description='Monitor RoboMonkey indexing progress')
    parser.add_argument('--repo', '-r', help='Repository name to monitor')
    parser.add_argument('--list', '-l', action='store_true', help='List available repos')
    parser.add_argument('--interval', '-i', type=int, default=10, help='Update interval in seconds (default: 10)')
    parser.add_argument('--database-url', '-d',
                       default=os.environ.get('DATABASE_URL', 'postgresql://postgres:postgres@localhost:5433/robomonkey'),
                       help='Database URL')

    args = parser.parse_args()

    if args.list:
        repos = await list_repos(args.database_url)
        print("\nAvailable repositories:")
        print("-" * 60)
        for repo in repos:
            pct = (repo['embeds'] / repo['chunks'] * 100) if repo['chunks'] > 0 else 0
            print(f"  {repo['name']:20} {repo['embeds']:>8,} / {repo['chunks']:>8,} chunks ({pct:.1f}%)")
        print()
        return

    if not args.repo:
        print("Error: --repo is required. Use --list to see available repos.")
        return

    schema_name = f"robomonkey_{args.repo.replace('-', '_')}"

    monitor = ProgressMonitor(
        database_url=args.database_url,
        schema_name=schema_name,
        repo_name=args.repo
    )

    await monitor.run(interval_seconds=args.interval)


if __name__ == '__main__':
    asyncio.run(main())

#!/usr/bin/env python
"""Run a local PostgreSQL 16 server for development, with no system install needed.

Uses the server binaries bundled in the ``pgserver`` wheel (``pip install -r
requirements/dev.txt``). Data lives in ``.pgdata/`` and the server listens on 127.0.0.1:5433,
matching the default ``DATABASE_URL``. If you already run PostgreSQL (Postgres.app, Docker,
Homebrew), skip this script and point ``DATABASE_URL`` at your server instead.

    python scripts/devdb.py start | stop | status | psql | reset
"""

import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / ".pgdata"
LOG_FILE = DATA_DIR / "server.log"
PORT = os.environ.get("DEVDB_PORT", "5433")
USER = DATABASE = PASSWORD = "ridepulse"


def bin_dir() -> Path:
    try:
        import pgserver
    except ImportError:
        sys.exit("pgserver is not installed. Run: pip install -r requirements/dev.txt")
    return Path(pgserver.__file__).parent / "pginstall" / "bin"


def run(*args: str, check: bool = True, **kwargs) -> subprocess.CompletedProcess:
    return subprocess.run([str(bin_dir() / args[0]), *args[1:]], check=check, **kwargs)


def is_running() -> bool:
    if not (DATA_DIR / "PG_VERSION").exists():
        return False
    return (
        run("pg_ctl", "-D", str(DATA_DIR), "status", check=False, capture_output=True).returncode
        == 0
    )


def psql(sql: str, database: str = "postgres") -> str:
    result = run(
        "psql",
        "-h",
        "127.0.0.1",
        "-p",
        PORT,
        "-U",
        "postgres",
        "-d",
        database,
        "-tAc",
        sql,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def start() -> None:
    if not (DATA_DIR / "PG_VERSION").exists():
        print("Initialising a new cluster in .pgdata/ ...")
        run(
            "initdb",
            "-D",
            str(DATA_DIR),
            "-U",
            "postgres",
            "-A",
            "trust",
            "-E",
            "UTF8",
            "--locale=C",
            capture_output=True,
        )
    if is_running():
        print(f"PostgreSQL is already running on 127.0.0.1:{PORT}")
    else:
        run(
            "pg_ctl",
            "-D",
            str(DATA_DIR),
            "-l",
            str(LOG_FILE),
            "-w",
            "start",
            # TCP only: Unix socket paths break on directories with spaces and have length limits.
            "-o",
            f"-p {PORT} -c listen_addresses=127.0.0.1 -c unix_socket_directories=''",
            capture_output=True,
        )
        print(f"PostgreSQL started on 127.0.0.1:{PORT} (log: .pgdata/server.log)")
    if psql(f"SELECT 1 FROM pg_roles WHERE rolname = '{USER}'") != "1":
        # CREATEDB lets the test runner create its throwaway test database.
        psql(f"CREATE ROLE {USER} LOGIN CREATEDB PASSWORD '{PASSWORD}'")
    if psql(f"SELECT 1 FROM pg_database WHERE datname = '{DATABASE}'") != "1":
        psql(f"CREATE DATABASE {DATABASE} OWNER {USER}")
        print(f"Created database '{DATABASE}'")
    print(f"DATABASE_URL=postgres://{USER}:{PASSWORD}@127.0.0.1:{PORT}/{DATABASE}")


def stop() -> None:
    if is_running():
        run("pg_ctl", "-D", str(DATA_DIR), "-m", "fast", "-w", "stop", capture_output=True)
        print("PostgreSQL stopped")
    else:
        print("PostgreSQL is not running")


def main() -> None:
    command = sys.argv[1] if len(sys.argv) > 1 else "status"
    if command == "start":
        start()
    elif command == "stop":
        stop()
    elif command == "status":
        print("running" if is_running() else "stopped")
    elif command == "psql":
        os.execv(
            str(bin_dir() / "psql"), ["psql", "-h", "127.0.0.1", "-p", PORT, "-U", USER, DATABASE]
        )
    elif command == "reset":
        stop()
        shutil.rmtree(DATA_DIR, ignore_errors=True)
        start()
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main()

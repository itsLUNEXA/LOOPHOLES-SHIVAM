#!/usr/bin/env python
"""
Vibento - Local Application Launcher
Run via: python start.py
"""
import os
import sys
import time
import socket
import threading
import webbrowser
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
HOST = "127.0.0.1"
PORT = 8000
URL = f"http://{HOST}:{PORT}"


def check_dependencies():
    missing = []
    for pkg in ('django', 'psycopg', 'dj_database_url', 'dotenv', 'PIL'):
        try:
            __import__(pkg)
        except ImportError:
            missing.append(pkg)
    if missing:
        print("\n[ERROR] Missing required dependencies.")
        print("Please install them by running:")
        print("    pip install -r requirements.txt\n")
        sys.exit(1)


def check_env():
    env_path = BASE_DIR / '.env'
    if not env_path.exists():
        print("\n[ERROR] Missing .env file.")
        print("Please create your .env configuration from .env.example:")
        print("    copy .env.example .env   (Windows)")
        print("    cp .env.example .env     (Linux / macOS)")
        print("Then configure your Supabase DATABASE_URL in .env.\n")
        sys.exit(1)

    from dotenv import load_dotenv
    load_dotenv(env_path)

    db_url = os.getenv('DATABASE_URL', '').strip()
    if not db_url or db_url.startswith('sqlite'):
        print("\n[ERROR] Supabase DATABASE_URL is not configured in .env.")
        print("Per project requirements, the launcher connects directly to Supabase PostgreSQL.")
        print("Please add your Supabase connection string to .env, for example:")
        print("    DATABASE_URL=postgresql://postgres.<project-ref>:<password>@<region>.pooler.supabase.com:5432/postgres\n")
        sys.exit(1)


def wait_and_open_browser():
    """Polls the local port until active, then opens the browser once."""
    for _ in range(60):
        try:
            with socket.create_connection((HOST, PORT), timeout=0.3):
                webbrowser.open(URL)
                return
        except (OSError, ConnectionRefusedError):
            time.sleep(0.25)


def main():
    check_dependencies()
    check_env()

    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
    import django
    django.setup()

    # Verify Supabase database connectivity
    from django.db import connection
    try:
        connection.ensure_connection()
    except Exception as err:
        print(f"\n[ERROR] Unable to connect to Supabase PostgreSQL database: {err}")
        print("Please check your database credentials, password, and network connection in .env.\n")
        sys.exit(1)

    # Apply existing migrations (do not run makemigrations automatically)
    from django.core.management import call_command
    print("\nApplying existing database migrations...")
    call_command('migrate', interactive=False)

    # Avoid duplicate tabs on autoreload by only starting browser watcher in parent process
    if os.environ.get('RUN_MAIN') != 'true':
        threading.Thread(target=wait_and_open_browser, daemon=True).start()

    print(f"\nStarting Vibento development server at {URL}...")
    print("Press Ctrl+C to stop the server.\n")

    try:
        call_command('runserver', f'{HOST}:{PORT}')
    except KeyboardInterrupt:
        print("\nShutting down Vibento server. Goodbye!")
        sys.exit(0)


if __name__ == '__main__':
    main()

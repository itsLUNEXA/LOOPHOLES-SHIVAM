"""
Django Management Command: run_sync_scheduler

Periodically checks enabled EventSources for due sync times without requiring
active web visitors, and triggers the background worker.

Usage:
    python manage.py run_sync_scheduler          # Continuous loop checking every minute
    python manage.py run_sync_scheduler --once   # Single pass check
"""
import sys
import time
from datetime import timedelta
from django.core.management.base import BaseCommand
from django.utils import timezone

from events.models import EventSource
from events.services import execute_source_sync


class Command(BaseCommand):
    help = "Periodically check and refresh due event sources without visitors"

    def add_arguments(self, parser):
        parser.add_argument(
            '--once',
            action='store_true',
            help='Run a single scheduler check and exit.'
        )
        parser.add_argument(
            '--check-interval',
            type=int,
            default=60,
            help='Seconds between scheduler checks in loop mode (default: 60s).'
        )

    def handle(self, *args, **options):
        single_pass = options['once']
        interval = options['check_interval']

        self.stdout.write(self.style.SUCCESS(
            f"Vibento Sync Scheduler started (interval={interval}s, single_pass={single_pass})."
        ))

        try:
            while True:
                now = timezone.now()
                # Sources where next_due_at <= now or never attempted
                due_sources = EventSource.objects.filter(is_enabled=True).exclude(
                    sync_status__in=['queued', 'running']
                )

                due_count = 0
                for source in due_sources:
                    is_due = (
                        source.last_sync_attempt_at is None or
                        (source.next_due_at and now >= source.next_due_at)
                    )
                    if is_due and source.can_run_today():
                        due_count += 1
                        self.stdout.write(f"Scheduler triggered sync for {source.name}...")
                        res = execute_source_sync(source.pk, trigger_type='scheduled_cron')
                        self.stdout.write(f"  Result: {res.get('status')}")

                if due_count == 0:
                    self.stdout.write(f"[{timezone.now().strftime('%H:%M:%S')}] No sources currently due.")

                if single_pass:
                    break

                time.sleep(interval)
        except KeyboardInterrupt:
            self.stdout.write(self.style.NOTICE("\nSync Scheduler stopped by user."))

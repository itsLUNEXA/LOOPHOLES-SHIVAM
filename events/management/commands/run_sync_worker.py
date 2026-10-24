"""
Django Management Command: run_sync_worker

Processes queued event synchronization jobs and polls active TinyFish runs.
Compatible with Windows PowerShell and background runners.

Usage:
    python manage.py run_sync_worker          # Runs continuous worker loop
    python manage.py run_sync_worker --once   # Runs a single pass and exits
    python manage.py run_sync_worker --source-id 1
"""
import sys
import time
import logging
from django.core.management.base import BaseCommand
from django.utils import timezone

from events.models import EventSource
from events.services import execute_source_sync

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Run the Vibento background event sync worker"

    def add_arguments(self, parser):
        parser.add_argument(
            '--once',
            action='store_true',
            help='Run a single processing pass over queued sources and exit.'
        )
        parser.add_argument(
            '--source-id',
            type=int,
            default=None,
            help='Execute sync for a specific EventSource ID.'
        )
        parser.add_argument(
            '--poll-interval',
            type=float,
            default=3.0,
            help='Sleep seconds between worker checks in continuous mode (default: 3.0s).'
        )

    def handle(self, *args, **options):
        single_pass = options['once']
        target_source_id = options['source_id']
        interval = options['poll_interval']

        self.stdout.write(self.style.SUCCESS(
            f"Vibento Sync Worker started at {timezone.now().strftime('%Y-%m-%d %H:%M:%S')} (single_pass={single_pass})"
        ))

        try:
            while True:
                sources_to_process = []
                if target_source_id:
                    sources_to_process = list(EventSource.objects.filter(pk=target_source_id, is_enabled=True))
                else:
                    # Look for queued or active sources
                    sources_to_process = list(EventSource.objects.filter(
                        is_enabled=True,
                        sync_status__in=['queued', 'running']
                    ))

                if sources_to_process:
                    for source in sources_to_process:
                        self.stdout.write(f"Processing sync for source #{source.pk} '{source.name}' ({source.source_url})...")
                        res = execute_source_sync(source.pk, trigger_type='scheduled_cron')
                        if res['success']:
                            self.stdout.write(self.style.SUCCESS(
                                f"  [SUCCESS] {source.name}: Extracted {res['records_extracted']}, Created {res['records_created']}, Skipped {res['duplicates_skipped']}."
                            ))
                        else:
                            self.stdout.write(self.style.WARNING(
                                f"  [FAILED] {source.name}: {res.get('error')}"
                            ))

                if single_pass:
                    break

                time.sleep(interval)
        except KeyboardInterrupt:
            self.stdout.write(self.style.NOTICE("\nSync Worker stopped by user."))

"""
Vibento Event Synchronization Services.

Implements background worker orchestration, atomic concurrency control,
bounded retries, daily rate limits, and truthful status auditing.
"""
import uuid
import time
import logging
from datetime import timedelta
from django.utils import timezone
from django.db import transaction
from django.contrib.auth.models import User

from .models import EventSource, SyncRunHistory, Event
from .tinyfish import fetch_events_from_tinyfish, check_tinyfish_run_result, validate_and_import_events

logger = logging.getLogger(__name__)


def sanitize_error_message(msg: str) -> str:
    """Removes sensitive tokens or private keys from error messages."""
    if not msg:
        return ""
    text = str(msg)
    # Mask any potential API key or Bearer tokens
    import re
    text = re.sub(r'(sk-[a-zA-Z0-9_\-]{8,})', 'sk-***[REDACTED]', text)
    text = re.sub(r'(postgres:[^@]+@)', 'postgres:***@', text)
    return text[:1000]


def get_default_sync_admin():
    """Returns or creates the system administrator user for automated imports."""
    admin = User.objects.filter(is_superuser=True).first()
    if not admin:
        admin = User.objects.filter(is_staff=True).first()
    if not admin:
        admin = User.objects.create(
            username='system_sync',
            email='system_sync@vibento.local',
            is_staff=True
        )
    return admin


def trigger_visitor_entry_refresh():
    """
    Called upon initial website entry or deliberate page reload.

    Behavior:
    1. Checks enabled EventSource instances.
    2. If a source is already running/queued, attaches visitor to active run (deduplication).
    3. If daily API run limit reached, logs RATE_LIMITED and informs truthfully.
    4. Otherwise, atomically acquires the concurrency lock and marks source 'queued'.

    Returns:
        list of dicts with outcome per source.
    """
    results = []
    now = timezone.now()
    enabled_sources = EventSource.objects.filter(is_enabled=True)

    if not enabled_sources.exists():
        return [{'status': 'no_enabled_sources', 'message': 'No enabled event sources configured.'}]

    for source in enabled_sources:
        # 1. Recover stale lock if worker crashed or timed out (> 5 mins)
        if source.sync_status in ('queued', 'running'):
            if source.concurrency_lock_until and source.concurrency_lock_until <= now:
                logger.warning(f"Recovering expired concurrency lock for source {source.name}.")
                source.sync_status = 'idle'
                source.concurrency_lock_until = None
                source.concurrency_lock_token = None
                source.save(update_fields=['sync_status', 'concurrency_lock_until', 'concurrency_lock_token'])

        # 2. Concurrent-Run Deduplication: Attach to active run if already executing
        if source.is_running:
            results.append({
                'source_id': source.pk,
                'source_name': source.name,
                'status': 'attached_to_active_run',
                'run_id': source.active_run_id,
                'message': f"Refresh already in-flight for {source.name} (Run ID: {source.active_run_id or 'queued'}). Attached to active run."
            })
            continue

        # 3. Check Daily Budget Limit
        if not source.can_run_today():
            err_msg = f"Daily run limit ({source.daily_run_limit} runs) reached for {source.name}. Paused to protect budget."
            SyncRunHistory.objects.create(
                source=source,
                trigger_type='visitor_entry',
                status='RATE_LIMITED',
                error_message=err_msg
            )
            results.append({
                'source_id': source.pk,
                'source_name': source.name,
                'status': 'rate_limited',
                'message': err_msg
            })
            continue

        # 4. Atomic Concurrency Lock Acquisition
        lock_token = uuid.uuid4().hex
        lock_until = now + timedelta(minutes=5)

        acquired = EventSource.objects.filter(
            pk=source.pk,
            is_enabled=True
        ).exclude(
            sync_status__in=['queued', 'running'],
            concurrency_lock_until__gt=now
        ).update(
            sync_status='queued',
            concurrency_lock_token=lock_token,
            concurrency_lock_until=lock_until,
            last_sync_attempt_at=now,
        )

        if acquired == 0:
            # Concurrent race condition lost - another request just claimed it
            source.refresh_from_db()
            results.append({
                'source_id': source.pk,
                'source_name': source.name,
                'status': 'attached_to_active_run',
                'run_id': source.active_run_id,
                'message': f"Attached to concurrent in-flight refresh for {source.name}."
            })
        else:
            # Successfully enqueued a new run!
            history = SyncRunHistory.objects.create(
                source=source,
                trigger_type='visitor_entry',
                status='PENDING'
            )
            results.append({
                'source_id': source.pk,
                'source_name': source.name,
                'status': 'enqueued',
                'history_id': history.pk,
                'lock_token': lock_token,
                'message': f"Enqueued new refresh for {source.name}."
            })

    return results


def execute_source_sync(source_id: int, trigger_type: str = 'visitor_entry', max_poll_attempts: int = 15, poll_interval: float = 2.0, user: User = None):
    """
    Executes a single source synchronization cycle.
    Used by management worker commands and test harnesses.

    Returns:
        dict: execution outcome and summary.
    """
    try:
        source = EventSource.objects.get(pk=source_id)
    except EventSource.DoesNotExist:
        return {'success': False, 'error': f"EventSource #{source_id} not found."}

    now = timezone.now()
    today = timezone.localdate()
    admin_user = user or get_default_sync_admin()

    # Track or create history entry
    history = SyncRunHistory.objects.filter(source=source, status='PENDING').order_by('-started_at').first()
    if not history:
        history = SyncRunHistory.objects.create(
            source=source,
            trigger_type=trigger_type,
            status='RUNNING'
        )
    else:
        history.status = 'RUNNING'
        history.save(update_fields=['status'])

    # Update source status and increment daily usage
    if source.last_run_date != today:
        source.last_run_date = today
        source.runs_today_count = 1
    else:
        source.runs_today_count += 1

    source.sync_status = 'running'
    source.save(update_fields=['sync_status', 'last_run_date', 'runs_today_count'])

    # Step 1: Call TinyFish Agent API
    try:
        fetch_res = fetch_events_from_tinyfish(
            source_url=source.source_url,
            sync_mode='async',
            content_type=source.content_type
        )
    except Exception as exc:
        fetch_res = {
            'success': False,
            'events': [],
            'run_id': None,
            'status': 'EXCEPTION',
            'error': str(exc)
        }

    run_id = fetch_res.get('run_id')
    if run_id:
        source.active_run_id = run_id
        source.save(update_fields=['active_run_id'])
        history.run_id = run_id
        history.save(update_fields=['run_id'])

    # Handle immediate failure
    if not fetch_res['success']:
        safe_err = sanitize_error_message(fetch_res.get('error') or "TinyFish run submission failed.")
        history.status = 'FAILED'
        history.completed_at = timezone.now()
        history.error_message = safe_err
        history.save()

        source.consecutive_failures += 1
        source.last_error_message = safe_err
        if source.consecutive_failures >= source.max_retries:
            source.sync_status = 'failed'
        else:
            source.sync_status = 'queued'  # Scheduled for bounded retry
        source.concurrency_lock_until = None
        source.concurrency_lock_token = None
        source.save()

        return {
            'success': False,
            'status': history.status,
            'run_id': run_id,
            'error': safe_err
        }

    # Step 2: Poll async status if run is pending/running
    run_status = fetch_res.get('status')
    events_data = fetch_res.get('events', [])

    if run_status in ('PENDING', 'RUNNING') and run_id:
        completed = False
        for attempt in range(max_poll_attempts):
            time.sleep(poll_interval)
            poll_res = check_tinyfish_run_result(run_id)
            if poll_res.get('status') == 'COMPLETED':
                events_data = poll_res.get('events', [])
                completed = True
                break
            elif poll_res.get('status') == 'FAILED':
                fail_err = sanitize_error_message(poll_res.get('error') or "TinyFish async run failed remotely.")
                history.status = 'FAILED'
                history.completed_at = timezone.now()
                history.error_message = fail_err
                history.save()

                source.consecutive_failures += 1
                source.last_error_message = fail_err
                source.sync_status = 'failed' if source.consecutive_failures >= source.max_retries else 'queued'
                source.concurrency_lock_until = None
                source.concurrency_lock_token = None
                source.save()
                return {'success': False, 'status': 'FAILED', 'run_id': run_id, 'error': fail_err}

        if not completed:
            # Poll timeout: keep active_run_id preserved for next worker poll
            history.status = 'TIMEOUT'
            history.error_message = f"Polled {max_poll_attempts} times without completion. Remote run preserved."
            history.save()

            source.sync_status = 'running'
            source.concurrency_lock_until = timezone.now() + timedelta(minutes=5)
            source.save()
            return {'success': False, 'status': 'TIMEOUT', 'run_id': run_id, 'error': history.error_message}

    # Step 3: Validate, deduplicate, and persist records
    summary = validate_and_import_events(
        raw_events=events_data,
        source_url=source.source_url,
        user=admin_user,
        source=source,
        auto_approve=source.auto_approve_trusted,
        default_category=source.default_category,
        category_mappings=source.category_mappings
    )

    created_count = summary.get('new_pending_created', 0) + summary.get('new_approved_created', 0)

    # Step 4: Audit trail in SyncRunHistory
    history.status = 'COMPLETED'
    history.completed_at = timezone.now()
    history.records_extracted_count = summary.get('records_returned', 0)
    history.records_created_count = created_count
    history.records_updated_count = summary.get('changes_detected', 0)
    history.records_skipped_count = summary.get('duplicates_skipped', 0)
    history.records_rejected_count = summary.get('invalid_records_skipped', 0)
    history.diagnostic_details = {
        'created_events': [e.get('title') for e in summary.get('created_events', [])],
        'changes_detected': summary.get('detected_changes', []),
        'invalid_records': summary.get('invalid_records', []),
    }
    history.save()

    # Step 5: Update source metrics and release lock
    source.last_successful_sync_at = timezone.now()
    source.next_due_at = timezone.now() + timedelta(minutes=source.freshness_interval_minutes)
    source.consecutive_failures = 0
    source.sync_status = 'completed'
    source.active_run_id = None
    source.concurrency_lock_until = None
    source.concurrency_lock_token = None
    source.last_error_message = ""
    source.save()

    return {
        'success': True,
        'status': 'COMPLETED',
        'run_id': run_id,
        'records_extracted': history.records_extracted_count,
        'records_created': history.records_created_count,
        'duplicates_skipped': history.records_skipped_count,
        'changes_detected': history.records_updated_count,
        'invalid_skipped': history.records_rejected_count,
    }


def get_sync_status_summary():
    """
    Returns high-level status for frontend live polling and UI banners.
    """
    now = timezone.now()
    active_sources = EventSource.objects.filter(sync_status__in=['queued', 'running'])
    is_syncing = False

    for s in active_sources:
        if s.concurrency_lock_until and s.concurrency_lock_until > now:
            is_syncing = True
            break

    last_history = SyncRunHistory.objects.order_by('-started_at').first()

    return {
        'is_syncing': is_syncing,
        'active_source_names': [s.name for s in active_sources],
        'last_status': last_history.status if last_history else 'IDLE',
        'last_run_id': last_history.run_id if last_history else None,
        'last_completed_at': last_history.completed_at.isoformat() if last_history and last_history.completed_at else None,
        'records_created': last_history.records_created_count if last_history else 0,
        'error_message': last_history.error_message if last_history and last_history.status in ('FAILED', 'RATE_LIMITED') else None,
    }

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
from django.db.models import Q
from django.contrib.auth.models import User

from .models import EventSource, SyncRunHistory, Event, Category, EventEnrollment
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


def ensure_default_event_sources():
    """
    Ensures that configured sources in settings/environment (e.g. Unstop)
    exist as enabled EventSource records in the database.
    Does not initiate live runs or bypass moderation.
    """
    from .tinyfish import get_tinyfish_config
    from .models import Category
    config = get_tinyfish_config()
    allowed_sources = config.get('allowed_sources', [])
    created_or_found = []

    for raw_url in allowed_sources:
        if not raw_url:
            continue
        clean_url = raw_url.strip()
        is_unstop = "unstop.com" in clean_url.lower()
        source = EventSource.objects.filter(source_url__iexact=clean_url).first()
        if not source:
            name = "Unstop Events & Hackathons" if is_unstop else f"External Source ({clean_url})"
            tech_cat = Category.objects.filter(slug='technology-ai').first()
            source = EventSource.objects.create(
                name=name,
                source_url=clean_url,
                content_type='all',
                default_category=tech_cat,
                category_mappings={
                    'hackathon': 'technology-ai',
                    'coding': 'technology-ai',
                    'competition': 'technology-ai',
                    'quiz': 'education-learning',
                    'workshop': 'education-learning',
                },
                is_enabled=True,
                daily_run_limit=10,
                auto_approve_trusted=is_unstop,  # User-approved publication policy: Unstop auto-publishes
                freshness_interval_minutes=360,
            )
            logger.info(f"Auto-configured EventSource #{source.pk} for {clean_url}")
        else:
            if is_unstop and not source.auto_approve_trusted:
                source.auto_approve_trusted = True
                source.save(update_fields=['auto_approve_trusted'])
        created_or_found.append(source)
    return created_or_found


def trigger_visitor_entry_refresh():
    """
    Called upon initial website entry or deliberate page reload.

    Behavior:
    1. Checks enabled EventSource instances (auto-registers from allowlist if empty).
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
        ensure_default_event_sources()
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

    records_created = last_history.records_created_count if last_history else 0
    records_extracted = last_history.records_extracted_count if last_history else 0
    auto_approve = getattr(last_history.source, 'auto_approve_trusted', False) if last_history and last_history.source else False

    return {
        'is_syncing': is_syncing,
        'active_source_names': [s.name for s in active_sources],
        'last_status': last_history.status if last_history else 'IDLE',
        'last_run_id': last_history.run_id if last_history else None,
        'last_completed_at': last_history.completed_at.isoformat() if last_history and last_history.completed_at else None,
        'records_extracted': records_extracted,
        'records_created': records_created,
        'records_pending': records_created if not auto_approve else 0,
        'records_approved': records_created if auto_approve else 0,
        'error_message': last_history.error_message if last_history and last_history.status in ('FAILED', 'RATE_LIMITED') else None,
    }


def map_interest_to_category_slugs(interest_str: str) -> list[str]:
    """
    Maps an interest string to matching event Category slugs.
    Case-insensitive, handles standard choices, synonyms, and custom variations.
    """
    if not interest_str:
        return []
    clean = interest_str.lower().strip()
    slugs = set()

    # Exact and keyword mapping dictionary
    mapping = {
        # Technology & AI
        'tech': ['technology-ai', 'tech-ai', 'technology', 'tech'],
        'ai': ['technology-ai', 'tech-ai', 'technology', 'tech'],
        'technology': ['technology-ai', 'tech-ai', 'technology', 'tech'],
        'technology & ai': ['technology-ai', 'tech-ai', 'technology', 'tech'],
        'software': ['technology-ai', 'tech-ai', 'technology', 'tech'],
        'coding': ['technology-ai', 'tech-ai', 'technology', 'tech'],
        'hackathon': ['technology-ai', 'tech-ai', 'technology', 'tech'],
        'developer': ['technology-ai', 'tech-ai', 'technology', 'tech'],
        'robotics': ['technology-ai', 'tech-ai', 'technology', 'tech'],
        'data science': ['technology-ai', 'tech-ai', 'technology', 'tech'],
        'machine learning': ['technology-ai', 'tech-ai', 'technology', 'tech'],

        # Startups & Business
        'startup': ['startups-business', 'startups', 'business'],
        'startups': ['startups-business', 'startups', 'business'],
        'startups & business': ['startups-business', 'startups', 'business'],
        'business': ['startups-business', 'startups', 'business'],
        'entrepreneur': ['startups-business', 'startups', 'business'],
        'entrepreneurship': ['startups-business', 'startups', 'business'],
        'founder': ['startups-business', 'startups', 'business'],
        'finance': ['startups-business', 'startups', 'business'],
        'economics': ['startups-business', 'startups', 'business'],

        # Live Music & Jam
        'music': ['music-live-jam', 'live-music', 'music'],
        'live music': ['music-live-jam', 'live-music', 'music'],
        'live music & jam': ['music-live-jam', 'live-music', 'music'],
        'jam': ['music-live-jam', 'live-music', 'music'],
        'jamming': ['music-live-jam', 'live-music', 'music'],
        'acoustic': ['music-live-jam', 'live-music', 'music'],
        'concert': ['music-live-jam', 'live-music', 'music'],
        'band': ['music-live-jam', 'live-music', 'music'],
        'singing': ['music-live-jam', 'live-music', 'music'],

        # Design & Creative Arts / Arts & Crafts
        'art': ['arts-crafts', 'arts'],
        'arts': ['arts-crafts', 'arts'],
        'craft': ['arts-crafts', 'arts'],
        'crafts': ['arts-crafts', 'arts'],
        'arts & crafts': ['arts-crafts', 'arts'],
        'design & creative arts': ['arts-crafts', 'arts'],
        'design': ['arts-crafts', 'arts'],
        'pottery': ['arts-crafts', 'arts'],
        'painting': ['arts-crafts', 'arts'],
        'sketching': ['arts-crafts', 'arts'],

        # Books & Literature
        'book': ['books-literature', 'books'],
        'books': ['books-literature', 'books'],
        'books & literature': ['books-literature', 'books'],
        'literature': ['books-literature', 'books'],
        'reading': ['books-literature', 'books'],
        'poetry': ['books-literature', 'books'],
        'writing': ['books-literature', 'books'],

        # Community & Social
        'community': ['community-social', 'community'],
        'social': ['community-social', 'community'],
        'community & social': ['community-social', 'community'],
        'meetup': ['community-social', 'community'],
        'quizzes': ['community-social', 'community'],
        'quiz': ['community-social', 'community'],
        'treasure hunt': ['community-social', 'community'],
        'escape room': ['community-social', 'community'],
        'board game': ['community-social', 'community'],
        'board games': ['community-social', 'community'],

        # Gaming & Esports
        'gaming': ['technology-ai', 'community-social'],
        'esports': ['technology-ai', 'community-social'],
        'gaming & esports': ['technology-ai', 'community-social'],

        # Fitness & Outdoors / Sports
        'sports': ['sports-outdoors', 'fitness-outdoors', 'sports'],
        'sport': ['sports-outdoors', 'fitness-outdoors', 'sports'],
        'sports & outdoor': ['sports-outdoors', 'fitness-outdoors', 'sports'],
        'sports & outdoors': ['sports-outdoors', 'fitness-outdoors', 'sports'],
        'fitness': ['sports-outdoors', 'fitness-outdoors'],
        'fitness & outdoors': ['sports-outdoors', 'fitness-outdoors'],
        'outdoor': ['sports-outdoors', 'fitness-outdoors'],
        'outdoors': ['sports-outdoors', 'fitness-outdoors'],
        'trek': ['sports-outdoors', 'fitness-outdoors'],
        'trekking': ['sports-outdoors', 'fitness-outdoors'],
        'running': ['sports-outdoors', 'fitness-outdoors'],
        'marathon': ['sports-outdoors', 'fitness-outdoors'],
        'football': ['sports-outdoors', 'fitness-outdoors'],
        'cricket': ['sports-outdoors', 'fitness-outdoors'],
    }

    for key, target_slugs in mapping.items():
        if key == clean or key in clean or clean in key:
            slugs.update(target_slugs)

    # Dynamic match against Category names and slugs in database
    for cat in Category.objects.all():
        cname = cat.name.lower()
        cslug = cat.slug.lower()
        if cname == clean or cname in clean or clean in cname or cslug == clean or cslug in clean:
            slugs.add(cat.slug)

    return list(slugs)


def get_recommended_events_for_user(user, limit=6):
    """
    Returns personalized upcoming event recommendations for a user based strictly
    on their explicit profile interests.

    Role does NOT dictate or stereotype interests.
    Only published, eligible, scheduled upcoming events are returned.

    Returns:
        tuple (recommended_events, user_interests, status_code)
        status_code:
        - 'matched': Found matching published events
        - 'no_matches': User has explicit interests, but no matching published events exist
        - 'no_interests': User has no interests configured in their profile
    """
    if not user or not user.is_authenticated:
        return [], [], 'no_interests'

    profile = getattr(user, 'profile', None)
    if not profile or not getattr(profile, 'interests', None) or not profile.interests.strip():
        from accounts.models import UserProfile
        profile = UserProfile.objects.filter(user=user).first()

    if not profile or not profile.interests or not profile.interests.strip():
        return [], [], 'no_interests'

    user_interests = [i.strip() for i in profile.interests.split(',') if i.strip()]
    if not user_interests:
        return [], [], 'no_interests'

    category_slugs = set()
    keyword_q = Q()

    for interest in user_interests:
        slugs = map_interest_to_category_slugs(interest)
        category_slugs.update(slugs)

        clean = interest.lower().strip()
        if len(clean) >= 3:
            keyword_q |= Q(title__icontains=clean) | Q(description__icontains=clean)

    # Base query for eligible published upcoming events
    now = timezone.now()
    today = timezone.localdate()
    eligible_events = Event.objects.filter(
        review_status='approved',
        event_status='scheduled'
    ).filter(
        Q(end_datetime__gte=now) |
        Q(end_datetime__isnull=True, start_datetime__gte=now) |
        Q(end_datetime__isnull=True, start_datetime__date=today)
    ).select_related('category', 'submitted_by', 'source')

    # Exclude events the user is already confirmed enrolled in
    enrolled_ids = EventEnrollment.objects.filter(
        user=user,
        status='confirmed'
    ).values_list('event_id', flat=True)
    if enrolled_ids:
        eligible_events = eligible_events.exclude(id__in=enrolled_ids)

    # Combined filter
    matching_q = Q()
    if category_slugs:
        matching_q |= Q(category__slug__in=category_slugs)
    if keyword_q:
        matching_q |= keyword_q

    if not matching_q:
        return [], user_interests, 'no_matches'

    matched_qs = eligible_events.filter(matching_q).distinct()

    # Explainable ordering:
    # 1. Preferred city first if specified
    # 2. Soonest upcoming start_datetime first
    if profile.preferred_city and profile.preferred_city.strip():
        city_clean = profile.preferred_city.strip()
        city_events = list(matched_qs.filter(city__iexact=city_clean).order_by('start_datetime')[:limit])
        remaining = limit - len(city_events)
        if remaining > 0:
            other_events = list(matched_qs.exclude(city__iexact=city_clean).order_by('start_datetime')[:remaining])
            recommended_events = city_events + other_events
        else:
            recommended_events = city_events
    else:
        recommended_events = list(matched_qs.order_by('start_datetime')[:limit])

    if not recommended_events:
        return [], user_interests, 'no_matches'

    return recommended_events, user_interests, 'matched'

"""
Vibento - TinyFish-assisted event import service.

Implements structured web agent automation via official TinyFish Agent API
for authorized, permitted event source synchronization.
"""
import os
import json
import logging
import urllib.request
import urllib.error
from datetime import datetime, timezone as dt_timezone
from decimal import Decimal, InvalidOperation

from django.conf import settings
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from django.contrib.auth.models import User

from .models import Category, Event

logger = logging.getLogger(__name__)

# TinyFish Agent API endpoints
TINYFISH_RUN_URL = "https://agent.tinyfish.ai/v1/automation/run"
TINYFISH_RUN_ASYNC_URL = "https://agent.tinyfish.ai/v1/automation/run-async"
TINYFISH_RUNS_STATUS_URL = "https://agent.tinyfish.ai/v1/runs/{run_id}"

# Default timeout in seconds for agent automation execution
TINYFISH_TIMEOUT_SECONDS = 60

# Structured output schema for TinyFish Web Agent API.
# Note: TinyFish does not support type arrays like ["boolean", "null"].
# Use a single type string with "nullable": True for fields that may be null.
TINYFISH_OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "events": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "description": {"type": "string", "nullable": True},
                    "start_datetime": {"type": "string"},
                    "end_datetime": {"type": "string", "nullable": True},
                    "venue": {"type": "string", "nullable": True},
                    "city": {"type": "string", "nullable": True},
                    "area": {"type": "string", "nullable": True},
                    "address": {"type": "string", "nullable": True},
                    "organizer_name": {"type": "string", "nullable": True},
                    "category_hints": {"type": "string", "nullable": True},
                    "intended_audience": {"type": "string", "nullable": True},
                    "is_free": {"type": "boolean", "nullable": True},
                    "price": {"type": "number", "nullable": True},
                    "registration_url": {"type": "string", "nullable": True},
                    "registration_deadline": {"type": "string", "nullable": True},
                    "original_event_page_url": {"type": "string", "nullable": True},
                    "status": {"type": "string", "nullable": True},
                },
                "required": ["title", "start_datetime"],
            },
        }
    },
    "required": ["events"],
}


def get_tinyfish_config():
    """
    Returns current TinyFish configuration and validation status.
    Keeps API key secure server-side.
    """
    if hasattr(settings, 'TINYFISH_API_KEY') and settings.TINYFISH_API_KEY is not None:
        api_key = str(settings.TINYFISH_API_KEY).strip()
    else:
        api_key = os.getenv('TINYFISH_API_KEY', '').strip()

    if hasattr(settings, 'TINYFISH_ALLOWED_SOURCE_URL') and settings.TINYFISH_ALLOWED_SOURCE_URL is not None:
        allowed_source_url = str(settings.TINYFISH_ALLOWED_SOURCE_URL).strip()
    else:
        allowed_source_url = os.getenv('TINYFISH_ALLOWED_SOURCE_URL', '').strip()
    
    allowed_sources = getattr(settings, 'TINYFISH_ALLOWED_SOURCES', [])
    if allowed_source_url and allowed_source_url not in allowed_sources:
        allowed_sources = [allowed_source_url] + [s for s in allowed_sources if s != allowed_source_url]

    missing = []
    if not api_key:
        missing.append("TINYFISH_API_KEY environment variable is not configured.")
    if not allowed_source_url:
        missing.append("TINYFISH_ALLOWED_SOURCE_URL environment variable is not configured.")

    return {
        'api_key_configured': bool(api_key),
        'allowed_source_url': allowed_source_url,
        'allowed_sources': allowed_sources,
        'is_configured': len(missing) == 0,
        'missing_reasons': missing,
    }


def normalize_url(url: str) -> str:
    """Normalize URLs for consistent duplicate detection and scheme validation."""
    if not url:
        return ''
    clean = url.strip()
    if clean.endswith('/'):
        clean = clean[:-1]
    return clean


def fetch_events_from_tinyfish(source_url: str, sync_mode: str = 'async', content_type: str = 'events'):
    """
    Calls official TinyFish Agent API to extract structured events.
    Uses async-first flow (POST /v1/automation/run-async) by default.
    Does NOT retry automatically on failure to prevent duplicate paid runs.
    
    Returns:
        dict: {
            'success': bool,
            'events': list,
            'run_id': str or None,
            'status': str,
            'error': str or None,
        }
    """
    config = get_tinyfish_config()
    if not config['is_configured']:
        return {
            'success': False,
            'events': [],
            'run_id': None,
            'status': 'CONFIG_ERROR',
            'error': " ; ".join(config['missing_reasons']),
        }

    # Verify source against configured allowlist
    permitted_sources = [normalize_url(s) for s in config['allowed_sources']]
    norm_target = normalize_url(source_url)
    if norm_target not in permitted_sources:
        return {
            'success': False,
            'events': [],
            'run_id': None,
            'status': 'FORBIDDEN_SOURCE',
            'error': f"Target URL '{source_url}' is not in the configured permitted sources allowlist.",
        }

    if hasattr(settings, 'TINYFISH_API_KEY') and settings.TINYFISH_API_KEY is not None:
        api_key = str(settings.TINYFISH_API_KEY).strip()
    else:
        api_key = os.getenv('TINYFISH_API_KEY', '').strip()

    if content_type == 'hackathons':
        goal = (
            "Extract all upcoming hackathons, coding sprints, and builder challenges from this page. "
            "For each listing, accurately extract: title, description, start_datetime (ISO 8601), "
            "end_datetime (ISO 8601 if specified), venue, city, area, address, organizer_name, "
            "category_hints (e.g. Hackathon, Coding, Web3, AI), intended_audience, is_free, price, registration_url, "
            "registration_deadline, original_event_page_url, and status. "
            "Do NOT invent dates, times, venues, prices, or links. Missing values must be null."
        )
    elif content_type == 'competitions':
        goal = (
            "Extract all upcoming competitions, challenges, and pitch contests from this page. "
            "For each listing, accurately extract: title, description, start_datetime (ISO 8601), "
            "end_datetime (ISO 8601 if specified), venue, city, area, address, organizer_name, "
            "category_hints (e.g. Competition, Contest, Startup, Pitch), intended_audience, is_free, price, registration_url, "
            "registration_deadline, original_event_page_url, and status. "
            "Do NOT invent dates, times, venues, prices, or links. Missing values must be null."
        )
    else:
        goal = (
            "Extract all upcoming public community event listings, hackathons, and competitions from this page. "
            "For each event, accurately extract: title, description, start_datetime (ISO 8601), "
            "end_datetime (ISO 8601 if specified), venue, city, area, address, organizer_name, "
            "category_hints, intended_audience, is_free, price, registration_url, "
            "registration_deadline, original_event_page_url, and status. "
            "Do NOT invent dates, times, venues, prices, or links. Missing values must be null."
        )

    payload = {
        "url": source_url,
        "goal": goal,
        "output_schema": TINYFISH_OUTPUT_SCHEMA,
        "browser_profile": "lite",
    }

    endpoint = TINYFISH_RUN_ASYNC_URL if sync_mode == 'async' else TINYFISH_RUN_URL

    req = urllib.request.Request(
        endpoint,
        data=json.dumps(payload).encode('utf-8'),
        headers={
            "X-API-Key": api_key,
            "Content-Type": "application/json",
            "User-Agent": "Vibento-Event-Sync/1.0",
        },
        method="POST"
    )

    try:
        with urllib.request.urlopen(req, timeout=TINYFISH_TIMEOUT_SECONDS) as response:
            status_code = response.getcode()
            response_body = response.read().decode('utf-8')
            data = json.loads(response_body)

            if status_code != 200:
                return {
                    'success': False,
                    'events': [],
                    'run_id': data.get('run_id'),
                    'status': 'API_ERROR',
                    'error': f"TinyFish API returned HTTP {status_code}: {data.get('error') or response_body}",
                }

            run_status = data.get('status', 'PENDING' if sync_mode == 'async' else 'COMPLETED')
            run_id = data.get('run_id')

            if run_status == 'FAILED':
                return {
                    'success': False,
                    'events': [],
                    'run_id': run_id,
                    'status': 'FAILED',
                    'error': data.get('error') or "TinyFish automation run failed to complete.",
                }

            if run_status in ('PENDING', 'RUNNING') or (sync_mode == 'async' and 'result' not in data):
                return {
                    'success': True,
                    'events': [],
                    'run_id': run_id,
                    'status': run_status,
                    'error': None,
                }

            result_data = data.get('result') or {}
            events_list = []
            if isinstance(result_data, dict):
                events_list = result_data.get('events', [])
            elif isinstance(result_data, list):
                events_list = result_data

            return {
                'success': True,
                'events': events_list,
                'run_id': run_id,
                'status': 'COMPLETED',
                'error': None,
            }

    except urllib.error.HTTPError as http_err:
        err_body = ""
        try:
            err_body = http_err.read().decode('utf-8')
            err_json = json.loads(err_body)
            err_msg = err_json.get('error', {}).get('message') or err_json.get('message') or err_body
        except Exception:
            err_msg = err_body or str(http_err)

        if http_err.code == 401:
            error_text = f"TinyFish authentication error (HTTP 401): {err_msg}. Please verify your TINYFISH_API_KEY."
        elif http_err.code == 429:
            error_text = f"TinyFish rate limit reached (HTTP 429): {err_msg}."
        else:
            error_text = f"TinyFish API HTTP error {http_err.code}: {err_msg}."

        return {
            'success': False,
            'events': [],
            'run_id': None,
            'status': 'HTTP_ERROR',
            'error': error_text,
        }

    except (urllib.error.URLError, TimeoutError) as net_err:
        if sync_mode == 'async':
            error_msg = (
                f"Submission outcome unknown: Request timed out or network error ({net_err}) "
                f"before receiving a Run ID from TinyFish. "
                f"A remote run may or may not be executing. Please check your TinyFish dashboard "
                f"or enter a Run ID manually before attempting another run."
            )
            return {
                'success': False,
                'events': [],
                'run_id': None,
                'status': 'SUBMISSION_OUTCOME_UNKNOWN',
                'error': error_msg,
            }
        return {
            'success': False,
            'events': [],
            'run_id': None,
            'status': 'NETWORK_TIMEOUT',
            'error': f"TinyFish request timed out or network error: {net_err}. No duplicate run was started.",
        }

    except json.JSONDecodeError as json_err:
        return {
            'success': False,
            'events': [],
            'run_id': None,
            'status': 'MALFORMED_RESPONSE',
            'error': f"TinyFish returned malformed response: {json_err}",
        }

    except Exception as exc:
        return {
            'success': False,
            'events': [],
            'run_id': None,
            'status': 'UNKNOWN_ERROR',
            'error': f"Unexpected error during TinyFish sync: {exc}",
        }


def check_tinyfish_run_result(run_id: str):
    """
    Polls existing run result for an asynchronous run identifier.
    Does NOT initiate a new run.
    """
    config = get_tinyfish_config()
    if not config['api_key_configured']:
        return {
            'success': False,
            'events': [],
            'run_id': run_id,
            'status': 'CONFIG_ERROR',
            'error': "TINYFISH_API_KEY is not configured.",
        }

    if hasattr(settings, 'TINYFISH_API_KEY') and settings.TINYFISH_API_KEY is not None:
        api_key = str(settings.TINYFISH_API_KEY).strip()
    else:
        api_key = os.getenv('TINYFISH_API_KEY', '').strip()
    url = TINYFISH_RUNS_STATUS_URL.format(run_id=run_id)

    req = urllib.request.Request(
        url,
        headers={
            "X-API-Key": api_key,
            "User-Agent": "Vibento-Event-Sync/1.0",
        },
        method="GET"
    )

    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            data = json.loads(response.read().decode('utf-8'))
            status = data.get('status', 'PENDING')
            if status == 'COMPLETED':
                result_data = data.get('result') or {}
                events_list = result_data.get('events', []) if isinstance(result_data, dict) else []
                return {
                    'success': True,
                    'events': events_list,
                    'run_id': run_id,
                    'status': 'COMPLETED',
                    'error': None,
                }
            elif status == 'FAILED':
                return {
                    'success': False,
                    'events': [],
                    'run_id': run_id,
                    'status': 'FAILED',
                    'error': data.get('error') or "Run failed.",
                }
            else:
                return {
                    'success': True,
                    'events': [],
                    'run_id': run_id,
                    'status': status,
                    'error': None,
                }
    except urllib.error.HTTPError as http_err:
        err_body = ""
        try:
            err_body = http_err.read().decode('utf-8')
        except Exception:
            pass
        return {
            'success': False,
            'events': [],
            'run_id': run_id,
            'status': 'HTTP_ERROR',
            'error': f"TinyFish status check returned HTTP {http_err.code}: {err_body or http_err}",
        }
    except (urllib.error.URLError, TimeoutError) as net_err:
        return {
            'success': False,
            'events': [],
            'run_id': run_id,
            'status': 'POLL_TIMEOUT',
            'error': f"Network timeout while checking status for run {run_id}: {net_err}. The remote run is preserved and still active. You can check again without launching a new run.",
        }
    except json.JSONDecodeError as json_err:
        return {
            'success': False,
            'events': [],
            'run_id': run_id,
            'status': 'RESULT_PARSE_ERROR',
            'error': f"Could not parse status response for run {run_id}: {json_err}",
        }
    except Exception as exc:
        return {
            'success': False,
            'events': [],
            'run_id': run_id,
            'status': 'ERROR',
            'error': f"Could not check run status: {exc}",
        }


def parse_and_validate_datetime(dt_str: str):
    """
    Parses datetime string into a timezone-aware datetime.
    Rejects malformed or ambiguous dates rather than guessing.
    """
    if not dt_str or not isinstance(dt_str, str):
        return None

    dt_str = dt_str.strip()
    try:
        # Try Django standard ISO parser first
        parsed = parse_datetime(dt_str)
        if parsed is None:
            # Fallback to python fromisoformat
            # Handle trailing 'Z'
            if dt_str.endswith('Z'):
                dt_str = dt_str[:-1] + '+00:00'
            parsed = datetime.fromisoformat(dt_str)

        if parsed:
            if timezone.is_naive(parsed):
                parsed = timezone.make_aware(parsed, timezone.get_current_timezone())
            return parsed
    except Exception:
        return None

    return None


def match_category(category_hint: str = None, category_mappings: dict = None, default_category = None):
    """
    Matches category hint against:
    1. Explicit keyword/tag category mappings dict
    2. Direct name or slug match
    3. Substring match against existing categories
    4. Default category configured on source
    5. First existing category in DB
    """
    if category_hint and category_mappings and isinstance(category_mappings, dict):
        hint_clean = str(category_hint).strip().lower()
        for kw, target_slug in category_mappings.items():
            if kw.lower() in hint_clean:
                cat = Category.objects.filter(slug__iexact=target_slug).first() or Category.objects.filter(name__iexact=target_slug).first()
                if cat:
                    return cat

    if category_hint:
        hint_clean = str(category_hint).strip().lower()
        cat = Category.objects.filter(name__iexact=hint_clean).first()
        if cat:
            return cat
        cat = Category.objects.filter(slug__iexact=hint_clean).first()
        if cat:
            return cat
        for existing in Category.objects.all():
            if existing.name.lower() in hint_clean or hint_clean in existing.name.lower():
                return existing

    if default_category:
        return default_category

    # Fallback to first existing category or create a 'Community' category
    fallback = Category.objects.first()
    if not fallback:
        fallback = Category.objects.create(name='Community', slug='community', badge_color='primary')
    return fallback


def validate_and_import_events(raw_events, source_url: str, user: User, source=None, auto_approve: bool = False, default_category=None, category_mappings: dict = None):
    """
    Validates extracted event data, performs duplicate & change detection,
    and creates pending or auto-approved external event drafts.
    
    Returns structured results summary.
    """
    now = timezone.now()
    summary = {
        'source_checked': source_url,
        'run_outcome': 'COMPLETED',
        'records_returned': len(raw_events) if isinstance(raw_events, list) else 0,
        'new_pending_created': 0,
        'duplicates_skipped': 0,
        'changes_detected': 0,
        'invalid_records_skipped': 0,
        'created_events': [],
        'skipped_duplicates': [],
        'detected_changes': [],
        'invalid_records': [],
    }

    if not isinstance(raw_events, list):
        summary['run_outcome'] = 'MALFORMED_DATA'
        summary['invalid_records'].append({'title': 'Unknown', 'reason': 'Extracted events payload was not a list.'})
        return summary

    for item in raw_events:
        if not isinstance(item, dict):
            summary['invalid_records_skipped'] += 1
            summary['invalid_records'].append({'title': 'Unknown', 'reason': 'Item is not a valid JSON object.'})
            continue

        title = str(item.get('title') or '').strip()
        if not title:
            summary['invalid_records_skipped'] += 1
            summary['invalid_records'].append({'title': 'Unknown', 'reason': 'Missing required event title.'})
            continue
        title = title[:200]

        # 1. Start datetime validation
        raw_start = item.get('start_datetime')
        start_dt = parse_and_validate_datetime(raw_start)
        if not start_dt:
            summary['invalid_records_skipped'] += 1
            summary['invalid_records'].append({
                'title': title,
                'reason': f"Malformed or ambiguous start datetime: '{raw_start}'"
            })
            continue

        # Exclude clearly past events
        if start_dt < now:
            summary['invalid_records_skipped'] += 1
            summary['invalid_records'].append({
                'title': title,
                'reason': f"Event start time ({start_dt.strftime('%Y-%m-%d %H:%M')}) is in the past."
            })
            continue

        # 2. End datetime validation (optional; missing values remain missing)
        raw_end = item.get('end_datetime')
        end_dt = parse_and_validate_datetime(raw_end) if raw_end else None
        if raw_end and not end_dt:
            summary['invalid_records_skipped'] += 1
            summary['invalid_records'].append({
                'title': title,
                'reason': f"Malformed end datetime: '{raw_end}'"
            })
            continue

        if end_dt and end_dt <= start_dt:
            summary['invalid_records_skipped'] += 1
            summary['invalid_records'].append({
                'title': title,
                'reason': f"End time ({end_dt}) cannot be earlier than or equal to start time ({start_dt})."
            })
            continue

        # 3. Location fields
        venue_name = str(item.get('venue') or '').strip()[:180]
        city = str(item.get('city') or '').strip()[:100]
        area = str(item.get('area') or '').strip()[:120]
        address = str(item.get('address') or '').strip()

        if not venue_name and not city:
            summary['invalid_records_skipped'] += 1
            summary['invalid_records'].append({
                'title': title,
                'reason': "Missing venue name and city location details."
            })
            continue

        if not venue_name:
            venue_name = f"Venue in {city}"
        if not city:
            city = "Bengaluru"  # Default reasonable regional city if venue is provided
        if not area:
            area = venue_name[:120]

        # 4. URLs & Schemes
        raw_page_url = str(item.get('original_event_page_url') or source_url).strip()
        if raw_page_url and not (raw_page_url.startswith('http://') or raw_page_url.startswith('https://')):
            summary['invalid_records_skipped'] += 1
            summary['invalid_records'].append({
                'title': title,
                'reason': f"Invalid original event page URL scheme: '{raw_page_url}'"
            })
            continue
        original_source_url = raw_page_url[:200]

        registration_url = str(item.get('registration_url') or '').strip()
        if registration_url and not (registration_url.startswith('http://') or registration_url.startswith('https://')):
            summary['invalid_records_skipped'] += 1
            summary['invalid_records'].append({
                'title': title,
                'reason': f"Invalid registration URL scheme: '{registration_url}'"
            })
            continue
        registration_url = registration_url[:200]

        # 5. Price & Free/Paid status
        is_free = item.get('is_free')
        price_val = item.get('price')
        price = None

        if price_val is not None:
            try:
                price = Decimal(str(price_val))
                if price < 0:
                    summary['invalid_records_skipped'] += 1
                    summary['invalid_records'].append({
                        'title': title,
                        'reason': f"Negative price value: {price}"
                    })
                    continue
                if is_free is None:
                    is_free = (price == 0)
            except (InvalidOperation, ValueError):
                summary['invalid_records_skipped'] += 1
                summary['invalid_records'].append({
                    'title': title,
                    'reason': f"Invalid numeric price: {price_val}"
                })
                continue

        # If price is unspecified and is_free is unspecified, do not assume free!
        # is_free remains None or True/False

        # 6. Duplicate & Change Detection
        # Match by:
        # A) Normalized original_event_page_url (exact page match)
        # B) Normalized title + start_datetime + city
        norm_page_url = normalize_url(original_source_url)
        norm_title = title.lower().strip()

        existing_match = None
        if norm_page_url and norm_page_url != normalize_url(source_url):
            existing_match = Event.objects.filter(original_source_url__iexact=norm_page_url).first()

        if not existing_match:
            existing_match = Event.objects.filter(
                title__iexact=norm_title,
                start_datetime=start_dt,
                city__iexact=city
            ).first()

        if existing_match:
            # Check for possible changes on existing record
            diffs = []
            extracted_status = str(item.get('status') or '').lower()
            if extracted_status == 'cancelled' and existing_match.event_status != 'cancelled':
                diffs.append("Source marks event as CANCELLED (currently scheduled in Vibento)")
            if venue_name and existing_match.venue_name.lower() != venue_name.lower():
                diffs.append(f"Venue difference: '{existing_match.venue_name}' vs '{venue_name}'")
            if end_dt and existing_match.end_datetime != end_dt:
                diffs.append(f"End time difference: '{existing_match.end_datetime}' vs '{end_dt}'")

            if diffs:
                summary['changes_detected'] += 1
                summary['detected_changes'].append({
                    'title': existing_match.title,
                    'event_id': existing_match.pk,
                    'review_status': existing_match.review_status,
                    'changes': diffs,
                })

            summary['duplicates_skipped'] += 1
            summary['skipped_duplicates'].append({
                'title': title,
                'reason': f"Matches existing event #{existing_match.pk} ('{existing_match.title}')"
            })
            continue

        # Check for uncertain possible matches (same title on same calendar day)
        uncertain = Event.objects.filter(
            title__iexact=norm_title,
            start_datetime__date=start_dt.date()
        ).first()
        if uncertain:
            summary['duplicates_skipped'] += 1
            summary['skipped_duplicates'].append({
                'title': title,
                'reason': f"Possible uncertain match with event #{uncertain.pk} on {start_dt.date()} - skipped for manual review."
            })
            continue

        # 7. Other fields & category
        category = match_category(
            item.get('category_hints'),
            category_mappings=category_mappings,
            default_category=default_category
        )
        intended_audience = str(item.get('intended_audience') or 'All Audiences').strip()
        valid_audiences = [c[0] for c in Event.INTENDED_AUDIENCE_CHOICES]
        if intended_audience not in valid_audiences:
            intended_audience = 'All Audiences'

        organizer_name = str(item.get('organizer_name') or 'Community Organizer').strip()[:150]
        description = str(item.get('description') or f"Event listing imported from {source_url}").strip()

        event_status = 'cancelled' if str(item.get('status') or '').lower() == 'cancelled' else 'scheduled'

        review_status = 'approved' if auto_approve else 'pending'
        reviewed_at = now if auto_approve else None
        reviewed_by = user if auto_approve else None
        reviewer_feedback = f"Automated import from trusted source {source.name if source else source_url}" if auto_approve else ""

        # 8. Create new Event
        try:
            new_event = Event.objects.create(
                title=title,
                description=description,
                category=category,
                intended_audience=intended_audience,
                start_datetime=start_dt,
                end_datetime=end_dt,
                city=city,
                area=area,
                venue_name=venue_name,
                address=address,
                organizer_display_name=organizer_name,
                submitted_by=user,
                is_free=is_free,
                price=price,
                registration_url=registration_url,
                source_type='external',
                source=source,
                original_source_url=original_source_url,
                source_checked_at=now,
                review_status=review_status,
                reviewed_at=reviewed_at,
                reviewed_by=reviewed_by,
                reviewer_feedback=reviewer_feedback,
                event_status=event_status,
            )
            summary['new_pending_created'] += 1
            if auto_approve:
                summary['new_approved_created'] = summary.get('new_approved_created', 0) + 1
            summary['created_events'].append({
                'id': new_event.pk,
                'title': new_event.title,
                'start_datetime': new_event.start_datetime.strftime('%Y-%m-%d %H:%M'),
                'city': new_event.city,
            })
        except Exception as save_err:
            summary['invalid_records_skipped'] += 1
            summary['invalid_records'].append({
                'title': title,
                'reason': f"Database save error: {save_err}"
            })

    return summary

from datetime import timedelta
from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.contrib import messages
from django.utils import timezone
from django.db.models import Q
from django.http import Http404

from .models import Event, WhatsAppSubmission, Category
from .forms import EventForm, WhatsAppEventSubmissionForm


def event_list(request):
    """
    Public event discovery listing.
    Only approved, upcoming, non-cancelled events are displayed.
    Supports keyword search, category, date-range, city/area, and free/paid filters.
    """
    now = timezone.now()
    events = Event.objects.filter(
        review_status='approved',
        event_status='scheduled',
        end_datetime__gte=now
    ).select_related('category', 'submitted_by').order_by('start_datetime')

    # Query params
    q = request.GET.get('q', '').strip()
    category_slug = request.GET.get('category', '').strip()
    city = request.GET.get('city', '').strip()
    area = request.GET.get('area', '').strip()
    pricing = request.GET.get('pricing', '').strip()
    date_range = request.GET.get('date_range', '').strip()
    start_date_str = request.GET.get('start_date', '').strip()
    end_date_str = request.GET.get('end_date', '').strip()

    # Apply search filter
    if q:
        events = events.filter(
            Q(title__icontains=q) |
            Q(description__icontains=q) |
            Q(venue_name__icontains=q) |
            Q(organizer_display_name__icontains=q) |
            Q(area__icontains=q) |
            Q(city__icontains=q)
        )

    # Category filter
    if category_slug:
        events = events.filter(category__slug=category_slug)

    # City filter
    if city:
        events = events.filter(city__iexact=city)

    # Area filter
    if area:
        events = events.filter(area__icontains=area)

    # Free / Paid filter
    if pricing == 'free':
        events = events.filter(is_free=True)
    elif pricing == 'paid':
        events = events.filter(is_free=False)

    # Date range filters
    today = timezone.localdate()
    if date_range == 'today':
        events = events.filter(
            start_datetime__date__lte=today,
            end_datetime__date__gte=today
        )
    elif date_range == 'tomorrow':
        tomorrow = today + timedelta(days=1)
        events = events.filter(
            start_datetime__date__lte=tomorrow,
            end_datetime__date__gte=tomorrow
        )
    elif date_range == 'this_weekend':
        # Saturday and Sunday
        weekday = today.weekday()  # Monday is 0, Sunday is 6
        if weekday == 6:  # Sunday
            saturday = today - timedelta(days=1)
            sunday = today
        elif weekday == 5:  # Saturday
            saturday = today
            sunday = today + timedelta(days=1)
        else:  # Monday through Friday
            saturday = today + timedelta(days=(5 - weekday))
            sunday = saturday + timedelta(days=1)
        events = events.filter(
            start_datetime__date__lte=sunday,
            end_datetime__date__gte=saturday
        )
    elif date_range == 'this_week':
        events = events.filter(
            start_datetime__date__lte=today + timedelta(days=7),
            end_datetime__date__gte=today
        )
    elif date_range == 'this_month':
        events = events.filter(
            start_datetime__date__lte=today + timedelta(days=30),
            end_datetime__date__gte=today
        )

    # Custom date picker filtering
    if start_date_str:
        try:
            events = events.filter(start_datetime__date__gte=start_date_str)
        except (ValueError, TypeError):
            pass

    if end_date_str:
        try:
            events = events.filter(start_datetime__date__lte=end_date_str)
        except (ValueError, TypeError):
            pass

    # Pagination: 9 events per page
    paginator = Paginator(events, 9)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    # Context helpers
    categories = Category.objects.all()
    raw_cities = Event.objects.filter(
        review_status='approved',
        event_status='scheduled',
        end_datetime__gte=now
    ).values_list('city', flat=True).distinct()
    
    # Normalize city names to avoid duplicate cases (e.g. 'delhi' vs 'Delhi')
    city_dict = {}
    for c in raw_cities:
        if c and c.strip():
            clean = c.strip()
            key = clean.lower()
            if key not in city_dict or clean[0].isupper():
                city_dict[key] = clean.title()
    available_cities = sorted(list(city_dict.values()))

    has_filters = any([q, category_slug, city, area, pricing, date_range, start_date_str, end_date_str])

    return render(request, 'events/event_list.html', {
        'events': page_obj,
        'categories': categories,
        'available_cities': available_cities,
        'selected_category': category_slug,
        'selected_city': city,
        'selected_area': area,
        'selected_pricing': pricing,
        'selected_date_range': date_range,
        'search_query': q,
        'start_date': start_date_str,
        'end_date': end_date_str,
        'has_filters': has_filters,
        'total_events_count': paginator.count,
    })


def event_detail(request, slug):
    """
    Public event detail page.
    Unapproved events are blocked from public access (returns 404 for unauthenticated or non-owner).
    Owners and staff visiting the public URL are redirected to preview if event is not approved.
    """
    event = get_object_or_404(Event.objects.select_related('category', 'submitted_by'), slug=slug)

    # Strict visibility restriction
    if event.review_status != 'approved':
        if request.user.is_authenticated and (request.user == event.submitted_by or request.user.is_staff):
            messages.info(request, "This event is not publicly visible yet. Showing owner preview mode.")
            return redirect('events:event_preview', slug=event.slug)
        else:
            raise Http404("Event not found or has not yet been approved.")

    return render(request, 'events/event_detail.html', {
        'event': event,
        'is_preview': False,
    })


@login_required
def event_preview(request, slug):
    """
    Protected preview view for the submission owner or staff.
    Allows inspection of pending/needs-correction/rejected drafts before or after review.
    """
    event = get_object_or_404(Event.objects.select_related('category', 'submitted_by'), slug=slug)

    if not (request.user == event.submitted_by or request.user.is_staff):
        raise PermissionDenied("You do not have permission to preview this event submission.")

    # Check if this was a WhatsApp submission to allow owner/admin to inspect original message
    whatsapp_sub = getattr(event, 'whatsapp_submission', None)

    return render(request, 'events/event_preview.html', {
        'event': event,
        'whatsapp_submission': whatsapp_sub,
        'is_preview': True,
    })


@login_required
def organizer_dashboard(request):
    """
    Organizer dashboard showing own event submissions, moderation status, and feedback.
    """
    own_events = Event.objects.filter(
        submitted_by=request.user
    ).select_related('category').order_by('-created_at')

    # Moderation breakdown
    counts = {
        'total': own_events.count(),
        'approved': own_events.filter(review_status='approved', event_status='scheduled').count(),
        'pending': own_events.filter(review_status='pending').count(),
        'correction': own_events.filter(review_status='correction').count(),
        'rejected': own_events.filter(review_status='rejected').count(),
        'cancelled': own_events.filter(event_status='cancelled').count(),
    }

    return render(request, 'events/organizer_dashboard.html', {
        'events': own_events,
        'counts': counts,
    })


@login_required
def event_create(request):
    """
    Standard organizer submission view.
    """
    if request.method == 'POST':
        form = EventForm(request.POST, request.FILES)
        if form.is_valid():
            event = form.save(commit=False)
            event.submitted_by = request.user
            event.source_type = 'organizer'
            event.review_status = 'pending'
            event.event_status = 'scheduled'
            event.save()
            messages.success(
                request,
                f"Event '{event.title}' submitted successfully! It is now pending admin review."
            )
            return redirect('events:organizer_dashboard')
        else:
            messages.error(request, "Please check the form for required fields or errors.")
    else:
        form = EventForm()

    return render(request, 'events/event_form.html', {
        'form': form,
        'is_edit': False,
        'title': 'Create New Event',
    })


@login_required
def event_edit(request, slug):
    """
    Edit own event view.
    Enforces owner-only access.
    Rule: Editing a published or reviewed event automatically resets moderation status to 'pending'.
    """
    event = get_object_or_404(Event, slug=slug)

    # Permission check: owner only
    if event.submitted_by != request.user and not request.user.is_staff:
        raise PermissionDenied("You can only edit events that you submitted.")

    was_approved = (event.review_status == 'approved')

    if request.method == 'POST':
        form = EventForm(request.POST, request.FILES, instance=event)
        if form.is_valid():
            updated_event = form.save(commit=False)
            # Avoid accidental edits to event owner or submitter
            updated_event.submitted_by = event.submitted_by

            # Prevent organizer edit/re-review logic from resetting an admin's approval back to pending
            if was_approved:
                updated_event.review_status = 'approved'
                updated_event.reviewed_by = event.reviewed_by
                updated_event.reviewed_at = event.reviewed_at
                updated_event.reviewer_feedback = event.reviewer_feedback
            else:
                updated_event.review_status = 'pending'
                updated_event.reviewed_by = None
                updated_event.reviewed_at = None

            updated_event.save()
            form.save_m2m()

            if was_approved:
                messages.success(
                    request,
                    f"'{updated_event.title}' has been updated. Admin approval remains active."
                )
            else:
                messages.success(
                    request,
                    f"Changes saved for '{updated_event.title}'. The submission is pending admin review."
                )
            return redirect('events:organizer_dashboard')
        else:
            messages.error(request, "Please correct the errors below.")
    else:
        form = EventForm(instance=event)

    return render(request, 'events/event_form.html', {
        'form': form,
        'event': event,
        'is_edit': True,
        'was_approved': was_approved,
        'title': f"Edit Event: {event.title}",
    })


@login_required
def event_cancel(request, slug):
    """
    Cancel an event submitted by the current user.
    """
    event = get_object_or_404(Event, slug=slug)

    if event.submitted_by != request.user and not request.user.is_staff:
        raise PermissionDenied("You can only cancel events you submitted.")

    if request.method == 'POST':
        event.event_status = 'cancelled'
        event.save()
        messages.success(
            request,
            f"Event '{event.title}' has been marked as Cancelled. It will no longer appear in active discovery "
            "and registrations are closed."
        )
        return redirect('events:organizer_dashboard')

    return render(request, 'events/cancel_confirm.html', {'event': event})


@login_required
def whatsapp_submission_create(request):
    """
    Manual WhatsApp submission view.
    Collects raw WhatsApp message + optional flyer + structured fields + public sharing confirmation.
    """
    if request.method == 'POST':
        form = WhatsAppEventSubmissionForm(request.POST, request.FILES)
        if form.is_valid():
            # Create event record
            event = form.save(commit=False)
            event.submitted_by = request.user
            event.source_type = 'whatsapp'
            event.review_status = 'pending'
            event.event_status = 'scheduled'
            event.save()

            # Create private WhatsAppSubmission record
            WhatsAppSubmission.objects.create(
                event=event,
                original_message=form.cleaned_data['original_message'],
                original_poster=form.cleaned_data.get('original_poster'),
                public_permission_confirmed=form.cleaned_data['public_permission_confirmed'],
                submitted_by=request.user
            )

            messages.success(
                request,
                f"WhatsApp event '{event.title}' submitted for review! "
                "Our team will verify the details against the message before publishing."
            )
            return redirect('events:organizer_dashboard')
        else:
            messages.error(request, "Please check the form. Confirming public sharing permission and valid dates are required.")
    else:
        form = WhatsAppEventSubmissionForm()

    return render(request, 'events/whatsapp_submission_form.html', {
        'form': form,
        'title': 'Submit a WhatsApp Event',
    })

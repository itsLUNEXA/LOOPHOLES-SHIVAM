import uuid
from django.db import models
from django.contrib.auth.models import User
from django.utils.text import slugify
from django.utils import timezone
from django.core.exceptions import ValidationError
from django.urls import reverse


class Category(models.Model):
    name = models.CharField(max_length=100, unique=True)
    slug = models.SlugField(max_length=120, unique=True, blank=True)
    description = models.TextField(blank=True)
    badge_color = models.CharField(max_length=30, default='primary', help_text="Bootstrap badge color (e.g. primary, success, info, warning, dark)")

    class Meta:
        verbose_name_plural = 'Categories'
        ordering = ['name']

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name


class EventSource(models.Model):
    CONTENT_TYPE_CHOICES = [
        ('events', 'Events & Meetups'),
        ('hackathons', 'Hackathons & Sprints'),
        ('competitions', 'Competitions & Challenges'),
        ('all', 'Mixed / All Listings'),
    ]

    SYNC_STATUS_CHOICES = [
        ('idle', 'Idle'),
        ('queued', 'Queued'),
        ('running', 'Running'),
        ('completed', 'Completed'),
        ('failed', 'Failed'),
    ]

    name = models.CharField(max_length=150, verbose_name="Source Name")
    source_url = models.URLField(max_length=500, unique=True, verbose_name="Source URL")
    content_type = models.CharField(
        max_length=30,
        choices=CONTENT_TYPE_CHOICES,
        default='events',
        verbose_name="Content Type"
    )
    default_category = models.ForeignKey(
        Category,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='sources',
        verbose_name="Default Category"
    )
    category_mappings = models.JSONField(
        default=dict,
        blank=True,
        verbose_name="Keyword / Tag Category Mappings",
        help_text="Optional JSON dictionary mapping tag keywords to category slugs (e.g. {'hackathon': 'technology-ai'})"
    )
    is_enabled = models.BooleanField(
        default=True,
        verbose_name="Enabled?",
        help_text="When disabled, automatic synchronization is bypassed."
    )
    freshness_interval_minutes = models.PositiveIntegerField(
        default=360,
        verbose_name="Freshness Interval (Minutes)",
        help_text="Interval before source data is considered stale. Default is 360 (6 hours)."
    )
    last_sync_attempt_at = models.DateTimeField(null=True, blank=True, verbose_name="Last Sync Attempt")
    last_successful_sync_at = models.DateTimeField(null=True, blank=True, verbose_name="Last Successful Sync")
    next_due_at = models.DateTimeField(null=True, blank=True, verbose_name="Next Due At")
    sync_status = models.CharField(
        max_length=30,
        choices=SYNC_STATUS_CHOICES,
        default='idle',
        verbose_name="Sync Status"
    )
    active_run_id = models.CharField(
        max_length=120,
        null=True,
        blank=True,
        verbose_name="Active TinyFish Run ID"
    )
    concurrency_lock_until = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="Concurrency Lock Until"
    )
    concurrency_lock_token = models.CharField(
        max_length=64,
        null=True,
        blank=True,
        verbose_name="Concurrency Lock Token"
    )
    consecutive_failures = models.PositiveIntegerField(
        default=0,
        verbose_name="Consecutive Failures"
    )
    max_retries = models.PositiveIntegerField(
        default=3,
        verbose_name="Max Retries",
        help_text="Bounded retries before marking source as failed."
    )
    daily_run_limit = models.PositiveIntegerField(
        default=10,
        verbose_name="Daily Run Limit",
        help_text="Hard limit on API runs per day to protect budget."
    )
    runs_today_count = models.PositiveIntegerField(
        default=0,
        verbose_name="Runs Today"
    )
    last_run_date = models.DateField(null=True, blank=True, verbose_name="Last Run Date")
    auto_approve_trusted = models.BooleanField(
        default=False,
        verbose_name="Auto-Approve Listings?",
        help_text="If True, listings from this source are approved immediately; if False, placed into moderation queue."
    )
    last_error_message = models.TextField(
        blank=True,
        verbose_name="Last Error Message"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Event Source"
        verbose_name_plural = "Event Sources"
        ordering = ['name']

    def __str__(self):
        return f"{self.name} ({self.get_content_type_display()})"

    @property
    def is_running(self):
        """Returns True if a sync run is currently active or queued and lock is unexpired."""
        if self.sync_status in ('queued', 'running'):
            if self.concurrency_lock_until and timezone.now() < self.concurrency_lock_until:
                return True
        return False

    @property
    def is_locked(self):
        return self.is_running

    def can_run_today(self):
        """Enforces daily API budget limit to prevent runaway billable usage."""
        today = timezone.localdate()
        if self.last_run_date != today:
            return True
        return self.runs_today_count < self.daily_run_limit


class SyncRunHistory(models.Model):
    TRIGGER_CHOICES = [
        ('visitor_entry', 'Website Entry / Page Reload'),
        ('visitor_stale_fallback', 'Visitor Stale Fallback'),
        ('scheduled_cron', 'Scheduled Cron / Worker'),
        ('admin_manual', 'Admin Manual Trigger'),
        ('retry', 'Bounded Retry'),
    ]

    STATUS_CHOICES = [
        ('PENDING', 'Pending'),
        ('RUNNING', 'Running'),
        ('COMPLETED', 'Completed'),
        ('FAILED', 'Failed'),
        ('TIMEOUT', 'Timeout'),
        ('RATE_LIMITED', 'Rate Limited'),
    ]

    source = models.ForeignKey(
        EventSource,
        on_delete=models.CASCADE,
        related_name='run_histories',
        verbose_name="Event Source"
    )
    run_id = models.CharField(max_length=120, null=True, blank=True, verbose_name="Run ID")
    trigger_type = models.CharField(
        max_length=40,
        choices=TRIGGER_CHOICES,
        default='scheduled_cron',
        verbose_name="Trigger Type"
    )
    status = models.CharField(
        max_length=40,
        choices=STATUS_CHOICES,
        default='PENDING',
        verbose_name="Status"
    )
    started_at = models.DateTimeField(auto_now_add=True, verbose_name="Started At")
    completed_at = models.DateTimeField(null=True, blank=True, verbose_name="Completed At")
    records_extracted_count = models.PositiveIntegerField(default=0, verbose_name="Extracted")
    records_created_count = models.PositiveIntegerField(default=0, verbose_name="Created (Pending)")
    records_updated_count = models.PositiveIntegerField(default=0, verbose_name="Changes Detected")
    records_skipped_count = models.PositiveIntegerField(default=0, verbose_name="Duplicates Skipped")
    records_rejected_count = models.PositiveIntegerField(default=0, verbose_name="Invalid / Rejected")
    error_message = models.TextField(blank=True, verbose_name="Error / Diagnostic Details")
    diagnostic_details = models.JSONField(default=dict, blank=True, verbose_name="Diagnostic JSON")

    class Meta:
        verbose_name = "Sync Run History"
        verbose_name_plural = "Sync Run Histories"
        ordering = ['-started_at']

    def __str__(self):
        return f"{self.source.name} - {self.status} ({self.started_at.strftime('%Y-%m-%d %H:%M')})"


class Event(models.Model):
    SOURCE_TYPE_CHOICES = [
        ('organizer', 'Organizer submission'),
        ('whatsapp', 'WhatsApp submission'),
        ('external', 'External website (reserved for Part 2)'),
    ]

    REVIEW_STATUS_CHOICES = [
        ('draft', 'Draft'),
        ('pending', 'Pending review'),
        ('correction', 'Needs correction'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
    ]

    EVENT_STATUS_CHOICES = [
        ('scheduled', 'Scheduled'),
        ('cancelled', 'Cancelled'),
    ]

    INTENDED_AUDIENCE_CHOICES = [
        ('All Audiences', 'All Audiences'),
        ('Students', 'Students'),
        ('Working Professionals', 'Working Professionals'),
        ('Entrepreneurs & Founders', 'Entrepreneurs & Founders'),
        ('Hobbyists & Creators', 'Hobbyists & Creators'),
        ('Developers & Tech Enthusiasts', 'Developers & Tech Enthusiasts'),
    ]

    title = models.CharField(max_length=200, verbose_name="Event Title")
    slug = models.SlugField(max_length=240, unique=True, blank=True)
    description = models.TextField(verbose_name="Event Description")
    category = models.ForeignKey(Category, on_delete=models.PROTECT, related_name='events')
    intended_audience = models.CharField(
        max_length=100,
        choices=INTENDED_AUDIENCE_CHOICES,
        default='All Audiences',
        verbose_name="Target Audience"
    )

    start_datetime = models.DateTimeField(verbose_name="Start Date & Time")
    end_datetime = models.DateTimeField(null=True, blank=True, verbose_name="End Date & Time")

    city = models.CharField(max_length=100, verbose_name="City")
    area = models.CharField(max_length=120, verbose_name="Area / Locality / Neighborhood")
    venue_name = models.CharField(max_length=180, verbose_name="Venue Name")
    address = models.TextField(verbose_name="Full Venue Address", blank=True)

    organizer_display_name = models.CharField(
        max_length=150,
        verbose_name="Organizer / Community Name",
        help_text="Name shown publicly as the event host"
    )
    submitted_by = models.ForeignKey(User, on_delete=models.CASCADE, related_name='submitted_events')

    is_free = models.BooleanField(null=True, blank=True, default=True, verbose_name="Free Event?")
    price = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        verbose_name="Ticket Price (INR / Local Currency)"
    )

    registration_url = models.URLField(
        blank=True,
        verbose_name="External Registration / Website URL",
        help_text="Direct link where attendees can RSVP, buy tickets, or sign up"
    )
    registration_deadline = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="Registration Deadline"
    )
    deadline_type = models.CharField(
        max_length=60,
        default='Registration Deadline',
        blank=True,
        verbose_name="Deadline Type",
        help_text="e.g. Registration Deadline, Submission Deadline, Application Deadline"
    )
    poster = models.ImageField(
        upload_to='event_posters/%Y/%m/',
        blank=True,
        null=True,
        verbose_name="Event Poster / Banner"
    )

    source_type = models.CharField(
        max_length=20,
        choices=SOURCE_TYPE_CHOICES,
        default='organizer',
        verbose_name="Submission Source"
    )
    original_source_url = models.URLField(
        blank=True,
        verbose_name="Original Source URL",
        help_text="Optional reference link (e.g. social post or meet page)"
    )
    source = models.ForeignKey(
        'EventSource',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='events',
        verbose_name="Configured Event Source"
    )
    source_checked_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="Source Checked At",
        help_text="Timestamp when the external source was checked"
    )

    review_status = models.CharField(
        max_length=20,
        choices=REVIEW_STATUS_CHOICES,
        default='pending',
        verbose_name="Moderation Status"
    )
    event_status = models.CharField(
        max_length=20,
        choices=EVENT_STATUS_CHOICES,
        default='scheduled',
        verbose_name="Event Status"
    )

    reviewer_feedback = models.TextField(
        blank=True,
        verbose_name="Reviewer / Admin Feedback",
        help_text="Visible to the submitting organizer if corrections are requested or explanation given"
    )
    reviewed_by = models.ForeignKey(
        User,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='reviewed_events'
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['start_datetime']
        indexes = [
            models.Index(fields=['review_status', 'event_status', 'start_datetime']),
            models.Index(fields=['city', 'area']),
        ]

    def __str__(self):
        return f"{self.title} ({self.city}) [{self.get_review_status_display()}]"

    def clean(self):
        super().clean()
        errors = {}

        if self.start_datetime and self.end_datetime:
            if self.end_datetime <= self.start_datetime:
                errors['end_datetime'] = "Event end time must be later than start time."

        if self.registration_deadline and self.start_datetime:
            if self.registration_deadline > self.start_datetime:
                errors['registration_deadline'] = "Registration deadline cannot be after the event start time."

        if self.is_free is False:
            if self.price is None:
                if self.source_type != 'external':
                    errors['price'] = "Price is required for paid events."
            elif self.price < 0:
                errors['price'] = "Price cannot be negative."

        if self.registration_url and not (self.registration_url.startswith('http://') or self.registration_url.startswith('https://')):
            errors['registration_url'] = "Registration URL must start with http:// or https://"

        if self.original_source_url and not (self.original_source_url.startswith('http://') or self.original_source_url.startswith('https://')):
            errors['original_source_url'] = "Original source URL must start with http:// or https://"

        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        if not self.slug:
            base_slug = slugify(self.title) or 'event'
            unique_slug = base_slug
            counter = 1
            while Event.objects.filter(slug=unique_slug).exclude(pk=self.pk).exists():
                unique_slug = f"{base_slug}-{counter}"
                counter += 1
            self.slug = unique_slug
        super().save(*args, **kwargs)

    @property
    def is_past(self):
        now = timezone.now()
        target_time = self.end_datetime if self.end_datetime else self.start_datetime
        return target_time < now

    @property
    def is_registration_closed(self):
        if self.event_status == 'cancelled' or self.is_past:
            return True
        if self.registration_deadline and self.registration_deadline < timezone.now():
            return True
        return False

    @property
    def is_active_public(self):
        return (
            self.review_status == 'approved' and
            self.event_status == 'scheduled' and
            not self.is_past
        )

    @property
    def effective_deadline_type(self):
        if self.deadline_type:
            return self.deadline_type
        if self.source and self.source.content_type in ('hackathons', 'competitions'):
            return "Submission Deadline"
        return "Registration Deadline"

    def get_absolute_url(self):
        return reverse('events:event_detail', kwargs={'slug': self.slug})


class WhatsAppSubmission(models.Model):
    event = models.OneToOneField(
        Event,
        on_delete=models.CASCADE,
        related_name='whatsapp_submission'
    )
    original_message = models.TextField(
        verbose_name="Original WhatsApp Message",
        help_text="Private: Raw forwarded text or announcement from WhatsApp"
    )
    original_poster = models.ImageField(
        upload_to='whatsapp_raw_posters/%Y/%m/',
        blank=True,
        null=True,
        verbose_name="Original WhatsApp Flyer/Poster"
    )
    public_permission_confirmed = models.BooleanField(
        default=False,
        verbose_name="Confirmed Public Sharing Permission",
        help_text="Submitter confirmed that they have authorization to publicly share this event."
    )
    submitted_by = models.ForeignKey(User, on_delete=models.CASCADE, related_name='whatsapp_submissions')
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"WhatsApp Submission for: {self.event.title} by {self.submitted_by.username}"

    def clean(self):
        super().clean()
        if not self.public_permission_confirmed:
            raise ValidationError({'public_permission_confirmed': "You must confirm that you have permission to share this event publicly."})


class EventEnrollment(models.Model):
    STATUS_CHOICES = [
        ('confirmed', 'Confirmed'),
        ('cancelled', 'Cancelled'),
    ]

    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='enrollments',
        verbose_name="Enrolled User"
    )
    event = models.ForeignKey(
        Event,
        on_delete=models.CASCADE,
        related_name='enrollments',
        verbose_name="Event"
    )
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='confirmed',
        verbose_name="Enrollment Status"
    )
    enrolled_at = models.DateTimeField(auto_now_add=True, verbose_name="Enrolled At")
    notes = models.TextField(blank=True, default='', verbose_name="Notes / Remarks")

    class Meta:
        verbose_name = "Event Enrollment"
        verbose_name_plural = "Event Enrollments"
        unique_together = ('user', 'event')
        ordering = ['-enrolled_at']

    def __str__(self):
        return f"{self.user.username} - {self.event.title} ({self.status})"

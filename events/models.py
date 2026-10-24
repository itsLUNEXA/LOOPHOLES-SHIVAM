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

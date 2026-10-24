from django.contrib import admin, messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import HttpResponseRedirect
from django.shortcuts import render, get_object_or_404
from django.utils import timezone
from django.utils.html import format_html
from django.urls import reverse
from django import forms
from .models import Category, Event, WhatsAppSubmission


def apply_event_moderation(queryset, reviewer, action_type, feedback=''):
    """
    Shared moderation logic for both individual and bulk review decisions.
    
    action_type: 'approved', 'rejected', or 'correction'
    reviewer: User instance (must have staff change permissions)
    feedback: str (required if action_type in ('rejected', 'correction'))
    """
    if action_type not in ('approved', 'rejected', 'correction'):
        raise ValidationError(f"Invalid moderation action: {action_type}")

    feedback_clean = (feedback or '').strip()
    if action_type in ('rejected', 'correction') and not feedback_clean:
        raise ValidationError("Reviewer feedback is required when rejecting or requesting correction for an event.")

    now = timezone.now()
    count = 0
    for event in queryset:
        event.review_status = action_type
        event.reviewed_by = reviewer
        event.reviewed_at = now
        if feedback_clean:
            event.reviewer_feedback = feedback_clean
        # Rule: Approval must not clear a cancellation status.
        # Event event_status is preserved unchanged.
        # Rule: Avoid accidental edits to submitter or other event fields.
        event.save(update_fields=[
            'review_status',
            'reviewed_by',
            'reviewed_at',
            'reviewer_feedback',
            'updated_at'
        ])
        count += 1
    return count


class EventAdminForm(forms.ModelForm):
    class Meta:
        model = Event
        fields = '__all__'

    def clean(self):
        cleaned_data = super().clean()
        review_status = cleaned_data.get('review_status')
        reviewer_feedback = cleaned_data.get('reviewer_feedback')
        if review_status in ('rejected', 'correction') and not (reviewer_feedback and reviewer_feedback.strip()):
            self.add_error('reviewer_feedback', "Reviewer feedback is required when rejecting or requesting correction.")
        return cleaned_data


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ['name', 'slug', 'badge_color', 'events_count']
    prepopulated_fields = {'slug': ('name',)}
    search_fields = ['name']

    def events_count(self, obj):
        return obj.events.count()
    events_count.short_description = 'Events'


class WhatsAppSubmissionInline(admin.StackedInline):
    model = WhatsAppSubmission
    can_delete = False
    extra = 0
    verbose_name = "Private WhatsApp Submission Inspection"
    verbose_name_plural = "Private WhatsApp Submission Inspection"
    fields = [
        'submitted_by',
        'public_permission_confirmed',
        'original_message_display',
        'original_poster_preview',
        'created_at'
    ]
    readonly_fields = [
        'submitted_by',
        'public_permission_confirmed',
        'original_message_display',
        'original_poster_preview',
        'created_at'
    ]

    def has_add_permission(self, request, obj=None):
        return False

    def original_message_display(self, obj):
        if not obj or not obj.original_message:
            return "No raw text available."
        return format_html("<pre style='white-space: pre-wrap; background: #f8f9fa; padding: 10px; border-radius: 4px; max-height: 250px; overflow-y: auto;'>{}</pre>", obj.original_message)
    original_message_display.short_description = "Original WhatsApp Text (Private)"

    def original_poster_preview(self, obj):
        if obj and obj.original_poster:
            return format_html(
                "<a href='{}' target='_blank'><img src='{}' style='max-height: 160px; border-radius: 6px; box-shadow: 0 2px 4px rgba(0,0,0,0.1);' /></a><br><small>Click to view full size</small>",
                obj.original_poster.url,
                obj.original_poster.url
            )
        return "No flyer uploaded."
    original_poster_preview.short_description = "Original WhatsApp Flyer (Private)"


@admin.register(Event)
class EventAdmin(admin.ModelAdmin):
    form = EventAdminForm
    list_display = [
        'title',
        'category',
        'city',
        'start_datetime',
        'source_type_badge',
        'review_status_badge',
        'event_status_badge',
        'submitted_by',
        'reviewed_by',
        'reviewed_at'
    ]
    list_filter = [
        'review_status',
        'source_type',
        'event_status',
        'category',
        'city',
        'is_free',
        'created_at'
    ]
    search_fields = [
        'title',
        'description',
        'city',
        'area',
        'venue_name',
        'organizer_display_name',
        'submitted_by__username',
        'submitted_by__email'
    ]
    readonly_fields = [
        'slug',
        'submitted_by',
        'source_type',
        'created_at',
        'updated_at',
        'reviewed_by',
        'reviewed_at',
        'public_preview_button',
    ]
    inlines = [WhatsAppSubmissionInline]
    date_hierarchy = 'start_datetime'
    actions = [
        'approve_selected_events',
        'request_correction_selected_events',
        'reject_selected_events',
        'mark_as_cancelled'
    ]

    fieldsets = [
        ("Moderation Decision & Feedback", {
            'fields': [
                'review_status',
                'reviewer_feedback',
                'reviewed_by',
                'reviewed_at',
                'event_status',
                'public_preview_button'
            ],
            'description': "Review the event submission. Only approved events appear in the public discovery feed."
        }),
        ("Core Event Details", {
            'fields': [
                'title',
                'slug',
                'category',
                'intended_audience',
                'description',
                'poster',
            ]
        }),
        ("Location & Timing", {
            'fields': [
                'start_datetime',
                'end_datetime',
                'city',
                'area',
                'venue_name',
                'address',
            ]
        }),
        ("Organizer & External Registration", {
            'fields': [
                'organizer_display_name',
                'submitted_by',
                'is_free',
                'price',
                'registration_url',
                'registration_deadline',
                'source_type',
                'original_source_url',
                'created_at',
                'updated_at',
            ]
        }),
    ]

    def changeform_view(self, request, object_id=None, form_url='', extra_context=None):
        if request.method == 'POST' and '_moderate_action' in request.POST and object_id:
            if not (request.user.is_authenticated and request.user.is_staff and request.user.has_perm('events.change_event')):
                raise PermissionDenied("You do not have permission to moderate events.")

            event = get_object_or_404(Event, pk=object_id)
            action_type = request.POST.get('_moderate_action')
            feedback = (request.POST.get('moderation_feedback') or request.POST.get('reviewer_feedback') or '').strip()

            if action_type in ('rejected', 'correction') and not feedback:
                messages.error(request, "Reviewer feedback is required when rejecting or requesting correction.")
                return HttpResponseRedirect(request.path)

            try:
                apply_event_moderation(Event.objects.filter(pk=event.pk), request.user, action_type, feedback)
                action_verbs = {
                    'approved': 'approved and published',
                    'rejected': 'rejected',
                    'correction': 'marked as needing correction'
                }
                messages.success(
                    request,
                    f"Event '{event.title}' successfully {action_verbs.get(action_type, action_type)} (1 event affected)."
                )
                return HttpResponseRedirect(reverse('admin:events_event_changelist') + '?review_status__exact=pending')
            except ValidationError as e:
                messages.error(request, str(e))
                return HttpResponseRedirect(request.path)

        return super().changeform_view(request, object_id, form_url, extra_context)

    def save_model(self, request, obj, form, change):
        # Auto-track reviewer and review timestamp when status or feedback is modified by staff
        if 'review_status' in form.changed_data or 'reviewer_feedback' in form.changed_data:
            obj.reviewed_by = request.user
            obj.reviewed_at = timezone.now()
        super().save_model(request, obj, form, change)

    def public_preview_button(self, obj):
        if obj.pk and obj.slug:
            url = reverse('events:event_preview', kwargs={'slug': obj.slug})
            return format_html("<a class='button' href='{}' target='_blank' style='background: #0d6efd; color: white; padding: 6px 12px; border-radius: 4px; text-decoration: none;'>View Submission Preview</a>", url)
        return "-"
    public_preview_button.short_description = "Preview Submission"

    def source_type_badge(self, obj):
        colors = {
            'organizer': '#0d6efd',
            'whatsapp': '#25D366',
            'external': '#6c757d'
        }
        color = colors.get(obj.source_type, '#6c757d')
        return format_html(
            "<span style='background-color: {}; color: white; padding: 3px 8px; border-radius: 4px; font-size: 11px; font-weight: 600;'>{}</span>",
            color,
            obj.get_source_type_display()
        )
    source_type_badge.short_description = "Source"

    def review_status_badge(self, obj):
        colors = {
            'approved': '#198754',
            'pending': '#ffc107',
            'correction': '#fd7e14',
            'rejected': '#dc3545',
            'draft': '#6c757d'
        }
        text_colors = {
            'pending': '#000',
        }
        color = colors.get(obj.review_status, '#6c757d')
        text_color = text_colors.get(obj.review_status, '#fff')
        return format_html(
            "<span style='background-color: {}; color: {}; padding: 3px 8px; border-radius: 4px; font-size: 11px; font-weight: 600;'>{}</span>",
            color,
            text_color,
            obj.get_review_status_display()
        )
    review_status_badge.short_description = "Review Status"

    def event_status_badge(self, obj):
        if obj.event_status == 'cancelled':
            return format_html("<span style='background-color: #dc3545; color: white; padding: 3px 8px; border-radius: 4px; font-size: 11px;'>{}</span>", "Cancelled")
        return format_html("<span style='background-color: #0dcaf0; color: #000; padding: 3px 8px; border-radius: 4px; font-size: 11px;'>{}</span>", "Scheduled")
    event_status_badge.short_description = "Event Status"

    @admin.action(description="Approve selected events")
    def approve_selected_events(self, request, queryset):
        if not (request.user.is_authenticated and request.user.is_staff and request.user.has_perm('events.change_event')):
            raise PermissionDenied("You do not have permission to moderate events.")

        if request.POST.get('confirmed') == 'yes':
            feedback = request.POST.get('reviewer_feedback', '').strip()
            count = apply_event_moderation(queryset, request.user, 'approved', feedback)
            self.message_user(request, f"Successfully approved {count} event(s).", messages.SUCCESS)
            return HttpResponseRedirect(request.get_full_path())

        return render(request, 'admin/events/event/confirm_bulk_moderation.html', {
            'title': "Confirm Bulk Approval",
            'action': 'approve_selected_events',
            'action_type': 'approved',
            'action_title': "Confirm Bulk Approval",
            'events': queryset,
            'requires_feedback': False,
            'opts': self.model._meta,
            'media': self.media,
        })

    @admin.action(description="Request correction for selected events")
    def request_correction_selected_events(self, request, queryset):
        if not (request.user.is_authenticated and request.user.is_staff and request.user.has_perm('events.change_event')):
            raise PermissionDenied("You do not have permission to moderate events.")

        if request.POST.get('confirmed') == 'yes':
            feedback = request.POST.get('reviewer_feedback', '').strip()
            if not feedback:
                self.message_user(request, "Reviewer feedback is required when requesting correction for events.", messages.ERROR)
                return render(request, 'admin/events/event/confirm_bulk_moderation.html', {
                    'title': "Confirm Request Correction",
                    'action': 'request_correction_selected_events',
                    'action_type': 'correction',
                    'action_title': "Confirm Request Correction",
                    'events': queryset,
                    'requires_feedback': True,
                    'opts': self.model._meta,
                    'media': self.media,
                })

            count = apply_event_moderation(queryset, request.user, 'correction', feedback)
            self.message_user(request, f"Successfully requested correction for {count} event(s).", messages.SUCCESS)
            return HttpResponseRedirect(request.get_full_path())

        return render(request, 'admin/events/event/confirm_bulk_moderation.html', {
            'title': "Confirm Request Correction",
            'action': 'request_correction_selected_events',
            'action_type': 'correction',
            'action_title': "Confirm Request Correction",
            'events': queryset,
            'requires_feedback': True,
            'opts': self.model._meta,
            'media': self.media,
        })

    @admin.action(description="Reject selected events")
    def reject_selected_events(self, request, queryset):
        if not (request.user.is_authenticated and request.user.is_staff and request.user.has_perm('events.change_event')):
            raise PermissionDenied("You do not have permission to moderate events.")

        if request.POST.get('confirmed') == 'yes':
            feedback = request.POST.get('reviewer_feedback', '').strip()
            if not feedback:
                self.message_user(request, "Reviewer feedback is required when rejecting events.", messages.ERROR)
                return render(request, 'admin/events/event/confirm_bulk_moderation.html', {
                    'title': "Confirm Bulk Rejection",
                    'action': 'reject_selected_events',
                    'action_type': 'rejected',
                    'action_title': "Confirm Bulk Rejection",
                    'events': queryset,
                    'requires_feedback': True,
                    'opts': self.model._meta,
                    'media': self.media,
                })

            count = apply_event_moderation(queryset, request.user, 'rejected', feedback)
            self.message_user(request, f"Successfully rejected {count} event(s).", messages.SUCCESS)
            return HttpResponseRedirect(request.get_full_path())

        return render(request, 'admin/events/event/confirm_bulk_moderation.html', {
            'title': "Confirm Bulk Rejection",
            'action': 'reject_selected_events',
            'action_type': 'rejected',
            'action_title': "Confirm Bulk Rejection",
            'events': queryset,
            'requires_feedback': True,
            'opts': self.model._meta,
            'media': self.media,
        })

    @admin.action(description="Mark selected events as Cancelled")
    def mark_as_cancelled(self, request, queryset):
        updated = queryset.update(event_status='cancelled')
        self.message_user(request, f"{updated} event(s) marked as cancelled.")


@admin.register(WhatsAppSubmission)
class WhatsAppSubmissionAdmin(admin.ModelAdmin):
    list_display = ['event', 'submitted_by', 'public_permission_confirmed', 'created_at']
    list_filter = ['public_permission_confirmed', 'created_at']
    search_fields = ['event__title', 'submitted_by__username', 'original_message']
    readonly_fields = ['event', 'submitted_by', 'public_permission_confirmed', 'original_message', 'created_at']

    def has_add_permission(self, request):
        return False

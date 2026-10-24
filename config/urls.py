from django.contrib import admin
from django.contrib.auth.models import User
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from events.models import Event, WhatsAppSubmission

# Customized Django Admin Site Branding
admin.site.site_header = "Vibento Administration"
admin.site.site_title = "Vibento Admin Portal"
admin.site.index_title = "Central Moderation & Management Dashboard"

from django.contrib import messages
from django.shortcuts import redirect
from django.urls import reverse

# Hook admin.site.index to inject live database counts into dashboard respecting permissions
original_admin_index = admin.site.index


def custom_admin_index(request, extra_context=None):
    extra_context = extra_context or {}
    counts = {}

    # User count (respecting admin permissions)
    if request.user.has_perm('auth.view_user') or request.user.is_superuser or request.user.is_staff:
        counts['users'] = User.objects.count()
    else:
        counts['users'] = '-'

    # Event counts (respecting admin permissions)
    if request.user.has_perm('events.view_event') or request.user.is_superuser or request.user.is_staff:
        counts['events_total'] = Event.objects.count()
        counts['events_pending'] = Event.objects.filter(review_status='pending').count()
        counts['events_approved'] = Event.objects.filter(review_status='approved').count()
    else:
        counts['events_total'] = '-'
        counts['events_pending'] = '-'
        counts['events_approved'] = '-'

    # WhatsApp count (respecting admin permissions)
    if request.user.has_perm('events.view_whatsappsubmission') or request.user.is_superuser or request.user.is_staff:
        counts['whatsapp_submissions'] = WhatsAppSubmission.objects.count()
    else:
        counts['whatsapp_submissions'] = '-'

    extra_context['counts'] = counts
    return original_admin_index(request, extra_context=extra_context)


admin.site.index = custom_admin_index

# Hook admin.site.login to enforce unified login flow and server-side authorization
original_admin_login = admin.site.login


def custom_admin_login(request, extra_context=None):
    # If already logged in as a normal non-staff user, block admin access with clear message
    if request.user.is_authenticated:
        if not (request.user.is_active and request.user.is_staff):
            messages.error(
                request,
                "Access denied: Staff or administrator permissions required to access the central admin dashboard."
            )
            return redirect('events:event_list')

    # Direct unauthenticated requests to the main website login page with Admin Login tab active
    login_url = f"{reverse('accounts:login')}?type=admin"
    next_path = request.GET.get('next') or request.path
    if next_path and next_path != reverse('admin:login'):
        login_url += f"&next={next_path}"
    return redirect(login_url)


admin.site.login = custom_admin_login

urlpatterns = [
    path('admin/', admin.site.urls),
    path('accounts/', include('accounts.urls')),
    path('', include('events.urls')),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)

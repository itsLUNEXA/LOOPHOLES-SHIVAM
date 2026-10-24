from django.urls import path
from . import views

app_name = 'events'

urlpatterns = [
    path('', views.landing_page, name='landing'),
    path('events/', views.event_list, name='event_list'),
    path('dashboard/', views.user_dashboard, name='user_dashboard'),
    path('organizer/dashboard/', views.organizer_dashboard, name='organizer_dashboard'),
    path('events/create/', views.event_create, name='event_create'),
    path('events/submit-whatsapp/', views.whatsapp_submission_create, name='whatsapp_submission'),
    path('events/<slug:slug>/', views.event_detail, name='event_detail'),
    path('events/<slug:slug>/enroll/', views.event_enroll, name='event_enroll'),
    path('events/<slug:slug>/preview/', views.event_preview, name='event_preview'),
    path('events/<slug:slug>/edit/', views.event_edit, name='event_edit'),
    path('events/<slug:slug>/cancel/', views.event_cancel, name='event_cancel'),
    path('api/sync-status/', views.sync_status_api, name='sync_status_api'),
]

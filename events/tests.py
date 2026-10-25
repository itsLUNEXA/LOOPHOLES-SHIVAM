from datetime import timedelta
from unittest.mock import patch
from django.test import TestCase, Client
from django.contrib.auth.models import User
from django.utils import timezone
from django.urls import reverse
from .models import Category, Event, WhatsAppSubmission, EventSource, SyncRunHistory, EventEnrollment
from .services import trigger_visitor_entry_refresh, execute_source_sync, get_sync_status_summary


class EventManagementAndDiscoveryTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.now = timezone.now()

        # Users
        self.admin = User.objects.create_superuser(username='admin', email='admin@test.com', password='AdminPassword123!')
        self.owner = User.objects.create_user(username='eventowner', email='owner@test.com', password='OwnerPassword123!')
        self.other_user = User.objects.create_user(username='otheruser', email='other@test.com', password='OtherPassword123!')

        # Categories
        self.cat_tech = Category.objects.create(name='Tech & AI', slug='tech-ai')
        self.cat_music = Category.objects.create(name='Live Music', slug='live-music')

        # Approved Event (Public)
        self.approved_event = Event.objects.create(
            title="Bangalore Tech Summit Meetup",
            category=self.cat_tech,
            intended_audience="Developers & Tech Enthusiasts",
            description="Discussion on distributed systems and vector databases.",
            start_datetime=self.now + timedelta(days=2),
            end_datetime=self.now + timedelta(days=2, hours=3),
            city="Bengaluru",
            area="Indiranagar",
            venue_name="Hub 101",
            address="100ft Rd, Indiranagar",
            organizer_display_name="Tech Collective",
            submitted_by=self.owner,
            is_free=True,
            registration_url="https://example.com/register",
            source_type="organizer",
            review_status="approved",
            event_status="scheduled",
            reviewed_by=self.admin,
            reviewed_at=self.now
        )

        # Pending Event (Private/Moderation)
        self.pending_event = Event.objects.create(
            title="Secret Draft Robotics Session",
            category=self.cat_tech,
            intended_audience="All Audiences",
            description="Under review robotics demonstration.",
            start_datetime=self.now + timedelta(days=5),
            end_datetime=self.now + timedelta(days=5, hours=2),
            city="Bengaluru",
            area="Koramangala",
            venue_name="Robo Lab",
            address="Koramangala 5th Block",
            organizer_display_name="Robo Guild",
            submitted_by=self.owner,
            is_free=True,
            source_type="organizer",
            review_status="pending",
            event_status="scheduled"
        )

    def test_standard_event_submission(self):
        """Test authenticated organizer submitting an event."""
        self.client.login(username='eventowner', password='OwnerPassword123!')
        create_url = reverse('events:event_create')

        payload = {
            'title': 'New Indie Music Jam',
            'category': self.cat_music.id,
            'intended_audience': 'All Audiences',
            'description': 'Acoustic evening with local musicians.',
            'start_datetime': (self.now + timedelta(days=3)).strftime('%Y-%m-%dT%H:%M'),
            'end_datetime': (self.now + timedelta(days=3, hours=2)).strftime('%Y-%m-%dT%H:%M'),
            'city': 'Mumbai',
            'area': 'Bandra',
            'venue_name': 'Cafe Music',
            'address': 'Carter Road',
            'organizer_display_name': 'Bandra Beats',
            'is_free': 'on',
            'registration_url': 'https://example.com/rsvp',
        }

        response = self.client.post(create_url, payload, follow=True)
        self.assertEqual(response.status_code, 200)

        new_event = Event.objects.get(title='New Indie Music Jam')
        self.assertEqual(new_event.submitted_by, self.owner)
        self.assertEqual(new_event.source_type, 'organizer')
        self.assertEqual(new_event.review_status, 'pending')
        self.assertEqual(new_event.event_status, 'scheduled')

    def test_whatsapp_submission_requires_permission(self):
        """Test manual WhatsApp submission requires explicit permission confirmation."""
        self.client.login(username='eventowner', password='OwnerPassword123!')
        whatsapp_url = reverse('events:whatsapp_submission')

        # Attempt submission without permission checkbox
        payload_no_permission = {
            'original_message': 'Hey guys, pottery session this Sunday in Koramangala!',
            'title': 'Pottery Sunday Workshop',
            'category': self.cat_tech.id,
            'intended_audience': 'All Audiences',
            'description': 'Clay hand-building session.',
            'start_datetime': (self.now + timedelta(days=4)).strftime('%Y-%m-%dT%H:%M'),
            'end_datetime': (self.now + timedelta(days=4, hours=2)).strftime('%Y-%m-%dT%H:%M'),
            'city': 'Bengaluru',
            'area': 'Koramangala',
            'venue_name': 'Clay House',
            'organizer_display_name': 'Pottery Club',
            'is_free': 'on',
            # 'public_permission_confirmed' is omitted
        }
        res_fail = self.client.post(whatsapp_url, payload_no_permission)
        self.assertEqual(res_fail.status_code, 200)
        self.assertFalse(Event.objects.filter(title='Pottery Sunday Workshop').exists())

        # Now submit with permission confirmation checked
        payload_with_permission = payload_no_permission.copy()
        payload_with_permission['public_permission_confirmed'] = 'on'
        res_success = self.client.post(whatsapp_url, payload_with_permission, follow=True)
        self.assertEqual(res_success.status_code, 200)

        wa_event = Event.objects.get(title='Pottery Sunday Workshop')
        self.assertEqual(wa_event.source_type, 'whatsapp')
        self.assertEqual(wa_event.review_status, 'pending')

        # Verify WhatsAppSubmission record created and private to submitter
        wa_record = WhatsAppSubmission.objects.get(event=wa_event)
        self.assertEqual(wa_record.submitted_by, self.owner)
        self.assertTrue(wa_record.public_permission_confirmed)
        self.assertIn('pottery session this Sunday', wa_record.original_message)

    def test_unapproved_event_visibility_restrictions(self):
        """Test unapproved events are excluded from public catalog and detail views."""
        list_url = reverse('events:event_list')
        response = self.client.get(list_url)
        self.assertContains(response, "Bangalore Tech Summit Meetup")
        self.assertNotContains(response, "Secret Draft Robotics Session")

        # Public detail URL for pending event returns 404 for anonymous users
        detail_url = reverse('events:event_detail', kwargs={'slug': self.pending_event.slug})
        detail_res = self.client.get(detail_url)
        self.assertEqual(detail_res.status_code, 404)

        # But submitter accessing it is redirected to the preview view
        self.client.login(username='eventowner', password='OwnerPassword123!')
        owner_res = self.client.get(detail_url, follow=True)
        self.assertEqual(owner_res.status_code, 200)
        self.assertContains(owner_res, "Organizer & Moderator Preview Mode")
        self.assertContains(owner_res, "Secret Draft Robotics Session")

    def test_owner_only_editing(self):
        """Test non-owners cannot edit another user's event."""
        edit_url = reverse('events:event_edit', kwargs={'slug': self.approved_event.slug})

        # Other user tries to edit
        self.client.login(username='otheruser', password='OtherPassword123!')
        unauthorized_res = self.client.get(edit_url)
        self.assertEqual(unauthorized_res.status_code, 403)

        # Owner can access edit form
        self.client.login(username='eventowner', password='OwnerPassword123!')
        owner_res = self.client.get(edit_url)
        self.assertEqual(owner_res.status_code, 200)

    def test_edits_do_not_reset_admin_approval(self):
        """Test rule: editing an approved event does NOT reset admin's approval back to pending."""
        self.client.login(username='eventowner', password='OwnerPassword123!')
        edit_url = reverse('events:event_edit', kwargs={'slug': self.approved_event.slug})

        update_payload = {
            'title': 'Bangalore Tech Summit Meetup (Updated)',
            'category': self.cat_tech.id,
            'intended_audience': 'Developers & Tech Enthusiasts',
            'description': 'Updated description with new speakers and agenda.',
            'start_datetime': (self.now + timedelta(days=2)).strftime('%Y-%m-%dT%H:%M'),
            'end_datetime': (self.now + timedelta(days=2, hours=4)).strftime('%Y-%m-%dT%H:%M'),
            'city': 'Bengaluru',
            'area': 'Indiranagar',
            'venue_name': 'Hub 101 Main Stage',
            'address': '100ft Rd',
            'organizer_display_name': 'Tech Collective',
            'is_free': 'on',
        }

        response = self.client.post(edit_url, update_payload, follow=True)
        self.assertEqual(response.status_code, 200)

        self.approved_event.refresh_from_db()
        self.assertEqual(self.approved_event.title, 'Bangalore Tech Summit Meetup (Updated)')
        # Admin approval must NOT be reset to pending!
        self.assertEqual(self.approved_event.review_status, 'approved')
        self.assertEqual(self.approved_event.reviewed_by, self.admin)

        # Remains visible in public discovery
        list_res = self.client.get(reverse('events:event_list'))
        self.assertContains(list_res, 'Bangalore Tech Summit Meetup (Updated)')

    def test_admin_approval_action(self):
        """Test admin approving an event marks it approved and sets reviewer."""
        self.assertEqual(self.pending_event.review_status, 'pending')

        # Use Django admin action simulation or model method
        self.pending_event.review_status = 'approved'
        self.pending_event.reviewed_by = self.admin
        self.pending_event.reviewed_at = timezone.now()
        self.pending_event.save()

        # Event is now visible publicly
        list_res = self.client.get(reverse('events:event_list'))
        self.assertContains(list_res, "Secret Draft Robotics Session")

    def test_event_cancellation_behavior(self):
        """Test marking event as cancelled disables registration and removes from active discovery."""
        self.client.login(username='eventowner', password='OwnerPassword123!')
        cancel_url = reverse('events:event_cancel', kwargs={'slug': self.approved_event.slug})

        # Confirm cancellation
        cancel_res = self.client.post(cancel_url, follow=True)
        self.assertEqual(cancel_res.status_code, 200)

        self.approved_event.refresh_from_db()
        self.assertEqual(self.approved_event.event_status, 'cancelled')

        # Does not appear in active discovery listing
        list_res = self.client.get(reverse('events:event_list'))
        self.assertNotContains(list_res, "Bangalore Tech Summit Meetup")

        # Detail page displays clear cancelled status and inactive registration
        detail_url = reverse('events:event_detail', kwargs={'slug': self.approved_event.slug})
        detail_res = self.client.get(detail_url)
        self.assertEqual(detail_res.status_code, 200)
        self.assertContains(detail_res, "This Event Has Been Cancelled")
        self.assertContains(detail_res, "Event Cancelled")

    def test_search_and_filtering(self):
        """Test keyword search and category/city filtering."""
        list_url = reverse('events:event_list')

        # Search matching
        res_search = self.client.get(list_url, {'q': 'Tech Summit'})
        self.assertContains(res_search, "Bangalore Tech Summit Meetup")

        # Search non-matching
        res_nomatch = self.client.get(list_url, {'q': 'Pottery Cooking Night'})
        self.assertContains(res_nomatch, "No approved events match your criteria")

        # Category filter
        res_cat = self.client.get(list_url, {'category': self.cat_tech.slug})
        self.assertContains(res_cat, "Bangalore Tech Summit Meetup")

        res_cat_empty = self.client.get(list_url, {'category': self.cat_music.slug})
        self.assertNotContains(res_cat_empty, "Bangalore Tech Summit Meetup")

        # City filter
        res_city = self.client.get(list_url, {'city': 'Bengaluru'})
        self.assertContains(res_city, "Bangalore Tech Summit Meetup")

        res_city_other = self.client.get(list_url, {'city': 'Delhi'})
        self.assertNotContains(res_city_other, "Bangalore Tech Summit Meetup")


class EventModerationControlsTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.now = timezone.now()

        # Admin user with full staff and superuser permissions
        self.admin = User.objects.create_superuser(
            username='admin_moderator',
            email='mod@vibento.local',
            password='ModPassword123!'
        )

        # Normal user with no staff permissions
        self.normal_user = User.objects.create_user(
            username='regular_user',
            email='user@vibento.local',
            password='UserPassword123!'
        )

        self.category = Category.objects.create(name='Technology', slug='tech')

        self.pending_event = Event.objects.create(
            title="AI Developers Meetup",
            category=self.category,
            intended_audience="Engineers",
            description="Deep dive into modern LLMs.",
            start_datetime=self.now + timedelta(days=3),
            end_datetime=self.now + timedelta(days=3, hours=2),
            city="Bengaluru",
            area="Koramangala",
            venue_name="Innovate Hub",
            address="123 Tech Park",
            organizer_display_name="AI Society",
            submitted_by=self.normal_user,
            review_status="pending",
            event_status="scheduled"
        )

        self.cancelled_event = Event.objects.create(
            title="Cancelled Indie Fest",
            category=self.category,
            intended_audience="All Audiences",
            description="Cancelled due to venue maintenance.",
            start_datetime=self.now + timedelta(days=4),
            end_datetime=self.now + timedelta(days=4, hours=3),
            city="Bengaluru",
            area="Indiranagar",
            venue_name="Old Hall",
            address="456 Main Rd",
            organizer_display_name="Indie Team",
            submitted_by=self.normal_user,
            review_status="pending",
            event_status="cancelled"
        )

    def test_apply_event_moderation_shared_function(self):
        """Test shared apply_event_moderation helper updates reviewer, time, and feedback."""
        from .admin import apply_event_moderation

        count = apply_event_moderation(
            queryset=Event.objects.filter(pk=self.pending_event.pk),
            reviewer=self.admin,
            action_type="approved",
            feedback="Looks great, verified venue."
        )
        self.assertEqual(count, 1)

        self.pending_event.refresh_from_db()
        self.assertEqual(self.pending_event.review_status, 'approved')
        self.assertEqual(self.pending_event.reviewed_by, self.admin)
        self.assertIsNotNone(self.pending_event.reviewed_at)
        self.assertEqual(self.pending_event.reviewer_feedback, "Looks great, verified venue.")
        # Ensure submitter and event_status are unchanged
        self.assertEqual(self.pending_event.submitted_by, self.normal_user)
        self.assertEqual(self.pending_event.event_status, 'scheduled')

    def test_rejection_requires_feedback(self):
        """Test that rejecting an event requires feedback."""
        from django.core.exceptions import ValidationError
        from .admin import apply_event_moderation

        with self.assertRaises(ValidationError):
            apply_event_moderation(
                queryset=Event.objects.filter(pk=self.pending_event.pk),
                reviewer=self.admin,
                action_type="rejected",
                feedback=""
            )

        # With feedback, rejection succeeds
        count = apply_event_moderation(
            queryset=Event.objects.filter(pk=self.pending_event.pk),
            reviewer=self.admin,
            action_type="rejected",
            feedback="Duplicate listing of previous event."
        )
        self.assertEqual(count, 1)
        self.pending_event.refresh_from_db()
        self.assertEqual(self.pending_event.review_status, 'rejected')
        self.assertEqual(self.pending_event.reviewer_feedback, "Duplicate listing of previous event.")

    def test_correction_request_requires_feedback(self):
        """Test that requesting correction requires feedback."""
        from django.core.exceptions import ValidationError
        from .admin import apply_event_moderation

        with self.assertRaises(ValidationError):
            apply_event_moderation(
                queryset=Event.objects.filter(pk=self.pending_event.pk),
                reviewer=self.admin,
                action_type="correction",
                feedback="   "
            )

        # With feedback, correction succeeds
        count = apply_event_moderation(
            queryset=Event.objects.filter(pk=self.pending_event.pk),
            reviewer=self.admin,
            action_type="correction",
            feedback="Please add precise address and ticket pricing info."
        )
        self.assertEqual(count, 1)
        self.pending_event.refresh_from_db()
        self.assertEqual(self.pending_event.review_status, 'correction')
        self.assertEqual(self.pending_event.reviewer_feedback, "Please add precise address and ticket pricing info.")

    def test_authorized_individual_approval_via_admin_post(self):
        """Test admin approving an event from the change form via POST."""
        self.client.login(username='admin_moderator', password='ModPassword123!')
        change_url = reverse('admin:events_event_change', args=[self.pending_event.pk])

        post_data = {
            '_moderate_action': 'approved',
            'reviewer_feedback': 'Approved after checking venue.',
        }

        response = self.client.post(change_url, post_data, follow=True)
        self.assertEqual(response.status_code, 200)

        self.pending_event.refresh_from_db()
        self.assertEqual(self.pending_event.review_status, 'approved')
        self.assertEqual(self.pending_event.reviewed_by, self.admin)
        self.assertIsNotNone(self.pending_event.reviewed_at)

    def test_unauthorized_moderation_blocked(self):
        """Test non-staff user cannot access admin changeform or moderate."""
        self.client.login(username='regular_user', password='UserPassword123!')
        change_url = reverse('admin:events_event_change', args=[self.pending_event.pk])

        # Regular user GET is redirected or rejected by admin portal
        response = self.client.get(change_url)
        self.assertIn(response.status_code, [302, 403])

        # Regular user POST does not modify review_status
        post_response = self.client.post(change_url, {'_moderate_action': 'approved'})
        self.assertIn(post_response.status_code, [302, 403])

        self.pending_event.refresh_from_db()
        self.assertEqual(self.pending_event.review_status, 'pending')

    def test_get_request_never_approves_event(self):
        """Ensure state-changing moderation can never be triggered via GET."""
        self.client.login(username='admin_moderator', password='ModPassword123!')
        change_url = reverse('admin:events_event_change', args=[self.pending_event.pk])

        # GET with moderation param should only display form, not approve
        self.client.get(change_url, {'_moderate_action': 'approved'})

        self.pending_event.refresh_from_db()
        self.assertEqual(self.pending_event.review_status, 'pending')

    def test_pending_list_behavior_after_approval(self):
        """Test that after approval, event disappears from pending changelist filter."""
        self.client.login(username='admin_moderator', password='ModPassword123!')
        pending_list_url = reverse('admin:events_event_changelist') + '?review_status__exact=pending'

        # Before approval: present in pending list
        res_before = self.client.get(pending_list_url)
        self.assertContains(res_before, "AI Developers Meetup")

        # Admin approves event
        change_url = reverse('admin:events_event_change', args=[self.pending_event.pk])
        self.client.post(change_url, {'_moderate_action': 'approved'}, follow=True)

        # After approval: no longer present in pending list
        res_after = self.client.get(pending_list_url)
        self.assertNotContains(res_after, "AI Developers Meetup")

    def test_approved_event_public_visibility(self):
        """Test approved, upcoming, non-cancelled event appears publicly."""
        public_list_url = reverse('events:event_list')

        # Initially pending: not visible publicly
        res_before = self.client.get(public_list_url)
        self.assertNotContains(res_before, "AI Developers Meetup")

        # Approve event
        from .admin import apply_event_moderation
        apply_event_moderation(Event.objects.filter(pk=self.pending_event.pk), self.admin, "approved")

        # Now visible publicly
        res_after = self.client.get(public_list_url)
        self.assertContains(res_after, "AI Developers Meetup")

    def test_approval_must_not_clear_cancellation_status(self):
        """Rule: approval must not clear a cancellation status (event_status stays 'cancelled')."""
        self.assertEqual(self.cancelled_event.event_status, 'cancelled')
        self.assertEqual(self.cancelled_event.review_status, 'pending')

        from .admin import apply_event_moderation
        apply_event_moderation(Event.objects.filter(pk=self.cancelled_event.pk), self.admin, "approved")

        self.cancelled_event.refresh_from_db()
        self.assertEqual(self.cancelled_event.review_status, 'approved')
        # Crucial: event_status MUST remain 'cancelled'
        self.assertEqual(self.cancelled_event.event_status, 'cancelled')

        # And because it is cancelled, it should not appear on public discovery
        public_list = self.client.get(reverse('events:event_list'))
        self.assertNotContains(public_list, "Cancelled Indie Fest")

    def test_bulk_moderation_flow(self):
        """Test bulk moderation actions via admin changelist."""
        self.client.login(username='admin_moderator', password='ModPassword123!')
        changelist_url = reverse('admin:events_event_changelist')

        # 1. Bulk approve step 1: confirmation page rendered
        data_step1 = {
            'action': 'approve_selected_events',
            '_selected_action': [self.pending_event.pk],
        }
        res_step1 = self.client.post(changelist_url, data_step1)
        self.assertEqual(res_step1.status_code, 200)
        self.assertContains(res_step1, "Confirm Bulk Approval")

        # 2. Bulk approve step 2: post confirmation
        data_step2 = {
            'action': 'approve_selected_events',
            '_selected_action': [self.pending_event.pk],
            'confirmed': 'yes',
            'action_type': 'approved',
            'reviewer_feedback': 'Approved in bulk.',
        }
        res_step2 = self.client.post(changelist_url, data_step2, follow=True)
        self.assertEqual(res_step2.status_code, 200)

        self.pending_event.refresh_from_db()
        self.assertEqual(self.pending_event.review_status, 'approved')
        self.assertEqual(self.pending_event.reviewed_by, self.admin)
        self.assertEqual(self.pending_event.reviewer_feedback, 'Approved in bulk.')


from unittest.mock import patch, MagicMock
import json
import urllib.error
from django.test import override_settings


class TinyFishEventSyncTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.now = timezone.now()

        # Admin user with staff & change permissions
        self.admin = User.objects.create_superuser(
            username='admin_sync',
            email='admin_sync@vibento.local',
            password='AdminSyncPass123!'
        )

        # Normal non-staff user
        self.normal_user = User.objects.create_user(
            username='regular_sync_user',
            email='user_sync@vibento.local',
            password='UserSyncPass123!'
        )

        self.category = Category.objects.create(name='Technology', slug='technology')
        self.sync_url = reverse('admin:events_event_sync')
        self.source_url = "https://example-community.org/events"

    @override_settings(
        TINYFISH_API_KEY='sk-test-tinyfish-key-12345',
        TINYFISH_ALLOWED_SOURCE_URL='https://example-community.org/events',
        TINYFISH_ALLOWED_SOURCES=['https://example-community.org/events']
    )
    def test_authorized_admin_can_access_and_start_sync(self):
        """Test authorized staff admin can view sync page and trigger sync via POST."""
        self.client.login(username='admin_sync', password='AdminSyncPass123!')

        # 1. GET page
        get_res = self.client.get(self.sync_url)
        self.assertEqual(get_res.status_code, 200)
        self.assertContains(get_res, "TinyFish Event Synchronization")
        self.assertContains(get_res, self.source_url)

        # 2. POST to sync with mocked response
        mock_response = MagicMock()
        mock_response.getcode.return_value = 200
        mock_response.read.return_value = json.dumps({
            "status": "COMPLETED",
            "run_id": "run_test_123",
            "result": {
                "events": [
                    {
                        "title": "Open Source Tech Meetup",
                        "description": "Collaborative coding and lightning talks.",
                        "start_datetime": (self.now + timedelta(days=5)).isoformat(),
                        "end_datetime": (self.now + timedelta(days=5, hours=2)).isoformat(),
                        "venue": "Open Lab",
                        "city": "Bengaluru",
                        "area": "Koramangala",
                        "address": "80 Feet Rd",
                        "organizer_name": "FOSS Community",
                        "category_hints": "Technology",
                        "intended_audience": "Developers & Tech Enthusiasts",
                        "is_free": True,
                        "original_event_page_url": "https://example-community.org/events/foss-meetup",
                    }
                ]
            }
        }).encode('utf-8')
        mock_response.__enter__.return_value = mock_response

        with patch('urllib.request.urlopen', return_value=mock_response):
            post_res = self.client.post(self.sync_url, {'action': 'sync_now'}, follow=True)
            self.assertEqual(post_res.status_code, 200)
            self.assertContains(post_res, "Open Source Tech Meetup")
            self.assertContains(post_res, "New Pending Created")

        created = Event.objects.filter(title="Open Source Tech Meetup").first()
        self.assertIsNotNone(created)
        self.assertEqual(created.review_status, 'pending')
        self.assertEqual(created.source_type, 'external')
        self.assertEqual(created.submitted_by, self.admin)
        self.assertIsNotNone(created.source_checked_at)

    def test_normal_users_cannot_start_sync(self):
        """Test non-staff user cannot access or trigger sync."""
        self.client.login(username='regular_sync_user', password='UserSyncPass123!')

        # GET is blocked (redirect or 403)
        get_res = self.client.get(self.sync_url)
        self.assertIn(get_res.status_code, [302, 403])

        # POST is blocked
        post_res = self.client.post(self.sync_url, {'action': 'sync_now'})
        self.assertIn(post_res.status_code, [302, 403])

    @patch('urllib.request.urlopen')
    def test_get_does_not_trigger_collection(self, mock_urlopen):
        """Test GET request to sync page displays config but NEVER triggers external API call."""
        self.client.login(username='admin_sync', password='AdminSyncPass123!')
        res = self.client.get(self.sync_url)
        self.assertEqual(res.status_code, 200)
        # Ensure urlopen was never called on GET
        mock_urlopen.assert_not_called()

    @override_settings(TINYFISH_API_KEY='', TINYFISH_ALLOWED_SOURCE_URL='')
    def test_missing_api_key_or_source_configuration(self):
        """Test missing credentials or source URL displays clear config message and blocks runs."""
        self.client.login(username='admin_sync', password='AdminSyncPass123!')

        get_res = self.client.get(self.sync_url)
        self.assertEqual(get_res.status_code, 200)
        self.assertContains(get_res, "Configuration Required")

        # POST without configuration
        post_res = self.client.post(self.sync_url, {'action': 'sync_now'}, follow=True)
        self.assertEqual(post_res.status_code, 200)
        self.assertContains(post_res, "Cannot start sync")

    @override_settings(
        TINYFISH_API_KEY='sk-test-tinyfish-key-12345',
        TINYFISH_ALLOWED_SOURCE_URL='https://example-community.org/events',
        TINYFISH_ALLOWED_SOURCES=['https://example-community.org/events']
    )
    def test_successful_import_creates_pending_non_public_events(self):
        """Test imported event enters pending review and is NOT visible in public catalog."""
        self.client.login(username='admin_sync', password='AdminSyncPass123!')

        mock_response = MagicMock()
        mock_response.getcode.return_value = 200
        mock_response.read.return_value = json.dumps({
            "status": "COMPLETED",
            "run_id": "run_test_456",
            "result": {
                "events": [
                    {
                        "title": "Private Draft Workshop",
                        "description": "Hands-on robotics session.",
                        "start_datetime": (self.now + timedelta(days=6)).isoformat(),
                        "venue": "Lab 2",
                        "city": "Bengaluru",
                        "area": "Indiranagar",
                        "original_event_page_url": "https://example-community.org/events/private-workshop",
                    }
                ]
            }
        }).encode('utf-8')
        mock_response.__enter__.return_value = mock_response

        with patch('urllib.request.urlopen', return_value=mock_response):
            self.client.post(self.sync_url, {'action': 'sync_now'}, follow=True)

        event = Event.objects.get(title="Private Draft Workshop")
        self.assertEqual(event.review_status, 'pending')
        self.assertFalse(event.is_active_public)

        # Anonymous user browsing public catalog cannot see it
        anon_client = Client()
        catalog_res = anon_client.get(reverse('events:event_list'))
        self.assertNotContains(catalog_res, "Private Draft Workshop")

    @override_settings(
        TINYFISH_API_KEY='sk-test-tinyfish-key-12345',
        TINYFISH_ALLOWED_SOURCE_URL='https://example-community.org/events',
        TINYFISH_ALLOWED_SOURCES=['https://example-community.org/events']
    )
    def test_reimport_does_not_create_duplicates(self):
        """Test repeated sync skips exact duplicates matching original URL or title+time."""
        self.client.login(username='admin_sync', password='AdminSyncPass123!')

        start_time = self.now + timedelta(days=7)
        mock_data = json.dumps({
            "status": "COMPLETED",
            "run_id": "run_test_dup",
            "result": {
                "events": [
                    {
                        "title": "AI Builders Hackathon",
                        "start_datetime": start_time.isoformat(),
                        "venue": "Innovation Hub",
                        "city": "Bengaluru",
                        "original_event_page_url": "https://example-community.org/events/ai-hackathon",
                    }
                ]
            }
        }).encode('utf-8')

        mock_response = MagicMock()
        mock_response.getcode.return_value = 200
        mock_response.read.return_value = mock_data
        mock_response.__enter__.return_value = mock_response

        # First sync: creates 1 event
        with patch('urllib.request.urlopen', return_value=mock_response):
            self.client.post(self.sync_url, {'action': 'sync_now'}, follow=True)
        self.assertEqual(Event.objects.filter(title="AI Builders Hackathon").count(), 1)

        # Second sync: skips duplicate creation
        with patch('urllib.request.urlopen', return_value=mock_response):
            res_second = self.client.post(self.sync_url, {'action': 'sync_now'}, follow=True)
            self.assertEqual(res_second.status_code, 200)
            self.assertContains(res_second, "Duplicates Skipped")

        self.assertEqual(Event.objects.filter(title="AI Builders Hackathon").count(), 1)

    @override_settings(
        TINYFISH_API_KEY='sk-test-tinyfish-key-12345',
        TINYFISH_ALLOWED_SOURCE_URL='https://example-community.org/events',
        TINYFISH_ALLOWED_SOURCES=['https://example-community.org/events']
    )
    def test_invalid_dates_and_missing_fields_skipped(self):
        """Test malformed dates, missing title, past events, and invalid URLs are rejected with reasons."""
        from .tinyfish import validate_and_import_events

        raw_records = [
            # 1. Missing title
            {"start_datetime": (self.now + timedelta(days=2)).isoformat(), "venue": "Hub", "city": "Bengaluru"},
            # 2. Malformed start date
            {"title": "Bad Date Meetup", "start_datetime": "2026-99-99-invalid", "venue": "Hub", "city": "Bengaluru"},
            # 3. Clearly past event
            {"title": "Past 2020 Summit", "start_datetime": "2020-01-01T10:00:00Z", "venue": "Hub", "city": "Bengaluru"},
            # 4. Invalid URL scheme
            {"title": "Bad Scheme Conf", "start_datetime": (self.now + timedelta(days=3)).isoformat(), "venue": "Hub", "city": "Bengaluru", "original_event_page_url": "ftp://bad-scheme.com"},
        ]

        summary = validate_and_import_events(raw_records, self.source_url, self.admin)
        self.assertEqual(summary['new_pending_created'], 0)
        self.assertEqual(summary['invalid_records_skipped'], 4)
        reasons = [item['reason'] for item in summary['invalid_records']]
        self.assertTrue(any("Missing required" in r for r in reasons))
        self.assertTrue(any("Malformed or ambiguous" in r for r in reasons))
        self.assertTrue(any("is in the past" in r for r in reasons))
        self.assertTrue(any("Invalid original event page URL scheme" in r for r in reasons))

    @override_settings(
        TINYFISH_API_KEY='sk-test-tinyfish-key-12345',
        TINYFISH_ALLOWED_SOURCE_URL='https://example-community.org/events',
        TINYFISH_ALLOWED_SOURCES=['https://example-community.org/events']
    )
    def test_api_timeout_auth_error_and_malformed_response(self):
        """Test API errors (401, timeout, malformed JSON) are handled safely without crashing."""
        from .tinyfish import fetch_events_from_tinyfish

        # 1. HTTP 401 Unauthorized
        err_fp = MagicMock()
        err_fp.read.return_value = b'{"error": {"message": "Invalid API key provided"}}'
        http_401 = urllib.error.HTTPError(
            url="https://agent.tinyfish.ai/v1/automation/run",
            code=401,
            msg="Unauthorized",
            hdrs={},
            fp=err_fp
        )
        with patch('urllib.request.urlopen', side_effect=http_401):
            res_401 = fetch_events_from_tinyfish(self.source_url)
            self.assertFalse(res_401['success'])
            self.assertEqual(res_401['status'], 'HTTP_ERROR')
            self.assertIn("authentication error", res_401['error'])

        # 2. Timeout (Async mode returns SUBMISSION_OUTCOME_UNKNOWN; Sync mode returns NETWORK_TIMEOUT)
        with patch('urllib.request.urlopen', side_effect=TimeoutError("Connection timed out")):
            res_async_timeout = fetch_events_from_tinyfish(self.source_url)
            self.assertFalse(res_async_timeout['success'])
            self.assertEqual(res_async_timeout['status'], 'SUBMISSION_OUTCOME_UNKNOWN')
            self.assertIn("Submission outcome unknown", res_async_timeout['error'])

            res_sync_timeout = fetch_events_from_tinyfish(self.source_url, sync_mode='sync')
            self.assertFalse(res_sync_timeout['success'])
            self.assertEqual(res_sync_timeout['status'], 'NETWORK_TIMEOUT')
            self.assertIn("timed out", res_sync_timeout['error'])

        # 3. Malformed JSON
        mock_malformed = MagicMock()
        mock_malformed.getcode.return_value = 200
        mock_malformed.read.return_value = b'Not valid JSON {[['
        mock_malformed.__enter__.return_value = mock_malformed
        with patch('urllib.request.urlopen', return_value=mock_malformed):
            res_json = fetch_events_from_tinyfish(self.source_url)
            self.assertFalse(res_json['success'])
            self.assertEqual(res_json['status'], 'MALFORMED_RESPONSE')

    @override_settings(
        TINYFISH_API_KEY='sk-test-tinyfish-key-12345',
        TINYFISH_ALLOWED_SOURCE_URL='https://example-community.org/events',
        TINYFISH_ALLOWED_SOURCES=['https://example-community.org/events']
    )
    def test_existing_approved_records_not_silently_overwritten(self):
        """Test change detection reports updates but never overwrites existing approved listings."""
        from .tinyfish import validate_and_import_events

        # Existing approved event
        event_time = self.now + timedelta(days=10)
        approved_event = Event.objects.create(
            title="Stable Community Meetup",
            category=self.category,
            start_datetime=event_time,
            end_datetime=event_time + timedelta(hours=2),
            venue_name="Old Main Venue",
            city="Bengaluru",
            area="Indiranagar",
            organizer_display_name="Core Team",
            submitted_by=self.admin,
            review_status="approved",
            event_status="scheduled",
            original_source_url="https://example-community.org/events/stable-meetup",
        )

        # Source returns same event with updated venue and status=cancelled
        raw_items = [
            {
                "title": "Stable Community Meetup",
                "start_datetime": event_time.isoformat(),
                "end_datetime": (event_time + timedelta(hours=3)).isoformat(),
                "venue": "New Alternate Venue",
                "city": "Bengaluru",
                "original_event_page_url": "https://example-community.org/events/stable-meetup",
                "status": "cancelled",
            }
        ]

        summary = validate_and_import_events(raw_items, self.source_url, self.admin)
        self.assertEqual(summary['new_pending_created'], 0)
        self.assertEqual(summary['duplicates_skipped'], 1)
        self.assertEqual(summary['changes_detected'], 1)
        self.assertEqual(len(summary['detected_changes']), 1)

        # Crucial: Existing approved event MUST NOT be silently changed
        approved_event.refresh_from_db()
        self.assertEqual(approved_event.review_status, 'approved')
        self.assertEqual(approved_event.venue_name, 'Old Main Venue')
        self.assertEqual(approved_event.event_status, 'scheduled')

    @override_settings(
        TINYFISH_API_KEY='sk-test-tinyfish-key-12345',
        TINYFISH_ALLOWED_SOURCE_URL='https://example-community.org/events',
        TINYFISH_ALLOWED_SOURCES=['https://example-community.org/events']
    )
    def test_regression_outbound_schema_has_no_type_arrays(self):
        """
        Regression Test:
        TinyFish returns HTTP 400 if output_schema contains type arrays (e.g. ['boolean', 'null']).
        Intercept the actual outbound Request payload and verify:
        1. No list-valued 'type' keywords exist anywhere recursively in output_schema.
        2. Every 'type' keyword is a single string.
        3. Nullable fields use 'nullable: true'.
        4. Legitimate event-list array ('type': 'array', 'items': ...) is preserved.
        """
        from .tinyfish import fetch_events_from_tinyfish, TINYFISH_OUTPUT_SCHEMA

        captured_requests = []

        def capture_urlopen(req, *args, **kwargs):
            captured_requests.append(req)
            mock_resp = MagicMock()
            mock_resp.getcode.return_value = 200
            mock_resp.read.return_value = json.dumps({"status": "COMPLETED", "result": {"events": []}}).encode('utf-8')
            mock_resp.__enter__.return_value = mock_resp
            return mock_resp

        with patch('urllib.request.urlopen', side_effect=capture_urlopen):
            fetch_events_from_tinyfish(self.source_url)

        self.assertEqual(len(captured_requests), 1)
        actual_req = captured_requests[0]
        actual_payload = json.loads(actual_req.data.decode('utf-8'))
        self.assertIn("output_schema", actual_payload)
        schema = actual_payload["output_schema"]

        # Recursive validator ensuring no list-valued type keywords
        def assert_no_type_arrays(obj, path=""):
            if isinstance(obj, dict):
                if "type" in obj:
                    type_val = obj["type"]
                    self.assertIsInstance(
                        type_val,
                        str,
                        f"Found list-valued type keyword at '{path}/type': {type_val}. "
                        f"TinyFish requires single type string and 'nullable: true' instead of type arrays."
                    )
                for k, v in obj.items():
                    assert_no_type_arrays(v, f"{path}/{k}")
            elif isinstance(obj, list):
                for idx, item in enumerate(obj):
                    assert_no_type_arrays(item, f"{path}[{idx}]")

        assert_no_type_arrays(schema, "#")

        # Verify specific fields match required specification
        event_props = schema["properties"]["events"]["items"]["properties"]
        self.assertEqual(schema["properties"]["events"]["type"], "array")
        self.assertIn("items", schema["properties"]["events"])
        self.assertEqual(event_props["is_free"], {"type": "boolean", "nullable": True})
        self.assertEqual(event_props["price"], {"type": "number", "nullable": True})
        self.assertTrue(event_props["end_datetime"].get("nullable"))

    def test_missing_pricing_preserved_as_none(self):
        """
        Rule 4: Preserve missing values as None.
        Do not convert unknown prices or unknown is_free values into free=True.
        """
        from .tinyfish import validate_and_import_events

        raw_items = [
            {
                "title": "Unspecified Pricing Workshop",
                "start_datetime": (self.now + timedelta(days=8)).isoformat(),
                "venue": "Workshop Hall",
                "city": "Bengaluru",
                "is_free": None,
                "price": None,
                "original_event_page_url": "https://example-community.org/events/unspecified-pricing",
            }
        ]

        summary = validate_and_import_events(raw_items, self.source_url, self.admin)
        self.assertEqual(summary['new_pending_created'], 1)

        event = Event.objects.get(title="Unspecified Pricing Workshop")
        # Must preserve missing values as None! Not convert to True or 0.00!
        self.assertIsNone(event.is_free)
        self.assertIsNone(event.price)

    @override_settings(
        TINYFISH_API_KEY='sk-test-tinyfish-key-12345',
        TINYFISH_ALLOWED_SOURCE_URL='https://example-community.org/events',
        TINYFISH_ALLOWED_SOURCES=['https://example-community.org/events']
    )
    def test_sync_now_calls_async_endpoint_and_saves_run_id(self):
        """
        Verify that Sync Now calls /v1/automation/run-async (not /run),
        receives run_id immediately, saves it in session, and displays Check Result control.
        """
        self.client.login(username='admin_sync', password='AdminSyncPass123!')

        captured_requests = []

        def capture_urlopen(req, *args, **kwargs):
            captured_requests.append(req)
            mock_resp = MagicMock()
            mock_resp.getcode.return_value = 200
            mock_resp.read.return_value = json.dumps({
                "status": "PENDING",
                "run_id": "run_async_789"
            }).encode('utf-8')
            mock_resp.__enter__.return_value = mock_resp
            return mock_resp

        with patch('urllib.request.urlopen', side_effect=capture_urlopen):
            res = self.client.post(self.sync_url, {'action': 'sync_now'}, follow=True)
            self.assertEqual(res.status_code, 200)

        # 1. Exactly one request was dispatched to /v1/automation/run-async
        self.assertEqual(len(captured_requests), 1)
        self.assertEqual(captured_requests[0].full_url, "https://agent.tinyfish.ai/v1/automation/run-async")
        self.assertNotEqual(captured_requests[0].full_url, "https://agent.tinyfish.ai/v1/automation/run")

        # 2. Session preserved the run_id
        session = self.client.session
        self.assertEqual(session.get('tinyfish_active_run_id'), 'run_async_789')

        # 3. UI displays active run ID and Check Result control
        self.assertContains(res, "run_async_789")
        self.assertContains(res, "Check Result for Run run_async_789")

    @override_settings(
        TINYFISH_API_KEY='sk-test-tinyfish-key-12345',
        TINYFISH_ALLOWED_SOURCE_URL='https://example-community.org/events',
        TINYFISH_ALLOWED_SOURCES=['https://example-community.org/events']
    )
    def test_check_status_reuses_existing_run_without_starting_another(self):
        """
        Verify that checking status calls GET /v1/runs/{run_id} only,
        does not start another run, imports events on COMPLETED, and clears session active_run_id.
        """
        self.client.login(username='admin_sync', password='AdminSyncPass123!')

        session = self.client.session
        session['tinyfish_active_run_id'] = 'run_async_789'
        session.save()

        captured_requests = []

        def capture_urlopen(req, *args, **kwargs):
            captured_requests.append(req)
            mock_resp = MagicMock()
            mock_resp.getcode.return_value = 200
            mock_resp.read.return_value = json.dumps({
                "status": "COMPLETED",
                "run_id": "run_async_789",
                "result": {
                    "events": [
                        {
                            "title": "Async Polled Tech Summit",
                            "start_datetime": (self.now + timedelta(days=12)).isoformat(),
                            "venue": "Hall A",
                            "city": "Bengaluru",
                            "original_event_page_url": "https://example-community.org/events/polled-summit",
                        }
                    ]
                }
            }).encode('utf-8')
            mock_resp.__enter__.return_value = mock_resp
            return mock_resp

        with patch('urllib.request.urlopen', side_effect=capture_urlopen):
            res = self.client.post(self.sync_url, {'action': 'check_run', 'run_id': 'run_async_789'}, follow=True)
            self.assertEqual(res.status_code, 200)

        # 1. Exactly 1 request made, which is GET /v1/runs/run_async_789
        self.assertEqual(len(captured_requests), 1)
        self.assertEqual(captured_requests[0].full_url, "https://agent.tinyfish.ai/v1/runs/run_async_789")
        self.assertEqual(captured_requests[0].get_method(), "GET")

        # 2. Event was imported into pending review
        event = Event.objects.filter(title="Async Polled Tech Summit").first()
        self.assertIsNotNone(event)
        self.assertEqual(event.review_status, 'pending')

        # 3. Session active_run_id is now cleared
        session_after = self.client.session
        self.assertIsNone(session_after.get('tinyfish_active_run_id'))

    @override_settings(
        TINYFISH_API_KEY='sk-test-tinyfish-key-12345',
        TINYFISH_ALLOWED_SOURCE_URL='https://example-community.org/events',
        TINYFISH_ALLOWED_SOURCES=['https://example-community.org/events']
    )
    def test_submission_timeout_shows_submission_outcome_unknown(self):
        """
        Verify that if the initial start request times out before run_id is received,
        the UI displays 'Submission outcome unknown' instead of declaring run failed,
        and provides manual run_id checking.
        """
        self.client.login(username='admin_sync', password='AdminSyncPass123!')

        with patch('urllib.request.urlopen', side_effect=TimeoutError("Request timed out during connection")):
            res = self.client.post(self.sync_url, {'action': 'sync_now'}, follow=True)
            self.assertEqual(res.status_code, 200)

        # Must display Submission outcome unknown warning
        self.assertContains(res, "Submission outcome unknown")
        self.assertContains(res, "SUBMISSION_OUTCOME_UNKNOWN")
        self.assertContains(res, "Do NOT immediately submit another run")

        # Session active_run_id must be None
        session = self.client.session
        self.assertIsNone(session.get('tinyfish_active_run_id'))

    @override_settings(
        TINYFISH_API_KEY='sk-test-tinyfish-key-12345',
        TINYFISH_ALLOWED_SOURCE_URL='https://example-community.org/events',
        TINYFISH_ALLOWED_SOURCES=['https://example-community.org/events']
    )
    def test_status_check_timeout_preserves_run_id(self):
        """
        Verify that if checking status times out (POLL_TIMEOUT),
        the run_id is preserved in session and the user can check again without restarting.
        """
        self.client.login(username='admin_sync', password='AdminSyncPass123!')

        session = self.client.session
        session['tinyfish_active_run_id'] = 'run_preserve_999'
        session.save()

        with patch('urllib.request.urlopen', side_effect=TimeoutError("Status check socket timeout")):
            res = self.client.post(self.sync_url, {'action': 'check_run', 'run_id': 'run_preserve_999'}, follow=True)
            self.assertEqual(res.status_code, 200)

        # Session active_run_id is preserved!
        session_after = self.client.session
        self.assertEqual(session_after.get('tinyfish_active_run_id'), 'run_preserve_999')

        # Warning displayed that remote run is preserved
        self.assertContains(res, "Network timeout while checking run run_preserve_999")
        self.assertContains(res, "Check Result for Run run_preserve_999")


class AutomatedWebsiteEntrySyncTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.now = timezone.now()
        self.admin = User.objects.create_superuser(
            username='entry_admin',
            email='admin@entrytest.local',
            password='AdminPassEntry123!'
        )
        self.cat_tech = Category.objects.create(name='Technology & AI', slug='technology-ai')
        self.cat_startups = Category.objects.create(name='Startups & Business', slug='startups-business')

        self.source = EventSource.objects.create(
            name="Bangalore Open Tech Community",
            source_url="https://example-community.org/events",
            content_type="events",
            default_category=self.cat_tech,
            is_enabled=True,
            freshness_interval_minutes=360,
            daily_run_limit=10,
            runs_today_count=0
        )

        self.event_list_url = reverse('events:event_list')
        self.sync_api_url = reverse('events:sync_status_api')

    @override_settings(
        TINYFISH_API_KEY='sk-test-tinyfish-key-12345',
        TINYFISH_ALLOWED_SOURCE_URL='https://example-community.org/events',
        TINYFISH_ALLOWED_SOURCES=['https://example-community.org/events']
    )
    def test_website_entry_initiates_refresh_even_if_data_is_fresh(self):
        """
        Product Requirement:
        Website entry must automatically initiate a new refresh even if saved data is recent.
        It must not be skipped solely because cached data is fresh.
        """
        # Data was synced 2 minutes ago (very fresh)
        self.source.last_successful_sync_at = self.now - timedelta(minutes=2)
        self.source.last_sync_attempt_at = self.now - timedelta(minutes=2)
        self.source.next_due_at = self.now + timedelta(hours=6)
        self.source.sync_status = 'idle'
        self.source.save()

        # Visitor loads event_list
        res = self.client.get(self.event_list_url)
        self.assertEqual(res.status_code, 200)

        # Source is queued for refresh despite fresh data
        self.source.refresh_from_db()
        self.assertEqual(self.source.sync_status, 'queued')
        self.assertTrue(self.source.is_running)

        # A PENDING history record was created
        history = SyncRunHistory.objects.filter(source=self.source, trigger_type='visitor_entry').first()
        self.assertIsNotNone(history)
        self.assertEqual(history.status, 'PENDING')

    def test_concurrent_website_entries_attach_rather_than_duplicate_run(self):
        """
        Concurrency:
        If an equivalent source refresh is already running, attach the new visitor to that active run
        rather than launching an identical concurrent paid run.
        """
        # Active in-flight run
        self.source.sync_status = 'running'
        self.source.active_run_id = 'run_inflight_555'
        self.source.concurrency_lock_until = self.now + timedelta(minutes=4)
        self.source.concurrency_lock_token = 'token_abc123'
        self.source.save()

        # Concurrent visitor enters
        res = self.client.get(self.event_list_url)
        self.assertEqual(res.status_code, 200)

        # Still only one run, not a duplicate
        self.source.refresh_from_db()
        self.assertEqual(self.source.active_run_id, 'run_inflight_555')
        self.assertEqual(self.source.sync_status, 'running')
        # No extra history record spawned
        self.assertEqual(SyncRunHistory.objects.filter(source=self.source).count(), 0)

    @override_settings(
        TINYFISH_API_KEY='sk-test-tinyfish-key-12345',
        TINYFISH_ALLOWED_SOURCE_URL='https://example-community.org/events',
        TINYFISH_ALLOWED_SOURCES=['https://example-community.org/events']
    )
    def test_subsequent_entry_after_completion_starts_new_refresh(self):
        """
        Acceptance test:
        After one refresh finishes, opening the website again starts a new real refresh
        even though the previous results are fresh.
        """
        # Run 1 completes
        self.source.sync_status = 'completed'
        self.source.last_successful_sync_at = self.now
        self.source.next_due_at = self.now + timedelta(hours=6)
        self.source.concurrency_lock_until = None
        self.source.concurrency_lock_token = None
        self.source.save()

        # User reloads / visits website again
        res = self.client.get(self.event_list_url)
        self.assertEqual(res.status_code, 200)

        # Brand new refresh was initiated!
        self.source.refresh_from_db()
        self.assertEqual(self.source.sync_status, 'queued')
        self.assertTrue(self.source.is_running)

    def test_daily_budget_limit_prevents_runaway_sync_and_reports_truthfully(self):
        """
        Safety & Abuse Protection:
        When daily run limit is reached, automated refresh is skipped to protect budget
        and truthfully reported as RATE_LIMITED.
        """
        today = timezone.localdate()
        self.source.daily_run_limit = 5
        self.source.runs_today_count = 5
        self.source.last_run_date = today
        self.source.sync_status = 'idle'
        self.source.save()

        res = self.client.get(self.event_list_url)
        self.assertEqual(res.status_code, 200)

        # Source remains idle, not queued
        self.source.refresh_from_db()
        self.assertEqual(self.source.sync_status, 'idle')

        # Honest RATE_LIMITED history record was created
        history = SyncRunHistory.objects.filter(source=self.source, status='RATE_LIMITED').first()
        self.assertIsNotNone(history)
        self.assertIn("Daily run limit", history.error_message)

    def test_stale_lock_recovery(self):
        """
        Lock Recovery:
        If a worker process crashed and left a stale lock (>5 minutes old),
        the next visitor safely recovers the lock and initiates a clean sync.
        """
        # Stale lock expired 10 minutes ago
        self.source.sync_status = 'running'
        self.source.concurrency_lock_until = self.now - timedelta(minutes=10)
        self.source.concurrency_lock_token = 'stale_token_dead'
        self.source.save()

        res = self.client.get(self.event_list_url)
        self.assertEqual(res.status_code, 200)

        self.source.refresh_from_db()
        # Successfully recovered and re-queued
        self.assertEqual(self.source.sync_status, 'queued')
        self.assertNotEqual(self.source.concurrency_lock_token, 'stale_token_dead')

    @override_settings(
        TINYFISH_API_KEY='sk-test-tinyfish-key-12345',
        TINYFISH_ALLOWED_SOURCE_URL='https://example-community.org/events',
        TINYFISH_ALLOWED_SOURCES=['https://example-community.org/events']
    )
    def test_hackathons_competitions_category_mapping(self):
        """
        Domain Extraction:
        Support hackathons and competitions with explicit category mapping and content types.
        """
        self.source.content_type = 'hackathons'
        self.source.category_mappings = {'hackathon': 'technology-ai', 'bounty': 'technology-ai'}
        self.source.save()

        mock_response = MagicMock()
        mock_response.getcode.return_value = 200
        mock_response.read.return_value = json.dumps({
            "status": "COMPLETED",
            "run_id": "run_hackathon_999",
            "result": {
                "events": [
                    {
                        "title": "Autonomous AI Agent Hackathon",
                        "description": "48-hour build sprint on agent architectures with $10k prizes.",
                        "start_datetime": (self.now + timedelta(days=14)).isoformat(),
                        "venue": "Bengaluru Innovation Lab",
                        "city": "Bengaluru",
                        "category_hints": "Hackathon, AI",
                        "intended_audience": "Developers & Tech Enthusiasts",
                        "original_event_page_url": "https://example-community.org/events/ai-hackathon",
                    }
                ]
            }
        }).encode('utf-8')
        mock_response.__enter__.return_value = mock_response

        with patch('urllib.request.urlopen', return_value=mock_response):
            outcome = execute_source_sync(self.source.pk, trigger_type='scheduled_cron')
            self.assertTrue(outcome['success'])

        hackathon = Event.objects.filter(title="Autonomous AI Agent Hackathon").first()
        self.assertIsNotNone(hackathon)
        self.assertEqual(hackathon.category, self.cat_tech)
        self.assertEqual(hackathon.source, self.source)
        self.assertEqual(hackathon.source_type, 'external')

    @override_settings(
        TINYFISH_API_KEY='sk-test-tinyfish-key-12345',
        TINYFISH_ALLOWED_SOURCE_URL='https://example-community.org/events',
        TINYFISH_ALLOWED_SOURCES=['https://example-community.org/events']
    )
    def test_moderation_policy_preserves_pending_review_unless_auto_approved(self):
        """
        Moderation Policy Integrity:
        Standard source imports require manual admin moderation (review_status='pending').
        Trusted sources with explicit auto_approve_trusted=True appear publicly.
        """
        # 1. Standard source: auto_approve_trusted=False
        self.source.auto_approve_trusted = False
        self.source.save()

        mock_data = json.dumps({
            "status": "COMPLETED",
            "run_id": "run_mod_1",
            "result": {
                "events": [{
                    "title": "Pending Moderation Meetup",
                    "start_datetime": (self.now + timedelta(days=5)).isoformat(),
                    "city": "Bengaluru",
                    "original_event_page_url": "https://example-community.org/events/pending-meetup"
                }]
            }
        }).encode('utf-8')
        mock_resp = MagicMock()
        mock_resp.getcode.return_value = 200
        mock_resp.read.return_value = mock_data
        mock_resp.__enter__.return_value = mock_resp

        with patch('urllib.request.urlopen', return_value=mock_resp):
            execute_source_sync(self.source.pk, trigger_type='scheduled_cron')

        pending_event = Event.objects.get(title="Pending Moderation Meetup")
        self.assertEqual(pending_event.review_status, 'pending')
        # Public visitor CANNOT see it
        public_res = self.client.get(self.event_list_url)
        self.assertNotContains(public_res, "Pending Moderation Meetup")

        # 2. Trusted source: auto_approve_trusted=True
        self.source.auto_approve_trusted = True
        self.source.save()

        mock_data_trusted = json.dumps({
            "status": "COMPLETED",
            "run_id": "run_mod_2",
            "result": {
                "events": [{
                    "title": "Trusted Partner Keynote",
                    "start_datetime": (self.now + timedelta(days=6)).isoformat(),
                    "city": "Bengaluru",
                    "original_event_page_url": "https://example-community.org/events/trusted-keynote"
                }]
            }
        }).encode('utf-8')
        mock_resp_trusted = MagicMock()
        mock_resp_trusted.getcode.return_value = 200
        mock_resp_trusted.read.return_value = mock_data_trusted
        mock_resp_trusted.__enter__.return_value = mock_resp_trusted

        with patch('urllib.request.urlopen', return_value=mock_resp_trusted):
            execute_source_sync(self.source.pk, trigger_type='scheduled_cron')

        trusted_event = Event.objects.get(title="Trusted Partner Keynote")
        self.assertEqual(trusted_event.review_status, 'approved')
        # Public visitor CAN see it
        public_res_after = self.client.get(self.event_list_url)
        self.assertContains(public_res_after, "Trusted Partner Keynote")

    def test_manual_and_local_events_preserved_during_sync(self):
        """
        Data Integrity:
        Manual organizer events and WhatsApp submissions are preserved without corruption during imports.
        """
        # Existing organizer event
        local_event = Event.objects.create(
            title="Local Community Pottery Workshop",
            category=self.cat_tech,
            start_datetime=self.now + timedelta(days=3),
            city="Bengaluru",
            area="Koramangala",
            venue_name="Clay Studio",
            organizer_display_name="Artisans Guild",
            submitted_by=self.admin,
            source_type="organizer",
            review_status="approved",
            event_status="scheduled"
        )

        mock_data = json.dumps({
            "status": "COMPLETED",
            "run_id": "run_preserve_test",
            "result": {
                "events": [{
                    "title": "TinyFish Sourced Tech Talk",
                    "start_datetime": (self.now + timedelta(days=7)).isoformat(),
                    "city": "Bengaluru",
                    "original_event_page_url": "https://example-community.org/events/tech-talk"
                }]
            }
        }).encode('utf-8')
        mock_resp = MagicMock()
        mock_resp.getcode.return_value = 200
        mock_resp.read.return_value = mock_data
        mock_resp.__enter__.return_value = mock_resp

        with patch('urllib.request.urlopen', return_value=mock_resp):
            execute_source_sync(self.source.pk, trigger_type='scheduled_cron')

        # Local event is completely intact
        local_event.refresh_from_db()
        self.assertEqual(local_event.title, "Local Community Pottery Workshop")
        self.assertEqual(local_event.source_type, "organizer")
        self.assertEqual(local_event.review_status, "approved")

    def test_live_sync_status_api_endpoint(self):
        """
        Frontend Dynamic Refresh:
        Verify /events/api/sync-status/ returns valid JSON with sync state.
        """
        # Idle status
        res = self.client.get(self.sync_api_url)
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertIn('is_syncing', data)
        self.assertFalse(data['is_syncing'])

        # Active syncing status
        self.source.sync_status = 'running'
        self.source.concurrency_lock_until = self.now + timedelta(minutes=3)
        self.source.save()

        res_active = self.client.get(self.sync_api_url)
        data_active = res_active.json()
        self.assertTrue(data_active['is_syncing'])
        self.assertIn(self.source.name, data_active['active_source_names'])


class VibentoRefinementAndDiscoveryTests(TestCase):
    def setUp(self):
        self.now = timezone.now()
        self.user = User.objects.create_user(
            username='learner@example.com',
            email='learner@example.com',
            password='Password123!'
        )
        self.other_user = User.objects.create_user(
            username='other@example.com',
            email='other@example.com',
            password='Password123!'
        )
        self.staff_user = User.objects.create_user(
            username='admin@example.com',
            email='admin@example.com',
            password='Password123!',
            is_staff=True,
            is_superuser=True
        )
        self.cat = Category.objects.create(name='Technology', slug='technology')

        self.event_a = Event.objects.create(
            title="AI Builders Hackathon",
            slug="ai-builders-hackathon",
            description="Build agent systems with team.",
            category=self.cat,
            start_datetime=self.now + timedelta(days=5),
            registration_deadline=self.now + timedelta(days=3),
            deadline_type="Registration Deadline",
            city="Bengaluru",
            venue_name="Tech Park",
            organizer_display_name="AI Guild",
            submitted_by=self.staff_user,
            review_status="approved",
            event_status="scheduled"
        )
        self.event_b = Event.objects.create(
            title="Design Sprint Competition",
            slug="design-sprint-competition",
            description="24-hour design sprint.",
            category=self.cat,
            start_datetime=self.now + timedelta(days=2),
            registration_deadline=self.now + timedelta(days=1),
            deadline_type="Submission Deadline",
            city="Bengaluru",
            venue_name="Design Hub",
            organizer_display_name="Design Hub",
            submitted_by=self.staff_user,
            review_status="approved",
            event_status="scheduled"
        )
        self.event_no_deadline = Event.objects.create(
            title="Open Meetup Without Deadline",
            slug="open-meetup-no-deadline",
            description="Open gathering.",
            category=self.cat,
            start_datetime=self.now + timedelta(days=4),
            registration_deadline=None,
            city="Bengaluru",
            venue_name="Open Park",
            organizer_display_name="Open Guild",
            submitted_by=self.staff_user,
            review_status="approved",
            event_status="scheduled"
        )
        self.event_passed = Event.objects.create(
            title="Expired Deadline Workshop",
            slug="expired-deadline-workshop",
            description="Workshop whose deadline was yesterday.",
            category=self.cat,
            start_datetime=self.now + timedelta(days=2),
            registration_deadline=self.now - timedelta(days=1),
            city="Bengaluru",
            venue_name="Old Studio",
            organizer_display_name="Past Guild",
            submitted_by=self.staff_user,
            review_status="approved",
            event_status="scheduled"
        )

    def test_clean_landing_page_structure_and_constraints(self):
        """
        Requirement 1: Clean Landing / Login Page
        3-4 scrolling sections:
        - Vibento name and clear intro
        - What the platform does
        - TinyFish discovery USP for events, hackathons, and competitions
        - How it works with clear Login/Sign In and Sign Up options
        - Does NOT show event cards, personal deadlines, or technical sync tables
        - Does NOT claim universal web coverage
        """
        res = self.client.get(reverse('events:landing'))
        self.assertEqual(res.status_code, 200)

        # Introduction & Name
        self.assertContains(res, "Vibento")
        self.assertContains(res, "Discover Local Events, Hackathons & Competitions")

        # Mentions TinyFish discovery for events, hackathons, and competitions
        self.assertContains(res, "TinyFish")
        self.assertContains(res, "hackathons")
        self.assertContains(res, "competitions")

        # How it works & Login / Sign Up options
        self.assertContains(res, "How It Works")
        self.assertContains(res, "User Sign In")
        self.assertContains(res, "Create Account")
        self.assertContains(res, "Admin Portal")

        # Prohibited elements check:
        # NO event cards or listings
        self.assertNotContains(res, "class=\"event-card\"")
        self.assertNotContains(res, "AI Builders Hackathon")
        # NO technical sync logs or tables
        self.assertNotContains(res, "records_extracted_count")
        self.assertNotContains(res, "run_id")
        # NO universal coverage claims
        self.assertNotContains(res, "universal web coverage")

    def test_event_enrollment_lifecycle(self):
        """
        User enrollment lifecycle:
        - Authenticated user enrolls in approved event.
        - Can cancel enrollment.
        - Can re-activate enrollment.
        - Unauthenticated user redirected to login.
        """
        self.client.force_login(self.user)
        enroll_url = reverse('events:event_enroll', kwargs={'slug': self.event_a.slug})

        # 1. Enroll
        res = self.client.post(enroll_url, {'action': 'enroll'})
        self.assertEqual(res.status_code, 302)
        enr = EventEnrollment.objects.filter(user=self.user, event=self.event_a).first()
        self.assertIsNotNone(enr)
        self.assertEqual(enr.status, 'confirmed')

        # 2. Cancel enrollment
        res_cancel = self.client.post(enroll_url, {'action': 'cancel'})
        self.assertEqual(res_cancel.status_code, 302)
        enr.refresh_from_db()
        self.assertEqual(enr.status, 'cancelled')

        # 3. Re-enroll
        res_reenroll = self.client.post(enroll_url, {'action': 'enroll'})
        self.assertEqual(res_reenroll.status_code, 302)
        enr.refresh_from_db()
        self.assertEqual(enr.status, 'confirmed')

        # 4. Anonymous user cannot enroll directly
        self.client.logout()
        res_anon = self.client.post(enroll_url, {'action': 'enroll'})
        self.assertEqual(res_anon.status_code, 302)
        self.assertIn(reverse('accounts:login'), res_anon.url)

    def test_user_dashboard_sections_and_profile(self):
        """
        Requirement 2: User Dashboard Sections:
        - My Profile
        - My Enrolled Events
        - Upcoming Events
        - Deadlines
        - Explore Events
        """
        self.client.force_login(self.user)
        EventEnrollment.objects.create(user=self.user, event=self.event_a, status='confirmed')

        res = self.client.get(reverse('events:user_dashboard'))
        self.assertEqual(res.status_code, 200)

        # Clearly named sections
        self.assertContains(res, "My Profile")
        self.assertContains(res, "My Enrolled Events")
        self.assertContains(res, "Upcoming Events")
        self.assertContains(res, "Deadlines")
        self.assertContains(res, "Explore Events")

        # Edit profile link exists
        self.assertContains(res, reverse('accounts:profile'))

    def test_compact_red_deadline_reminder_selects_nearest_future_deadline(self):
        """
        Compact red reminder:
        - Selects the nearest future relevant deadline among upcoming enrolled events.
        - Event B deadline is in 1 day; Event A is in 3 days. Event B must be selected!
        - Shows event name, deadline type, date/time, remaining time, and View Event link.
        """
        self.client.force_login(self.user)
        # Enroll user in both Event A and Event B
        EventEnrollment.objects.create(user=self.user, event=self.event_a, status='confirmed')
        EventEnrollment.objects.create(user=self.user, event=self.event_b, status='confirmed')

        res = self.client.get(reverse('events:user_dashboard'))
        self.assertEqual(res.status_code, 200)

        # Red alert container must exist
        self.assertContains(res, "alert alert-danger")
        self.assertContains(res, "Action Required")

        # Event B is nearest (1 day vs 3 days)
        self.assertContains(res, self.event_b.title)
        self.assertContains(res, "Submission Deadline")
        self.assertContains(res, "remaining")
        self.assertContains(res, self.event_b.get_absolute_url())

    def test_compact_red_reminder_excludes_passed_cancelled_and_missing_deadlines(self):
        """
        Compact red reminder exclusions:
        - Passed deadline is excluded.
        - Event without deadline does NOT substitute start time.
        - Cancelled enrollment is excluded.
        - If no eligible future deadline exists, NO red warning is shown.
        """
        self.client.force_login(self.user)

        # Scenario 1: Only enrolled in event without a deadline
        EventEnrollment.objects.create(user=self.user, event=self.event_no_deadline, status='confirmed')
        res1 = self.client.get(reverse('events:user_dashboard'))
        self.assertNotContains(res1, "alert alert-danger")
        self.assertNotContains(res1, "Action Required")

        # Scenario 2: Enrolled in event with passed deadline
        EventEnrollment.objects.create(user=self.user, event=self.event_passed, status='confirmed')
        res2 = self.client.get(reverse('events:user_dashboard'))
        self.assertNotContains(res2, "alert alert-danger")

        # Scenario 3: Enrolled in Event A with future deadline, but status is 'cancelled'
        EventEnrollment.objects.create(user=self.user, event=self.event_a, status='cancelled')
        res3 = self.client.get(reverse('events:user_dashboard'))
        self.assertNotContains(res3, "alert alert-danger")

        # Scenario 4: Another user has an enrolled deadline - must not appear for self.user
        EventEnrollment.objects.create(user=self.other_user, event=self.event_b, status='confirmed')
        res4 = self.client.get(reverse('events:user_dashboard'))
        self.assertNotContains(res4, "alert alert-danger")

    def test_clean_organized_admin_dashboard_sections(self):
        """
        Requirement 3: Clean, organized admin dashboard flow:
        - Overview
        - TinyFish Sync
        - Events & Moderation
        - Users & Enrollments
        - Settings
        - No credentials leaked
        """
        self.client.force_login(self.staff_user)
        res = self.client.get(reverse('admin:index'))
        self.assertEqual(res.status_code, 200)

        # Tab navigation items
        self.assertContains(res, "Overview")
        self.assertContains(res, "TinyFish Sync")
        self.assertContains(res, "Events & Moderation")
        self.assertContains(res, "Users & Enrollments")
        self.assertContains(res, "Settings & Sources")

        # Credentials safeguard
        self.assertNotContains(res, "sk-test-tinyfish")
        self.assertNotContains(res, "TINYFISH_API_KEY")


class UnstopPipelineRegressionTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username='tester@example.com',
            email='tester@example.com',
            password='Password123!'
        )
        self.admin = User.objects.create_user(
            username='admin_sync@example.com',
            email='admin_sync@example.com',
            password='Password123!',
            is_staff=True,
            is_superuser=True
        )
        self.tech_cat = Category.objects.create(name='Technology & AI', slug='technology-ai')
        self.now = timezone.now()

    def test_extract_events_from_json_string_response(self):
        from events.tinyfish import extract_events_from_tinyfish_response
        payload = {
            'status': 'COMPLETED',
            'result': json.dumps({
                'events': [
                    {
                        'title': 'Innovasia 2026 Hackathon',
                        'start_datetime': (self.now + timedelta(days=5)).isoformat()
                    }
                ]
            })
        }
        events = extract_events_from_tinyfish_response(payload)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]['title'], 'Innovasia 2026 Hackathon')

    def test_extract_events_from_markdown_code_fence(self):
        from events.tinyfish import extract_events_from_tinyfish_response
        inner_json = json.dumps({
            'events': [
                {
                    'title': 'Viral Theory Contest',
                    'start_datetime': (self.now + timedelta(days=3)).isoformat()
                }
            ]
        })
        payload = {
            'status': 'COMPLETED',
            'result': f"```json\n{inner_json}\n```"
        }
        events = extract_events_from_tinyfish_response(payload)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]['title'], 'Viral Theory Contest')

    def test_extract_events_from_direct_list(self):
        from events.tinyfish import extract_events_from_tinyfish_response
        payload = {
            'status': 'COMPLETED',
            'result': [
                {
                    'title': 'Robo Sumo Challenge',
                    'start_datetime': (self.now + timedelta(days=4)).isoformat()
                }
            ]
        }
        events = extract_events_from_tinyfish_response(payload)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]['title'], 'Robo Sumo Challenge')

    def test_online_hackathon_location_handling(self):
        from events.tinyfish import validate_and_import_events
        raw_events = [
            {
                'title': 'National Online Hackathon 2026',
                'description': 'A virtual national hackathon for developers',
                'start_datetime': (self.now + timedelta(days=7)).isoformat(),
                'venue': None,
                'city': None,
                'original_event_page_url': 'https://unstop.com/hackathons/online-2026',
            }
        ]
        summary = validate_and_import_events(raw_events, 'https://unstop.com/', self.admin)
        self.assertEqual(summary['records_returned'], 1)
        self.assertEqual(summary['new_pending_created'], 1)
        self.assertEqual(summary['invalid_records_skipped'], 0)

        imported = Event.objects.get(title='National Online Hackathon 2026')
        self.assertEqual(imported.venue_name, 'Online')
        self.assertEqual(imported.city, 'Online')
        self.assertEqual(imported.review_status, 'pending')

    def test_relative_url_resolution(self):
        from events.tinyfish import validate_and_import_events
        raw_events = [
            {
                'title': 'Innovasia 2026 Challenge',
                'description': 'Tech competition on Unstop',
                'start_datetime': (self.now + timedelta(days=10)).isoformat(),
                'venue': 'Online',
                'city': 'Online',
                'original_event_page_url': '/competitions/innovasia-2026',
                'registration_url': '/competitions/innovasia-2026/register',
            }
        ]
        summary = validate_and_import_events(raw_events, 'https://unstop.com/', self.admin)
        self.assertEqual(summary['new_pending_created'], 1)

        imported = Event.objects.get(title='Innovasia 2026 Challenge')
        self.assertEqual(imported.original_source_url, 'https://unstop.com/competitions/innovasia-2026')
        self.assertEqual(imported.registration_url, 'https://unstop.com/competitions/innovasia-2026/register')

    def test_sync_status_summary_reports_pending_vs_approved(self):
        from events.models import EventSource, SyncRunHistory
        from events.services import get_sync_status_summary
        source = EventSource.objects.create(
            name="Unstop Test",
            source_url="https://unstop.com/",
            auto_approve_trusted=False
        )
        SyncRunHistory.objects.create(
            source=source,
            status='COMPLETED',
            records_extracted_count=5,
            records_created_count=3
        )
        status = get_sync_status_summary()
        self.assertEqual(status['records_created'], 3)
        self.assertEqual(status['records_pending'], 3)
        self.assertEqual(status['records_approved'], 0)
        self.assertEqual(status['records_extracted'], 5)

    def test_ensure_default_event_sources(self):
        from events.models import EventSource
        from events.services import ensure_default_event_sources
        EventSource.objects.all().delete()
        created = ensure_default_event_sources()
        self.assertTrue(len(created) > 0)
        unstop = EventSource.objects.filter(source_url__icontains='unstop.com').first()
        self.assertIsNotNone(unstop)
        self.assertTrue(unstop.is_enabled)
        self.assertTrue(unstop.auto_approve_trusted)
        self.assertEqual(unstop.content_type, 'all')

    def test_zero_records_run_not_reported_as_success_import(self):
        from events.tinyfish import validate_and_import_events
        summary = validate_and_import_events([], 'https://unstop.com/', self.admin)
        self.assertEqual(summary['records_returned'], 0)
        self.assertEqual(summary['new_pending_created'], 0)
        self.assertEqual(summary['invalid_records_skipped'], 0)

    def test_auto_publication_for_trusted_unstop_source(self):
        from events.models import EventSource
        from events.tinyfish import validate_and_import_events
        source = EventSource.objects.create(
            name="Unstop Events & Hackathons",
            source_url="https://unstop.com/",
            auto_approve_trusted=True
        )
        raw_events = [
            {
                'title': 'AI Builders Hackathon 2026',
                'description': 'Online coding sprint on Unstop',
                'start_datetime': (self.now + timedelta(days=6)).isoformat(),
                'venue': 'Online',
                'city': 'Online',
                'original_event_page_url': 'https://unstop.com/hackathons/ai-builders-2026',
            }
        ]
        summary = validate_and_import_events(
            raw_events=raw_events,
            source_url='https://unstop.com/',
            user=self.admin,
            source=source,
            auto_approve=source.auto_approve_trusted
        )
        self.assertEqual(summary['new_approved_created'], 1)
        self.assertEqual(summary['new_pending_created'], 0)
        ev = Event.objects.get(title='AI Builders Hackathon 2026')
        self.assertEqual(ev.review_status, 'approved')
        self.assertIsNotNone(ev.reviewed_at)
        # Appears immediately in public discovery feed query
        self.assertTrue(Event.objects.filter(review_status='approved', pk=ev.pk).exists())

    def test_hostname_trust_matching_and_lookalike_rejection(self):
        from events.models import EventSource
        from events.tinyfish import validate_and_import_events
        source = EventSource.objects.create(
            name="Unstop Trusted",
            source_url="https://unstop.com/",
            auto_approve_trusted=True
        )
        # Lookalike / untrusted external domain attempting to spoof Unstop
        raw_events = [
            {
                'title': 'Phishing Challenge 2026',
                'description': 'Unverified external contest',
                'start_datetime': (self.now + timedelta(days=8)).isoformat(),
                'venue': 'Online',
                'city': 'Online',
                'original_event_page_url': 'https://unstop-phishing.com/competitions/phishing-101',
            }
        ]
        summary = validate_and_import_events(
            raw_events=raw_events,
            source_url='https://unstop.com/',
            user=self.admin,
            source=source,
            auto_approve=source.auto_approve_trusted
        )
        # Must NOT auto-publish untrusted lookalike domains!
        self.assertEqual(summary['new_approved_created'], 0)
        self.assertEqual(summary['new_pending_created'], 1)
        ev = Event.objects.get(title='Phishing Challenge 2026')
        self.assertEqual(ev.review_status, 'pending')
        self.assertIn("does not match trusted source hostname", ev.reviewer_feedback)

    def test_preserve_admin_rejected_and_unpublished_events(self):
        from events.models import EventSource
        from events.tinyfish import validate_and_import_events
        source = EventSource.objects.create(
            name="Unstop Trusted",
            source_url="https://unstop.com/",
            auto_approve_trusted=True
        )
        # Admin previously rejected an event
        rejected_event = Event.objects.create(
            title='Deliberately Rejected Event',
            slug='deliberately-rejected-event',
            description='Not suitable for platform',
            category=self.tech_cat,
            start_datetime=self.now + timedelta(days=4),
            submitted_by=self.admin,
            source=source,
            original_source_url='https://unstop.com/hackathons/rejected-hackathon',
            review_status='rejected',
            city='Online',
            venue_name='Online',
        )

        raw_events = [
            {
                'title': 'Deliberately Rejected Event',
                'description': 'Attempting re-import',
                'start_datetime': (self.now + timedelta(days=4)).isoformat(),
                'venue': 'Online',
                'city': 'Online',
                'original_event_page_url': 'https://unstop.com/hackathons/rejected-hackathon',
            }
        ]
        summary = validate_and_import_events(
            raw_events=raw_events,
            source_url='https://unstop.com/',
            user=self.admin,
            source=source,
            auto_approve=source.auto_approve_trusted
        )
        self.assertEqual(summary['new_approved_created'], 0)
        self.assertEqual(summary['duplicates_skipped'], 1)
        rejected_event.refresh_from_db()
        self.assertEqual(rejected_event.review_status, 'rejected')  # Admin decision preserved!

    def test_optional_fields_not_invented(self):
        from events.tinyfish import validate_and_import_events
        raw_events = [
            {
                'title': 'Delhi Tech Summit 2026',
                'description': 'Tech meetup in Delhi',
                'start_datetime': (self.now + timedelta(days=9)).isoformat(),
                'venue': 'Campus Auditorium',
                'city': None,  # Missing optional city
                'original_event_page_url': 'https://unstop.com/events/delhi-tech-summit',
            }
        ]
        summary = validate_and_import_events(
            raw_events=raw_events,
            source_url='https://unstop.com/',
            user=self.admin,
            auto_approve=False
        )
        self.assertEqual(summary['new_pending_created'], 1)
        ev = Event.objects.get(title='Delhi Tech Summit 2026')
        # Does NOT invent "Bengaluru"
        self.assertNotEqual(ev.city, "Bengaluru")
        self.assertEqual(ev.city, "")

    @patch('events.views.trigger_visitor_entry_refresh')
    def test_ajax_fragment_update_does_not_enqueue_refresh(self, mock_refresh):
        """Completion-driven in-place UI update via AJAX does not trigger background sync loop."""
        mock_refresh.return_value = []
        # AJAX fetch with X-Requested-With header
        resp = self.client.get(reverse('events:event_list'), HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(resp.status_code, 200)
        mock_refresh.assert_not_called()

        # Regular browser entry / full reload without AJAX header DOES trigger visitor refresh
        resp_direct = self.client.get(reverse('events:event_list'))
        self.assertEqual(resp_direct.status_code, 200)
        mock_refresh.assert_called_once()

    def test_content_based_category_mapping_accuracy(self):
        """Categories are mapped using actual content analysis and not all generic competitions become Tech."""
        from events.tinyfish import match_category
        cat_biz = Category.objects.create(name='Startups & Business', slug='startups-business')
        cat_comm = Category.objects.create(name='Community & Social', slug='community-social')

        # 1. Economic / portfolio simulation -> Startups & Business
        matched_biz = match_category(
            category_hint="Quizzes & Treasure Hunt, Online Gaming",
            title="Moral Hazard : An Economic Social-Deduction & Portfolio Simulation",
            description="A social-deduction and portfolio simulation game involving economic concepts, macroeconomics, policy, logical puzzles."
        )
        self.assertEqual(matched_biz, cat_biz)

        # 2. Treasure hunt / escape room -> Community & Social
        matched_comm = match_category(
            category_hint="Quizzes & Treasure Hunt",
            title="Market Maze: Treasure Hunt & Escape Room",
            description="A high-stakes treasure hunt and escape room competition testing logic and teamwork."
        )
        self.assertEqual(matched_comm, cat_comm)

        # 3. Coding competition -> Technology & AI
        matched_tech = match_category(
            category_hint="Competitive Coding",
            title="CodeClash: The November Nexus 2026",
            description="A national-level coding competition testing problem-solving, DSA, and DBMS."
        )
        self.assertEqual(matched_tech, self.tech_cat)

        # 4. Uncertain generic competition falls back to general Community category, not Tech
        matched_fallback = match_category(
            category_hint="",
            title="Citywide Championship Challenge",
            description="An open competition for local participants."
        )
        self.assertEqual(matched_fallback, cat_comm)

    def test_optional_end_date_visibility_in_public_listings(self):
        """Events with end_datetime=None are valid and visible in general listings and date filters."""
        # Create event with end_datetime=None scheduled for tomorrow
        tomorrow = timezone.localdate() + timedelta(days=1)
        ev_no_end = Event.objects.create(
            title="Open Source Community Meetup Without End Time",
            description="Meetup without a strict end time specified by organizer.",
            category=self.tech_cat,
            start_datetime=self.now + timedelta(days=1),
            end_datetime=None,  # Optional field is null
            city="Bangalore",
            area="Koramangala",
            venue_name="Open Space",
            organizer_display_name="Open Collective",
            submitted_by=self.user,
            review_status='approved',
            event_status='scheduled',
            is_free=True,
        )

        # 1. Appears in general public listing
        resp = self.client.get(reverse('events:event_list'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Open Source Community Meetup Without End Time")

        # 2. Appears in tomorrow date range filter
        resp_tomorrow = self.client.get(f"{reverse('events:event_list')}?date_range=tomorrow")
        self.assertEqual(resp_tomorrow.status_code, 200)
        self.assertContains(resp_tomorrow, "Open Source Community Meetup Without End Time")

        # 3. Appears in this_week date range filter
        resp_week = self.client.get(f"{reverse('events:event_list')}?date_range=this_week")
        self.assertEqual(resp_week.status_code, 200)
        self.assertContains(resp_week, "Open Source Community Meetup Without End Time")


class ProfilePersonalizationRecommendationTests(TestCase):
    """
    Tests for explicit profile-based event recommendations on the user dashboard.
    Verifies:
    1. Student with Technology & AI receives matching tech records.
    2. Working Professional with Jamming/Sports & Outdoor receives matching music records.
    3. Same role with different interests receives different recommendations.
    4. Different roles with the same interests share relevant recommendations (no stereotyping).
    5. No matching records produces an honest empty state with 'Browse All Events' link.
    6. Profile interest updates refresh recommendations immediately.
    7. Account switching / logout never leaks or reuses another user's recommendations.
    8. Background sync checks do not replace personalized results with the global feed.
    9. Recommendation cards do not automatically enroll users; already-enrolled events are excluded.
    """

    def setUp(self):
        from accounts.models import UserProfile
        self.client = Client()
        self.now = timezone.now()

        # Admin user
        self.admin = User.objects.create_superuser(username='rec_admin', email='rec_admin@test.com', password='password123')

        # Categories
        self.cat_tech = Category.objects.create(name='Technology & AI', slug='technology-ai')
        self.cat_music = Category.objects.create(name='Music & Live Jam', slug='music-live-jam')
        self.cat_arts = Category.objects.create(name='Arts & Crafts', slug='arts-crafts')

        # Events
        self.tech_event = Event.objects.create(
            title="Bangalore Tech Hackathon 2026",
            category=self.cat_tech,
            description="Deep dive into LLMs and generative agents.",
            start_datetime=self.now + timedelta(days=2),
            end_datetime=self.now + timedelta(days=2, hours=8),
            city="Bengaluru",
            venue_name="Innovation Hub",
            submitted_by=self.admin,
            review_status='approved',
            event_status='scheduled',
            is_free=True,
        )

        self.music_event = Event.objects.create(
            title="Bandra Sunset Acoustic Jam & Open Mic",
            category=self.cat_music,
            description="Bring your acoustic guitar, cajon, or just your voice for a relaxed jam.",
            start_datetime=self.now + timedelta(days=3),
            end_datetime=self.now + timedelta(days=3, hours=3),
            city="Mumbai",
            venue_name="Bandstand Amphitheatre",
            submitted_by=self.admin,
            review_status='approved',
            event_status='scheduled',
            is_free=True,
        )

        self.art_event = Event.objects.create(
            title="Pottery & Watercolor Weekend",
            category=self.cat_arts,
            description="Hands-on pottery workshop with ceramic artists.",
            start_datetime=self.now + timedelta(days=4),
            end_datetime=self.now + timedelta(days=4, hours=4),
            city="Bengaluru",
            venue_name="Art Loft",
            submitted_by=self.admin,
            review_status='approved',
            event_status='scheduled',
            is_free=True,
        )

        # Users and Profiles
        # Profile A: Student; interest: Technology & AI
        self.user_a = User.objects.create_user(username='student_tech_user', email='a@test.com', password='password123')
        self.prof_a = self.user_a.profile
        self.prof_a.profile_type = 'student'
        self.prof_a.interests = 'Technology & AI'
        self.prof_a.preferred_city = 'Bengaluru'
        self.prof_a.save()
        self.user_a.refresh_from_db()

        # Profile B: Working Professional; interests: Jamming and Sports & Outdoor
        self.user_b = User.objects.create_user(username='pro_jam_user', email='b@test.com', password='password123')
        self.prof_b = self.user_b.profile
        self.prof_b.profile_type = 'professional'
        self.prof_b.interests = 'Jamming, Sports & Outdoor'
        self.prof_b.preferred_city = 'Mumbai'
        self.prof_b.save()
        self.user_b.refresh_from_db()

        # Profile C: Student; interest: Jamming (Different role, same interest as B)
        self.user_c = User.objects.create_user(username='student_jam_user', email='c@test.com', password='password123')
        self.prof_c = self.user_c.profile
        self.prof_c.profile_type = 'student'
        self.prof_c.interests = 'Jamming'
        self.prof_c.preferred_city = 'Mumbai'
        self.prof_c.save()
        self.user_c.refresh_from_db()

        # Profile D: Working Professional; interest: Sports & Outdoor (0 DB coverage)
        self.user_d = User.objects.create_user(username='pro_sports_only', email='d@test.com', password='password123')
        self.prof_d = self.user_d.profile
        self.prof_d.profile_type = 'professional'
        self.prof_d.interests = 'Sports & Outdoor'
        self.prof_d.save()
        self.user_d.refresh_from_db()

    def test_student_with_tech_interest_receives_tech_events(self):
        """Profile A (Student, Technology & AI) receives matching tech events only."""
        from events.services import get_recommended_events_for_user
        recs, ints, status = get_recommended_events_for_user(self.user_a)
        self.assertEqual(status, 'matched')
        self.assertIn('Technology & AI', ints)
        rec_ids = [e.id for e in recs]
        self.assertIn(self.tech_event.id, rec_ids)
        self.assertNotIn(self.music_event.id, rec_ids)
        self.assertNotIn(self.art_event.id, rec_ids)

        # In dashboard UI
        self.client.login(username='student_tech_user', password='password123')
        resp = self.client.get(reverse('events:user_dashboard'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Bangalore Tech Hackathon 2026")
        self.assertNotContains(resp, "Bandra Sunset Acoustic Jam")
        self.assertNotContains(resp, "Pottery & Watercolor Weekend")

    def test_professional_with_jamming_and_sports_receives_music_records(self):
        """Profile B (Professional, Jamming + Sports) receives music records and not unrelated tech."""
        from events.services import get_recommended_events_for_user
        recs, ints, status = get_recommended_events_for_user(self.user_b)
        self.assertEqual(status, 'matched')
        rec_ids = [e.id for e in recs]
        self.assertIn(self.music_event.id, rec_ids)
        self.assertNotIn(self.tech_event.id, rec_ids)
        self.assertNotIn(self.art_event.id, rec_ids)

        # In dashboard UI
        self.client.login(username='pro_jam_user', password='password123')
        resp = self.client.get(reverse('events:user_dashboard'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Bandra Sunset Acoustic Jam")
        self.assertNotContains(resp, "Bangalore Tech Hackathon 2026")

    def test_same_role_different_interests_receives_different_recommendations(self):
        """Two students with different interests receive strictly different recommendations."""
        from events.services import get_recommended_events_for_user
        self.assertEqual(self.user_a.profile.profile_type, 'student')
        self.assertEqual(self.user_c.profile.profile_type, 'student')

        recs_a, _, _ = get_recommended_events_for_user(self.user_a)
        recs_c, _, _ = get_recommended_events_for_user(self.user_c)

        recs_a_ids = {e.id for e in recs_a}
        recs_c_ids = {e.id for e in recs_c}

        self.assertIn(self.tech_event.id, recs_a_ids)
        self.assertNotIn(self.tech_event.id, recs_c_ids)

        self.assertIn(self.music_event.id, recs_c_ids)
        self.assertNotIn(self.music_event.id, recs_a_ids)

    def test_different_roles_same_interests_shares_recommendations(self):
        """Role does NOT stereotype: Student and Working Professional with Jamming share recommendations."""
        from events.services import get_recommended_events_for_user
        self.assertEqual(self.user_b.profile.profile_type, 'professional')
        self.assertEqual(self.user_c.profile.profile_type, 'student')

        recs_b, _, _ = get_recommended_events_for_user(self.user_b)
        recs_c, _, _ = get_recommended_events_for_user(self.user_c)

        self.assertIn(self.music_event.id, [e.id for e in recs_b])
        self.assertIn(self.music_event.id, [e.id for e in recs_c])

    def test_no_matching_records_produces_honest_empty_state(self):
        """When no matching records exist (Sports & Outdoor with 0 DB items), dashboard shows honest empty state."""
        from events.services import get_recommended_events_for_user
        recs, ints, status = get_recommended_events_for_user(self.user_d)
        self.assertEqual(status, 'no_matches')
        self.assertEqual(recs, [])
        self.assertIn('Sports & Outdoor', ints)

        # Dashboard UI displays honest empty state and browse catalog link
        self.client.login(username='pro_sports_only', password='password123')
        resp = self.client.get(reverse('events:user_dashboard'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "No matching events available yet")
        self.assertContains(resp, "Browse All Events")
        # Never silently present unrelated tech or music events
        self.assertNotContains(resp, "Bangalore Tech Hackathon 2026")
        self.assertNotContains(resp, "Bandra Sunset Acoustic Jam")

    def test_profile_interest_update_refreshes_recommendations_immediately(self):
        """Updating user interests immediately refreshes dashboard recommendations."""
        self.client.login(username='student_tech_user', password='password123')

        # Initially shows tech
        resp_before = self.client.get(reverse('events:user_dashboard'))
        self.assertContains(resp_before, "Bangalore Tech Hackathon 2026")
        self.assertNotContains(resp_before, "Bandra Sunset Acoustic Jam")

        # Update interests to Live Music via POST to interests view
        resp_update = self.client.post(
            reverse('accounts:interests'),
            {'selected_interests': ['Live Music & Jam']},
            follow=True
        )
        self.assertEqual(resp_update.status_code, 200)

        # Now dashboard shows music, not tech
        resp_after = self.client.get(reverse('events:user_dashboard'))
        self.assertContains(resp_after, "Bandra Sunset Acoustic Jam")
        self.assertNotContains(resp_after, "Bangalore Tech Hackathon 2026")

    def test_account_switching_does_not_leak_recommendations(self):
        """Logging out and logging in as another user never leaks or reuses recommendations."""
        # 1. Login as Student (Tech)
        self.client.login(username='student_tech_user', password='password123')
        resp_a = self.client.get(reverse('events:user_dashboard'))
        self.assertContains(resp_a, "Bangalore Tech Hackathon 2026")
        self.assertNotContains(resp_a, "Bandra Sunset Acoustic Jam")

        # 2. Logout
        self.client.post(reverse('accounts:logout'))

        # 3. Login as Working Professional (Jamming)
        self.client.login(username='pro_jam_user', password='password123')
        resp_b = self.client.get(reverse('events:user_dashboard'))
        self.assertContains(resp_b, "Bandra Sunset Acoustic Jam")
        self.assertNotContains(resp_b, "Bangalore Tech Hackathon 2026")

    def test_background_sync_does_not_replace_personalized_feed_with_global(self):
        """Sync status checks preserve the user dashboard's personalized results without replacing them with the global catalog."""
        self.client.login(username='student_tech_user', password='password123')

        # Trigger sync status check (AJAX)
        resp_sync = self.client.get(reverse('events:sync_status_api'))
        self.assertEqual(resp_sync.status_code, 200)

        # Dashboard remains personalized
        resp_dash = self.client.get(reverse('events:user_dashboard'))
        self.assertEqual(resp_dash.status_code, 200)
        self.assertContains(resp_dash, "Bangalore Tech Hackathon 2026")
        self.assertNotContains(resp_dash, "Bandra Sunset Acoustic Jam")

    def test_recommendation_cards_do_not_auto_enroll_user(self):
        """Viewing recommendations does NOT auto-enroll the user; enrolling requires explicit user action."""
        self.client.login(username='student_tech_user', password='password123')
        resp = self.client.get(reverse('events:user_dashboard'))
        self.assertEqual(resp.status_code, 200)

        # Confirm 0 enrollments created
        enrollment_count = EventEnrollment.objects.filter(user=self.user_a).count()
        self.assertEqual(enrollment_count, 0)

        # Explicit enrollment
        resp_enroll = self.client.post(reverse('events:event_enroll', kwargs={'slug': self.tech_event.slug}), follow=True)
        self.assertEqual(resp_enroll.status_code, 200)
        self.assertTrue(EventEnrollment.objects.filter(user=self.user_a, event=self.tech_event, status='confirmed').exists())

        # Once confirmed enrolled, the event is excluded from recommendations to keep recommendations fresh
        from events.services import get_recommended_events_for_user
        recs, _, _ = get_recommended_events_for_user(self.user_a)
        self.assertNotIn(self.tech_event.id, [e.id for e in recs])

    def test_background_completion_refreshes_personalized_recommendations_with_new_arrival(self):
        """Newly arrived records from background sync immediately refresh and appear in personalized recommendations."""
        self.client.login(username='student_tech_user', password='password123')

        # 1. Initial dashboard shows initial tech event
        resp_init = self.client.get(reverse('events:user_dashboard'))
        self.assertContains(resp_init, "Bangalore Tech Hackathon 2026")
        self.assertNotContains(resp_init, "Autonomous AI Agent Hackathon 2026")

        # 2. Background sync completes and auto-publishes a new matching external event
        new_tech_event = Event.objects.create(
            title="Autonomous AI Agent Hackathon 2026",
            category=self.cat_tech,
            description="Build autonomous agent workflows with real-time feedback.",
            start_datetime=self.now + timedelta(days=6),
            end_datetime=self.now + timedelta(days=6, hours=8),
            city="Bengaluru",
            venue_name="AI Campus",
            submitted_by=self.admin,
            source_type="external",
            review_status="approved",
            event_status="scheduled",
            is_free=True,
        )

        # 3. User dashboard refresh immediately reflects the newly arrived event in their personalized feed
        resp_refreshed = self.client.get(reverse('events:user_dashboard'))
        self.assertEqual(resp_refreshed.status_code, 200)
        self.assertContains(resp_refreshed, "Autonomous AI Agent Hackathon 2026")

        # 4. Profile B (Jamming) does NOT receive the new tech event
        self.client.logout()
        self.client.login(username='pro_jam_user', password='password123')
        resp_b = self.client.get(reverse('events:user_dashboard'))
        self.assertContains(resp_b, "Bandra Sunset Acoustic Jam")
        self.assertNotContains(resp_b, "Autonomous AI Agent Hackathon 2026")

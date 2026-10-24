from datetime import timedelta
from django.test import TestCase, Client
from django.contrib.auth.models import User
from django.utils import timezone
from django.urls import reverse
from .models import Category, Event, WhatsAppSubmission


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





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


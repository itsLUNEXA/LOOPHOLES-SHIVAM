from django.test import TestCase, Client
from django.contrib.auth.models import User
from django.urls import reverse
from .models import UserProfile


class EmailAuthAndMultiStepSignupTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.login_url = reverse('accounts:login')
        self.signup_url = reverse('accounts:signup')
        self.interests_url = reverse('accounts:interests')
        self.profile_url = reverse('accounts:profile')

        # Existing user for testing email login
        self.existing_user = User.objects.create_user(
            username='existing@example.com',
            email='existing@example.com',
            password='ExistingPassword123!'
        )
        self.profile = self.existing_user.profile
        self.profile.age = 28
        self.profile.profile_type = 'professional'
        self.profile.preferred_city = 'Bengaluru'
        self.profile.save()

    def test_email_login_success(self):
        """Existing users log in with email and password without re-entering profile data."""
        response = self.client.post(self.login_url, {
            'email': 'existing@example.com',
            'password': 'ExistingPassword123!'
        }, follow=True)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context['user'].is_authenticated)
        self.assertEqual(response.context['user'].email, 'existing@example.com')

    def test_email_login_invalid_credentials(self):
        """Invalid email or password returns clear error."""
        response = self.client.post(self.login_url, {
            'email': 'existing@example.com',
            'password': 'WrongPassword123!'
        })
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Invalid email or password")

    def test_multistep_signup_complete_flow(self):
        """Multi-step signup proceeds through email, age, user type, location, password, and interests."""
        # Step 1: Email
        r1 = self.client.post(self.signup_url, {'step': 1, 'email': 'student.priya@example.com'})
        self.assertEqual(r1.status_code, 302)
        self.assertIn('step=2', r1.url)

        # Step 2: Age
        r2 = self.client.post(self.signup_url, {'step': 2, 'age': 21})
        self.assertEqual(r2.status_code, 302)
        self.assertIn('step=3', r2.url)

        # Step 3: User type
        r3 = self.client.post(self.signup_url, {'step': 3, 'profile_type': 'student'})
        self.assertEqual(r3.status_code, 302)
        self.assertIn('step=4', r3.url)

        # Step 4: Location
        r4 = self.client.post(self.signup_url, {'step': 4, 'preferred_city': 'Bengaluru', 'preferred_area': 'HSR Layout'})
        self.assertEqual(r4.status_code, 302)
        self.assertIn('step=5', r4.url)

        # Passwords must not be in session
        session_data = self.client.session.get('signup_data', {})
        self.assertNotIn('password', session_data)

        # Step 5: Password & confirm (creates account)
        r5 = self.client.post(self.signup_url, {
            'step': 5,
            'password': 'StrongPassword123!',
            'password_confirm': 'StrongPassword123!'
        })
        self.assertEqual(r5.status_code, 302)
        self.assertEqual(r5.url, self.interests_url)

        # Verify user & profile persisted
        created_user = User.objects.get(email='student.priya@example.com')
        self.assertTrue(created_user.check_password('StrongPassword123!'))
        self.assertEqual(created_user.profile.age, 21)
        self.assertEqual(created_user.profile.profile_type, 'student')
        self.assertEqual(created_user.profile.preferred_city, 'Bengaluru')
        self.assertEqual(created_user.profile.preferred_area, 'HSR Layout')

        # Step 6: Interests selection screen
        r6 = self.client.post(self.interests_url, {
            'selected_interests': ['Technology & AI', 'Gaming & Esports'],
            'custom_interests': 'Robotics'
        }, follow=True)
        self.assertEqual(r6.status_code, 200)

        created_user.profile.refresh_from_db()
        self.assertIn('Technology & AI', created_user.profile.interests)
        self.assertIn('Robotics', created_user.profile.interests)

    def test_signup_email_uniqueness_validation(self):
        """Signup Step 1 rejects already registered email."""
        r = self.client.post(self.signup_url, {'step': 1, 'email': 'existing@example.com'})
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "account with this email address already exists")

    def test_signup_back_button_preserves_data(self):
        """User can navigate back to earlier steps with inputs preserved."""
        # Enter Step 1
        self.client.post(self.signup_url, {'step': 1, 'email': 'backtest@example.com'})
        # At Step 2, click Back
        r_back = self.client.post(self.signup_url, {'step': 2, 'action': 'back'})
        self.assertEqual(r_back.status_code, 302)
        self.assertIn('step=1', r_back.url)

        # Session data preserved
        self.assertEqual(self.client.session.get('signup_data', {}).get('email'), 'backtest@example.com')

    def test_signup_password_mismatch_validation(self):
        """Step 5 validates password confirmation match and password rules."""
        # Prime session
        s = self.client.session
        s['signup_data'] = {'email': 'valid@example.com', 'age': 25, 'profile_type': 'hobbyist', 'preferred_city': 'Pune'}
        s.save()

        r = self.client.post(self.signup_url, {
            'step': 5,
            'password': 'Password123!',
            'password_confirm': 'DifferentPassword123!'
        })
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Passwords do not match")


class AdminLoginAndDashboardAcceptanceTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.login_url = reverse('accounts:login')
        self.logout_url = reverse('accounts:logout')
        self.events_url = reverse('events:event_list')
        self.landing_url = reverse('events:landing')
        self.admin_url = reverse('admin:index')

        # Normal User
        self.normal_user = User.objects.create_user(
            username='user@community.test',
            email='user@community.test',
            password='UserPass123!',
            is_staff=False,
            is_superuser=False
        )

        # Authorized Admin User
        self.admin_user = User.objects.create_user(
            username='staff@community.test',
            email='staff@community.test',
            password='AdminPass123!',
            is_staff=True,
            is_superuser=True
        )

    def test_acceptance_1_main_login_page_offers_user_and_admin_login(self):
        """1. Main login page visibly offers User Login and Admin Login with clear labeling."""
        response = self.client.get(self.login_url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "User Login")
        self.assertContains(response, "Admin Login")
        self.assertContains(response, 'id="tabUser"')
        self.assertContains(response, 'id="tabAdmin"')
        self.assertContains(response, 'name="login_type"')

        # Check explicit query param switching
        r_admin = self.client.get(f"{self.login_url}?type=admin")
        self.assertEqual(r_admin.status_code, 200)
        self.assertContains(r_admin, "Sign in with your staff account")

        r_user = self.client.get(f"{self.login_url}?type=user")
        self.assertEqual(r_user.status_code, 200)
        self.assertContains(r_user, "Sign in with your email")

    def test_acceptance_2_normal_user_login_opens_public_website(self):
        """2. Normal user login opens the public event-discovery website."""
        response = self.client.post(self.login_url, {
            'email': 'user@community.test',
            'password': 'UserPass123!',
            'login_type': 'user'
        })
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, self.events_url)

        # Follow redirect and verify normal discovery view
        follow_resp = self.client.get(response.url)
        self.assertEqual(follow_resp.status_code, 200)
        self.assertTrue(follow_resp.context['user'].is_authenticated)
        # Normal user does NOT see admin dashboard links
        self.assertNotContains(follow_resp, "Admin Dashboard")

    def test_acceptance_3_authorized_admin_login_opens_central_dashboard(self):
        """3. Authorized admin login opens the central dashboard directly and shows dashboard link."""
        response = self.client.post(self.login_url, {
            'email': 'staff@community.test',
            'password': 'AdminPass123!',
            'login_type': 'admin'
        })
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, self.admin_url)

        # Follow redirect to central dashboard
        dashboard_resp = self.client.get(response.url)
        self.assertEqual(dashboard_resp.status_code, 200)
        self.assertContains(dashboard_resp, "Central Admin Dashboard")

        # Main website now visibly offers Admin Dashboard link to logged-in admin
        web_resp = self.client.get(self.events_url)
        self.assertEqual(web_resp.status_code, 200)
        self.assertContains(web_resp, "Admin Dashboard")

    def test_acceptance_4_normal_users_cannot_access_admin_pages_even_with_direct_urls(self):
        """4. Normal users cannot access admin pages, even with direct URLs or Admin Login."""
        # 4a. Attempting Admin Login with normal user credentials fails with clear denial
        resp = self.client.post(self.login_url, {
            'email': 'user@community.test',
            'password': 'UserPass123!',
            'login_type': 'admin'
        })
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Access denied: This account does not have staff or administrator permissions")
        self.assertFalse(resp.context['user'].is_authenticated)

        # 4b. Log in as normal user and attempt to open /admin/ directly
        self.client.force_login(self.normal_user)
        r_admin = self.client.get(self.admin_url, follow=True)
        # Redirected away from admin dashboard to public website with error message
        self.assertEqual(r_admin.status_code, 200)
        self.assertContains(r_admin, "Access denied: Staff or administrator permissions required")

        # 4c. Direct sub-URL like /admin/events/event/ is also blocked
        r_sub = self.client.get('/admin/events/event/', follow=True)
        self.assertEqual(r_sub.status_code, 200)
        self.assertContains(r_sub, "Access denied: Staff or administrator permissions required")

    def test_acceptance_5_summary_cards_and_counts_accessible(self):
        """5. Existing users and events are accessible through clickable dashboard summary cards."""
        from events.models import Category, Event
        from django.utils import timezone
        cat = Category.objects.create(name='Tech', slug='tech')
        Event.objects.create(
            title='Demo Meetup',
            slug='demo-meetup',
            category=cat,
            submitted_by=self.normal_user,
            start_datetime=timezone.now() + timezone.timedelta(days=1),
            end_datetime=timezone.now() + timezone.timedelta(days=1, hours=2),
            city='Bengaluru',
            review_status='pending',
            source_type='organizer'
        )

        self.client.force_login(self.admin_user)
        resp = self.client.get(self.admin_url)
        self.assertEqual(resp.status_code, 200)
        # Clickable summary cards
        self.assertContains(resp, "Registered Users")
        self.assertContains(resp, "Total Events")
        self.assertContains(resp, "Pending-Review Events")
        self.assertContains(resp, "Approved Events")
        self.assertContains(resp, "WhatsApp Submissions")

        # All users changelist opens user list, not create form
        users_resp = self.client.get(reverse('admin:auth_user_changelist'))
        self.assertEqual(users_resp.status_code, 200)
        self.assertContains(users_resp, "Select user to change")

        # All events changelist opens event list, not create form
        events_resp = self.client.get(reverse('admin:events_event_changelist'))
        self.assertEqual(events_resp.status_code, 200)
        self.assertContains(events_resp, "Select event to change")

    def test_acceptance_6_pending_events_review_and_approval(self):
        """6. Pending events can be reviewed, approved, and moderation feedback/reviewer is tracked."""
        from events.models import Category, Event
        from django.utils import timezone
        cat = Category.objects.create(name='Music', slug='music')
        event = Event.objects.create(
            title='Acoustic Jam',
            slug='acoustic-jam',
            category=cat,
            submitted_by=self.normal_user,
            description='Live acoustic music and open mic under the stars.',
            start_datetime=timezone.now() + timezone.timedelta(days=2),
            end_datetime=timezone.now() + timezone.timedelta(days=2, hours=3),
            city='Mumbai',
            area='Bandra West',
            venue_name='The Hive',
            organizer_display_name='Mumbai Music Circle',
            review_status='pending',
            source_type='organizer'
        )

        # Public visibility: Pending event not visible in public feed
        pub_list = self.client.get(self.events_url)
        self.assertNotContains(pub_list, "Acoustic Jam")

        # Pending approvals link opens filtered list
        self.client.force_login(self.admin_user)
        pending_list = self.client.get(f"{reverse('admin:events_event_changelist')}?review_status__exact=pending")
        self.assertEqual(pending_list.status_code, 200)
        self.assertContains(pending_list, "Acoustic Jam")

        # Admin approves event with feedback
        change_url = reverse('admin:events_event_change', args=[event.pk])
        # GET the changeform first to verify inline prefix and form rendering
        get_form = self.client.get(change_url)
        self.assertEqual(get_form.status_code, 200)

        # Admin reviews event and sets feedback
        form = get_form.context['adminform'].form
        post_data = {}
        for field_name, field in form.fields.items():
            if field_name == 'poster':
                continue
            val = form.initial.get(field_name)
            if hasattr(val, 'strftime'):
                post_data[f"{field_name}_0"] = val.strftime('%Y-%m-%d')
                post_data[f"{field_name}_1"] = val.strftime('%H:%M:%S')
            elif val is not None:
                post_data[field_name] = val

        for formset in get_form.context['inline_admin_formsets']:
            prefix = formset.formset.prefix
            post_data[f"{prefix}-TOTAL_FORMS"] = '0'
            post_data[f"{prefix}-INITIAL_FORMS"] = '0'
            post_data[f"{prefix}-MIN_NUM_FORMS"] = '0'
            post_data[f"{prefix}-MAX_NUM_FORMS"] = '0'

        post_data['review_status'] = 'approved'
        post_data['reviewer_feedback'] = 'Verified and approved by admin team.'
        post_data['_save'] = 'Save'

        resp = self.client.post(change_url, post_data)
        self.assertEqual(resp.status_code, 302)

        # Verify reviewer & review time recorded
        event.refresh_from_db()
        self.assertEqual(event.review_status, 'approved')
        self.assertEqual(event.reviewed_by, self.admin_user)
        self.assertIsNotNone(event.reviewed_at)
        self.assertIn('Verified and approved', event.reviewer_feedback)

        # Public visibility: Now visible in public feed
        pub_list_after = self.client.get(self.events_url)
        self.assertContains(pub_list_after, "Acoustic Jam")

    def test_acceptance_7_dashboard_navigation_available_without_typing_urls(self):
        """7. Dashboard navigation is accessible on dashboard, list, and detail pages."""
        self.client.force_login(self.admin_user)

        for url in [self.admin_url, reverse('admin:auth_user_changelist'), reverse('admin:events_event_changelist')]:
            r = self.client.get(url)
            self.assertEqual(r.status_code, 200)
            self.assertContains(r, "Dashboard")
            self.assertContains(r, "All Users")
            self.assertContains(r, "User Profiles")
            self.assertContains(r, "All Events")
            self.assertContains(r, "Pending Approvals")
            self.assertContains(r, "WhatsApp Submissions")
            self.assertContains(r, "Categories")
            self.assertContains(r, "View Website")
            self.assertContains(r, "Logout")

    def test_acceptance_8_logout_works_and_protects_admin(self):
        """8. Logout works via POST, redirects to landing page, and protected pages require authentication afterward."""
        self.client.force_login(self.admin_user)
        r_dash = self.client.get(self.admin_url)
        self.assertEqual(r_dash.status_code, 200)

        # Execute POST logout
        logout_resp = self.client.post(self.logout_url)
        self.assertEqual(logout_resp.status_code, 302)
        self.assertEqual(logout_resp.url, self.landing_url)

        # After logout, accessing admin redirects to login page with type=admin
        r_protected = self.client.get(self.admin_url, follow=True)
        self.assertEqual(r_protected.status_code, 200)
        self.assertContains(r_protected, "Admin Login")
        self.assertContains(r_protected, "Sign in with your staff account")

    def test_logout_redirects_to_landing_and_shows_logged_out_navbar(self):
        """User logout terminates auth session, opens /, displays logged-out navbar, and protects dashboard."""
        self.client.force_login(self.normal_user)

        # Confirm user can access dashboard before logout
        dash_resp = self.client.get(reverse('events:user_dashboard'))
        self.assertEqual(dash_resp.status_code, 200)

        # Execute secure POST logout
        logout_resp = self.client.post(self.logout_url)
        self.assertEqual(logout_resp.status_code, 302)
        self.assertEqual(logout_resp.url, self.landing_url)

        # Follow redirect to intro landing page
        landing_resp = self.client.get(logout_resp.url)
        self.assertEqual(landing_resp.status_code, 200)

        # Verify logged-out navbar is rendered
        self.assertContains(landing_resp, "Log In")
        self.assertContains(landing_resp, "Sign Up")
        self.assertNotContains(landing_resp, "Log Out")

        # Verify intro page contains clean overview and NO event cards or personal dashboard widgets
        self.assertContains(landing_resp, "Discover Local Events, Hackathons & Competitions")
        self.assertContains(landing_resp, "What Vibento Does")
        self.assertNotContains(landing_resp, "My Enrolled Events")
        self.assertNotContains(landing_resp, "Upcoming Events")
        self.assertNotContains(landing_resp, "Nearest Deadline")
        self.assertNotContains(landing_resp, "event-card")

        # Verify protected dashboard pages require login after logout
        user_dash_resp = self.client.get(reverse('events:user_dashboard'))
        self.assertEqual(user_dash_resp.status_code, 302)
        self.assertIn(reverse('accounts:login'), user_dash_resp.url)

        org_dash_resp = self.client.get(reverse('events:organizer_dashboard'))
        self.assertEqual(org_dash_resp.status_code, 302)
        self.assertIn(reverse('accounts:login'), org_dash_resp.url)

    def test_login_success_behavior_remains_unchanged(self):
        """Login success behavior is preserved and redirects to discovery /events/ or specified next parameter."""
        # Default login redirect
        login_resp = self.client.post(self.login_url, {
            'email': 'user@community.test',
            'password': 'UserPass123!',
        })
        self.assertEqual(login_resp.status_code, 302)
        self.assertEqual(login_resp.url, self.events_url)

        self.client.logout()

        # Login with next parameter
        login_with_next = self.client.post(f"{self.login_url}?next={reverse('events:user_dashboard')}", {
            'email': 'user@community.test',
            'password': 'UserPass123!',
        })
        self.assertEqual(login_with_next.status_code, 302)
        self.assertEqual(login_with_next.url, reverse('events:user_dashboard'))

    def test_prototype_badge_absent_from_discovery_page(self):
        """Prototype badge ('Part 1 Working Prototype') is completely removed from discovery UI."""
        resp = self.client.get(self.events_url)
        self.assertEqual(resp.status_code, 200)
        self.assertNotContains(resp, "Part 1 Working Prototype")
        self.assertNotContains(resp, "Working Prototype")
        self.assertContains(resp, "Vibento")
        self.assertContains(resp, "Discover nearby events. Connect with your community.")

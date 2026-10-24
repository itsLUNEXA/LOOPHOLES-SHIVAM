# Vibento

> **“Discover nearby events. Connect with your community.”**

Vibento is a production-structured hyperlocal event-discovery and community engagement platform built with Python and Django. It connects diverse community members—students, working professionals, entrepreneurs & startup founders, hobbyists, and neighborhood groups—with local gatherings, tech meetups, cultural workshops, indie jams, and community initiatives happening around them.

---

## 1. Implemented Features (Part 1)

Vibento implements a full set of core event discovery, submission, moderation, and authentication features:

- **Email/Password Authentication:**
  - Secure authentication using email and password via a custom `EmailAuthBackend` (no separate username required).
  - Existing registered users log in directly without repeating onboarding or profile prompts.
  - Active staff and superuser authentication with secure session handling.

- **Multi-Step Signup Wizard (`/accounts/signup/`):**
  - Clean 5-step registration wizard with Back/Next state preservation:
    1. **Email:** Validates format and ensures global email uniqueness. Kept private.
    2. **Age:** Validates age range (13–120). Kept private.
    3. **User Type:** Selects community profile type (*Student*, *Working professional*, *Entrepreneur / startup founder*, *Hobbyist / community member*, *Other / exploring*).
    4. **Location:** City (required) and Locality/Area (optional).
    5. **Password:** Secure password and confirmation validated server-side by Django's password validators. Passwords are never stored in plaintext, query parameters, or session storage.

- **Profile Preferences and Interests (`/accounts/interests/` & `/accounts/profile/`):**
  - Post-signup interest selection with topic chips (*Technology & AI, Startups & Business, Live Music, Arts & Crafts, Books, Social, Gaming, Outdoors*) and custom tag entries.
  - Profile inspection and update screen allowing members to adjust their city, locality, user type, and interests.

- **Main-Website Admin Login & Central Admin Dashboard:**
  - A dual-mode toggle directly on the main website login page (`/accounts/login/`) allows users to switch between **User Login** and **Admin Login**.
  - Admin Login strictly validates active staff permissions (`is_staff` or `is_superuser`); non-staff users attempting Admin Login receive a clear access-denied message without exposing internal endpoints.
  - Successful admin login directs administrators to a styled administrative dashboard (`/admin/`) with rapid shortcuts to pending submissions, all events, user profiles, categories, and WhatsApp submissions.

- **Organizer Event Management (`/events/manage/`):**
  - Authenticated organizers can create detailed event listings with title, category, target audience, schedule, city, area, venue, pricing (free vs. paid), poster image, and external RSVP/ticket URL.
  - Dedicated organizer dashboard displays an organizer's submitted events with real-time review badges (*Pending Review*, *Approved*, *Needs Correction*, *Rejected*) and reviewer feedback notes.
  - Event editing allows organizers to update details. Updating an already-approved event retains its approved status and does not reset it back to pending.
  - Event cancellation feature allows organizers to mark an event as cancelled, which immediately removes it from public discovery while preserving historical records.

- **Manual WhatsApp Submission Intake (`/events/whatsapp/`):**
  - Allows organizers and community scouts to manually submit raw event flyers, text messages, or broadcast copy.
  - Enforces mandatory explicit public-sharing consent (`public_permission_confirmed`) before submission.
  - Stores raw WhatsApp message copy in a private `WhatsAppSubmission` model linked to the event, accessible only to moderators.

- **Event Moderation & Approval Controls:**
  - **Individual Moderation:** Opening an event from the pending approvals queue (`/admin/events/event/?review_status__exact=pending`) presents dedicated moderation controls:
    - **Approve Event** (green)
    - **Request Correction** (amber)
    - **Reject Event** (rose)
    - Reviewer feedback field: mandatory for Rejection and Correction requests; optional for Approvals.
    - Full event details inspection with quick links to public preview.
  - **Bulk Moderation:** The changelist Action dropdown includes bulk actions:
    - *Approve selected events*
    - *Reject selected events*
    - *Request correction for selected events*
    - Intermediary confirmation screen displaying selected events, requiring reviewer feedback for rejections/corrections, and confirming decision via POST.
  - **Review Metadata & State Integrity:**
    - Uses a single shared moderation method (`apply_event_moderation`).
    - Consistently records `reviewed_by`, `reviewed_at`, and `reviewer_feedback`.
    - Protected by POST and CSRF; state changes are never triggered through GET links.
    - Approval preserves cancellation status (an event marked cancelled remains cancelled).
    - Prevents accidental changes to the event submitter or owner.

- **Event Browsing, Search, and Filtering (`/`):**
  - Public discovery catalog displaying only approved, upcoming, scheduled events.
  - Real-time search across event titles, descriptions, venues, and organizers.
  - Multi-attribute filters for Category, City, Date Range, and Free/Paid admission.

- **Event Detail & External Registration:**
  - Individual event pages (`/events/<slug>/`) showing complete schedule, venue details, organizer display name, audience tags, and an external registration button.
  - Unapproved events are blocked with HTTP 404 for the general public, while organizers and moderators can preview them in a specialized preview mode.

---

## 2. Technology Stack & Dependencies

The project uses the following verified technologies and library versions:

- **Backend Framework:** Python `3.14.7` and Django `6.1.2`
- **Database Engine:** Hosted PostgreSQL on **Supabase** via Django ORM
  - Database Adapter: `psycopg` `3.3.6` (with `psycopg-binary`)
  - Connection URL Parser: `dj-database-url` `2.3.0`
- **Configuration & Utilities:**
  - Environment Loading: `python-dotenv` `1.1.1`
  - Image Processing: `Pillow` `13.0.0`
- **Frontend Architecture:**
  - Server-rendered Django Templates
  - CSS Framework: Bootstrap `5.3.3` + Bootstrap Icons `1.11.3`
  - Design System: Custom CSS tokens (`theme.css`) with curated indigo/violet/slate palette
  - Interactive Behavior: Vanilla JavaScript (no React, Vue, or bulky frontend frameworks)
- **Authentication:** Django session authentication with custom `EmailAuthBackend`

---

## 3. First-Time Setup (Windows PowerShell)

Follow these steps to set up Vibento locally:

### 1. Clone & Enter Project Directory
```powershell
cd e:\veck
```

### 2. Create and Activate Virtual Environment
```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

### 3. Install Dependencies
```powershell
pip install -r requirements.txt
```

### 4. Configure Environment Variables
Copy the example environment file:
```powershell
copy .env.example .env
```
Open `.env` in an editor and fill in your configuration (use placeholders; never commit real credentials):
```env
SECRET_KEY=your-secure-random-secret-key-placeholder
DEBUG=True
ALLOWED_HOSTS=localhost,127.0.0.1,testserver
TIME_ZONE=Asia/Kolkata

# Supabase Session Pooler (Port 5432 is recommended for Django ORM & migrations)
DATABASE_URL=postgresql://postgres.<your-project-ref>:<your-db-password>@<your-pooler-host>.pooler.supabase.com:5432/postgres
```

### 5. Apply Database Migrations
```powershell
python manage.py migrate
```

### 6. Create an Administrator Account
```powershell
python manage.py createsuperuser
```
Follow the interactive prompt to set your admin username, email, and password.

---

## 4. Environment Configuration

The application uses the following environment variables defined in `.env`:

| Variable | Description | Example / Recommended Value |
| :--- | :--- | :--- |
| `SECRET_KEY` | Django cryptographic signing key for sessions and CSRF. | `django-insecure-...` (generate a unique string for production) |
| `DEBUG` | Enables Django debug mode and detailed tracebacks. | `True` for development; `False` in production |
| `ALLOWED_HOSTS` | Comma-separated list of hostnames/IPs the application accepts. | `localhost,127.0.0.1,testserver` |
| `TIME_ZONE` | Standard timezone string for event scheduling. | `Asia/Kolkata` |
| `DATABASE_URL` | PostgreSQL connection URI for Supabase. | `postgresql://<user>:<password>@<host>:5432/<dbname>` |
| `TINYFISH_API_KEY` | Server-side API key for official TinyFish Agent API automation. | `sk-tinyfish-...` (keep private; never commit) |
| `TINYFISH_ALLOWED_SOURCE_URL` | Explicitly configured permitted source website for automated sync. | `https://example-community.org/events` |


---

## 5. Running Locally

### Standard Launcher Command
```powershell
python start.py
```

### Explicit Virtual-Environment Launcher Command
```powershell
.\.venv\Scripts\python.exe start.py
```

### What the Launcher Does
The launcher script (`start.py`) performs automated pre-flight checks:
1. **Dependency Verification:** Validates that `django`, `psycopg`, `dj_database_url`, `dotenv`, and `PIL` are installed.
2. **Environment Check:** Ensures `.env` exists and that `DATABASE_URL` is configured for Supabase.
3. **Database Connectivity:** Verifies active connection to the remote Supabase PostgreSQL database.
4. **Applies Migrations:** Automatically runs `call_command('migrate')` to ensure schema synchronization.
5. **Single Browser Tab:** Starts a background thread in the parent process that polls the local port and opens the browser once at `http://127.0.0.1:8000/` without creating duplicate tabs on autoreload.
6. **Local Server:** Serves the application locally on `127.0.0.1:8000`. Stop the server cleanly at any time by pressing `Ctrl+C`.

> **Note:** The local development server is intended for testing and review on your local machine; it is not a publicly exposed production deployment.

---

## 6. Usage & Workflow Guide

### User Browsing Flow
1. Visit `http://127.0.0.1:8000/`.
2. Browse the event catalog cards showing dates, venues, categories, and tags.
3. Use the search bar to find events by keyword, or use the category, city, and pricing filters.
4. Click on an event card to view the full details page.
5. Click **Register on Official Website** to visit the organizer's external ticketing or RSVP link.

### Organizer Submission Flow
1. Click **Log In** and sign in as a registered user (or click **Sign Up** to create an account).
2. Click **Submit Event** in the navigation bar (`/events/create/`).
3. Fill in the event title, category, date/time, city, venue, description, and external registration URL.
4. Submit the form. The event will appear in your **Organizer Dashboard** (`/events/manage/`) marked as **Pending Review**.

### Manual WhatsApp Submission Flow
1. From the navigation bar, select **Submit WhatsApp Event** (`/events/whatsapp/`).
2. Paste the raw WhatsApp text or announcement copy, and optionally attach a flyer image.
3. Fill in the structured event fields extracted from the message.
4. Check the mandatory declaration: *"I confirm that this event information is public and permitted to be listed on Vibento."*
5. Click **Submit for Review**. The submission is sent to the moderation queue with its original message copy saved privately.

### Admin Login & Dashboard Flow
1. Navigate to `/accounts/login/` on the main website.
2. Click the **Admin Login** tab on the login card.
3. Enter your administrator email and password.
4. Click **Sign In as Administrator**.
5. Upon successful staff verification, you are redirected to the **Vibento Central Admin Portal** (`/admin/`).

### Approving, Rejecting, and Requesting Corrections
- **Individual Event Moderation:**
  1. From the admin navigation bar or dashboard, click **Pending Approvals** (`/admin/events/event/?review_status__exact=pending`).
  2. Click any event to open its moderation inspection form.
  3. Review the event details, description, venue, and submitter info.
  4. In the **Event Moderation Controls** card:
     - To **Approve**: Click **Approve Event** (feedback is optional).
     - To **Request Correction**: Type required feedback in the textarea explaining what the organizer must update, then click **Request Correction**.
     - To **Reject**: Type required feedback explaining the reason for rejection, then click **Reject Event**.
  5. The action updates the event immediately via a secure POST request, records reviewer metadata (`reviewed_by`, `reviewed_at`), and returns to the pending queue.
- **Bulk Moderation:**
  1. Go to **All Events** or **Pending Approvals**.
  2. Select the checkboxes next to the events you wish to moderate.
  3. In the **Action** dropdown, select **Approve selected events**, **Reject selected events**, or **Request correction for selected events**, then click **Go**.
  4. On the confirmation screen, inspect the list of selected events and enter reviewer feedback (required for rejection/correction).
  5. Click **Confirm & Apply**.

### Admin TinyFish Synchronization Flow (Part 2 - Milestone 1)
1. Sign in as an administrator via the **Admin Login** tab at `/accounts/login/`.
2. From the top navigation bar or the Central Dashboard, click **Sync Events** (or **Sync Events (TinyFish)**).
3. The sync dashboard at `/admin/events/event/sync/` displays:
   - Configuration status of `TINYFISH_API_KEY`.
   - The verified, permitted source URL from `TINYFISH_ALLOWED_SOURCE_URL`.
   - Any active asynchronous run identifier if an earlier batch run was enqueued.
4. Click **Sync Now** to start collection via a secure POST request.
5. Vibento connects to the official TinyFish Agent API (`https://agent.tinyfish.ai/v1/automation/run`) using strict JSON schema extraction.
6. The synchronization results summary immediately displays:
   - Source checked and run outcome.
   - Total records returned by the agent.
   - **New Pending Created:** Number of valid upcoming event drafts created (with links to review).
   - **Duplicates Skipped:** Number of exact duplicates matching existing event URLs or title + time.
   - **Possible Changes Detected:** Flagged differences on existing records (without silently overwriting approved listings).
   - **Invalid Records Skipped:** Records omitted due to malformed dates, past timestamps, missing titles/venues, or invalid URL schemes with concise explanatory reasons.

---

## 7. Project Structure & Testing

### Project Structure
```text
e:\veck\
├── accounts/                  # User accounts, custom auth backend, signup wizard
│   ├── admin.py               # Custom User & UserProfile admin configuration
│   ├── backends.py            # EmailAuthBackend (case-insensitive email authentication)
│   ├── forms.py               # Signup forms, InterestsForm, ProfileForm
│   ├── models.py              # UserProfile model (user_type, city, area, interests)
│   ├── tests.py               # Authentication and wizard test suite
│   ├── urls.py                # Account routing
│   └── views.py               # Login, signup wizard steps, interests, profile
├── config/                    # Django core configuration
│   ├── settings.py            # Project settings, Supabase DB & SQLite test routing, TinyFish settings
│   ├── urls.py                # Root URL routing and admin portal branding
│   └── wsgi.py                # WSGI entry point
├── events/                    # Event management, moderation, and discovery
│   ├── admin.py               # EventAdmin, apply_event_moderation, bulk actions, sync_events_view
│   ├── forms.py               # EventForm and WhatsAppSubmissionForm
│   ├── models.py              # Category, Event, and WhatsAppSubmission models
│   ├── tests.py               # Event lifecycle, discovery, moderation, and TinyFish test suite
│   ├── tinyfish.py            # TinyFish Agent API client, validation, duplicate & change detection
│   ├── urls.py                # Event routes
│   └── views.py               # Discovery feed, event details, organizer dashboard
├── static/css/                # Custom CSS styling tokens and components
├── templates/                 # Global and app templates
│   ├── admin/                 # Custom admin base, index, and moderation templates
│   │   └── events/event/      # change_form.html, confirm_bulk_moderation.html, sync_events.html
│   ├── accounts/              # Login, multi-step signup, interests, profile
│   └── events/                # Discovery feed, event details, preview, forms
├── manage.py                  # Django CLI entry point
├── requirements.txt           # Python package requirements
├── start.py                   # Automated local launcher script
├── .env.example               # Example environment variable template with TinyFish config
└── README.md                  # Project documentation
```

### Automated Testing
Run the automated test suite with:
```powershell
.\.venv\Scripts\python.exe manage.py test
```

> **Safe Test Database Isolation:**
> In `config/settings.py`, tests automatically route to an in-memory SQLite database (`:memory:`) whenever `'test'` is in `sys.argv`. This ensures tests run safely and quickly without modifying or attempting to execute `CREATE DATABASE` queries against the live Supabase connection pooler.
>
> **Mocked TinyFish Tests:**
> Automated unit tests mock all external TinyFish network calls via `unittest.mock.patch('urllib.request.urlopen')`. No live or paid API requests are made during testing.
>
> **Verified Result:** 47 tests executed and verified passing (`Ran 47 tests in 40.391s ... OK`).

---

## 8. Security & Limitations

- **Private Credentials:** The `.env` file contains sensitive credentials (`SECRET_KEY`, `DATABASE_URL`, `TINYFISH_API_KEY`) and is strictly excluded from Git tracking via `.gitignore`. Never share or commit `.env`.
- **TinyFish API Protection:** The `TINYFISH_API_KEY` is maintained strictly server-side. It is never rendered in templates, transmitted in JavaScript, logged, or exposed in public responses.
- **Configured Source Allowlist:** Only explicitly configured, authorized partner URLs (`TINYFISH_ALLOWED_SOURCE_URL`) can be crawled. Arbitrary public submissions for automated browsing are rejected.
- **No Silent Overwrites:** Detected changes to existing approved events are reported in the admin summary for manual review rather than silently altering published event listings.
- **Local Development Environment:** The built-in Django server (`python start.py`) is suitable for local development only and should not be used as an unhardened public web server.
- **Manual WhatsApp Intake:** The WhatsApp submission feature is an organizer/scout intake tool that requires explicit user confirmation. It does not automatically crawl or scan private WhatsApp chats.
- **External Registration:** Vibento provides outbound links to external registration services (Eventbrite, Luma, Google Forms, etc.) and does not monitor or capture off-platform transactions.
- **Media Storage:** In this development prototype, user-uploaded posters are stored in local media storage. Production deployments should configure persistent cloud storage (such as Supabase Storage or Amazon S3) with appropriate access control policies.

---

## 9. Planned Features (Part 2 — Remaining Milestones)

The current release completes **Part 2 Milestone 1** (TinyFish-assisted event import from a configured permitted source). Subsequent milestones will introduce:

- **Automated Scheduling & Background Runners:** Periodic polling via cron/worker runners to refresh configured sources automatically.
- **Full Two-Way Change Synchronization:** Automated diff review workflow to accept or decline organizer updates from external source changes.
- **Personalized Ranking:** Recommendation engine tailored to individual user interests, browsing history, and locality proximity.


from datetime import timedelta
from django.core.management.base import BaseCommand
from django.contrib.auth.models import User
from django.utils import timezone
from accounts.models import UserProfile
from events.models import Category, Event, WhatsAppSubmission


class Command(BaseCommand):
    help = "Seeds database with categories, demo users, and rich fictional events."

    def handle(self, *args, **options):
        self.stdout.write(self.style.NOTICE("Seeding categories..."))
        categories_data = [
            {'name': 'Technology & AI', 'slug': 'technology-ai', 'badge_color': 'primary', 'description': 'Software, AI, hardware, open source, and developer gatherings.'},
            {'name': 'Startups & Business', 'slug': 'startups-business', 'badge_color': 'success', 'description': 'Pitch nights, founder meetups, networking, and venture talks.'},
            {'name': 'Arts & Crafts', 'slug': 'arts-crafts', 'badge_color': 'warning', 'description': 'Pottery, sketching, painting, and hands-on maker workshops.'},
            {'name': 'Music & Live Jam', 'slug': 'music-live-jam', 'badge_color': 'info', 'description': 'Acoustic jams, jazz nights, indie gigs, and classical recitals.'},
            {'name': 'Books & Literature', 'slug': 'books-literature', 'badge_color': 'secondary', 'description': 'Book clubs, poetry slams, author chats, and writing circles.'},
            {'name': 'Community & Social', 'slug': 'community-social', 'badge_color': 'dark', 'description': 'Neighborhood cleanups, board game nights, and cultural festivals.'},
        ]

        categories = {}
        for cdata in categories_data:
            cat, created = Category.objects.get_or_create(
                slug=cdata['slug'],
                defaults=cdata
            )
            categories[cdata['slug']] = cat

        self.stdout.write(self.style.NOTICE("Seeding demo users..."))

        # 1. Staff Admin User
        admin_user, _ = User.objects.get_or_create(username='admin', defaults={
            'email': 'admin@hyperlocal.demo',
            'first_name': 'Platform',
            'last_name': 'Moderator',
            'is_staff': True,
            'is_superuser': True,
        })
        admin_user.set_password('AdminPass123!')
        admin_user.save()
        admin_profile, _ = UserProfile.objects.get_or_create(user=admin_user)
        admin_profile.profile_type = 'professional'
        admin_profile.preferred_city = 'Bengaluru'
        admin_profile.interests = 'Community Building, Safety, Platform Integrity'
        admin_profile.save()

        # 2. Organizer 1 (Bengaluru Entrepreneur)
        org1, _ = User.objects.get_or_create(username='organizer_priya', defaults={
            'email': 'priya@techfoundry.demo',
            'first_name': 'Priya',
            'last_name': 'Sharma',
        })
        org1.set_password('OrganizerPass123!')
        org1.save()
        p1, _ = UserProfile.objects.get_or_create(user=org1)
        p1.profile_type = 'entrepreneur'
        p1.interests = 'AI, SaaS, Angel Investing'
        p1.preferred_city = 'Bengaluru'
        p1.preferred_area = 'Koramangala'
        p1.organization_name = 'Bengaluru AI Collective'
        p1.save()

        # 3. Organizer 2 (Mumbai Professional / Hobbyist)
        org2, _ = User.objects.get_or_create(username='organizer_rahul', defaults={
            'email': 'rahul@mumbaimakers.demo',
            'first_name': 'Rahul',
            'last_name': 'Verma',
        })
        org2.set_password('OrganizerPass123!')
        org2.save()
        p2, _ = UserProfile.objects.get_or_create(user=org2)
        p2.profile_type = 'professional'
        p2.interests = 'Acoustic Music, Pottery, Open Source'
        p2.preferred_city = 'Mumbai'
        p2.preferred_area = 'Bandra West'
        p2.organization_name = 'Bandra Indie Circle'
        p2.save()

        # 4. Student Attendee
        student, _ = User.objects.get_or_create(username='student_arjun', defaults={
            'email': 'arjun@campus.demo',
            'first_name': 'Arjun',
            'last_name': 'Nair',
        })
        student.set_password('StudentPass123!')
        student.save()
        p3, _ = UserProfile.objects.get_or_create(user=student)
        p3.profile_type = 'student'
        p3.interests = 'Hackathons, Web Development, Gaming'
        p3.preferred_city = 'Bengaluru'
        p3.preferred_area = 'HSR Layout'
        p3.save()

        now = timezone.now()

        self.stdout.write(self.style.NOTICE("Seeding sample events..."))

        # Event 1: Tech & AI Hacknight (Approved, Scheduled, Free)
        e1, _ = Event.objects.get_or_create(
            title="Bengaluru Open-Source & LLM Hacknight",
            defaults={
                'category': categories['technology-ai'],
                'intended_audience': 'Developers & Tech Enthusiasts',
                'description': (
                    "Bring your laptop and join 60+ local builders for an evening of collaborative coding, "
                    "benchmarking local LLMs, and building developer tools. Free pizza and lightning talks at 8:00 PM."
                ),
                'start_datetime': now + timedelta(days=2, hours=3),
                'end_datetime': now + timedelta(days=2, hours=7),
                'city': 'Bengaluru',
                'area': 'Koramangala 4th Block',
                'venue_name': '91springboard Coworking',
                'address': 'Salarpuria Tower I, Hosur Main Rd, Koramangala, Bengaluru, Karnataka 560095',
                'organizer_display_name': 'Bengaluru AI Collective',
                'submitted_by': org1,
                'is_free': True,
                'registration_url': 'https://luma.com/demo-blr-hacknight',
                'registration_deadline': now + timedelta(days=2, hours=1),
                'source_type': 'organizer',
                'review_status': 'approved',
                'event_status': 'scheduled',
                'reviewed_by': admin_user,
                'reviewed_at': now,
            }
        )

        # Event 2: Clay Pottery Studio (Approved, Scheduled, Paid ₹750, WhatsApp source)
        e2, _ = Event.objects.get_or_create(
            title="Koramangala Weekend Clay & Hand-Building Pottery",
            defaults={
                'category': categories['arts-crafts'],
                'intended_audience': 'Hobbyists & Creators',
                'description': (
                    "Unwind with a 2-hour sensory pottery workshop. Learn wheel basics, slab-building, "
                    "and pinch pots. All raw clay, glazing, and firing are included in the workshop fee. Take home your finished creation!"
                ),
                'start_datetime': now + timedelta(days=4, hours=4),
                'end_datetime': now + timedelta(days=4, hours=6),
                'city': 'Bengaluru',
                'area': 'Koramangala 5th Block',
                'venue_name': 'Earth & Fire Clay Studio',
                'address': '142, 1st Cross, 5th Block, Koramangala, Bengaluru',
                'organizer_display_name': 'Earth & Fire Studios',
                'submitted_by': org1,
                'is_free': False,
                'price': 750.00,
                'registration_url': 'https://instamojo.com/demo-pottery-workshop',
                'registration_deadline': now + timedelta(days=3, hours=12),
                'source_type': 'whatsapp',
                'review_status': 'approved',
                'event_status': 'scheduled',
                'reviewed_by': admin_user,
                'reviewed_at': now,
            }
        )
        WhatsAppSubmission.objects.get_or_create(
            event=e2,
            defaults={
                'original_message': (
                    "🎨 *WEEKEND POTTERY ALERT* 🏺\nHey guys! Hosting a chill hand-building & wheel pottery session "
                    "this Saturday at Koramangala 5th block. 750 INR per head, clay provided. DM @priya or register on link below."
                ),
                'public_permission_confirmed': True,
                'submitted_by': org1,
            }
        )

        # Event 3: Bandra Acoustic Jam (Approved, Scheduled, Free)
        e3, _ = Event.objects.get_or_create(
            title="Bandra Sunset Acoustic Jam & Open Mic",
            defaults={
                'category': categories['music-live-jam'],
                'intended_audience': 'All Audiences',
                'description': (
                    "Bring your guitar, ukulele, cajon, or just your singing voice! "
                    "We gather by the promenade steps for an unplugged evening of indie covers, original tunes, and seaside breeze."
                ),
                'start_datetime': now + timedelta(days=3, hours=2),
                'end_datetime': now + timedelta(days=3, hours=5),
                'city': 'Mumbai',
                'area': 'Bandra West',
                'venue_name': 'Carter Road Amphitheatre',
                'address': 'Sangeet Samrat Naushad Ali Marg, Bandra West, Mumbai, Maharashtra 400052',
                'organizer_display_name': 'Bandra Indie Circle',
                'submitted_by': org2,
                'is_free': True,
                'registration_url': 'https://meetup.com/demo-bandra-music',
                'source_type': 'organizer',
                'review_status': 'approved',
                'event_status': 'scheduled',
                'reviewed_by': admin_user,
                'reviewed_at': now,
            }
        )

        # Event 4: SaaS Founder Breakfast (Approved, Scheduled, Paid ₹300)
        e4, _ = Event.objects.get_or_create(
            title="SaaS Founder Breakfast & Growth Roundtable",
            defaults={
                'category': categories['startups-business'],
                'intended_audience': 'Entrepreneurs & Founders',
                'description': (
                    "Intimate breakfast roundtable for B2B SaaS founders scaling to their first $100K ARR. "
                    "Topics: outbound playbook, PMF signals, and hiring your first founding engineer."
                ),
                'start_datetime': now + timedelta(days=5, hours=1),
                'end_datetime': now + timedelta(days=5, hours=3),
                'city': 'Bengaluru',
                'area': 'Indiranagar',
                'venue_name': 'The Flying Squirrel Coffee',
                'address': '136, 1st Cross, 5th Block, Indiranagar, Bengaluru',
                'organizer_display_name': 'Founders Guild BLR',
                'submitted_by': org1,
                'is_free': False,
                'price': 300.00,
                'registration_url': 'https://luma.com/demo-saas-breakfast',
                'registration_deadline': now + timedelta(days=4, hours=18),
                'source_type': 'organizer',
                'review_status': 'approved',
                'event_status': 'scheduled',
                'reviewed_by': admin_user,
                'reviewed_at': now,
            }
        )

        # Event 5: Delhi Book Club (Approved, Scheduled, Free, WhatsApp source)
        e5, _ = Event.objects.get_or_create(
            title="Hauz Khas Weekend Philosophy & Sci-Fi Book Circle",
            defaults={
                'category': categories['books-literature'],
                'intended_audience': 'All Audiences',
                'description': (
                    "Discussing Ted Chiang's 'Stories of Your Life and Others' and Ursula K. Le Guin. "
                    "New readers and listeners are warmly welcome. Grab a hot beverage and join the circle."
                ),
                'start_datetime': now + timedelta(days=6, hours=3),
                'end_datetime': now + timedelta(days=6, hours=5),
                'city': 'Delhi',
                'area': 'Hauz Khas Village',
                'venue_name': 'Kunzum Travel Cafe & Library',
                'address': 'T-49, Ground Floor, Hauz Khas Village, New Delhi, Delhi 110016',
                'organizer_display_name': 'Delhi Readers Circle',
                'submitted_by': org2,
                'is_free': True,
                'registration_url': '',  # Test: no registration url provided
                'source_type': 'whatsapp',
                'review_status': 'approved',
                'event_status': 'scheduled',
                'reviewed_by': admin_user,
                'reviewed_at': now,
            }
        )
        WhatsAppSubmission.objects.get_or_create(
            event=e5,
            defaults={
                'original_message': (
                    "📚 Delhi Sci-Fi & Philosophy readers meetup this Sunday @ Kunzum Hauz Khas! "
                    "Entry free, open to all. DM Rahul to RSVP."
                ),
                'public_permission_confirmed': True,
                'submitted_by': org2,
            }
        )

        # Event 6: Pune Indie Game Developers Meetup (Approved, Scheduled, Free)
        e6, _ = Event.objects.get_or_create(
            title="Pune Indie Game Developers Meetup #14",
            defaults={
                'category': categories['technology-ai'],
                'intended_audience': 'Developers & Tech Enthusiasts',
                'description': (
                    "Showcase your Unity, Godot, or Unreal prototypes. Get playtesting feedback from fellow game designers "
                    "and discuss steam publishing strategies."
                ),
                'start_datetime': now + timedelta(days=7, hours=2),
                'end_datetime': now + timedelta(days=7, hours=5),
                'city': 'Pune',
                'area': 'Baner',
                'venue_name': 'WeWork Futura',
                'address': 'Magarpatta Road / Baner High Street, Pune',
                'organizer_display_name': 'Pune Game Devs Community',
                'submitted_by': org2,
                'is_free': True,
                'registration_url': 'https://eventbrite.com/demo-pune-gamedev',
                'source_type': 'organizer',
                'review_status': 'approved',
                'event_status': 'scheduled',
                'reviewed_by': admin_user,
                'reviewed_at': now,
            }
        )

        # Event 7: Hyderabad Rooftop Watercolor Workshop (Approved, Scheduled, Paid ₹500)
        e7, _ = Event.objects.get_or_create(
            title="Hyderabad Rooftop Watercolor & Coffee Morning",
            defaults={
                'category': categories['arts-crafts'],
                'intended_audience': 'Hobbyists & Creators',
                'description': (
                    "Capture monsoon hues and cityscapes using wet-on-wet watercolor techniques. "
                    "Art supplies and artisan cappuccino included."
                ),
                'start_datetime': now + timedelta(days=8, hours=2),
                'end_datetime': now + timedelta(days=8, hours=5),
                'city': 'Hyderabad',
                'area': 'Jubilee Hills',
                'venue_name': 'Roastery Coffee House',
                'address': 'Road No. 45, Jubilee Hills, Hyderabad',
                'organizer_display_name': 'Deccan Sketchers Guild',
                'submitted_by': org1,
                'is_free': False,
                'price': 500.00,
                'registration_url': 'https://luma.com/demo-hyd-watercolor',
                'source_type': 'organizer',
                'review_status': 'approved',
                'event_status': 'scheduled',
                'reviewed_by': admin_user,
                'reviewed_at': now,
            }
        )

        # Event 8: Pending Submission (Testing admin moderation)
        e8, _ = Event.objects.get_or_create(
            title="Early Stage AI Pitch & Demo Night (Pending Review)",
            defaults={
                'category': categories['startups-business'],
                'intended_audience': 'Entrepreneurs & Founders',
                'description': (
                    "10 early-stage generative AI startups pitch live before angel investors and community mentors. "
                    "3-minute pitch followed by 2 minutes of rapid Q&A."
                ),
                'start_datetime': now + timedelta(days=10, hours=3),
                'end_datetime': now + timedelta(days=10, hours=6),
                'city': 'Bengaluru',
                'area': 'HSR Layout',
                'venue_name': 'BHIVE Workspace HSR Campus',
                'address': '27th Main Rd, Sector 2, HSR Layout, Bengaluru',
                'organizer_display_name': 'Priya Sharma (Founder)',
                'submitted_by': org1,
                'is_free': True,
                'registration_url': 'https://luma.com/demo-ai-pitch-hsr',
                'source_type': 'organizer',
                'review_status': 'pending',  # Moderation test
                'event_status': 'scheduled',
            }
        )

        # Event 9: Needs Correction Submission (Testing feedback workflow)
        e9, _ = Event.objects.get_or_create(
            title="Powai College Code Sprint & Algorithm Challenge",
            defaults={
                'category': categories['technology-ai'],
                'intended_audience': 'Students',
                'description': (
                    "Inter-college algorithmic problem solving marathon. Teams of 2 solve 6 competitive programming challenges."
                ),
                'start_datetime': now + timedelta(days=12, hours=4),
                'end_datetime': now + timedelta(days=12, hours=8),
                'city': 'Mumbai',
                'area': 'Powai',
                'venue_name': 'Campus Computer Center',
                'address': 'Powai Lake Road, Mumbai',
                'organizer_display_name': 'Campus Tech Club',
                'submitted_by': student,
                'is_free': True,
                'source_type': 'organizer',
                'review_status': 'correction',
                'reviewer_feedback': 'Please provide the official college registration link and confirm if non-students can participate.',
                'reviewed_by': admin_user,
                'reviewed_at': now - timedelta(hours=5),
                'event_status': 'scheduled',
            }
        )

        # Event 10: Cancelled Event (Testing cancellation behavior)
        e10, _ = Event.objects.get_or_create(
            title="Indiranagar Urban Gardening & Seed Swap (Cancelled)",
            defaults={
                'category': categories['community-social'],
                'intended_audience': 'All Audiences',
                'description': (
                    "Bring your native heirloom seeds, plant cuttings, and compost queries. Cancelled due to venue maintenance."
                ),
                'start_datetime': now + timedelta(days=9, hours=2),
                'end_datetime': now + timedelta(days=9, hours=4),
                'city': 'Bengaluru',
                'area': 'Indiranagar 100ft Rd',
                'venue_name': 'Green Terrace Community Space',
                'address': '100ft Road, HAL 2nd Stage, Indiranagar, Bengaluru',
                'organizer_display_name': 'Bengaluru AI Collective',
                'submitted_by': org1,
                'is_free': True,
                'registration_url': 'https://luma.com/demo-urban-garden',
                'source_type': 'organizer',
                'review_status': 'approved',
                'event_status': 'cancelled',  # Test cancellation
                'reviewed_by': admin_user,
                'reviewed_at': now - timedelta(days=1),
            }
        )

        self.stdout.write(self.style.SUCCESS("Database successfully seeded!"))
        self.stdout.write(self.style.SUCCESS("Sample Credentials created:"))
        self.stdout.write("  Admin/Staff:       username: admin            | password: AdminPass123!")
        self.stdout.write("  Organizer 1:       username: organizer_priya  | password: OrganizerPass123!")
        self.stdout.write("  Organizer 2:       username: organizer_rahul  | password: OrganizerPass123!")
        self.stdout.write("  Student Attendee:  username: student_arjun    | password: StudentPass123!")

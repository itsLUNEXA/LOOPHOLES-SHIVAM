from django.db import models
from django.contrib.auth.models import User
from django.db.models.signals import post_save
from django.dispatch import receiver


class UserProfile(models.Model):
    PROFILE_TYPE_CHOICES = [
        ('student', 'Student'),
        ('professional', 'Working professional'),
        ('entrepreneur', 'Entrepreneur / startup founder'),
        ('hobbyist', 'Hobbyist / community member'),
        ('other', 'Other / exploring'),
    ]

    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='profile')
    profile_type = models.CharField(
        max_length=20,
        choices=PROFILE_TYPE_CHOICES,
        default='other',
        verbose_name="Profile Type"
    )
    age = models.PositiveIntegerField(
        null=True,
        blank=True,
        verbose_name="Age",
        help_text="Private: Never displayed publicly."
    )
    interests = models.CharField(
        max_length=255,
        blank=True,
        help_text="Topics you care about (e.g. AI & Tech, Startup Meetups, Live Music, Board Games, Design)",
        verbose_name="Interests"
    )
    preferred_city = models.CharField(
        max_length=100,
        blank=True,
        verbose_name="Preferred City"
    )
    preferred_area = models.CharField(
        max_length=100,
        blank=True,
        verbose_name="Preferred Locality / Area"
    )
    organization_name = models.CharField(
        max_length=150,
        blank=True,
        help_text="Optional: Organization, college club, or community name if you organize events",
        verbose_name="Organization / Community Name"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.user.username} ({self.get_profile_type_display()})"


@receiver(post_save, sender=User)
def create_user_profile(sender, instance, created, **kwargs):
    if created:
        UserProfile.objects.get_or_create(user=instance)

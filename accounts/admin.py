from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth.models import User
from .models import UserProfile


class UserProfileInline(admin.StackedInline):
    model = UserProfile
    can_delete = False
    verbose_name = 'Community Profile'
    verbose_name_plural = 'Community Profile & Preferences'
    fields = ['profile_type', 'age', 'interests', 'preferred_city', 'preferred_area', 'organization_name', 'created_at', 'updated_at']
    readonly_fields = ['created_at', 'updated_at']


class UserAdmin(BaseUserAdmin):
    inlines = [UserProfileInline]
    list_display = ['email', 'username', 'get_profile_type', 'is_active', 'is_staff', 'date_joined']
    list_filter = ['is_staff', 'is_active', 'profile__profile_type', 'date_joined']
    search_fields = ['email', 'username', 'first_name', 'last_name', 'profile__preferred_city', 'profile__preferred_area']
    ordering = ['-date_joined']

    def get_profile_type(self, obj):
        if hasattr(obj, 'profile'):
            return obj.profile.get_profile_type_display()
        return '-'
    get_profile_type.short_description = 'Profile Type'


admin.site.unregister(User)
admin.site.register(User, UserAdmin)


@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    list_display = ['user', 'user_email', 'profile_type', 'age', 'preferred_city', 'preferred_area', 'updated_at']
    list_filter = ['profile_type', 'preferred_city']
    search_fields = ['user__email', 'user__username', 'interests', 'preferred_city', 'preferred_area']
    readonly_fields = ['created_at', 'updated_at']

    def user_email(self, obj):
        return obj.user.email
    user_email.short_description = 'User Email'

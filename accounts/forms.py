from django import forms
from django.contrib.auth.models import User
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from .models import UserProfile

INTEREST_CHOICES = [
    ('Technology & AI', 'Technology & AI'),
    ('Startups & Business', 'Startups & Business'),
    ('Design & Creative Arts', 'Design & Creative Arts'),
    ('Live Music & Jam', 'Live Music & Jam'),
    ('Books & Literature', 'Books & Literature'),
    ('Community & Social', 'Community & Social'),
    ('Gaming & Esports', 'Gaming & Esports'),
    ('Fitness & Outdoors', 'Fitness & Outdoors'),
]


class EmailLoginForm(forms.Form):
    email = forms.EmailField(
        label="Email",
        widget=forms.EmailInput(attrs={'class': 'form-control', 'placeholder': 'name@example.com', 'autofocus': True})
    )
    password = forms.CharField(
        label="Password",
        widget=forms.PasswordInput(attrs={'class': 'form-control', 'placeholder': 'Enter password'})
    )


class SignupStep1EmailForm(forms.Form):
    email = forms.EmailField(
        label="Email Address",
        help_text="Private: Used for account access. We will never share your email publicly.",
        widget=forms.EmailInput(attrs={'class': 'form-control', 'placeholder': 'name@example.com', 'autofocus': True})
    )

    def clean_email(self):
        email = self.cleaned_data['email'].strip().lower()
        if User.objects.filter(email__iexact=email).exists():
            raise ValidationError("An account with this email address already exists. Please log in.")
        return email


class SignupStep2AgeForm(forms.Form):
    age = forms.IntegerField(
        min_value=13,
        max_value=120,
        label="Age",
        help_text="Private: We only ask your age to understand community demographics.",
        widget=forms.NumberInput(attrs={'class': 'form-control', 'placeholder': 'e.g. 24', 'autofocus': True})
    )


class SignupStep3UserTypeForm(forms.Form):
    profile_type = forms.ChoiceField(
        choices=UserProfile.PROFILE_TYPE_CHOICES,
        label="User Type",
        widget=forms.Select(attrs={'class': 'form-select', 'autofocus': True}),
        help_text="Select what best describes your primary interest in local events."
    )


class SignupStep4LocationForm(forms.Form):
    preferred_city = forms.CharField(
        max_length=100,
        label="City",
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g. Bengaluru, Mumbai, Delhi', 'autofocus': True})
    )
    preferred_area = forms.CharField(
        max_length=100,
        required=False,
        label="Area / Neighborhood (Optional)",
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g. Koramangala, Bandra West, Indiranagar'})
    )


class SignupStep5PasswordForm(forms.Form):
    password = forms.CharField(
        min_length=8,
        label="Password",
        widget=forms.PasswordInput(attrs={'class': 'form-control', 'placeholder': 'At least 8 characters', 'autofocus': True})
    )
    password_confirm = forms.CharField(
        label="Confirm Password",
        widget=forms.PasswordInput(attrs={'class': 'form-control', 'placeholder': 'Re-enter your password'})
    )

    def __init__(self, *args, user_email=None, **kwargs):
        self.user_email = user_email
        super().__init__(*args, **kwargs)

    def clean(self):
        cleaned_data = super().clean()
        p1 = cleaned_data.get('password')
        p2 = cleaned_data.get('password_confirm')
        if p1 and p2:
            if p1 != p2:
                self.add_error('password_confirm', "Passwords do not match.")
            else:
                dummy_user = User(username=self.user_email or 'temp', email=self.user_email or '')
                try:
                    validate_password(p1, user=dummy_user)
                except ValidationError as e:
                    self.add_error('password', e)
        return cleaned_data


class InterestsSelectionForm(forms.Form):
    selected_interests = forms.MultipleChoiceField(
        choices=INTEREST_CHOICES,
        required=False,
        widget=forms.CheckboxSelectMultiple(attrs={'class': 'btn-check'}),
        label="Choose topics you care about"
    )
    custom_interests = forms.CharField(
        required=False,
        label="Other Interests (Optional)",
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g. Board games, Philosophy, Pottery, Robotics'})
    )

    def get_combined_interests(self):
        selected = self.cleaned_data.get('selected_interests', [])
        custom = self.cleaned_data.get('custom_interests', '').strip()
        all_items = list(selected)
        if custom:
            all_items.extend([item.strip() for item in custom.split(',') if item.strip()])
        return ", ".join(all_items)


class UserProfileUpdateForm(forms.ModelForm):
    first_name = forms.CharField(max_length=100, required=False, widget=forms.TextInput(attrs={'class': 'form-control'}))
    last_name = forms.CharField(max_length=100, required=False, widget=forms.TextInput(attrs={'class': 'form-control'}))
    email = forms.EmailField(required=False, widget=forms.EmailInput(attrs={'class': 'form-control', 'readonly': 'readonly'}))

    class Meta:
        model = UserProfile
        fields = ['profile_type', 'age', 'interests', 'preferred_city', 'preferred_area', 'organization_name']
        widgets = {
            'profile_type': forms.Select(attrs={'class': 'form-select'}),
            'age': forms.NumberInput(attrs={'class': 'form-control'}),
            'interests': forms.TextInput(attrs={'class': 'form-control'}),
            'preferred_city': forms.TextInput(attrs={'class': 'form-control'}),
            'preferred_area': forms.TextInput(attrs={'class': 'form-control'}),
            'organization_name': forms.TextInput(attrs={'class': 'form-control'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance and self.instance.user:
            self.fields['first_name'].initial = self.instance.user.first_name
            self.fields['last_name'].initial = self.instance.user.last_name
            self.fields['email'].initial = self.instance.user.email

    def save(self, commit=True):
        profile = super().save(commit=commit)
        user = profile.user
        user.first_name = self.cleaned_data.get('first_name', '')
        user.last_name = self.cleaned_data.get('last_name', '')
        if commit:
            user.save()
        return profile

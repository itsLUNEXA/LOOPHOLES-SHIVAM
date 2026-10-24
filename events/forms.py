from django import forms
from django.utils import timezone
from django.core.exceptions import ValidationError
from .models import Event, WhatsAppSubmission, Category

VALID_IMAGE_EXTENSIONS = ['.jpg', '.jpeg', '.png', '.webp']
MAX_IMAGE_SIZE_MB = 5


def validate_image_file(image):
    if not image:
        return
    if image.size > MAX_IMAGE_SIZE_MB * 1024 * 1024:
        raise ValidationError(f"Image file size cannot exceed {MAX_IMAGE_SIZE_MB}MB.")
    name = image.name.lower()
    if not any(name.endswith(ext) for ext in VALID_IMAGE_EXTENSIONS):
        raise ValidationError("Only JPG, PNG, and WebP image formats are supported.")


class EventForm(forms.ModelForm):
    start_datetime = forms.DateTimeField(
        widget=forms.DateTimeInput(
            attrs={'type': 'datetime-local', 'class': 'form-control'},
            format='%Y-%m-%dT%H:%M'
        ),
        input_formats=['%Y-%m-%dT%H:%M', '%Y-%m-%d %H:%M:%S', '%Y-%m-%d %H:%M'],
        label="Start Date & Time"
    )
    end_datetime = forms.DateTimeField(
        widget=forms.DateTimeInput(
            attrs={'type': 'datetime-local', 'class': 'form-control'},
            format='%Y-%m-%dT%H:%M'
        ),
        input_formats=['%Y-%m-%dT%H:%M', '%Y-%m-%d %H:%M:%S', '%Y-%m-%d %H:%M'],
        label="End Date & Time"
    )
    registration_deadline = forms.DateTimeField(
        required=False,
        widget=forms.DateTimeInput(
            attrs={'type': 'datetime-local', 'class': 'form-control'},
            format='%Y-%m-%dT%H:%M'
        ),
        input_formats=['%Y-%m-%dT%H:%M', '%Y-%m-%d %H:%M:%S', '%Y-%m-%d %H:%M'],
        label="Registration Deadline (Optional)",
        help_text="Deadline after which registration link is closed"
    )

    class Meta:
        model = Event
        fields = [
            'title',
            'category',
            'intended_audience',
            'description',
            'start_datetime',
            'end_datetime',
            'city',
            'area',
            'venue_name',
            'address',
            'organizer_display_name',
            'is_free',
            'price',
            'registration_url',
            'registration_deadline',
            'poster',
            'original_source_url',
        ]
        widgets = {
            'title': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g. Bangalore AI Founders Breakfast'}),
            'category': forms.Select(attrs={'class': 'form-select'}),
            'intended_audience': forms.Select(attrs={'class': 'form-select'}),
            'description': forms.Textarea(attrs={'class': 'form-control', 'rows': 4, 'placeholder': 'Full description, agenda, prerequisites, etc.'}),
            'city': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g. Bengaluru'}),
            'area': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g. Koramangala 4th Block'}),
            'venue_name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g. 91springboard Coworking'}),
            'address': forms.Textarea(attrs={'class': 'form-control', 'rows': 2, 'placeholder': 'Complete street address, landmarks'}),
            'organizer_display_name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g. Bangalore AI Collective'}),
            'is_free': forms.CheckboxInput(attrs={'class': 'form-check-input', 'id': 'id_is_free'}),
            'price': forms.NumberInput(attrs={'class': 'form-control', 'placeholder': '0.00', 'step': '0.01'}),
            'registration_url': forms.URLInput(attrs={'class': 'form-control', 'placeholder': 'https://luma.com/your-event or https://meetup.com/...'}),
            'poster': forms.FileInput(attrs={'class': 'form-control', 'accept': 'image/*'}),
            'original_source_url': forms.URLInput(attrs={'class': 'form-control', 'placeholder': 'https://twitter.com/... or announcement post'}),
        }

    def clean_poster(self):
        poster = self.cleaned_data.get('poster')
        if poster and hasattr(poster, 'size'):
            validate_image_file(poster)
        return poster

    def clean(self):
        cleaned_data = super().clean()
        start = cleaned_data.get('start_datetime')
        end = cleaned_data.get('end_datetime')
        deadline = cleaned_data.get('registration_deadline')
        is_free = cleaned_data.get('is_free')
        price = cleaned_data.get('price')

        # Check if creating a new event or modifying
        if not self.instance.pk and start and start < timezone.now():
            self.add_error('start_datetime', "New event submissions must have an upcoming start time.")

        if start and end and end <= start:
            self.add_error('end_datetime', "Event end time must be later than start time.")

        if deadline and start and deadline > start:
            self.add_error('registration_deadline', "Registration deadline cannot be after the event start time.")

        if not is_free:
            if price is None:
                self.add_error('price', "Price is required for paid events.")
            elif price < 0:
                self.add_error('price', "Price cannot be negative.")

        return cleaned_data


class WhatsAppEventSubmissionForm(forms.ModelForm):
    # WhatsApp specific inputs
    original_message = forms.CharField(
        widget=forms.Textarea(attrs={
            'class': 'form-control',
            'rows': 5,
            'placeholder': 'Paste the raw text of the WhatsApp forward, flyer text, or group announcement here...'
        }),
        label="Original WhatsApp Message Text",
        help_text="Private: Used by moderators to verify details. Never displayed publicly."
    )
    original_poster = forms.ImageField(
        required=False,
        widget=forms.FileInput(attrs={'class': 'form-control', 'accept': 'image/*'}),
        label="Original Flyer / Screenshot (Optional)",
        help_text="Private: Upload original image received on WhatsApp for admin reference."
    )
    public_permission_confirmed = forms.BooleanField(
        required=True,
        widget=forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        label="I confirm that this event information is meant for public circulation and I have permission to submit it for community discovery."
    )

    # Structured fields for public listing
    start_datetime = forms.DateTimeField(
        widget=forms.DateTimeInput(
            attrs={'type': 'datetime-local', 'class': 'form-control'},
            format='%Y-%m-%dT%H:%M'
        ),
        input_formats=['%Y-%m-%dT%H:%M', '%Y-%m-%d %H:%M:%S', '%Y-%m-%d %H:%M'],
        label="Start Date & Time"
    )
    end_datetime = forms.DateTimeField(
        widget=forms.DateTimeInput(
            attrs={'type': 'datetime-local', 'class': 'form-control'},
            format='%Y-%m-%dT%H:%M'
        ),
        input_formats=['%Y-%m-%dT%H:%M', '%Y-%m-%d %H:%M:%S', '%Y-%m-%d %H:%M'],
        label="End Date & Time"
    )
    registration_deadline = forms.DateTimeField(
        required=False,
        widget=forms.DateTimeInput(
            attrs={'type': 'datetime-local', 'class': 'form-control'},
            format='%Y-%m-%dT%H:%M'
        ),
        input_formats=['%Y-%m-%dT%H:%M', '%Y-%m-%d %H:%M:%S', '%Y-%m-%d %H:%M'],
        label="Registration Deadline (Optional)"
    )

    class Meta:
        model = Event
        fields = [
            'title',
            'category',
            'intended_audience',
            'description',
            'start_datetime',
            'end_datetime',
            'city',
            'area',
            'venue_name',
            'address',
            'organizer_display_name',
            'is_free',
            'price',
            'registration_url',
            'registration_deadline',
            'poster',
        ]
        widgets = {
            'title': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Event title extracted from WhatsApp'}),
            'category': forms.Select(attrs={'class': 'form-select'}),
            'intended_audience': forms.Select(attrs={'class': 'form-select'}),
            'description': forms.Textarea(attrs={'class': 'form-control', 'rows': 4, 'placeholder': 'Structured description formatted for public view'}),
            'city': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'City'}),
            'area': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Area / locality'}),
            'venue_name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Venue or online platform'}),
            'address': forms.Textarea(attrs={'class': 'form-control', 'rows': 2, 'placeholder': 'Address'}),
            'organizer_display_name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Host / organizer name'}),
            'is_free': forms.CheckboxInput(attrs={'class': 'form-check-input', 'id': 'id_is_free'}),
            'price': forms.NumberInput(attrs={'class': 'form-control', 'placeholder': '0.00', 'step': '0.01'}),
            'registration_url': forms.URLInput(attrs={'class': 'form-control', 'placeholder': 'https://...'}),
            'poster': forms.FileInput(attrs={'class': 'form-control', 'accept': 'image/*'}),
        }

    def clean_poster(self):
        poster = self.cleaned_data.get('poster')
        if poster and hasattr(poster, 'size'):
            validate_image_file(poster)
        return poster

    def clean_original_poster(self):
        original_poster = self.cleaned_data.get('original_poster')
        if original_poster and hasattr(original_poster, 'size'):
            validate_image_file(original_poster)
        return original_poster

    def clean(self):
        cleaned_data = super().clean()
        start = cleaned_data.get('start_datetime')
        end = cleaned_data.get('end_datetime')
        deadline = cleaned_data.get('registration_deadline')
        is_free = cleaned_data.get('is_free')
        price = cleaned_data.get('price')

        if not self.instance.pk and start and start < timezone.now():
            self.add_error('start_datetime', "New event submissions must have an upcoming start time.")

        if start and end and end <= start:
            self.add_error('end_datetime', "Event end time must be later than start time.")

        if deadline and start and deadline > start:
            self.add_error('registration_deadline', "Registration deadline cannot be after the event start time.")

        if not is_free:
            if price is None:
                self.add_error('price', "Price is required for paid events.")
            elif price < 0:
                self.add_error('price', "Price cannot be negative.")

        return cleaned_data

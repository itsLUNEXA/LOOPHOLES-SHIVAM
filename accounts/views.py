from django.shortcuts import render, redirect
from django.contrib.auth import login, logout, authenticate
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.contrib import messages
from django.conf import settings
from .forms import (
    EmailLoginForm,
    SignupStep1EmailForm,
    SignupStep2AgeForm,
    SignupStep3UserTypeForm,
    SignupStep4LocationForm,
    SignupStep5PasswordForm,
    InterestsSelectionForm,
    UserProfileUpdateForm,
)
from .models import UserProfile

STEP_FORMS = {
    1: SignupStep1EmailForm,
    2: SignupStep2AgeForm,
    3: SignupStep3UserTypeForm,
    4: SignupStep4LocationForm,
    5: SignupStep5PasswordForm,
}

STEP_TITLES = {
    1: "What's your email?",
    2: "How old are you?",
    3: "Select your profile type",
    4: "Where are you located?",
    5: "Choose a secure password",
}


def login_view(request):
    if request.user.is_authenticated:
        if request.GET.get('type') == 'admin':
            if request.user.is_staff:
                return redirect('admin:index')
            messages.error(request, "Access denied: Staff or administrator permissions required to access the central admin dashboard.")
            return redirect('events:event_list')
        return redirect('events:event_list')

    login_type = (request.POST.get('login_type') or request.GET.get('type') or 'user').lower()
    if login_type not in ('user', 'admin'):
        login_type = 'user'

    next_url = request.POST.get('next') or request.GET.get('next', '')
    form = EmailLoginForm(request.POST or None)

    if request.method == 'POST' and form.is_valid():
        email = form.cleaned_data['email']
        password = form.cleaned_data['password']
        user = authenticate(request, email=email, password=password)

        if not user:
            form.add_error(None, "Invalid email or password. Please verify your credentials.")
        else:
            if login_type == 'admin':
                # Enforce server-side authorization: must be active staff
                if not (user.is_active and user.is_staff):
                    form.add_error(
                        None,
                        "Access denied: This account does not have staff or administrator permissions. Please use User Login."
                    )
                else:
                    login(request, user)
                    messages.success(request, f"Welcome to the Vibento Admin Portal, {user.username}!")
                    next_target = request.POST.get('next') or request.GET.get('next')
                    if next_target and next_target.startswith('/') and not next_target.startswith('//'):
                        return redirect(next_target)
                    return redirect('admin:index')
            else:
                # Standard User Login
                login(request, user)
                messages.success(request, f"Welcome back to Vibento, {user.first_name or user.email}!")
                next_target = request.POST.get('next') or request.GET.get('next')
                if next_target and next_target.startswith('/') and not next_target.startswith('//'):
                    return redirect(next_target)
                return redirect('events:event_list')

    return render(request, 'accounts/login.html', {
        'form': form,
        'login_type': login_type,
        'next': next_url
    })


def logout_view(request):
    logout(request)
    messages.info(request, "You have been logged out.")
    next_target = request.POST.get('next') or request.GET.get('next')
    if next_target and next_target.startswith('/') and not next_target.startswith('//'):
        return redirect(next_target)
    return redirect(getattr(settings, 'LOGOUT_REDIRECT_URL', 'events:landing'))


def signup_view(request):
    if request.user.is_authenticated:
        return redirect('events:event_list')

    signup_data = request.session.get('signup_data', {})

    # Determine current step
    try:
        step = int(request.GET.get('step') or request.POST.get('step', 1))
    except (ValueError, TypeError):
        step = 1
    step = max(1, min(step, 5))

    # Guard: prevent skipping forward without completing prior steps
    if step > 1 and 'email' not in signup_data:
        step = 1
    elif step > 2 and 'age' not in signup_data:
        step = 2
    elif step > 3 and 'profile_type' not in signup_data:
        step = 3
    elif step > 4 and 'preferred_city' not in signup_data:
        step = 4

    # Handle Back button action
    if request.method == 'POST' and request.POST.get('action') == 'back':
        return redirect(f"{request.path}?step={max(1, step - 1)}")

    FormClass = STEP_FORMS[step]
    kwargs = {}
    if step == 5:
        kwargs['user_email'] = signup_data.get('email')

    if request.method == 'POST':
        form = FormClass(request.POST, **kwargs)
        if form.is_valid():
            # Update session with validated fields from current step (exclude passwords from session)
            for k, v in form.cleaned_data.items():
                if k not in ('password', 'password_confirm'):
                    signup_data[k] = v
            request.session['signup_data'] = signup_data

            if step < 5:
                return redirect(f"{request.path}?step={step + 1}")
            else:
                # Step 5 completed: Create user and profile
                email = signup_data['email']
                password = form.cleaned_data['password']

                user = User.objects.create_user(
                    username=email,
                    email=email,
                    password=password
                )

                profile, _ = UserProfile.objects.get_or_create(user=user)
                profile.age = signup_data.get('age')
                profile.profile_type = signup_data.get('profile_type', 'other')
                profile.preferred_city = signup_data.get('preferred_city', '')
                profile.preferred_area = signup_data.get('preferred_area', '')
                profile.save()

                # Clean up session & log in
                if 'signup_data' in request.session:
                    del request.session['signup_data']

                login(request, user, backend='accounts.backends.EmailAuthBackend')
                messages.success(request, "Account created successfully! Personalize your interests below.")
                return redirect('accounts:interests')
    else:
        # Initial form population from session
        initial = {k: signup_data[k] for k in signup_data if k in FormClass.base_fields}
        form = FormClass(initial=initial, **kwargs)

    return render(request, 'accounts/signup_step.html', {
        'form': form,
        'step': step,
        'total_steps': 5,
        'step_title': STEP_TITLES[step],
    })


@login_required
def interests_view(request):
    profile, _ = UserProfile.objects.get_or_create(user=request.user)

    if request.method == 'POST':
        form = InterestsSelectionForm(request.POST)
        if form.is_valid():
            combined = form.get_combined_interests()
            if combined:
                profile.interests = combined
                profile.save()
            messages.success(request, "Preferences saved! Explore upcoming events in your area.")
            return redirect('events:event_list')
    else:
        # Prepopulate existing interests
        current = [i.strip() for i in (profile.interests or '').split(',') if i.strip()]
        form = InterestsSelectionForm(initial={'selected_interests': current})

    return render(request, 'accounts/interests.html', {'form': form})


@login_required
def profile_view(request):
    profile, _ = UserProfile.objects.get_or_create(user=request.user)
    if request.method == 'POST':
        form = UserProfileUpdateForm(request.POST, instance=profile)
        if form.is_valid():
            form.save()
            messages.success(request, "Your profile and community preferences have been updated.")
            return redirect('accounts:profile')
        messages.error(request, "Please check the form for errors.")
    else:
        form = UserProfileUpdateForm(instance=profile)

    return render(request, 'accounts/profile.html', {'form': form, 'profile': profile})

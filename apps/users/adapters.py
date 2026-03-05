from allauth.socialaccount.adapter import DefaultSocialAccountAdapter
from allauth.account.utils import perform_login
from django.conf import settings


class SocialAccountAdapter(DefaultSocialAccountAdapter):
    
    def pre_social_login(self, request, sociallogin):
        """
        Connect existing accounts and bypass email verification
        for social logins.
        """
        # If user is already logged in, skip
        if request.user.is_authenticated:
            return
            
        # If social login has no email, skip
        if not sociallogin.email_addresses:
            return
        
        # Try to find existing user with same email
        from apps.users.models import CustomUser
        try:
            email = sociallogin.email_addresses[0].email
            user = CustomUser.objects.get(email=email)
            # Connect this social account to existing user
            sociallogin.connect(request, user)
        except CustomUser.DoesNotExist:
            pass

    def save_user(self, request, sociallogin, form=None):
        """Save new user from social login with correct defaults."""
        user = super().save_user(request, sociallogin, form)
        # Mark social users as verified immediately
        user.is_verified = True
        user.save(update_fields=['is_verified'])
        return user
    
    def get_connect_redirect_url(self, request, socialaccount):
        return settings.LOGIN_REDIRECT_URL
import logging
logger = logging.getLogger(__name__)
from allauth.socialaccount.adapter import DefaultSocialAccountAdapter
from django.conf import settings
from django.db import IntegrityError


class SocialAccountAdapter(DefaultSocialAccountAdapter):

    def pre_social_login(self, request, sociallogin):
        """
        Connect existing accounts and bypass email verification
        for social logins.
        """
        if request.user.is_authenticated:
            logger.info(f"User {request.user.email} already authenticated, skipping pre_social_login")
            return

        if not sociallogin.email_addresses:
            logger.warning("No email addresses in sociallogin object")
            return

        from apps.users.models import CustomUser
        try:
            email = sociallogin.email_addresses[0].email
            logger.info(f"Looking for existing user with email: {email}")
            user = CustomUser.objects.get(email=email)
            logger.info(f"Found existing user, connecting: {email}")

            # Decide what the incoming flow intends (vendor vs buyer) so we can
            # detect mismatches.  We look for the session hint first, then the
            # next parameter (mirror logic used elsewhere).
            desired_role = 'buyer'
            next_url = ''
            try:
                next_url = (request.GET.get('next', '') or '').lower()
            except Exception:
                pass
            session_role = request.session.get('signup_role')
            if session_role == 'vendor' or 'vendor' in next_url:
                desired_role = 'vendor'

            # if the existing user already has a different role, abort with a
            # friendly error rather than silently changing it.
            if user.role and user.role != desired_role:
                from allauth.exceptions import ImmediateHttpResponse
                from django.contrib import messages
                from django.shortcuts import redirect
                from django.contrib.auth import logout

                # clear the hint so repeated attempts don't keep firing
                try:
                    request.session.pop('signup_role', None)
                    request.session.save()
                except Exception:
                    pass

                # ensure the request is not authenticated (protect against
                # possible downstream login happening despite the exception)
                try:
                    logout(request)
                except Exception:
                    pass

                messages.error(
                    request,
                    f"Email already registered as {user.get_role_display()}. "
                    f"Please log in or use a different address."
                )

                # send them to the login page instead of signup; they already have an account
                raise ImmediateHttpResponse(redirect('users:login'))

            # otherwise, connect the social account and optionally update the
            # role if it was unset (rare) or if we are explicitly elevating
            # during a vendor flow and the user is currently buyer.
            if desired_role == 'vendor' and not user.is_vendor:
                user.role = 'vendor'
                user.save(update_fields=['role'])
                logger.info(f"Updated role to vendor for existing user {user.email}")

            sociallogin.connect(request, user)
        except CustomUser.DoesNotExist:
            logger.info(f"No existing user found for email: {email}, proceeding with new account creation")
            pass
        except Exception as e:
            logger.error(f"Error in pre_social_login: {str(e)}", exc_info=True)
    
    def populate_user(self, request, sociallogin, data):
        """
        Hook to customize user data before save.
        data contains the user info from the OAuth provider.
        """
        try:
            logger.info(f"OAuth Provider: {sociallogin.account.provider}")
            logger.info(f"OAuth Data Keys: {list(data.keys())}")
            logger.debug(f"OAuth Data: {data}")
            user = super().populate_user(request, sociallogin, data)
            # honor session hint or next URL for initial role assignment
            session_role = request.session.get('signup_role') if request else None
            if session_role == 'vendor':
                user.role = 'vendor'
                # keep the session key until save_user cleans it up
            else:
                # we might inspect next parameter as additional hint
                try:
                    next_url = (request.GET.get('next', '') or '').lower()
                except Exception:
                    next_url = ''
                if 'vendor' in next_url and not user.role:
                    user.role = 'vendor'
            return user
        except Exception as e:
            logger.error(f"Error in populate_user: {str(e)}", exc_info=True)
            raise
        

    def save_user(self, request, sociallogin, form=None):
        """Save new user from social login with correct defaults.

        We set ``sociallogin.user.role`` *before* calling the parent method so that
        the initial database insert reflects the desired role.  This allows our
        post_save signals (which create buyer/vendor profiles) to fire with the
        correct value immediately.
        """
        # pre‑populate role based on session/next so super().save_user uses it
        try:
            session_role = None
            if request:
                session_role = request.session.get('signup_role')
                # we intentionally do not pop here; cleanup happens later
            if session_role == 'vendor':
                sociallogin.user.role = 'vendor'
        except Exception:
            pass

        try:
            user = super().save_user(request, sociallogin, form)
            logger.info(f"User created from social login: {user.email}")
        except Exception as e:
            logger.error(f"Error creating user from social login: {str(e)}", exc_info=True)
            raise
        
        try:
            # Ensure all required fields are set for social login
            username = user.username
            if not username:
                # Generate username from email if not set
                email_prefix = user.email.split('@')[0]
                username = email_prefix
            
            logger.info(f"Updating user fields - username: {username}, email: {user.email}")
            
            # Mark as verified since they authenticated via social provider
            user.is_verified = True
            user.is_active = True  # Ensure account is active
            # respect vendor signup flag stored in session or next_url
            session_role = None
            try:
                session_role = request.session.get('signup_role')
            except Exception:
                pass
            if session_role == 'vendor':
                user.role = 'vendor'
            elif not user.role:
                user.role = 'buyer'  # Default role for new social login users
            # cleanup session key to avoid reuse
            if 'signup_role' in request.session:
                del request.session['signup_role']
            user.username = username
            
            logger.info(f"About to save user with: username={user.username}, is_verified={user.is_verified}, is_active={user.is_active}, role={user.role}")
            
            # Save and catch any signal-related exceptions
            try:
                user.save(update_fields=['username', 'is_verified', 'is_active', 'role'])
                logger.info(f"User save successful: {user.email}")
            except Exception as signal_error:
                logger.error(f"Error during user.save() (likely signal-related): {str(signal_error)}", exc_info=True)
                # Try to save without the role field update if the issue is role-related
                if 'role' in str(signal_error):
                    logger.info("Attempting save without role field...")
                    user.save(update_fields=['username', 'is_verified', 'is_active'])
                else:
                    raise
            
            logger.info(f"Social login user setup complete: {user.email} (verified={user.is_verified}, active={user.is_active}, role={user.role})")
            return user
        except IntegrityError as e:
            logger.error(f"IntegrityError saving user fields: {str(e)}", exc_info=True)
            raise
        except Exception as e:
            logger.error(f"Error setting user fields after social login: {str(e)}", exc_info=True)
            raise
    
    def get_connect_redirect_url(self, request, socialaccount):
        """Redirect to login success page after connecting social account."""
        # After connecting an account the user will already be logged in,
        # so we can safely redirect based on their role.
        user = request.user
        try:
            if user.is_vendor:
                from django.urls import reverse
                return reverse('vendors:dashboard')
            if user.is_buyer:
                from django.urls import reverse
                return reverse('users:buyer_dashboard')
        except Exception:
            pass
        return settings.LOGIN_REDIRECT_URL

    def get_login_redirect_url(self, request):
        """Determine where to send user after social login or normal login.
        allauth uses this method for both registration and login redirects.
        """
        user = request.user
        try:
            if user.is_vendor:
                from django.urls import reverse
                return reverse('vendors:dashboard')
            if user.is_buyer:
                from django.urls import reverse
                return reverse('users:buyer_dashboard')
        except Exception:
            pass
        # fall back to default
        return settings.LOGIN_REDIRECT_URL
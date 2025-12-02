from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from .models import CustomUser

class CustomUserAdmin(UserAdmin):
    model = CustomUser
    # Use the model's get_full_name method and existing fields
    list_display = ('email', 'get_full_name', 'role', 'is_verified', 'is_active')
    list_filter = ('role', 'is_verified', 'is_active')
    ordering = ('email',)
    # search_fields must reference model fields (not properties/methods)
    search_fields = ('email', 'username')

    fieldsets = (
        (None, {'fields': ('email', 'password')}),
        # model stores username (used as display name) rather than full_name
        ('Personal info', {'fields': ('username', 'role')}),
        # model uses otp_code field name
        ('Verification', {'fields': ('is_verified', 'otp_code')}),
        ('Permissions', {'fields': ('is_active', 'is_staff', 'is_superuser')}),
    )

    add_fieldsets = (
        (None, {
            'classes': ('wide',),
            'fields': ('email', 'password1', 'password2', 'role', 'is_active', 'is_verified')}
        ),
    )

admin.site.register(CustomUser, CustomUserAdmin)

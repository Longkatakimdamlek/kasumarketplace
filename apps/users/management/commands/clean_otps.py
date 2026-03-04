"""
Management command to clean expired and old OTPs.
Location: apps/users/management/commands/clean_otps.py

Django management command that can be scheduled via cron or Celery to
automatically remove expired and old used OTPs from the database.

Usage:
    python manage.py clean_otps
    python manage.py clean_otps --keep-days 7
"""

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from apps.users.services import OTPService


class Command(BaseCommand):
    """
    Clean expired and old used OTPs from the database.
    """
    
    help = 'Remove expired OTPs and old used OTPs from the database'
    
    def add_arguments(self, parser):
        """Define command arguments."""
        parser.add_argument(
            '--keep-days',
            type=int,
            default=7,
            help='Number of days to keep used OTPs (default: 7)'
        )
        parser.add_argument(
            '--expired-only',
            action='store_true',
            help='Only clean expired OTPs, not old used ones'
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show what would be deleted without actually deleting'
        )
    
    def handle(self, *args, **options):
        """Execute the cleanup command."""
        keep_days = options['keep_days']
        expired_only = options['expired_only']
        dry_run = options['dry_run']
        
        if dry_run:
            self.stdout.write(
                self.style.WARNING('DRY RUN: No data will be deleted')
            )
        
        try:
            # Clean expired OTPs
            if dry_run:
                self.stdout.write('Would clean expired OTPs...')
            else:
                expired_count = OTPService.clean_expired_otps()
                self.stdout.write(
                    self.style.SUCCESS(f'✓ Deleted {expired_count} expired OTPs')
                )
            
            # Clean old used OTPs
            if not expired_only:
                if dry_run:
                    self.stdout.write(
                        f'Would clean used OTPs older than {keep_days} days...'
                    )
                else:
                    used_count = OTPService.clean_used_otps(days=keep_days)
                    self.stdout.write(
                        self.style.SUCCESS(
                            f'✓ Deleted {used_count} used OTPs older than {keep_days} days'
                        )
                    )
            
            total_msg = 'OTP cleanup completed'
            if dry_run:
                self.stdout.write(self.style.WARNING(f'{total_msg} (dry run)'))
            else:
                self.stdout.write(self.style.SUCCESS(f'✓ {total_msg}'))
        
        except Exception as e:
            raise CommandError(f'Error cleaning OTPs: {str(e)}')

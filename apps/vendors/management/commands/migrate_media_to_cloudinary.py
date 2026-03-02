from django.core.management.base import BaseCommand
from django.core.files import File
from django.conf import settings
import os

from apps.vendors.models import ProductImage, Store, VendorProfile


class Command(BaseCommand):
    help = 'Upload existing local media files to Cloudinary for models using CloudinaryField'

    def handle(self, *args, **options):
        models_and_fields = [
            (ProductImage, 'image'),
            (Store, 'logo'),
            (Store, 'banner'),
            (VendorProfile, 'photo_from_nin'),
            (VendorProfile, 'student_id_image'),
            (VendorProfile, 'selfie'),
        ]

        for model, field in models_and_fields:
            qs = model.objects.exclude(**{f"{field}__isnull": True}).exclude(**{f"{field}": ""})
            for obj in qs.iterator():
                ffield = getattr(obj, field)

                # If field already references Cloudinary (public_id or cloud URL), skip
                try:
                    url = getattr(ffield, 'url', '')
                except Exception:
                    url = ''

                if url and 'res.cloudinary.com' in url:
                    self.stdout.write(f"Skipping {model.__name__} id={obj.pk} {field} already in Cloudinary (url)")
                    continue

                # Some Cloudinary-backed objects expose 'public_id' instead of 'name'
                public_id = getattr(ffield, 'public_id', None)
                if public_id:
                    self.stdout.write(f"Skipping {model.__name__} id={obj.pk} {field} already in Cloudinary (public_id={public_id})")
                    continue

                # For locally-stored files (FieldFile), use .name
                name = getattr(ffield, 'name', None)
                if not name:
                    self.stdout.write(f"No filename for {model.__name__} id={obj.pk} {field}; skipping")
                    continue

                # Try to find the local file under MEDIA_ROOT
                local_path = os.path.join(getattr(settings, 'MEDIA_ROOT', ''), name)
                if not os.path.exists(local_path):
                    # try relative path fallback
                    local_path = os.path.join(settings.BASE_DIR, name) if hasattr(settings, 'BASE_DIR') else name

                if not os.path.exists(local_path):
                    self.stdout.write(f"Local file not found for {model.__name__} id={obj.pk}: {local_path}")
                    continue

                try:
                    with open(local_path, 'rb') as fh:
                        django_file = File(fh)
                        # saving the same name will use DEFAULT_FILE_STORAGE (Cloudinary)
                        getattr(obj, field).save(os.path.basename(name), django_file, save=True)
                        self.stdout.write(f"Uploaded {model.__name__} id={obj.pk} -> Cloudinary")
                except Exception as exc:
                    self.stderr.write(f"Failed to upload {model.__name__} id={obj.pk}: {exc}")

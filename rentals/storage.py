"""Explicit local-filesystem / production-Supabase storage for Django uploads."""
import os
import uuid
import mimetypes
from urllib.parse import urlparse
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.core.files.storage import FileSystemStorage, Storage
from django.utils.deconstruct import deconstructible
@deconstructible
class SupabaseStorage(Storage):
    """
    Compatibility-stable storage class. It selects filesystem storage only
    when UPLOAD_STORAGE_BACKEND explicitly requests it; otherwise it uses
    Supabase. Keeping this class path preserves existing migration state.

    Supabase settings in the environment:
    - SUPABASE_URL=https://your-project.supabase.co
    - SUPABASE_KEY=your-service-role-key
    - SUPABASE_BUCKET=unit-images
    - SUPABASE_USER_FILES_BUCKET=user-files
    """
    
    def __init__(self, bucket=None, **kwargs):
        self.bucket_name = bucket or os.environ.get('SUPABASE_BUCKET', 'unit-images')
        self.supabase_url = os.environ.get('SUPABASE_URL', '')
        self.supabase_key = os.environ.get('SUPABASE_KEY', '')
        self._client = None
        super().__init__(**kwargs)

    def _local_storage(self):
        """Return filesystem storage only when explicitly selected by settings."""
        backend = getattr(settings, "UPLOAD_STORAGE_BACKEND", "supabase")
        if getattr(settings, "IS_PRODUCTION", False) and backend != "supabase":
            raise ImproperlyConfigured("Production uploads must use Supabase storage.")
        if backend == "filesystem":
            return FileSystemStorage(location=settings.MEDIA_ROOT, base_url=settings.MEDIA_URL)
        if backend == "supabase":
            return None
        raise ImproperlyConfigured(
            "UPLOAD_STORAGE_BACKEND must be either 'filesystem' or 'supabase'."
        )
    
    @property
    def client(self):
        """Lazy initialization of Supabase client."""
        if self._client is None:
            from supabase import create_client, Client
            if not self.supabase_url or not self.supabase_key:
                raise ValueError("SUPABASE_URL and SUPABASE_KEY must be set in environment")
            self._client = create_client(self.supabase_url, self.supabase_key)
        return self._client
    
    def _open(self, name, mode='rb'):
        """Open from the explicitly selected backend."""
        local_storage = self._local_storage()
        if local_storage:
            return local_storage.open(name, mode)

        from django.core.files.base import ContentFile
        
        try:
            response = self.client.storage.from_(self.bucket_name).download(name)
            return ContentFile(response, name=name)
        except Exception as e:
            raise FileNotFoundError(f"File {name} not found in Supabase: {e}")
    
    def _save(self, name, content):
        """Upload file to Supabase Storage."""
        # Generate unique filename to prevent collisions
        ext = os.path.splitext(name)[1]
        folder = os.path.dirname(name).replace("\\", "/").strip("/")
        unique_filename = f"{uuid.uuid4().hex}{ext}"
        unique_name = f"{folder}/{unique_filename}" if folder else unique_filename

        local_storage = self._local_storage()
        if local_storage:
            if hasattr(content, 'seek'):
                content.seek(0)
            return local_storage.save(unique_name, content)
        
        # Read file content
        if hasattr(content, 'seek'):
            content.seek(0)
        file_bytes = content.read()
        
        # Upload to Supabase
        def upload_with_bucket(bucket_name):
            return self.client.storage.from_(bucket_name).upload(
                path=unique_name,
                file=file_bytes,
                file_options={
                    'content-type': content_type,
                    'upsert': 'false'
                }
            )

        content_type = getattr(content, 'content_type', None) or mimetypes.guess_type(name)[0] or 'application/octet-stream'
        try:
            result = upload_with_bucket(self.bucket_name)
            return unique_name
        except Exception as e:
            error_text = str(e).lower()
            if self.bucket_name == 'user-files' and 'bucket not found' in error_text:
                self.bucket_name = 'uesr-files'
                result = upload_with_bucket(self.bucket_name)
                return unique_name
            if 'already exists' in error_text:
                unique_filename = f"{uuid.uuid4().hex}{ext}"
                unique_name = f"{folder}/{unique_filename}" if folder else unique_filename
                result = upload_with_bucket(self.bucket_name)
                return unique_name
            raise
    
    def delete(self, name):
        """Delete a file from the explicitly selected upload backend."""
        local_storage = self._local_storage()
        if local_storage:
            return local_storage.delete(name)
        try:
            self.client.storage.from_(self.bucket_name).remove([name])
        except Exception:
            # File might not exist, ignore
            pass
    
    def exists(self, name):
        """Check whether a file exists in the selected upload backend."""
        local_storage = self._local_storage()
        if local_storage:
            return local_storage.exists(name)
        try:
            # Try to get file info
            self.client.storage.from_(self.bucket_name).list(name.rsplit('/', 1)[0] if '/' in name else '')
            return True
        except Exception:
            return False
    
    def url(self, name):
        """Return the public URL for the file."""
        if not name:
            return None

        local_storage = self._local_storage()
        if local_storage:
            return local_storage.url(name)

        bucket = self.client.storage.from_(self.bucket_name)
        signed_bucket_name = os.environ.get('SUPABASE_USER_FILES_BUCKET', 'user-files')
        if self.bucket_name == signed_bucket_name:
            try:
                signed_response = bucket.create_signed_url(name, 86400)
                if isinstance(signed_response, dict):
                    return (
                        signed_response.get('signedURL')
                        or signed_response.get('signedUrl')
                        or signed_response.get('signed_url')
                    )
                return signed_response
            except Exception:
                pass

        try:
            return bucket.get_public_url(name)
        except Exception:
            # Fallback: construct URL manually using the configured bucket.
            return f"{self.supabase_url}/storage/v1/object/public/{self.bucket_name}/{name}"
    
    def size(self, name):
        """Return file size in bytes."""
        local_storage = self._local_storage()
        if local_storage:
            return local_storage.size(name)
        # This is expensive in Supabase, return 0 for now
        return 0

    def path(self, name):
        local_storage = self._local_storage()
        if local_storage:
            return local_storage.path(name)
        return super().path(name)

    def listdir(self, path):
        local_storage = self._local_storage()
        if local_storage:
            return local_storage.listdir(path)
        return super().listdir(path)

    def get_accessed_time(self, name):
        local_storage = self._local_storage()
        if local_storage:
            return local_storage.get_accessed_time(name)
        return super().get_accessed_time(name)

    def get_created_time(self, name):
        local_storage = self._local_storage()
        if local_storage:
            return local_storage.get_created_time(name)
        return super().get_created_time(name)

    def get_modified_time(self, name):
        local_storage = self._local_storage()
        if local_storage:
            return local_storage.get_modified_time(name)
        return super().get_modified_time(name)
    
    def get_available_name(self, name, max_length=None):
        """Generate a unique name for the file."""
        local_storage = self._local_storage()
        if local_storage:
            return local_storage.get_available_name(name, max_length)
        return name


# Convenience function for direct uploads
def upload_to_supabase(file_obj, bucket='unit-images', folder='units'):
    """
    Direct upload helper for views/forms.
    
    Args:
        file_obj: Django UploadedFile or file-like object
        bucket: Supabase bucket name
        folder: Folder prefix in bucket
    
    Returns:
        str: Public URL of uploaded file
    """
    storage = SupabaseStorage(bucket=bucket)
    
    # Generate path with folder
    ext = os.path.splitext(file_obj.name)[1]
    filename = f"{folder}/{uuid.uuid4().hex}{ext}" if folder else f"{uuid.uuid4().hex}{ext}"
    
    # Save and get URL
    saved_name = storage._save(filename, file_obj)
    return storage.url(saved_name)


def get_user_files_storage():
    """Storage backend for private tenant-uploaded files."""
    return SupabaseStorage(bucket=os.environ.get('SUPABASE_USER_FILES_BUCKET', 'user-files'))

"""
Supabase Storage backend for Django.
Uploads files to Supabase Storage instead of local filesystem.
"""
import os
import uuid
from urllib.parse import urlparse
from django.conf import settings
from django.core.files.storage import Storage
from django.utils.deconstruct import deconstructible
@deconstructible
class SupabaseStorage(Storage):
    """
    Django storage backend for Supabase Storage.
    
    Required settings in .env:
    - SUPABASE_URL=https://your-project.supabase.co
    - SUPABASE_KEY=your-service-role-key
    - SUPABASE_BUCKET=unit-images
    """
    
    def __init__(self, bucket=None, **kwargs):
        self.bucket_name = bucket or os.environ.get('SUPABASE_BUCKET', 'unit-images')
        self.supabase_url = os.environ.get('SUPABASE_URL', '')
        self.supabase_key = os.environ.get('SUPABASE_KEY', '')
        self._client = None
        super().__init__(**kwargs)
    
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
        """Open file from Supabase - returns file-like object."""
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
        unique_name = f"{uuid.uuid4().hex}{ext}"
        
        # Read file content
        if hasattr(content, 'seek'):
            content.seek(0)
        file_bytes = content.read()
        
        # Upload to Supabase
        try:
            result = self.client.storage.from_(self.bucket_name).upload(
                path=unique_name,
                file=file_bytes,
                file_options={
                    'content-type': getattr(content, 'content_type', 'application/octet-stream'),
                    'upsert': 'false'
                }
            )
            
            # Return the public URL path
            return unique_name
            
        except Exception as e:
            # If file exists, try with different UUID
            if "already exists" in str(e).lower():
                unique_name = f"{uuid.uuid4().hex}{ext}"
                result = self.client.storage.from_(self.bucket_name).upload(
                    path=unique_name,
                    file=file_bytes,
                    file_options={'upsert': 'false'}
                )
                return unique_name
            raise
    
    def delete(self, name):
        """Delete file from Supabase."""
        try:
            self.client.storage.from_(self.bucket_name).remove([name])
        except Exception:
            # File might not exist, ignore
            pass
    
    def exists(self, name):
        """Check if file exists in Supabase."""
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
        
        # Get public URL from Supabase
        try:
            public_url = self.client.storage.from_(self.bucket_name).get_public_url(name)
            return public_url
        except Exception:
            # Fallback: construct URL manually
            return f"{self.supabase_url}/storage/v1/object/public/{self.bucket_name}/{name}"
    
    def size(self, name):
        """Return file size in bytes."""
        # This is expensive in Supabase, return 0 for now
        return 0
    
    def get_available_name(self, name, max_length=None):
        """Generate a unique name for the file."""
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

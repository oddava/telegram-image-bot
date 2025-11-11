import asyncio
import io
from concurrent.futures.thread import ThreadPoolExecutor

from minio import Minio
from urllib.parse import urljoin

from .config import settings


class S3Client:
    def __init__(self):
        self.client = Minio(
            settings.minio_endpoint,
            access_key=settings.minio_access_key,
            secret_key=settings.minio_secret_key,
            secure=settings.minio_use_ssl,
        )
        self.bucket_name = settings.minio_bucket_name
        self.public_url = settings.minio_public_url
        self.executor = ThreadPoolExecutor(max_workers=4)
        self._bucket_checked = False  # ✅ Add flag

    def _ensure_bucket(self):
        """Ensure bucket exists - called lazily on first use"""
        if self._bucket_checked:
            return

        try:
            if not self.client.bucket_exists(self.bucket_name):
                self.client.make_bucket(self.bucket_name)
            self._bucket_checked = True
        except Exception as e:
            print(f"Warning: Could not check/create bucket: {e}")
            # Don't raise - let the actual operation fail if needed

    async def upload_file(self, file_data: bytes, object_key: str, content_type: str = "image/png") -> str:
        """Async wrapper for upload"""
        self._ensure_bucket()
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(
            self.executor,
            self._upload_sync,
            file_data,
            object_key,
            content_type
        )
        return self.get_public_url(object_key)

    def _upload_sync(self, file_data: bytes, object_key: str, content_type: str):
        """Synchronous upload logic"""
        file_stream = io.BytesIO(file_data)
        self.client.put_object(
            bucket_name=self.bucket_name,
            object_name=object_key,
            data=file_stream,
            length=len(file_data),
            content_type=content_type,
        )

    async def download_file(self, object_key: str) -> bytes:
        """Async wrapper for download"""
        self._ensure_bucket()
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            self.executor,
            self._download_sync,
            object_key
        )

    def _download_sync(self, object_key: str) -> bytes:
        """Synchronous download logic"""
        response = self.client.get_object(self.bucket_name, object_key)
        data = response.read()
        response.close()
        response.release_conn()
        return data

    def get_public_url(self, object_key: str) -> str:
        return urljoin(f"{self.public_url}/", f"{self.bucket_name}/{object_key}")

    async def delete_file(self, object_key: str):
        """Async wrapper for delete"""
        self._ensure_bucket()
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(
            self.executor,
            self.client.remove_object,
            self.bucket_name,
            object_key
        )


s3_client = S3Client()  # ✅ Now safe to import
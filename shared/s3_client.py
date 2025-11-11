import io
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
        self._ensure_bucket()

    def _ensure_bucket(self):
        if not self.client.bucket_exists(self.bucket_name):
            self.client.make_bucket(self.bucket_name)

    def upload_file(self, file_data: bytes, object_key: str, content_type: str = "image/png") -> str:
        file_stream = io.BytesIO(file_data)
        self.client.put_object(
            bucket_name=self.bucket_name,
            object_name=object_key,
            data=file_stream,
            length=len(file_data),
            content_type=content_type,
        )
        return self.get_public_url(object_key)

    def download_file(self, object_key: str) -> bytes:
        response = self.client.get_object(self.bucket_name, object_key)
        data = response.read()
        response.close()
        response.release_conn()
        return data

    def get_public_url(self, object_key: str) -> str:
        return urljoin(f"{self.public_url}/", f"{self.bucket_name}/{object_key}")

    def delete_file(self, object_key: str):
        self.client.remove_object(self.bucket_name, object_key)


s3_client = S3Client()
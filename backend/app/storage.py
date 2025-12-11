import os
from minio import Minio
from minio.error import S3Error
from datetime import timedelta
from dotenv import load_dotenv

load_dotenv()

MINIO_ENDPOINT = os.getenv("MINIO_ENDPOINT", "localhost:9000").replace("http://", "").replace("https://", "")
MINIO_ACCESS_KEY = os.getenv("MINIO_ACCESS_KEY", "minioadmin")
MINIO_SECRET_KEY = os.getenv("MINIO_SECRET_KEY", "minioadmin")
MINIO_SECURE = False # Set to True if using https

BUCKET_NAME = "logion-files"

client = Minio(
    MINIO_ENDPOINT,
    access_key=MINIO_ACCESS_KEY,
    secret_key=MINIO_SECRET_KEY,
    secure=MINIO_SECURE
)

def ensure_bucket_exists():
    try:
        if not client.bucket_exists(BUCKET_NAME):
            client.make_bucket(BUCKET_NAME)
    except S3Error as err:
        print(f"MinIO Error: {err}")

def upload_file(file_data, object_name, content_type="application/octet-stream"):
    ensure_bucket_exists()
    try:
        # file_data is bytes or a file-like object
        # If bytes, wrap in BytesIO
        import io
        if isinstance(file_data, bytes):
            data = io.BytesIO(file_data)
            length = len(file_data)
        else:
            data = file_data
            # Try to get length if possible, or read into memory (careful with large files)
            # For UploadFile from FastAPI, it's a SpooledTemporaryFile
            file_data.seek(0, 2)
            length = file_data.tell()
            file_data.seek(0)
            data = file_data

        client.put_object(
            BUCKET_NAME,
            object_name,
            data,
            length,
            content_type=content_type
        )
        return object_name
    except S3Error as err:
        print(f"MinIO Upload Error: {err}")
        raise err

def download_file(object_name, file_path):
    ensure_bucket_exists()
    try:
        client.fget_object(BUCKET_NAME, object_name, file_path)
    except S3Error as err:
        print(f"MinIO Download Error: {err}")
        raise err

def get_file_url(object_name):
    ensure_bucket_exists()
    try:
        url = client.get_presigned_url(
            "GET",
            BUCKET_NAME,
            object_name,
            expires=timedelta(hours=2)
        )
        return url
    except S3Error as err:
        print(f"MinIO URL Error: {err}")
        return None

def delete_file(object_name):
    ensure_bucket_exists()
    try:
        client.remove_object(BUCKET_NAME, object_name)
    except S3Error as err:
        print(f"MinIO Delete Error: {err}")

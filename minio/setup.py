import os
from minio import Minio

MINIO_ENDPOINT = os.getenv("MINIO_ENDPOINT", "minio:9000")
MINIO_ACCESS_KEY = os.getenv("MINIO_ACCESS_KEY", "minioadmin")
MINIO_SECRET_KEY = os.getenv("MINIO_SECRET_KEY", "minioadmin")
MINIO_BUCKET = os.getenv("MINIO_BUCKET", "ragreader-files")

client = Minio(
    MINIO_ENDPOINT,
    access_key=MINIO_ACCESS_KEY,
    secret_key=MINIO_SECRET_KEY,
    secure=False,
)

if not client.bucket_exists(MINIO_BUCKET):
    client.make_bucket(MINIO_BUCKET)
    print(f"Bucket '{MINIO_BUCKET}' created")
else:
    print(f"Bucket '{MINIO_BUCKET}' already exists")

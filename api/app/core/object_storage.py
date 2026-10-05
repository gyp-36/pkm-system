"""S3-compatible object storage used for immutable note-file versions."""

from __future__ import annotations

import os
from typing import Any, BinaryIO

import boto3
from botocore.client import Config
from botocore.exceptions import ClientError


BUCKET = os.getenv("OBJECT_STORAGE_BUCKET", "pkm-files")
INTERNAL_ENDPOINT = os.getenv("OBJECT_STORAGE_ENDPOINT", "http://minio:9000")
PUBLIC_ENDPOINT = os.getenv("OBJECT_STORAGE_PUBLIC_ENDPOINT", "http://localhost:19000")
REGION = os.getenv("OBJECT_STORAGE_REGION", "us-east-1")


def _client(*, browser_endpoint: bool = False):
    endpoint = PUBLIC_ENDPOINT if browser_endpoint else INTERNAL_ENDPOINT
    return boto3.client(
        "s3",
        endpoint_url=endpoint,
        region_name=REGION,
        aws_access_key_id=os.getenv("OBJECT_STORAGE_ACCESS_KEY", ""),
        aws_secret_access_key=os.getenv("OBJECT_STORAGE_SECRET_KEY", ""),
        config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
    )


def ensure_bucket() -> None:
    client = _client()
    try:
        client.head_bucket(Bucket=BUCKET)
    except ClientError as exc:
        code = str(exc.response.get("Error", {}).get("Code", ""))
        if code not in {"404", "NoSuchBucket", "NotFound"}:
            raise
        client.create_bucket(Bucket=BUCKET)
    # MinIO 通过 MINIO_API_CORS_ALLOW_ORIGIN 全局配置浏览器跨域访问。
    # 部分 MinIO 版本未实现 S3 的 PutBucketCors 操作。


def put(key: str, content: bytes, media_type: str) -> None:
    _client().put_object(Bucket=BUCKET, Key=key, Body=content, ContentType=media_type)


def get(key: str) -> bytes:
    response = _client().get_object(Bucket=BUCKET, Key=key)
    return response["Body"].read()


def open_object(key: str) -> BinaryIO:
    return _client().get_object(Bucket=BUCKET, Key=key)["Body"]


def delete(key: str) -> None:
    _client().delete_object(Bucket=BUCKET, Key=key)


def create_multipart(key: str, media_type: str) -> str:
    return _client().create_multipart_upload(Bucket=BUCKET, Key=key, ContentType=media_type)["UploadId"]


def part_url(key: str, upload_id: str, part_number: int) -> str:
    return _client(browser_endpoint=True).generate_presigned_url(
        "upload_part",
        Params={"Bucket": BUCKET, "Key": key, "UploadId": upload_id, "PartNumber": part_number},
        ExpiresIn=900,
        HttpMethod="PUT",
    )


def complete_multipart(key: str, upload_id: str, parts: list[dict[str, Any]]) -> None:
    _client().complete_multipart_upload(
        Bucket=BUCKET,
        Key=key,
        UploadId=upload_id,
        MultipartUpload={"Parts": [{"PartNumber": item["part_number"], "ETag": item["etag"]} for item in parts]},
    )


def abort_multipart(key: str, upload_id: str) -> None:
    try:
        _client().abort_multipart_upload(Bucket=BUCKET, Key=key, UploadId=upload_id)
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") not in {"NoSuchUpload", "404"}:
            raise


def head(key: str) -> dict[str, Any]:
    return _client().head_object(Bucket=BUCKET, Key=key)


def hash_object(key: str) -> tuple[str, int]:
    import hashlib

    response = _client().get_object(Bucket=BUCKET, Key=key)
    digest = hashlib.sha256()
    size = 0
    body = response["Body"]
    try:
        while chunk := body.read(1024 * 1024):
            digest.update(chunk)
            size += len(chunk)
    finally:
        body.close()
    return digest.hexdigest(), size


def presign_download(key: str, filename: str, expires: int = 300) -> str:
    return _client(browser_endpoint=True).generate_presigned_url(
        "get_object",
        Params={"Bucket": BUCKET, "Key": key, "ResponseContentDisposition": f'attachment; filename="{filename}"'},
        ExpiresIn=expires,
    )

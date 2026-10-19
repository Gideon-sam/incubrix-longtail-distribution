"""
Lightweight MinIO / S3 mock server for IncuBrix evidence and manifest storage.
Provides S3 API endpoints for bucket management and object storage,
plus /minio/health/live and /minio/health/ready for health checks.
"""
from __future__ import annotations
import os
import hashlib
from pathlib import Path
from fastapi import FastAPI, Request, Response, HTTPException

DATA_DIR = Path(os.getenv("MINIO_DATA_DIR", "/data"))
DATA_DIR.mkdir(parents=True, exist_ok=True)

app = FastAPI(title="MinIO S3 Mock Server")

# Track buckets in memory and on disk
_buckets: set[str] = {"incubrix-evidence", "incubrix"}


@app.get("/minio/health/live")
@app.get("/minio/health/ready")
@app.get("/health")
def health():
    return {"status": "ok"}


@app.head("/")
@app.get("/")
def list_buckets():
    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<ListAllMyBucketsResult xmlns="http://s3.amazonaws.com/doc/2006-03-01/">'
        "<Owner><ID>incubrix</ID><DisplayName>incubrix</DisplayName></Owner>"
        "<Buckets>"
        + "".join(f"<Bucket><Name>{b}</Name></Bucket>" for b in _buckets)
        + "</Buckets></ListAllMyBucketsResult>"
    )
    return Response(content=xml, media_type="application/xml")


@app.head("/{bucket}")
@app.head("/{bucket}/")
def head_bucket(bucket: str):
    if bucket in _buckets or (DATA_DIR / bucket).is_dir():
        return Response(status_code=200)
    return Response(status_code=404)


@app.get("/{bucket}")
@app.get("/{bucket}/")
def get_bucket(bucket: str):
    if bucket not in _buckets and not (DATA_DIR / bucket).is_dir():
        return Response(status_code=404)
    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        f'<ListBucketResult xmlns="http://s3.amazonaws.com/doc/2006-03-01/">'
        f"<Name>{bucket}</Name>"
        f"<Prefix></Prefix>"
        f"<Marker></Marker>"
        f"<MaxKeys>1000</MaxKeys>"
        f"<IsTruncated>false</IsTruncated>"
        f"</ListBucketResult>"
    )
    return Response(content=xml, media_type="application/xml")


@app.put("/{bucket}")
@app.put("/{bucket}/")
def make_bucket(bucket: str):
    _buckets.add(bucket)
    (DATA_DIR / bucket).mkdir(parents=True, exist_ok=True)
    return Response(status_code=200)


@app.head("/{bucket}/{key:path}")
def head_object(bucket: str, key: str):
    obj_path = DATA_DIR / bucket / key
    if not obj_path.is_file():
        return Response(status_code=404)
    size = obj_path.stat().st_size
    etag = hashlib.md5(obj_path.read_bytes()).hexdigest()
    return Response(
        status_code=200,
        headers={
            "ETag": f'"{etag}"',
            "Content-Length": str(size),
            "Content-Type": "application/octet-stream",
        },
    )


@app.get("/{bucket}/{key:path}")
def get_object(bucket: str, key: str):
    obj_path = DATA_DIR / bucket / key
    if not obj_path.is_file():
        return Response(status_code=404)
    data = obj_path.read_bytes()
    etag = hashlib.md5(data).hexdigest()
    return Response(
        content=data,
        status_code=200,
        headers={
            "ETag": f'"{etag}"',
            "Content-Length": str(len(data)),
            "Content-Type": "application/octet-stream",
        },
    )


@app.put("/{bucket}/{key:path}")
async def put_object(bucket: str, key: str, request: Request):
    _buckets.add(bucket)
    body = await request.body()
    obj_path = DATA_DIR / bucket / key
    obj_path.parent.mkdir(parents=True, exist_ok=True)
    obj_path.write_bytes(body)
    etag = hashlib.md5(body).hexdigest()
    return Response(
        status_code=200,
        headers={"ETag": f'"{etag}"'},
    )

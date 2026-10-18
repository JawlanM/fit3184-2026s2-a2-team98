"""Reading EcoGuardFiles items and turning them into the contract's FileItem."""
import time
from decimal import Decimal

from . import aws, config, urls
from .expr import Expr

# Everything a FileItem needs. `embedding` (512 floats) is never read.
_FILE_FIELDS = ("fileId", "fileType", "mimeType", "url", "thumbnailUrl", "s3Key", "thumbKey",
                "tags", "attributes", "visibility", "location", "uploadedBy", "uploadedAt",
                "status", "modelVersion")


def _plain(v):
    """DynamoDB gives numbers back as Decimal, which JSON can't encode."""
    if isinstance(v, Decimal):
        return int(v) if v == v.to_integral_value() else float(v)
    if isinstance(v, dict):
        return {k: _plain(x) for k, x in v.items()}
    if isinstance(v, (list, set, tuple)):
        return [_plain(x) for x in v]
    return v


def projection(fields=_FILE_FIELDS) -> tuple[str, dict]:
    e = Expr()
    return ", ".join(e.name(f) for f in fields), e.names


def get(file_id: str, consistent: bool = False) -> dict | None:
    proj, names = projection()
    item = aws.table(config.FILES_TABLE).get_item(
        Key={"fileId": file_id}, ProjectionExpression=proj,
        ExpressionAttributeNames=names, ConsistentRead=consistent).get("Item")
    return _plain(item) if item else None


def batch_get(file_ids: list[str], fields=_FILE_FIELDS) -> dict[str, dict]:
    """BatchGetItem in chunks of 100, retrying UnprocessedKeys. Returns {fileId: item}."""
    proj, names = projection(fields)
    client = aws.dynamodb()
    found: dict[str, dict] = {}
    for i in range(0, len(file_ids), 100):
        request = {config.FILES_TABLE: {
            "Keys": [{"fileId": f} for f in file_ids[i:i + 100]],
            "ProjectionExpression": proj, "ExpressionAttributeNames": names}}
        for attempt in range(5):
            resp = client.batch_get_item(RequestItems=request)
            for item in resp["Responses"].get(config.FILES_TABLE, []):
                found[item["fileId"]] = _plain(item)
            request = resp.get("UnprocessedKeys") or {}
            if not request:
                break
            time.sleep(0.05 * 2 ** attempt)
    return found


def can_see(item: dict, caller: str) -> bool:
    """Private files are visible to their uploader only (D-16)."""
    return item.get("visibility") != "private" or item.get("uploadedBy") == caller


def _presign(bucket: str, key: str) -> str:
    # Pure computation inside the Lambda: no network call.
    return aws.s3().generate_presigned_url(
        "get_object", Params={"Bucket": bucket, "Key": key}, ExpiresIn=config.VIEW_URL_SECONDS)


def media_key(item: dict) -> str | None:
    return item.get("s3Key")


def thumb_key(item: dict) -> str | None:
    if item.get("thumbKey"):
        return item["thumbKey"]
    if item.get("thumbnailUrl"):
        return f"thumbs/{item['fileId']}.jpg"
    return None


def to_file_item(item: dict) -> dict:
    """Database item -> FileItem dict with fresh presigned view links."""
    mkey, tkey = media_key(item), thumb_key(item)
    url = item.get("url") or (urls.object_url(config.MEDIA_BUCKET, mkey) if mkey else None)
    thumb = item.get("thumbnailUrl") or (urls.object_url(config.THUMBS_BUCKET, tkey) if tkey else None)
    out = {k: item.get(k) for k in ("fileId", "fileType", "mimeType", "visibility", "location",
                                    "uploadedBy", "uploadedAt", "status", "modelVersion")}
    out.update(
        url=url,
        thumbnailUrl=thumb,
        viewUrl=_presign(config.MEDIA_BUCKET, mkey) if mkey else None,
        thumbnailViewUrl=_presign(config.THUMBS_BUCKET, tkey) if tkey else None,
        tags=item.get("tags") or {},
        attributes=item.get("attributes") or {},
    )
    return out

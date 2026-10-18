"""Canonical file URLs <-> fileId (D-07).

Every canonical URL already contains the fileId (the SHA-256 of the file), so
a lookup reads it from the URL instead of searching the database.
"""
import re
from urllib.parse import urlsplit

from . import config

_EXTS = "|".join(config.MEDIA_EXTS)
_MEDIA = re.compile(rf"^/media/([0-9a-f]{{64}})\.({_EXTS})$")
_THUMB = re.compile(r"^/thumbs/([0-9a-f]{64})\.jpg$")


def object_url(bucket: str, key: str) -> str:
    return f"https://{bucket}.s3.{config.REGION}.amazonaws.com/{key}"


def media_url(file_id: str, ext: str) -> str:
    return object_url(config.MEDIA_BUCKET, f"media/{file_id}.{ext}")


def thumb_url(file_id: str) -> str:
    return object_url(config.THUMBS_BUCKET, f"thumbs/{file_id}.jpg")


def _bucket_of(host: str) -> str | None:
    # <bucket>.s3.ap-southeast-2.amazonaws.com or <bucket>.s3.amazonaws.com
    bucket, sep, rest = host.lower().partition(".s3.")
    if not sep:
        return None
    if rest == "amazonaws.com" or (rest.endswith(".amazonaws.com") and rest.count(".") == 2):
        return bucket
    return None


def parse_file_url(url: str) -> tuple[str, str | None] | None:
    """(fileId, ext) for a media URL, (fileId, None) for a thumbnail URL, else None.

    The query string is ignored, so presigned viewUrl links work too.
    """
    try:
        parts = urlsplit(url.strip())
    except ValueError:
        return None
    bucket = _bucket_of(parts.netloc)
    if parts.scheme != "https" or bucket is None:
        return None
    if bucket == config.MEDIA_BUCKET and (m := _MEDIA.match(parts.path)):
        return m.group(1), m.group(2)
    if bucket == config.THUMBS_BUCKET and (m := _THUMB.match(parts.path)):
        return m.group(1), None
    return None

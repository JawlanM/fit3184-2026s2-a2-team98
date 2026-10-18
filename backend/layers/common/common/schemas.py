"""Request and response models that mirror docs/api-contract.md.

Strict mode stops JSON `true` or "1" being accepted where the contract wants
an integer. Bad input becomes 400 VALIDATION_ERROR through common.errors.
"""
from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from . import labels

MAX_TAGS = 20


def _clean_tags(v: dict[str, int]) -> dict[str, int]:
    out: dict[str, int] = {}
    for raw, n in v.items():
        if n < 1:
            raise ValueError("every tag count must be an integer >= 1")
        name = labels.normalise(raw)
        if not name:
            raise ValueError("tag names must not be empty")
        out[name] = max(out.get(name, 0), n)   # "fox" and "foxes" both given: keep the larger
    return out


def _iso_utc(v: str | None) -> str | None:
    """Accept any ISO-8601 date or time; store as 2026-10-20T03:15:00Z."""
    if v is None:
        return None
    try:
        dt = datetime.fromisoformat(v.replace("Z", "+00:00"))
    except ValueError:
        raise ValueError("must be an ISO-8601 date or time, e.g. 2026-10-20T03:15:00Z")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class _Strict(BaseModel):
    model_config = ConfigDict(strict=True, extra="ignore")


# ---------- queries ----------

class _Paged(_Strict):
    from_: str | None = Field(default=None, alias="from")
    to: str | None = None
    limit: int = Field(default=50, ge=1, le=100)
    nextToken: str | None = None

    model_config = ConfigDict(strict=True, extra="ignore", populate_by_name=True)

    @field_validator("from_", "to")
    @classmethod
    def _dates(cls, v):
        return _iso_utc(v)


class TagQuery(_Paged):
    tags: dict[str, int] = Field(min_length=1, max_length=MAX_TAGS)

    @field_validator("tags")
    @classmethod
    def _tags(cls, v):
        return _clean_tags(v)


class SpeciesQuery(_Paged):
    species: list[str] = Field(min_length=1, max_length=MAX_TAGS)

    @field_validator("species")
    @classmethod
    def _species(cls, v):
        out = sorted({labels.normalise(s) for s in v})
        if "" in out:
            raise ValueError("species names must not be empty")
        return out


class ThumbnailQuery(_Strict):
    thumbnailUrl: str = Field(min_length=1, max_length=2048)


class FileItem(BaseModel):
    fileId: str
    fileType: str | None = None
    mimeType: str | None = None
    url: str | None = None
    thumbnailUrl: str | None = None
    viewUrl: str | None = None
    thumbnailViewUrl: str | None = None
    tags: dict[str, int] = {}
    attributes: dict[str, str | None] = {}
    visibility: str | None = None
    location: str | None = None
    uploadedBy: str | None = None
    uploadedAt: str | None = None
    status: str | None = None
    modelVersion: str | None = None


class QueryResponse(BaseModel):
    count: int
    results: list[FileItem]
    nextToken: str | None = None


class ThumbnailResponse(BaseModel):
    url: str
    viewUrl: str
    fileId: str


# ---------- data management ----------

class BulkTagRequest(_Strict):
    urls: list[str] = Field(min_length=1, max_length=100)
    operation: Literal[0, 1]
    tags: dict[str, int] = Field(min_length=1, max_length=MAX_TAGS)

    @field_validator("operation", mode="before")
    @classmethod
    def _no_bool(cls, v):
        # Python treats True as 1, so Literal[0, 1] alone would accept JSON true.
        if isinstance(v, bool):
            raise ValueError("operation must be 0 (remove) or 1 (add)")
        return v

    @field_validator("tags")
    @classmethod
    def _tags(cls, v):
        return _clean_tags(v)


class Skipped(BaseModel):
    url: str
    reason: Literal["processing", "failed", "conflict", "error"]


class BulkTagResponse(BaseModel):
    updated: list[str]
    notFound: list[str]
    skipped: list[Skipped] = []


class DeleteRequest(_Strict):
    urls: list[str] = Field(min_length=1, max_length=100)


class DeleteResponse(BaseModel):
    deleted: list[str]
    notFound: list[str]
    failed: list[str]


# ---------- notifications ----------

class SubscribeRequest(_Strict):
    species: list[str] = Field(min_length=1, max_length=MAX_TAGS)

    @field_validator("species")
    @classmethod
    def _species(cls, v):
        out = sorted({labels.normalise(s) for s in v})
        if "" in out:
            raise ValueError("species names must not be empty")
        return out


class Subscription(BaseModel):
    id: str
    species: list[str]
    status: Literal["pending", "confirmed"]


class SubscriptionList(BaseModel):
    subscriptions: list[Subscription]

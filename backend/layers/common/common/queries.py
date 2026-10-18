"""Query logic shared by the REST `query` Lambda (A) and `lex-fulfilment` (C).

C's Lex code can call these functions directly instead of going over HTTP:

    from common import queries
    page = queries.find_by_tags({"fox": 1}, caller=user_sub, frm="2026-10-17T00:00:00Z")
    page["results"]   # list of FileItem dicts

Tag search is AND across tags (D-03): every match is collected first, then the
list is cut into pages, so a file is never missed because it sat on a
different DynamoDB page for each tag.
"""
import base64
import hashlib
import json

from . import aws, config, files, urls
from .errors import ApiError
from .expr import Expr


def _files_for_tag(tag: str, min_count: int, frm: str | None, to: str | None) -> dict[str, str]:
    """{fileId: uploadedAt} for every file with tag count >= min_count."""
    e = Expr()
    cond = f"{e.name('count')} >= {e.value(min_count)}"
    if frm:
        cond += f" AND {e.name('uploadedAt')} >= {e.value(frm)}"
    if to:
        cond += f" AND {e.name('uploadedAt')} <= {e.value(to)}"
    key_cond = f"{e.name('tag')} = {e.value(tag)}"
    kwargs = dict(
        KeyConditionExpression=key_cond,
        FilterExpression=cond,
        ProjectionExpression=f"{e.name('fileId')}, {e.name('uploadedAt')}",
        **e.kwargs(),
    )
    table = aws.table(config.TAG_INDEX_TABLE)
    found: dict[str, str] = {}
    while True:
        page = table.query(**kwargs)
        found.update({i["fileId"]: i.get("uploadedAt", "") for i in page["Items"]})
        if "LastEvaluatedKey" not in page:
            return found
        kwargs["ExclusiveStartKey"] = page["LastEvaluatedKey"]


def _fingerprint(tags: dict, frm, to, caller: str) -> str:
    raw = json.dumps({"tags": tags, "from": frm, "to": to, "u": caller}, sort_keys=True)
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def _encode_token(offset: int, fp: str) -> str:
    return base64.urlsafe_b64encode(json.dumps({"o": offset, "f": fp}).encode()).decode()


def _decode_token(token: str, fp: str) -> int:
    try:
        data = json.loads(base64.urlsafe_b64decode(token.encode()))
        offset, token_fp = int(data["o"]), data["f"]
    except Exception:
        raise ApiError(400, "VALIDATION_ERROR", "nextToken is not valid")
    if token_fp != fp or offset < 0:
        raise ApiError(400, "VALIDATION_ERROR", "nextToken belongs to a different search")
    return offset


def find_by_tags(tags: dict[str, int], caller: str, frm: str | None = None,
                 to: str | None = None, limit: int = 50, next_token: str | None = None) -> dict:
    """Files where every tag has count >= its value. Newest first.

    `tags` must already be cleaned (common.schemas does that for HTTP input;
    call labels.normalise yourself otherwise).
    """
    fp = _fingerprint(tags, frm, to, caller)
    offset = _decode_token(next_token, fp) if next_token else 0

    # 1-2. One Query per tag, intersect, stop early when nothing is left.
    ids: dict[str, str] | None = None
    for tag, n in tags.items():
        hits = _files_for_tag(tag, n, frm, to)
        ids = hits if ids is None else {f: t for f, t in ids.items() if f in hits}
        if not ids:
            break
    ids = ids or {}

    # Private files of other users are dropped before paging, so pages stay full (D-16).
    if ids:
        owners = files.batch_get(list(ids), fields=("fileId", "visibility", "uploadedBy"))
        ids = {f: t for f, t in ids.items() if f in owners and files.can_see(owners[f], caller)}

    # 3-4. Newest first, then the requested page.
    ordered = sorted(ids.items(), key=lambda kv: (kv[1], kv[0]), reverse=True)
    page_ids = [f for f, _ in ordered[offset:offset + limit]]

    # 5-6. Full items for this page only, with view links.
    items = files.batch_get(page_ids)
    results = [files.to_file_item(items[f]) for f in page_ids if f in items]

    more = offset + limit < len(ordered)
    return {"count": len(results), "results": results,
            "nextToken": _encode_token(offset + limit, fp) if more else None}


def find_by_species(species: list[str], caller: str, **kw) -> dict:
    """{"species": ["cat"]} is the same search as {"tags": {"cat": 1}}."""
    return find_by_tags({s: 1 for s in species}, caller, **kw)


def full_size_for_thumbnail(thumbnail_url: str, caller: str) -> dict:
    """Thumbnail URL (canonical or presigned) -> the original's URL and a view link."""
    parsed = urls.parse_file_url(thumbnail_url)
    if parsed is None or parsed[1] is not None:
        raise ApiError(404, "NOT_FOUND", "not a known thumbnail URL")
    item = files.get(parsed[0])
    if item is None or not files.can_see(item, caller):
        raise ApiError(404, "NOT_FOUND", "no file for this thumbnail")
    fi = files.to_file_item(item)
    if not fi["url"]:
        raise ApiError(404, "NOT_FOUND", "file has no original stored")
    return {"url": fi["url"], "viewUrl": fi["viewUrl"], "fileId": fi["fileId"]}

"""POST /tags/bulk: add (operation 1) or remove (operation 0) tags on many files (owner A).

- Any logged-in user may edit tags (D-01).
- Files that aren't `ready` are skipped, not changed (D-10).
- Each file is one transaction over both tables, and the write only happens
  if the tags it touches still hold the values we read (D-11).
"""
import logging

from botocore.exceptions import ClientError
from fastapi import Request

from common import aws, config, files, urls, web
from common.expr import Expr
from common.schemas import BulkTagRequest, BulkTagResponse

app = web.create_app()
log = logging.getLogger("ecoguard")

MAX_ATTEMPTS = 3


def apply(tags: dict[str, int], op: int, delta: dict[str, int]) -> dict[str, int]:
    """New tag map. op 1 adds; op 0 subtracts and drops tags at <= 0.

    Removing a tag the file doesn't have is ignored (spec 4.3).
    """
    out = dict(tags)
    for t, n in delta.items():
        if op == 1:
            out[t] = out.get(t, 0) + n
        elif t in out:
            out[t] -= n
            if out[t] <= 0:
                del out[t]
    return out


def build_transaction(item: dict, new: dict[str, int], delta: dict[str, int]) -> list[dict] | None:
    """TransactItems for one file, or None if nothing would change.

    Only the tags named in the request are touched, each guarded by its old
    value, so a concurrent edit to the same tag makes the condition fail and
    a concurrent edit to a different tag is kept.
    """
    fid, old = item["fileId"], item.get("tags")
    changed = {t: new[t] for t in delta if t in new and new[t] != (old or {}).get(t)}
    removed = [t for t in delta if t in (old or {}) and t not in new]
    if not changed and not removed:
        return None

    e = Expr()
    cond = [f"{e.name('status')} = {e.value('ready')}"]
    if old is None:
        # No tags map yet: create it whole, and only if still absent.
        update = f"SET {e.name('tags')} = {e.value(new)}"
        cond.append(f"attribute_not_exists({e.name('tags')})")
    else:
        sets, rems = [], []
        for t in delta:
            path = f"{e.name('tags')}.{e.name(t)}"
            if t in old:
                cond.append(f"{path} = {e.value(old[t])}")
            else:
                cond.append(f"attribute_not_exists({path})")
            if t in changed:
                sets.append(f"{path} = {e.value(changed[t])}")
            elif t in removed:
                rems.append(path)
        update = " ".join(p for p in (
            "SET " + ", ".join(sets) if sets else "",
            "REMOVE " + ", ".join(rems) if rems else "") if p)

    actions = [{"Update": {
        "TableName": config.FILES_TABLE, "Key": {"fileId": fid},
        "UpdateExpression": update, "ConditionExpression": " AND ".join(cond),
        **e.kwargs()}}]
    for t, n in changed.items():
        row = {"tag": t, "fileId": fid, "count": n}
        if item.get("uploadedAt"):
            row["uploadedAt"] = item["uploadedAt"]
        actions.append({"Put": {"TableName": config.TAG_INDEX_TABLE, "Item": row}})
    for t in removed:
        actions.append({"Delete": {"TableName": config.TAG_INDEX_TABLE,
                                   "Key": {"tag": t, "fileId": fid}}})
    return actions


def _status_reason(item: dict) -> str:
    return "failed" if item.get("status") == "failed" else "processing"


def edit_file(file_id: str, op: int, delta: dict[str, int]) -> str:
    """'updated', 'notFound', or a skip reason ('processing'/'failed'/'conflict')."""
    for _ in range(MAX_ATTEMPTS):
        item = files.get(file_id, consistent=True)
        if item is None:
            return "notFound"
        if item.get("status") != "ready":
            return _status_reason(item)
        actions = build_transaction(item, apply(item.get("tags") or {}, op, delta), delta)
        if actions is None:
            return "updated"          # e.g. removing a tag the file doesn't have
        try:
            aws.ddb_client().transact_write_items(TransactItems=actions)
            return "updated"
        except ClientError as e:
            if e.response["Error"]["Code"] != "TransactionCanceledException":
                raise
            # Someone else changed the file first (or a write conflict): re-read and retry.
    return "conflict"


@app.post("/tags/bulk", response_model=BulkTagResponse)
def bulk_tag(body: BulkTagRequest, request: Request):
    caller = web.caller(request)
    web.log_action("bulk_tag", caller=caller, operation=body.operation,
                   tags=body.tags, files=len(body.urls))

    # Several URLs can name one file (original + thumbnail): edit it once.
    outcome_by_id: dict[str, str] = {}
    updated, not_found, skipped = [], [], []
    for url in body.urls:
        parsed = urls.parse_file_url(url)
        if parsed is None:
            not_found.append(url)
            continue
        fid = parsed[0]
        if fid not in outcome_by_id:
            try:
                outcome_by_id[fid] = edit_file(fid, body.operation, body.tags)
            except Exception:
                log.exception("bulk_tag failed for %s", fid)
                outcome_by_id[fid] = "error"
        outcome = outcome_by_id[fid]
        if outcome == "updated":
            updated.append(url)
        elif outcome == "notFound":
            not_found.append(url)
        else:
            skipped.append({"url": url, "reason": outcome})
    return {"updated": updated, "notFound": not_found, "skipped": skipped}


handler = web.make_handler(app)

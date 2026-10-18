"""POST /files/delete (owner A).

Per file: (1) one transaction deletes the file row and its tag-index rows,
guarded by "uploadedBy = caller" (D-09); (2) delete the original and the
thumbnail from S3. If the row is already gone, S3 is still cleaned, so a
retry after a failed step 2 removes the leftovers (D-08).
"""
import logging

from botocore.exceptions import ClientError
from fastapi import Request

from common import aws, config, files, urls, web
from common.errors import ApiError
from common.schemas import DeleteRequest, DeleteResponse

app = web.create_app()
log = logging.getLogger("ecoguard")


def purge_s3(file_id: str, media_keys: list[str], thumb_key: str) -> None:
    """Delete the original(s) and thumbnail. Deleting a missing key is not an error in S3."""
    s3 = aws.s3()
    resp = s3.delete_objects(Bucket=config.MEDIA_BUCKET, Delete={
        "Objects": [{"Key": k} for k in media_keys], "Quiet": True})
    if resp.get("Errors"):
        raise RuntimeError(f"S3 refused: {resp['Errors'][0].get('Code')}")
    s3.delete_object(Bucket=config.THUMBS_BUCKET, Key=thumb_key)


def _keys_without_row(file_id: str, ext: str | None) -> list[str]:
    # Original URL given: its extension is known. Thumbnail URL: try every allowed one.
    return [f"media/{file_id}.{e}" for e in ([ext] if ext else config.MEDIA_EXTS)]


def _delete_rows(item: dict, caller: str) -> None:
    fid = item["fileId"]
    actions = [{"Delete": {
        "TableName": config.FILES_TABLE, "Key": {"fileId": fid},
        "ConditionExpression": "#u = :me",
        "ExpressionAttributeNames": {"#u": "uploadedBy"},
        "ExpressionAttributeValues": {":me": caller}}}]
    actions += [{"Delete": {"TableName": config.TAG_INDEX_TABLE, "Key": {"tag": t, "fileId": fid}}}
                for t in (item.get("tags") or {})]
    aws.ddb_client().transact_write_items(TransactItems=actions)


def delete_file(file_id: str, ext: str | None, caller: str) -> str:
    """'deleted', 'notFound', 'forbidden' or 'failed'."""
    item = files.get(file_id, consistent=True)
    if item is None:
        try:
            purge_s3(file_id, _keys_without_row(file_id, ext), f"thumbs/{file_id}.jpg")
        except Exception:
            log.exception("leftover clean-up failed for %s", file_id)
        return "notFound"
    if item.get("uploadedBy") != caller:
        return "forbidden"

    try:
        _delete_rows(item, caller)
    except ClientError as e:
        if e.response["Error"]["Code"] != "TransactionCanceledException":
            raise
        # The row changed between our read and the delete: decide again from scratch.
        again = files.get(file_id, consistent=True)
        if again is None:
            return delete_file(file_id, ext, caller)
        if again.get("uploadedBy") != caller:
            return "forbidden"
        return "failed"

    media = [files.media_key(item)] if files.media_key(item) else _keys_without_row(file_id, ext)
    try:
        purge_s3(file_id, media, files.thumb_key(item) or f"thumbs/{file_id}.jpg")
    except Exception:
        log.exception("S3 delete failed for %s; a retry will clean it up", file_id)
        return "failed"
    return "deleted"


@app.post("/files/delete", response_model=DeleteResponse)
def delete_files(body: DeleteRequest, request: Request):
    caller = web.caller(request)
    web.log_action("delete", caller=caller, files=len(body.urls))

    outcome_by_id: dict[str, str] = {}
    deleted, not_found, failed, forbidden = [], [], [], 0
    for url in body.urls:
        parsed = urls.parse_file_url(url)
        if parsed is None:
            not_found.append(url)
            continue
        fid, ext = parsed
        if fid not in outcome_by_id:
            try:
                outcome_by_id[fid] = delete_file(fid, ext, caller)
            except Exception:
                log.exception("delete failed for %s", fid)
                outcome_by_id[fid] = "failed"
        outcome = outcome_by_id[fid]
        if outcome == "deleted":
            deleted.append(url)
        elif outcome == "notFound":
            not_found.append(url)
        else:
            failed.append(url)
            forbidden += outcome == "forbidden"

    if forbidden and forbidden == len(body.urls):
        raise ApiError(403, "FORBIDDEN", "only the uploader can delete these files")
    return {"deleted": deleted, "notFound": not_found, "failed": failed}


handler = web.make_handler(app)

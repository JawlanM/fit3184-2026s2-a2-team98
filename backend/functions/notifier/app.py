"""DynamoDB Streams on EcoGuardFiles -> SNS email (owner A).

Emails go out when a ready file gains a species or a higher count; never for
placeholders, failures, removals or repeated writes (D-02). The stream's
FilterCriteria in template.yaml already drops records that aren't `ready`.
"""
import json
import logging

from boto3.dynamodb.types import TypeDeserializer

from common import aws, config

log = logging.getLogger()
log.setLevel(logging.INFO)
_d = TypeDeserializer()


def _plain(image: dict | None) -> dict:
    """Stream images use typed JSON ({"S": "fox"}); turn them into Python values."""
    return {k: _d.deserialize(v) for k, v in (image or {}).items()}


def gained_species(old: dict, new: dict) -> dict[str, int]:
    """Species whose count went up. A file that wasn't ready before counts as no tags."""
    if new.get("status") != "ready":
        return {}
    before = (old.get("tags") or {}) if old.get("status") == "ready" else {}
    return {s: int(c) for s, c in (new.get("tags") or {}).items() if c > before.get(s, 0)}


def subject(gained: dict[str, int]) -> str:
    s = "EcoGuard sighting: " + ", ".join(f"{n} {sp}" for sp, n in sorted(gained.items()))
    return s if len(s) <= 100 else s[:97] + "..."     # SNS subject limit: 100 characters


def email_body(item: dict, gained: dict[str, int]) -> str:
    tags = item.get("tags") or {}
    lines = ["A file on EcoGuard now shows a species you follow.", ""]
    lines += [f"  {sp}: {int(tags[sp])}" for sp in sorted(gained)]
    others = sorted(set(tags) - set(gained))
    if others:
        lines += ["", "Also in this file: " + ", ".join(f"{sp} ({int(tags[sp])})" for sp in others)]
    lines += ["",
              f"Uploaded: {item.get('uploadedAt', 'unknown')}",
              f"Location: {item.get('location') or 'not given'}",
              f"View it: {config.WEB_APP_URL.rstrip('/')}/files/{item['fileId']}",
              "",
              "To stop these emails, use the unsubscribe link below or the Alerts page."]
    return "\n".join(lines)


def handler(event, context):
    failures = []
    for rec in event.get("Records", []):
        try:
            ddb = rec["dynamodb"]
            new, old = _plain(ddb.get("NewImage")), _plain(ddb.get("OldImage"))
            gained = gained_species(old, new)
            if not gained:
                continue
            aws.sns().publish(
                TopicArn=config.TOPIC_ARN,
                Subject=subject(gained),
                Message=email_body(new, gained),
                MessageAttributes={"species": {
                    "DataType": "String.Array",
                    "StringValue": json.dumps(sorted(gained))}},
            )
            log.info(json.dumps({"action": "notify", "fileId": new.get("fileId"),
                                 "species": sorted(gained)}))
        except Exception:
            log.exception("notify failed")
            failures.append({"itemIdentifier": rec["dynamodb"]["SequenceNumber"]})
    # Only failed records are retried, so emails already sent aren't sent twice.
    return {"batchItemFailures": failures}

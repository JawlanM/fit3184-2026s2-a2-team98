"""POST/GET /subscriptions, DELETE /subscriptions/{id} (owner A).

SNS allows one subscription per (topic, email address), so each user has at
most one; subscribing again merges the new species into its filter (D-05).
The `id` returned to the browser is the last part of the subscription ARN.
"""
import json
import logging
from datetime import datetime, timezone

from boto3.dynamodb.conditions import Key
from botocore.exceptions import ClientError
from fastapi import Request, Response

from common import aws, config, web
from common.errors import ApiError
from common.schemas import SubscribeRequest, Subscription, SubscriptionList

app = web.create_app()
log = logging.getLogger("ecoguard")


def _table():
    return aws.table(config.SUBSCRIPTIONS_TABLE)


def _rows(user: str) -> list[dict]:
    return _table().query(KeyConditionExpression=Key("userSub").eq(user),
                          ConsistentRead=True)["Items"]


def _sub_id(arn: str) -> str:
    return arn.rsplit(":", 1)[-1]


def _filter(species) -> str:
    return json.dumps({"species": sorted(species)})


def _status(arn: str) -> str | None:
    """'pending', 'confirmed', or None if SNS no longer has it (e.g. unconfirmed for 3 days)."""
    try:
        attrs = aws.sns().get_subscription_attributes(SubscriptionArn=arn)["Attributes"]
    except ClientError as e:
        if e.response["Error"]["Code"] in ("NotFound", "NotFoundException"):
            return None
        raise
    return "pending" if attrs.get("PendingConfirmation") == "true" else "confirmed"


def _apply_filter(row: dict) -> bool:
    """Push the stored species to SNS. False if SNS refused (it may while pending)."""
    try:
        aws.sns().set_subscription_attributes(
            SubscriptionArn=row["subscriptionArn"], AttributeName="FilterPolicy",
            AttributeValue=_filter(row["species"]))
        return True
    except ClientError as e:
        log.warning("filter update refused for %s: %s", row["subscriptionArn"],
                    e.response["Error"]["Code"])
        return False


def _set_synced(row: dict, synced: bool) -> None:
    _table().update_item(
        Key={"userSub": row["userSub"], "subscriptionArn": row["subscriptionArn"]},
        UpdateExpression="SET #s = :s", ExpressionAttributeNames={"#s": "filterSynced"},
        ExpressionAttributeValues={":s": synced})


def _create(user: str, email: str, species: list[str]) -> dict:
    sns = aws.sns()
    try:
        arn = sns.subscribe(
            TopicArn=config.TOPIC_ARN, Protocol="email", Endpoint=email,
            Attributes={"FilterPolicy": _filter(species), "FilterPolicyScope": "MessageAttributes"},
            ReturnSubscriptionArn=True,      # the real ARN now, not "pending confirmation"
        )["SubscriptionArn"]
        synced = True
    except ClientError as e:
        if e.response["Error"]["Code"] != "InvalidParameter":
            raise
        # SNS still holds an older subscription for this email with another filter
        # (e.g. unsubscribed while pending). Take that one over and set our filter on it.
        arn = sns.subscribe(TopicArn=config.TOPIC_ARN, Protocol="email", Endpoint=email,
                            ReturnSubscriptionArn=True)["SubscriptionArn"]
        synced = None
    row = {"userSub": user, "subscriptionArn": arn, "email": email, "species": set(species),
           "createdAt": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
           "filterSynced": True}
    if synced is None:
        row["filterSynced"] = _apply_filter(row)
    _table().put_item(Item=row)
    return row


def _view(row: dict, status: str) -> dict:
    return {"id": _sub_id(row["subscriptionArn"]), "species": sorted(row["species"]),
            "status": status}


@app.post("/subscriptions", response_model=Subscription)
def subscribe(body: SubscribeRequest, request: Request):
    c = web.claims(request)
    user, email = web.caller(request), c.get("email")
    if not email:
        raise ApiError(400, "VALIDATION_ERROR", "the login token has no email")

    rows = _rows(user)
    row = rows[0] if rows else None
    if row is not None and _status(row["subscriptionArn"]) is None:
        _table().delete_item(Key={"userSub": user, "subscriptionArn": row["subscriptionArn"]})
        row = None                            # SNS dropped it; start again

    if row is None:
        row = _create(user, email, body.species)
    else:
        row["species"] = set(row["species"]) | set(body.species)
        _table().update_item(
            Key={"userSub": user, "subscriptionArn": row["subscriptionArn"]},
            UpdateExpression="SET #sp = :sp", ExpressionAttributeNames={"#sp": "species"},
            ExpressionAttributeValues={":sp": row["species"]})
        _set_synced(row, _apply_filter(row))

    web.log_action("subscribe", caller=user, species=sorted(row["species"]))
    return _view(row, _status(row["subscriptionArn"]) or "pending")


@app.get("/subscriptions", response_model=SubscriptionList)
def list_subscriptions(request: Request):
    user = web.caller(request)
    out = []
    for row in _rows(user):
        status = _status(row["subscriptionArn"])
        if status is None:
            continue
        if status == "confirmed" and not row.get("filterSynced", True):
            _set_synced(row, _apply_filter(row))    # catch up on an edit SNS refused while pending
        out.append(_view(row, status))
    return {"subscriptions": out}


@app.delete("/subscriptions/{sub_id}", status_code=204)
def unsubscribe(sub_id: str, request: Request):
    user = web.caller(request)
    row = next((r for r in _rows(user) if _sub_id(r["subscriptionArn"]) == sub_id), None)
    if row is None:
        raise ApiError(404, "NOT_FOUND", "no such subscription")
    try:
        aws.sns().unsubscribe(SubscriptionArn=row["subscriptionArn"])
    except ClientError as e:
        # Still pending, or already gone. SNS removes unconfirmed subscriptions after ~3 days.
        log.warning("unsubscribe refused for %s: %s", row["subscriptionArn"],
                    e.response["Error"]["Code"])
    _table().delete_item(Key={"userSub": user, "subscriptionArn": row["subscriptionArn"]})
    web.log_action("unsubscribe", caller=user)
    return Response(status_code=204)


handler = web.make_handler(app)

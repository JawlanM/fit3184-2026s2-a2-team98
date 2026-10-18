import json

import boto3

from conftest import ALICE, BOB, call, cloud, load  # noqa: F401

subs = load("subscriptions")


def _sns_subs():
    return boto3.client("sns", region_name="ap-southeast-2").list_subscriptions()["Subscriptions"]


def _filter_of(arn):
    attrs = boto3.client("sns", region_name="ap-southeast-2").get_subscription_attributes(
        SubscriptionArn=arn)["Attributes"]
    return json.loads(attrs["FilterPolicy"])


def test_subscribe_list_merge_unsubscribe(cloud):
    code, body, _ = call(subs, "POST", "/subscriptions", {"species": ["Fox", "toads"]})
    assert code == 200 and body["species"] == ["cane toad", "fox"]
    sub_id = body["id"]
    assert len(_sns_subs()) == 1
    arn = _sns_subs()[0]["SubscriptionArn"]
    assert _filter_of(arn) == {"species": ["cane toad", "fox"]}

    code, body, _ = call(subs, "POST", "/subscriptions", {"species": ["rabbit"]})
    assert code == 200 and body["id"] == sub_id                     # same subscription (D-05)
    assert body["species"] == ["cane toad", "fox", "rabbit"]
    assert len(_sns_subs()) == 1
    assert _filter_of(arn) == {"species": ["cane toad", "fox", "rabbit"]}

    code, body, _ = call(subs, "GET", "/subscriptions")
    assert code == 200 and [s["id"] for s in body["subscriptions"]] == [sub_id]

    code, body, _ = call(subs, "GET", "/subscriptions", user=BOB)
    assert body == {"subscriptions": []}

    code, _, _ = call(subs, "DELETE", f"/subscriptions/{sub_id}", user=BOB)
    assert code == 404                                              # not Bob's
    code, body, headers = call(subs, "DELETE", f"/subscriptions/{sub_id}", user=ALICE)
    assert code == 204 and body is None
    assert headers["Access-Control-Allow-Origin"] == "http://localhost:5173"
    assert _sns_subs() == []
    _, body, _ = call(subs, "GET", "/subscriptions")
    assert body == {"subscriptions": []}


def test_empty_species_is_400(cloud):
    code, body, _ = call(subs, "POST", "/subscriptions", {"species": []})
    assert code == 400 and body["error"]["code"] == "VALIDATION_ERROR"

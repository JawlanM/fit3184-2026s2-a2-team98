"""Test setup: fake AWS with moto, then call each Lambda the way API Gateway does."""
import hashlib
import importlib.util
import json
import os
import shutil
from decimal import Decimal
import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parent.parent
ROOT = BACKEND.parent

# Settings the Lambdas read at import time (template.yaml sets the real ones).
os.environ.update({
    "AWS_REGION": "ap-southeast-2",
    "AWS_DEFAULT_REGION": "ap-southeast-2",
    "AWS_ACCESS_KEY_ID": "testing",
    "AWS_SECRET_ACCESS_KEY": "testing",
    "FILES_TABLE": "EcoGuardFiles",
    "TAG_INDEX_TABLE": "EcoGuardTagIndex",
    "SUBSCRIPTIONS_TABLE": "EcoGuardSubscriptions",
    "MEDIA_BUCKET": "ecoguard-media-test",
    "THUMBS_BUCKET": "ecoguard-thumbs-test",
    "ALLOWED_ORIGIN": "http://localhost:5173",
    "WEB_APP_URL": "http://localhost:5173",
    "TOPIC_ARN": "arn:aws:sns:ap-southeast-2:123456789012:ecoguard-sightings",
})

# The layer reads labels.json next to itself; the master copy lives in config/.
shutil.copyfile(ROOT / "config" / "labels.json",
                BACKEND / "layers" / "common" / "common" / "labels.json")
sys.path.insert(0, str(BACKEND / "layers" / "common"))

import boto3  # noqa: E402
from moto import mock_aws  # noqa: E402

from common import aws  # noqa: E402

MEDIA, THUMBS = os.environ["MEDIA_BUCKET"], os.environ["THUMBS_BUCKET"]
ALICE, BOB = "sub-alice", "sub-bob"


def load(function: str):
    """Import backend/functions/<function>/app.py under a unique module name."""
    path = BACKEND / "functions" / function / "app.py"
    spec = importlib.util.spec_from_file_location(f"fn_{function}", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def cloud():
    with mock_aws():
        aws.reset()
        ddb = boto3.client("dynamodb", region_name="ap-southeast-2")
        ddb.create_table(
            TableName="EcoGuardFiles", BillingMode="PAY_PER_REQUEST",
            AttributeDefinitions=[{"AttributeName": n, "AttributeType": "S"}
                                  for n in ("fileId", "visibility", "uploadedAt")],
            KeySchema=[{"AttributeName": "fileId", "KeyType": "HASH"}],
            GlobalSecondaryIndexes=[{
                "IndexName": "uploadedAt-index",
                "KeySchema": [{"AttributeName": "visibility", "KeyType": "HASH"},
                              {"AttributeName": "uploadedAt", "KeyType": "RANGE"}],
                "Projection": {"ProjectionType": "ALL"}}])
        ddb.create_table(
            TableName="EcoGuardTagIndex", BillingMode="PAY_PER_REQUEST",
            AttributeDefinitions=[{"AttributeName": "tag", "AttributeType": "S"},
                                  {"AttributeName": "fileId", "AttributeType": "S"}],
            KeySchema=[{"AttributeName": "tag", "KeyType": "HASH"},
                       {"AttributeName": "fileId", "KeyType": "RANGE"}])
        ddb.create_table(
            TableName="EcoGuardSubscriptions", BillingMode="PAY_PER_REQUEST",
            AttributeDefinitions=[{"AttributeName": "userSub", "AttributeType": "S"},
                                  {"AttributeName": "subscriptionArn", "AttributeType": "S"}],
            KeySchema=[{"AttributeName": "userSub", "KeyType": "HASH"},
                       {"AttributeName": "subscriptionArn", "KeyType": "RANGE"}])
        s3 = boto3.client("s3", region_name="ap-southeast-2")
        for b in (MEDIA, THUMBS):
            s3.create_bucket(Bucket=b, CreateBucketConfiguration={
                "LocationConstraint": "ap-southeast-2"})
        boto3.client("sns", region_name="ap-southeast-2").create_topic(Name="ecoguard-sightings")
        yield
        aws.reset()


def fid(name: str) -> str:
    return hashlib.sha256(name.encode()).hexdigest()


def media_url(file_id: str, ext: str = "jpg") -> str:
    return f"https://{MEDIA}.s3.ap-southeast-2.amazonaws.com/media/{file_id}.{ext}"


def thumb_url(file_id: str) -> str:
    return f"https://{THUMBS}.s3.ap-southeast-2.amazonaws.com/thumbs/{file_id}.jpg"


def put_file(name: str, tags: dict, *, owner=ALICE, at="2026-10-20T03:15:00Z",
             status="ready", visibility="public", ext="jpg", objects=True) -> str:
    """Write a file the way B's pipeline will: both tables, plus the S3 objects."""
    f = fid(name)
    item = {"fileId": f, "fileType": "video" if ext in ("mp4", "mov") else "image",
            "mimeType": "image/jpeg", "s3Key": f"media/{f}.{ext}", "thumbKey": f"thumbs/{f}.jpg",
            "url": media_url(f, ext), "thumbnailUrl": thumb_url(f), "tags": tags,
            "attributes": {}, "visibility": visibility, "uploadedBy": owner,
            "uploadedAt": at, "status": status, "modelVersion": "test",
            "embedding": [Decimal("0.1")] * 4}
    ddb = boto3.resource("dynamodb", region_name="ap-southeast-2")
    ddb.Table("EcoGuardFiles").put_item(Item=item)
    for t, n in tags.items():
        ddb.Table("EcoGuardTagIndex").put_item(Item={"tag": t, "fileId": f, "count": n,
                                                     "uploadedAt": at})
    if objects:
        s3 = boto3.client("s3", region_name="ap-southeast-2")
        s3.put_object(Bucket=MEDIA, Key=f"media/{f}.{ext}", Body=b"x")
        s3.put_object(Bucket=THUMBS, Key=f"thumbs/{f}.jpg", Body=b"x")
    return f


def call(fn_module, method: str, path: str, body=None, *, user=ALICE, email="alice@example.com"):
    """Invoke a Lambda with a REST API (v1) proxy event, like API Gateway does."""
    event = {
        "resource": path, "path": path, "httpMethod": method,
        "headers": {"Content-Type": "application/json", "Host": "api.example.com"},
        "multiValueHeaders": {"Content-Type": ["application/json"], "Host": ["api.example.com"]},
        "queryStringParameters": None, "multiValueQueryStringParameters": None,
        "pathParameters": None, "stageVariables": None,
        "requestContext": {"resourcePath": path, "httpMethod": method, "path": f"/prod{path}",
                           "stage": "prod", "identity": {"sourceIp": "127.0.0.1"},
                           "authorizer": {"claims": {"sub": user, "email": email}}},
        "body": None if body is None else json.dumps(body),
        "isBase64Encoded": False,
    }
    resp = fn_module.handler(event, None)
    text = resp.get("body") or ""
    return resp["statusCode"], (json.loads(text) if text else None), resp.get("headers", {})


def tag_rows(file_id: str) -> dict:
    t = boto3.resource("dynamodb", region_name="ap-southeast-2").Table("EcoGuardTagIndex")
    return {i["tag"]: int(i["count"]) for i in t.scan()["Items"] if i["fileId"] == file_id}


def file_row(file_id: str) -> dict | None:
    t = boto3.resource("dynamodb", region_name="ap-southeast-2").Table("EcoGuardFiles")
    return t.get_item(Key={"fileId": file_id}).get("Item")


def s3_keys(bucket: str) -> list[str]:
    s3 = boto3.client("s3", region_name="ap-southeast-2")
    return [o["Key"] for o in s3.list_objects_v2(Bucket=bucket).get("Contents", [])]

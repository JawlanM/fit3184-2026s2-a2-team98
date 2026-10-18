"""End-to-end check of A's routes against the deployed stack.

Creates two throwaway Cognito users (alice, bob), seeds one fake "fox" file
the way B's pipeline will write it, calls every route, then removes
everything it created. Needs admin AWS credentials (it creates users).

    python scripts/smoke_test.py            # uses stack "ecoguard"
    python scripts/smoke_test.py --keep     # leave the seeded file and users for manual tests
"""
import argparse
import hashlib
import json
import sys
import time
import urllib.error
import urllib.request
import uuid

import boto3

REGION = "ap-southeast-2"
PASSWORD = "Smoke-" + uuid.uuid4().hex[:10] + "A1"

cf = boto3.client("cloudformation", region_name=REGION)
idp = boto3.client("cognito-idp", region_name=REGION)
s3 = boto3.client("s3", region_name=REGION)
ddb = boto3.resource("dynamodb", region_name=REGION)
logs = boto3.client("logs", region_name=REGION)

passed = failed = 0


def check(name: str, ok: bool, detail="") -> None:
    global passed, failed
    if ok:
        passed += 1
        print(f"  PASS  {name}")
    else:
        failed += 1
        print(f"  FAIL  {name}  {detail}")


def outputs(stack: str) -> dict:
    out = cf.describe_stacks(StackName=stack)["Stacks"][0]["Outputs"]
    return {o["OutputKey"]: o["OutputValue"] for o in out}


def http(method, url, body=None, token=None, headers=None):
    h = {"Content-Type": "application/json", "Origin": "http://localhost:5173", **(headers or {})}
    if token:
        h["Authorization"] = f"Bearer {token}"
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(url, data=data, method=method, headers=h)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            raw, code, hdrs = r.read(), r.status, dict(r.headers)
    except urllib.error.HTTPError as e:
        raw, code, hdrs = e.read(), e.code, dict(e.headers)
    text = raw.decode() if raw else ""
    try:
        parsed = json.loads(text) if text else None
    except ValueError:
        parsed = text
    return code, parsed, {k.lower(): v for k, v in hdrs.items()}


def make_user(pool: str, client: str, name: str) -> tuple[str, str, str]:
    email = f"ecoguard-smoke-{name}-{uuid.uuid4().hex[:6]}@example.com"
    idp.admin_create_user(UserPoolId=pool, Username=email, MessageAction="SUPPRESS",
                          UserAttributes=[{"Name": "email", "Value": email},
                                          {"Name": "email_verified", "Value": "true"},
                                          {"Name": "given_name", "Value": name.title()},
                                          {"Name": "family_name", "Value": "Smoke"}])
    idp.admin_set_user_password(UserPoolId=pool, Username=email, Password=PASSWORD, Permanent=True)
    auth = idp.initiate_auth(ClientId=client, AuthFlow="USER_PASSWORD_AUTH",
                             AuthParameters={"USERNAME": email, "PASSWORD": PASSWORD})
    claims = idp.get_user(AccessToken=auth["AuthenticationResult"]["AccessToken"])
    sub = next(a["Value"] for a in claims["UserAttributes"] if a["Name"] == "sub")
    return email, sub, auth["AuthenticationResult"]["IdToken"]


def seed(o: dict, owner: str) -> dict:
    """One ready image with {"fox": 2}, written to both tables and both buckets."""
    fid = hashlib.sha256(f"smoke {uuid.uuid4()}".encode()).hexdigest()
    media, thumbs = o["MediaBucketName"], o["ThumbsBucketName"]
    url = f"https://{media}.s3.{REGION}.amazonaws.com/media/{fid}.jpg"
    turl = f"https://{thumbs}.s3.{REGION}.amazonaws.com/thumbs/{fid}.jpg"
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    s3.put_object(Bucket=media, Key=f"media/{fid}.jpg", Body=b"smoke", ContentType="image/jpeg")
    s3.put_object(Bucket=thumbs, Key=f"thumbs/{fid}.jpg", Body=b"smoke", ContentType="image/jpeg")
    ddb.Table(o["FilesTableName"]).put_item(Item={
        "fileId": fid, "fileType": "image", "mimeType": "image/jpeg", "originalName": "smoke.jpg",
        "s3Key": f"media/{fid}.jpg", "thumbKey": f"thumbs/{fid}.jpg", "url": url,
        "thumbnailUrl": turl, "tags": {"fox": 2}, "attributes": {}, "visibility": "public",
        "location": "Clayton VIC", "uploadedBy": owner, "uploadedAt": now, "status": "ready",
        "modelVersion": "smoke-test"})
    ddb.Table(o["TagIndexTableName"]).put_item(Item={
        "tag": "fox", "fileId": fid, "count": 2, "uploadedAt": now})
    return {"fileId": fid, "url": url, "thumbnailUrl": turl}


def notifier_logged(file_id: str, since_ms: int) -> bool:
    for _ in range(20):
        events = logs.filter_log_events(logGroupName="/aws/lambda/ecoguard-notifier",
                                        startTime=since_ms, filterPattern=f'"{file_id}"')["events"]
        if any('"action": "notify"' in e["message"] for e in events):
            return True
        time.sleep(3)
    return False


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--stack", default="ecoguard")
    ap.add_argument("--keep", action="store_true")
    args = ap.parse_args()

    o = outputs(args.stack)
    api, pool, client = o["ApiUrl"], o["UserPoolId"], o["WebClientId"]
    print(f"API {api}")

    print("\n1. Without a token every route is 401, in our format, with CORS")
    routes = [("GET", "/me"), ("POST", "/query/tags"), ("POST", "/query/species"),
              ("POST", "/query/thumbnail"), ("POST", "/tags/bulk"), ("POST", "/files/delete"),
              ("POST", "/subscriptions"), ("GET", "/subscriptions"), ("DELETE", "/subscriptions/x")]
    for method, path in routes:
        code, body, hdrs = http(method, api + path, {} if method == "POST" else None)
        check(f"{method} {path} -> 401", code == 401 and isinstance(body, dict)
              and body.get("error", {}).get("code") == "UNAUTHORIZED"
              and hdrs.get("access-control-allow-origin") == "http://localhost:5173",
              f"got {code} {body} {hdrs.get('access-control-allow-origin')}")
    code, _, hdrs = http("OPTIONS", api + "/query/tags", headers={
        "Access-Control-Request-Method": "POST",
        "Access-Control-Request-Headers": "authorization,content-type"})
    check("OPTIONS preflight needs no token", code == 200
          and hdrs.get("access-control-allow-origin") == "http://localhost:5173", f"got {code}")

    print("\n2. Log in two test users")
    alice_email, alice, a_tok = make_user(pool, client, "alice")
    bob_email, bob, b_tok = make_user(pool, client, "bob")
    users = [alice_email, bob_email]
    code, body, _ = http("GET", api + "/me", token=a_tok)
    check("GET /me returns the token's user", code == 200 and body.get("sub") == alice, body)

    f = None
    sub_id = None
    try:
        print("\n3. Queries")
        f = seed(o, alice)
        code, body, hdrs = http("POST", api + "/query/tags", {"tags": {"Fox": 2}}, a_tok)
        ids = [r["fileId"] for r in (body or {}).get("results", [])] if code == 200 else []
        check("tags {fox: 2} finds the seeded file", f["fileId"] in ids, f"{code} {body}")
        check("normal responses carry CORS", hdrs.get("access-control-allow-origin") == "http://localhost:5173")
        if code == 200 and ids:
            r = next(x for x in body["results"] if x["fileId"] == f["fileId"])
            vcode, _, _ = http("GET", r["viewUrl"], headers={"Origin": ""})
            check("viewUrl opens the private object", vcode == 200, vcode)
        code, body, _ = http("POST", api + "/query/tags", {"tags": {"fox": 3}}, a_tok)
        check("tags {fox: 3} does not match", code == 200 and
              f["fileId"] not in [r["fileId"] for r in body["results"]], body)
        code, body, _ = http("POST", api + "/query/species", {"species": ["foxes"]}, b_tok)
        check("species [foxes] (synonym) finds it", code == 200 and
              f["fileId"] in [r["fileId"] for r in body["results"]], body)
        code, body, _ = http("POST", api + "/query/thumbnail", {"thumbnailUrl": f["thumbnailUrl"]}, b_tok)
        check("thumbnail -> full-size URL", code == 200 and body.get("url") == f["url"], body)
        code, body, _ = http("POST", api + "/query/tags", {"tags": {"fox": 0}}, a_tok)
        check("count 0 -> 400 VALIDATION_ERROR", code == 400 and
              body["error"]["code"] == "VALIDATION_ERROR", body)

        print("\n4. Tag edits (and the notifier)")
        since = int(time.time() * 1000) - 5000
        code, body, _ = http("POST", api + "/tags/bulk",
                             {"urls": [f["url"]], "operation": 1, "tags": {"rabbit": 1}}, b_tok)
        check("bob adds rabbit to alice's file", code == 200 and body["updated"] == [f["url"]], body)
        item = ddb.Table(o["FilesTableName"]).get_item(Key={"fileId": f["fileId"]})["Item"]
        check("files table now {fox: 2, rabbit: 1}",
              {k: int(v) for k, v in item["tags"].items()} == {"fox": 2, "rabbit": 1}, item["tags"])
        row = ddb.Table(o["TagIndexTableName"]).get_item(Key={"tag": "rabbit", "fileId": f["fileId"]})
        check("tag index has the rabbit row", "Item" in row)
        check("notifier published for rabbit", notifier_logged(f["fileId"], since))
        code, body, _ = http("POST", api + "/tags/bulk",
                             {"urls": [f["thumbnailUrl"]], "operation": 0, "tags": {"rabbit": 5}}, a_tok)
        row = ddb.Table(o["TagIndexTableName"]).get_item(Key={"tag": "rabbit", "fileId": f["fileId"]})
        check("removing more than the count drops the tag", code == 200 and "Item" not in row, body)
        code, body, _ = http("POST", api + "/tags/bulk",
                             {"urls": [f["url"]], "operation": 7, "tags": {"fox": 1}}, a_tok)
        check("operation 7 -> 400", code == 400, body)

        print("\n5. Subscriptions")
        code, body, _ = http("POST", api + "/subscriptions", {"species": ["Fox"]}, a_tok)
        sub_id = (body or {}).get("id")
        check("subscribe -> pending", code == 200 and body.get("status") == "pending", body)
        code, body, _ = http("POST", api + "/subscriptions", {"species": ["toad"]}, a_tok)
        check("second subscribe merges species", code == 200 and body.get("id") == sub_id
              and body.get("species") == ["cane toad", "fox"], body)
        code, body, _ = http("GET", api + "/subscriptions", token=a_tok)
        check("list shows one subscription", code == 200 and len(body["subscriptions"]) == 1, body)
        code, body, _ = http("DELETE", api + f"/subscriptions/{sub_id}", token=b_tok)
        check("bob can't delete alice's subscription", code == 404, body)
        code, body, _ = http("DELETE", api + f"/subscriptions/{sub_id}", token=a_tok)
        check("alice unsubscribes -> 204", code == 204, body)
        sub_id = None if code == 204 else sub_id

        print("\n6. Delete")
        code, body, _ = http("POST", api + "/files/delete", {"urls": [f["url"]]}, b_tok)
        check("bob deleting alice's file -> 403", code == 403 and
              body["error"]["code"] == "FORBIDDEN", body)
        if not args.keep:
            code, body, _ = http("POST", api + "/files/delete", {"urls": [f["url"]]}, a_tok)
            check("alice deletes her file", code == 200 and body["deleted"] == [f["url"]], body)
            gone = "Item" not in ddb.Table(o["FilesTableName"]).get_item(Key={"fileId": f["fileId"]})
            left = s3.list_objects_v2(Bucket=o["MediaBucketName"], Prefix=f"media/{f['fileId']}")
            check("row and S3 object are gone", gone and left.get("KeyCount", 0) == 0)
            f = None
    finally:
        if not args.keep:
            if f:
                http("POST", api + "/files/delete", {"urls": [f["url"]]}, a_tok)
            if sub_id:
                http("DELETE", api + f"/subscriptions/{sub_id}", token=a_tok)
            for u in users:
                idp.admin_delete_user(UserPoolId=pool, Username=u)
        else:
            print(f"\nkept users {users} with password {PASSWORD}")

    print(f"\n{passed} passed, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())

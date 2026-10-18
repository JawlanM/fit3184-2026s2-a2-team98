"""Machine-to-machine access token for calling Cloud Run when no user is present.

For B's tagging-dispatcher:

    from common import m2m
    headers = {"Authorization": f"Bearer {m2m.access_token()}"}

The token is cached until 5 minutes before it expires (Cognito issues 1-hour
tokens), so a warm Lambda asks Cognito about once an hour. Each token request
is billed, which is why the cache matters.

The calling Lambda's role needs secretsmanager:GetSecretValue on M2MSecret.
"""
import base64
import json
import os
import time
import urllib.parse
import urllib.request

import boto3

from . import config

SECRET_ID = os.environ.get("M2M_SECRET_ID", "ecoguard/m2m-client")
_REFRESH_EARLY = 300

_cache: dict = {}


def _secret() -> dict:
    if "secret" not in _cache:
        sm = boto3.client("secretsmanager", region_name=config.REGION)
        _cache["secret"] = json.loads(sm.get_secret_value(SecretId=SECRET_ID)["SecretString"])
    return _cache["secret"]


def access_token() -> str:
    now = time.time()
    if _cache.get("token") and now < _cache["expires"] - _REFRESH_EARLY:
        return _cache["token"]
    s = _secret()
    basic = base64.b64encode(f"{s['clientId']}:{s['clientSecret']}".encode()).decode()
    req = urllib.request.Request(
        s["tokenUrl"],
        data=urllib.parse.urlencode({"grant_type": "client_credentials", "scope": s["scope"]}).encode(),
        headers={"Authorization": f"Basic {basic}",
                 "Content-Type": "application/x-www-form-urlencoded"})
    with urllib.request.urlopen(req, timeout=10) as r:
        body = json.loads(r.read())
    _cache.update(token=body["access_token"], expires=now + int(body["expires_in"]))
    return _cache["token"]

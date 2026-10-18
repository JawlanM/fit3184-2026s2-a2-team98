import io
import json
from unittest import mock

from common import m2m

SECRET = {"clientId": "cid", "clientSecret": "shh", "scope": "ecoguard/detect",
          "tokenUrl": "https://example.auth.ap-southeast-2.amazoncognito.com/oauth2/token"}


def _resp(token):
    return io.BytesIO(json.dumps({"access_token": token, "expires_in": 3600}).encode())


def test_token_is_cached_until_near_expiry():
    m2m._cache.clear()
    m2m._cache["secret"] = SECRET
    with mock.patch.object(m2m.urllib.request, "urlopen",
                           side_effect=[_resp("t1"), _resp("t2")]) as op, \
         mock.patch.object(m2m.time, "time", return_value=1000.0):
        assert m2m.access_token() == "t1"
        assert m2m.access_token() == "t1"
        assert op.call_count == 1
        req = op.call_args.args[0]
        assert req.full_url == SECRET["tokenUrl"]
        assert b"grant_type=client_credentials" in req.data
    with mock.patch.object(m2m.urllib.request, "urlopen", return_value=_resp("t2")), \
         mock.patch.object(m2m.time, "time", return_value=1000.0 + 3600 - 299):
        assert m2m.access_token() == "t2"          # inside the 5-minute refresh window

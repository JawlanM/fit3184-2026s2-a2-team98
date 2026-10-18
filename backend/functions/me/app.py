"""GET /me: returns the caller's token fields. Smoke test for the Cognito authorizer."""
import json
import os

CORS_HEADERS = {
    "Access-Control-Allow-Origin": os.environ.get("ALLOWED_ORIGIN", "http://localhost:5173"),
    "Access-Control-Allow-Headers": "Authorization,Content-Type",
    "Vary": "Origin",
}


def handler(event, context):
    claims = event["requestContext"]["authorizer"]["claims"]
    body = {
        "sub": claims.get("sub"),
        "email": claims.get("email"),
        "givenName": claims.get("given_name"),
        "familyName": claims.get("family_name"),
        "tokenUse": claims.get("token_use"),
    }
    return {
        "statusCode": 200,
        "headers": {"Content-Type": "application/json", **CORS_HEADERS},
        "body": json.dumps(body),
    }

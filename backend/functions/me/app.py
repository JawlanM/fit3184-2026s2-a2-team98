import json


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
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(body),
    }

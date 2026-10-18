"""FastAPI app factory and the Lambda entry point every HTTP function uses."""
import json
import logging

from fastapi import FastAPI, Request
from mangum import Mangum

from . import config, errors

logging.getLogger().setLevel(logging.INFO)

CORS_HEADERS = {
    "Access-Control-Allow-Origin": config.ALLOWED_ORIGIN,
    "Access-Control-Allow-Headers": "Authorization,Content-Type",
    "Vary": "Origin",
}


def create_app() -> FastAPI:
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    errors.install(app)
    return app


def make_handler(app: FastAPI):
    """Wrap the app for API Gateway and add the CORS headers to every response.

    The headers are added here, outside FastAPI, so even a 500 from a crash
    carries them and the browser can read it (D-06, D-14).
    """
    mangum = Mangum(app, lifespan="off")

    def handler(event, context):
        resp = mangum(event, context)
        resp.setdefault("headers", {}).update(CORS_HEADERS)
        return resp

    return handler


def claims(request: Request) -> dict:
    """The Cognito token's fields, put there by API Gateway's authorizer."""
    event = request.scope.get("aws.event") or {}
    return ((event.get("requestContext") or {}).get("authorizer") or {}).get("claims") or {}


def caller(request: Request) -> str:
    sub = claims(request).get("sub")
    if not sub:
        # Only reachable if a route were deployed without the authorizer.
        raise errors.ApiError(401, "UNAUTHORIZED", "no user in request")
    return sub


def log_action(action: str, **fields) -> None:
    """One JSON line per action, searchable in CloudWatch Logs Insights."""
    logging.getLogger("ecoguard").info(json.dumps({"action": action, **fields}, default=str))

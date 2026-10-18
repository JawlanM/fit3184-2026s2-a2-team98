"""Settings every Lambda reads from its environment.

template.yaml sets these through Globals.Function.Environment, so a function
never hard-codes a table or bucket name.
"""
import os

REGION = os.environ.get("AWS_REGION", "ap-southeast-2")

FILES_TABLE = os.environ.get("FILES_TABLE", "EcoGuardFiles")
TAG_INDEX_TABLE = os.environ.get("TAG_INDEX_TABLE", "EcoGuardTagIndex")
SUBSCRIPTIONS_TABLE = os.environ.get("SUBSCRIPTIONS_TABLE", "EcoGuardSubscriptions")

MEDIA_BUCKET = os.environ.get("MEDIA_BUCKET", "ecoguard-media")
THUMBS_BUCKET = os.environ.get("THUMBS_BUCKET", "ecoguard-thumbs")

TOPIC_ARN = os.environ.get("TOPIC_ARN", "")

# One origin, never "*" (D-14).
ALLOWED_ORIGIN = os.environ.get("ALLOWED_ORIGIN", "http://localhost:5173")
WEB_APP_URL = os.environ.get("WEB_APP_URL", ALLOWED_ORIGIN)

# Presigned GET links in responses (contract: valid 1 h).
VIEW_URL_SECONDS = 3600

# Original file extensions the presign Lambda (B) may use. D-08 relies on this list.
MEDIA_EXTS = ("jpg", "png", "webp", "mp4", "mov")

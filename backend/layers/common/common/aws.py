"""boto3 clients, created on first use and then reused.

Creating them lazily (not at import) lets the tests switch on moto before any
client exists. In Lambda the cache lives as long as the container, so each
client is still built only once per cold start.
"""
from functools import lru_cache

import boto3
from botocore.config import Config

from . import config


@lru_cache(maxsize=None)
def dynamodb():
    return boto3.resource("dynamodb", region_name=config.REGION)


def ddb_client():
    # The resource's own client accepts plain Python values in transact_write_items.
    return dynamodb().meta.client


def table(name: str):
    return dynamodb().Table(name)


@lru_cache(maxsize=None)
def s3():
    # Regional virtual-hosted URLs: https://<bucket>.s3.ap-southeast-2.amazonaws.com/<key>
    return boto3.client(
        "s3",
        region_name=config.REGION,
        config=Config(signature_version="s3v4", s3={"addressing_style": "virtual"}),
    )


@lru_cache(maxsize=None)
def sns():
    return boto3.client("sns", region_name=config.REGION)


def reset():
    """Forget cached clients (tests only)."""
    dynamodb.cache_clear()
    s3.cache_clear()
    sns.cache_clear()

"""Raw span storage — S3 is the system of record (TRUNK_SPEC.md §2.4)."""

from __future__ import annotations

import gzip
import json
import logging
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from functools import cache

import boto3

from ..hashing import canonical_json
from ..settings import settings
from .models import CanonicalSpan

logger = logging.getLogger("continual.otel.store")

_ONE_HOUR = timedelta(hours=1)


@cache
def _client():  # noqa: ANN202 (boto3 clients are untyped)
    if not settings.s3_bucket:
        raise RuntimeError("S3_BUCKET is not set (put it in .env.local)")
    return boto3.client("s3")


def raw_key(tenant_id: str, received_at: datetime, batch_id: str) -> str:
    """S3 key for one received batch, partitioned for cheap range reads."""
    at = received_at.astimezone(UTC)
    return f"raw/tenant={tenant_id}/date={at:%Y-%m-%d}/hour={at:%H}/{batch_id}.jsonl.gz"


def write_raw_spans(
    tenant_id: str,
    spans: list[CanonicalSpan],
    received_at: datetime | None = None,
) -> str:
    """Append one immutable batch of spans to S3; returns the key written."""
    at = received_at or datetime.now(UTC)
    # A fresh uuid per batch, never a content hash: two identical batches are two
    # real deliveries, and collapsing them would silently drop a retry we may
    # need in order to audit what the customer actually sent.
    key = raw_key(tenant_id, at, uuid.uuid4().hex)
    lines = b"\n".join(canonical_json(s.model_dump(mode="json")) for s in spans)
    _client().put_object(
        Bucket=settings.s3_bucket,
        Key=key,
        Body=gzip.compress(lines),
        ContentType="application/x-ndjson",
        ContentEncoding="gzip",
    )
    logger.info("wrote %d spans to s3://%s/%s", len(spans), settings.s3_bucket, key)
    return key


def _partition_prefixes(tenant_id: str, since: datetime, until: datetime) -> Iterator[str]:
    """Hour-partition prefixes covering [since, until]."""
    cursor = since.astimezone(UTC).replace(minute=0, second=0, microsecond=0)
    end = until.astimezone(UTC)
    while cursor <= end:
        yield f"raw/tenant={tenant_id}/date={cursor:%Y-%m-%d}/hour={cursor:%H}/"
        cursor = cursor + _ONE_HOUR


def read_raw_spans(tenant_id: str, since: datetime, until: datetime) -> Iterator[CanonicalSpan]:
    """Every stored span in the partition range, oldest partition first."""
    paginator = _client().get_paginator("list_objects_v2")
    for prefix in _partition_prefixes(tenant_id, since, until):
        for page in paginator.paginate(Bucket=settings.s3_bucket, Prefix=prefix):
            for obj in page.get("Contents", []):
                body = (
                    _client().get_object(Bucket=settings.s3_bucket, Key=obj["Key"])["Body"].read()
                )
                for line in gzip.decompress(body).splitlines():
                    if line:
                        yield CanonicalSpan(**json.loads(line))

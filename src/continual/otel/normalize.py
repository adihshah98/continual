"""OTLP/JSON payloads -> CanonicalSpan. The wire format stops here."""

from __future__ import annotations

import logging
from typing import Any

from .models import CanonicalSpan

logger = logging.getLogger("continual.otel.normalize")

_STATUS_CODES = {0: "UNSET", 1: "OK", 2: "ERROR"}


def _attr_value(value: dict[str, Any]) -> Any:
    """Unwrap one OTLP AnyValue into a plain Python value."""
    if "stringValue" in value:
        return value["stringValue"]
    if "intValue" in value:
        # OTLP/JSON encodes 64-bit ints as strings to survive JavaScript.
        return int(value["intValue"])
    if "boolValue" in value:
        return value["boolValue"]
    if "doubleValue" in value:
        return value["doubleValue"]
    if "arrayValue" in value:
        return [_attr_value(v) for v in value["arrayValue"].get("values", [])]
    if "kvlistValue" in value:
        return _flatten_attributes(value["kvlistValue"].get("values", []))
    return None


def _flatten_attributes(attributes: list[dict[str, Any]]) -> dict[str, Any]:
    """OTLP KeyValue list -> plain dict."""
    return {a["key"]: _attr_value(a.get("value", {})) for a in attributes if "key" in a}


def normalize_otlp_json(payload: dict[str, Any]) -> list[CanonicalSpan]:
    """Flatten an OTLP/JSON ExportTraceServiceRequest into canonical spans."""
    spans: list[CanonicalSpan] = []
    for resource_span in payload.get("resourceSpans", []):
        resource_attributes = _flatten_attributes(
            resource_span.get("resource", {}).get("attributes", [])
        )
        for scope_span in resource_span.get("scopeSpans", []):
            for raw in scope_span.get("spans", []):
                span = _one_span(raw, resource_attributes)
                if span is not None:
                    spans.append(span)
    return spans


def _one_span(raw: dict[str, Any], resource_attributes: dict[str, Any]) -> CanonicalSpan | None:
    """One OTLP span -> CanonicalSpan, or None if it is unusable."""
    # A span with no id cannot be addressed or deduplicated. Drop it alone —
    # rejecting the whole batch would cost every good span in the export.
    if not raw.get("spanId") or not raw.get("traceId"):
        logger.warning("dropping span with no trace/span id: name=%s", raw.get("name"))
        return None
    try:
        return CanonicalSpan(
            trace_id=raw["traceId"],
            span_id=raw["spanId"],
            parent_span_id=raw.get("parentSpanId") or None,
            name=raw.get("name", ""),
            start_time_unix_nano=int(raw.get("startTimeUnixNano", 0)),
            end_time_unix_nano=int(raw.get("endTimeUnixNano", 0)),
            attributes=_flatten_attributes(raw.get("attributes", [])),
            resource_attributes=resource_attributes,
            status_code=_STATUS_CODES.get(raw.get("status", {}).get("code", 0)),
            events=raw.get("events", []),
        )
    except (ValueError, TypeError, KeyError):
        logger.exception("dropping unparseable span: name=%s", raw.get("name"))
        return None

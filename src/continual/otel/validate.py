"""Structural validation at the door — what makes a span storable at all."""

from __future__ import annotations

from .models import CanonicalSpan


def validate_span(span: CanonicalSpan) -> list[str]:
    """Structural problems with a span; empty list means it is storable."""
    problems: list[str] = []
    if not span.trace_id:
        problems.append("empty trace_id")
    if not span.span_id:
        problems.append("empty span_id")
    if span.start_time_unix_nano <= 0:
        problems.append("missing or zero start_time_unix_nano")
    if span.end_time_unix_nano < span.start_time_unix_nano:
        problems.append("end_time_unix_nano precedes start_time_unix_nano")
    return problems


def partition_valid(
    spans: list[CanonicalSpan],
) -> tuple[list[CanonicalSpan], list[tuple[CanonicalSpan, list[str]]]]:
    """Split spans into storable and rejected-with-reasons."""
    valid: list[CanonicalSpan] = []
    rejected: list[tuple[CanonicalSpan, list[str]]] = []
    for span in spans:
        problems = validate_span(span)
        if problems:
            rejected.append((span, problems))
        else:
            valid.append(span)
    return valid, rejected

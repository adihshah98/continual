"""PII redaction hook — positioned now, implemented later (TRUNK_SPEC.md §2.5)."""

from __future__ import annotations

from .models import CanonicalSpan


def redact_span(span: CanonicalSpan) -> CanonicalSpan:
    """Redact PII from a span before it is written. Currently a no-op."""
    # Deliberately empty. It sits between validation and the first write so that
    # turning redaction on is a config change, not a re-plumbing of a live
    # pipeline under security-review deadline pressure. PLAN.md §4 makes
    # redaction non-negotiable before real traffic; TRUNK_SPEC.md §2.5 scopes it
    # to a Stage 1 EXIT criterion for design-partner traffic only, under a
    # written agreement about what is stored.
    return span

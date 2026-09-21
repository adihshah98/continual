"""The canonical span — our normalized form of an OTLP span."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from ..hashing import content_hash

# Precedence for resolving which conversation a span belongs to
# (TRUNK_SPEC.md §5.2). Explicit beats conventional beats inferred.
_SESSION_ATTRIBUTE_PRECEDENCE = (
    "continual.session_id",
    "session.id",
    "gen_ai.conversation.id",
)

# Any of these marks a span as an LLM call for replay-tier purposes.
_LLM_MARKER_PREFIXES = ("gen_ai.",)


class CanonicalSpan(BaseModel):
    """One OTLP span, normalized. The unit ingest stores."""

    trace_id: str
    span_id: str
    parent_span_id: str | None = None
    name: str
    start_time_unix_nano: int
    end_time_unix_nano: int
    attributes: dict[str, Any] = Field(default_factory=dict)
    resource_attributes: dict[str, Any] = Field(default_factory=dict)
    status_code: str | None = None
    events: list[dict[str, Any]] = Field(default_factory=list)

    def span_hash(self) -> str:
        """Content hash of this span — what an episode binds to."""
        return content_hash(self.model_dump(mode="json"))

    def session_key(self) -> str:
        """Which conversation this span belongs to; falls back to the trace id."""
        for key in _SESSION_ATTRIBUTE_PRECEDENCE:
            value = self.attributes.get(key) or self.resource_attributes.get(key)
            if value:
                return str(value)
        # No session marker anywhere: degrade to one episode per trace rather
        # than dropping the span. Coarse, but never silently merges conversations.
        return self.trace_id

    def is_llm_call(self) -> bool:
        """True if this span represents a model invocation."""
        return any(
            key.startswith(prefix) for key in self.attributes for prefix in _LLM_MARKER_PREFIXES
        )

from continual.otel.models import CanonicalSpan
from continual.otel.redact import redact_span
from continual.otel.validate import partition_valid, validate_span


def _span(**overrides):
    base = {
        "trace_id": "t",
        "span_id": "s",
        "name": "chat",
        "start_time_unix_nano": 1_700_000_000_000_000_000,
        "end_time_unix_nano": 1_700_000_001_000_000_000,
        "attributes": {},
    }
    return CanonicalSpan(**{**base, **overrides})


def test_a_well_formed_span_has_no_problems():
    assert validate_span(_span()) == []


def test_zero_start_time_is_a_problem():
    problems = validate_span(_span(start_time_unix_nano=0))
    assert any("start_time" in p for p in problems)


def test_end_before_start_is_a_problem():
    problems = validate_span(_span(start_time_unix_nano=2_000, end_time_unix_nano=1_000))
    assert any("end_time" in p for p in problems)


def test_end_time_equal_to_start_is_allowed():
    # A sub-nanosecond span is implausible but not malformed, and some
    # instrumentation rounds. Do not reject real data over it.
    assert validate_span(_span(start_time_unix_nano=5, end_time_unix_nano=5)) == []


def test_empty_trace_id_is_a_problem():
    assert any("trace_id" in p for p in validate_span(_span(trace_id="")))


def test_partition_separates_valid_from_rejected():
    good, bad = partition_valid([_span(), _span(trace_id="")])
    assert len(good) == 1
    assert len(bad) == 1
    rejected_span, reasons = bad[0]
    assert rejected_span.trace_id == ""
    assert reasons


def test_redaction_is_a_positioned_no_op():
    # TRUNK_SPEC.md §2.5: the hook exists and is wired in now; the implementation
    # is deferred. This test pins the seam, not the behavior.
    span = _span(attributes={"gen_ai.input.messages": "my email is a@b.com"})
    assert redact_span(span) == span

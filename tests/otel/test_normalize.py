from continual.otel.models import CanonicalSpan
from continual.otel.normalize import normalize_otlp_json


def _otlp_payload(attributes, resource_attributes=None, name="chat gpt-4o"):
    """Minimal OTLP/JSON ExportTraceServiceRequest with one span."""
    return {
        "resourceSpans": [
            {
                "resource": {"attributes": resource_attributes or []},
                "scopeSpans": [
                    {
                        "scope": {"name": "test"},
                        "spans": [
                            {
                                "traceId": "5b8efff798038103d269b633813fc60c",
                                "spanId": "eee19b7ec3c1b174",
                                "name": name,
                                "startTimeUnixNano": "1700000000000000000",
                                "endTimeUnixNano": "1700000001000000000",
                                "attributes": attributes,
                                "status": {"code": 1},
                            }
                        ],
                    }
                ],
            }
        ]
    }


def _attr(key, value):
    return {"key": key, "value": {"stringValue": value}}


def test_normalizes_a_single_span():
    payload = _otlp_payload([_attr("gen_ai.request.model", "gpt-4o")])
    spans = normalize_otlp_json(payload)
    assert len(spans) == 1
    assert spans[0].trace_id == "5b8efff798038103d269b633813fc60c"
    assert spans[0].span_id == "eee19b7ec3c1b174"
    assert spans[0].attributes["gen_ai.request.model"] == "gpt-4o"


def test_times_parse_from_string_nanos():
    spans = normalize_otlp_json(_otlp_payload([]))
    assert spans[0].start_time_unix_nano == 1700000000000000000
    assert spans[0].end_time_unix_nano == 1700000001000000000


def test_flattens_all_otlp_attribute_value_types():
    payload = _otlp_payload(
        [
            {"key": "s", "value": {"stringValue": "x"}},
            {"key": "i", "value": {"intValue": "42"}},
            {"key": "b", "value": {"boolValue": True}},
            {"key": "d", "value": {"doubleValue": 0.5}},
            {"key": "arr", "value": {"arrayValue": {"values": [{"stringValue": "a"}]}}},
        ]
    )
    attrs = normalize_otlp_json(payload)[0].attributes
    assert attrs == {"s": "x", "i": 42, "b": True, "d": 0.5, "arr": ["a"]}


def test_resource_attributes_are_kept_separate():
    payload = _otlp_payload([], resource_attributes=[_attr("service.name", "agent")])
    span = normalize_otlp_json(payload)[0]
    assert span.resource_attributes["service.name"] == "agent"
    assert "service.name" not in span.attributes


def test_empty_payload_yields_no_spans():
    assert normalize_otlp_json({"resourceSpans": []}) == []
    assert normalize_otlp_json({}) == []


def test_missing_parent_span_id_is_none():
    assert normalize_otlp_json(_otlp_payload([]))[0].parent_span_id is None


def test_session_key_prefers_explicit_continual_attribute():
    span = CanonicalSpan(
        trace_id="t",
        span_id="s",
        name="n",
        start_time_unix_nano=1,
        end_time_unix_nano=2,
        attributes={
            "continual.session_id": "explicit",
            "session.id": "otel",
            "gen_ai.conversation.id": "conv",
        },
    )
    assert span.session_key() == "explicit"


def test_session_key_falls_back_through_the_precedence_chain():
    def span_with(attrs):
        return CanonicalSpan(
            trace_id="trace-fallback",
            span_id="s",
            name="n",
            start_time_unix_nano=1,
            end_time_unix_nano=2,
            attributes=attrs,
        )

    assert span_with({"session.id": "otel"}).session_key() == "otel"
    assert span_with({"gen_ai.conversation.id": "conv"}).session_key() == "conv"
    # Nothing better available: degrade to one-episode-per-trace.
    assert span_with({}).session_key() == "trace-fallback"


def test_is_llm_call_detects_gen_ai_spans():
    def span_with(attrs):
        return CanonicalSpan(
            trace_id="t",
            span_id="s",
            name="n",
            start_time_unix_nano=1,
            end_time_unix_nano=2,
            attributes=attrs,
        )

    assert span_with({"gen_ai.request.model": "gpt-4o"}).is_llm_call() is True
    assert span_with({"gen_ai.system": "openai"}).is_llm_call() is True
    assert span_with({"http.method": "GET"}).is_llm_call() is False


def test_span_hash_is_stable_and_content_sensitive():
    a = CanonicalSpan(
        trace_id="t",
        span_id="s",
        name="n",
        start_time_unix_nano=1,
        end_time_unix_nano=2,
        attributes={"x": 1},
    )
    b = a.model_copy(deep=True)
    c = a.model_copy(update={"attributes": {"x": 2}}, deep=True)
    assert a.span_hash() == b.span_hash()
    assert a.span_hash() != c.span_hash()


def test_malformed_span_is_skipped_not_fatal():
    # A span missing spanId cannot be addressed; drop it rather than reject the
    # whole batch, or one bad span costs us every good span in the export.
    payload = _otlp_payload([])
    payload["resourceSpans"][0]["scopeSpans"][0]["spans"].append({"name": "broken"})
    spans = normalize_otlp_json(payload)
    assert len(spans) == 1

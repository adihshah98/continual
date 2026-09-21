from continual.hashing import canonical_json, content_hash


def test_key_order_does_not_change_the_hash():
    assert content_hash({"a": 1, "b": 2}) == content_hash({"b": 2, "a": 1})


def test_different_content_changes_the_hash():
    assert content_hash({"a": 1}) != content_hash({"a": 2})


def test_hash_is_64_char_lowercase_hex():
    h = content_hash({"a": 1})
    assert len(h) == 64
    assert h == h.lower()
    assert all(c in "0123456789abcdef" for c in h)


def test_nested_key_order_does_not_change_the_hash():
    left = {"outer": {"x": 1, "y": [{"p": 1, "q": 2}]}}
    right = {"outer": {"y": [{"q": 2, "p": 1}], "x": 1}}
    assert content_hash(left) == content_hash(right)


def test_list_order_does_change_the_hash():
    # Span order within an episode is meaningful; lists must not be sorted.
    assert content_hash([1, 2]) != content_hash([2, 1])


def test_unicode_is_stable():
    # ensure_ascii=False plus UTF-8 encoding, so the same string always hashes
    # the same regardless of the platform's default encoding.
    assert content_hash({"k": "café"}) == content_hash({"k": "café"})


def test_canonical_json_has_no_incidental_whitespace():
    assert canonical_json({"a": 1, "b": 2}) == b'{"a":1,"b":2}'

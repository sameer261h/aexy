"""Tests for the inbound email webhook payload parsers
(UX-INB-027 / UX-DEF-007).

The frontend's inbox thread strip depends on `in_reply_to_message_id`
being populated at ingest time. These tests pin the parser behavior
for the generic JSON path so a future provider integration can't
silently drop the parent pointer.
"""

from __future__ import annotations

from aexy.api.email_webhooks import _parse_inbound_json


class TestGenericJsonParser:
    def test_extracts_in_reply_to_from_explicit_field(self):
        payload = {
            "to": "agent@example.com",
            "from": "user@example.com",
            "subject": "Re: deploy",
            "body": "thanks",
            "in_reply_to": "<parent@example.com>",
        }
        result = _parse_inbound_json(payload)
        assert result is not None
        assert result["in_reply_to_message_id"] == "<parent@example.com>"

    def test_extracts_in_reply_to_from_alt_field_name(self):
        """Some providers emit the snake_case key directly."""
        payload = {
            "to": "agent@example.com",
            "from": "user@example.com",
            "in_reply_to_message_id": "<parent@example.com>",
        }
        result = _parse_inbound_json(payload)
        assert result is not None
        assert result["in_reply_to_message_id"] == "<parent@example.com>"

    def test_in_reply_to_missing_returns_none(self):
        payload = {"to": "agent@example.com", "from": "user@example.com", "subject": "hi"}
        result = _parse_inbound_json(payload)
        assert result is not None
        assert result["in_reply_to_message_id"] is None

    def test_thread_id_still_populated_when_present(self):
        """The new in_reply_to field must not displace the existing
        thread_id semantics — both can be set."""
        payload = {
            "to": "a@example.com",
            "from": "b@example.com",
            "thread_id": "thread-1",
            "in_reply_to": "<parent@example.com>",
        }
        result = _parse_inbound_json(payload)
        assert result["thread_id"] == "thread-1"
        assert result["in_reply_to_message_id"] == "<parent@example.com>"

    def test_in_reply_to_falsback_used_when_no_thread_id(self):
        """When thread_id is missing, the parser already falls back
        to in_reply_to (existing behavior). The new
        in_reply_to_message_id field must coexist with that."""
        payload = {
            "to": "a@example.com",
            "from": "b@example.com",
            "in_reply_to": "<parent@example.com>",
        }
        result = _parse_inbound_json(payload)
        # Legacy thread_id field falls back from in_reply_to
        assert result["thread_id"] == "<parent@example.com>"
        # New explicit field also surfaces
        assert result["in_reply_to_message_id"] == "<parent@example.com>"


class TestPostmarkParser:
    """Postmark uses In-Reply-To headers in its Headers array. The
    JSON parser surfaces it in `thread_id`. This test pins the
    behavior for the postmark branch so it doesn't regress when we
    extend it to populate in_reply_to_message_id directly."""

    def test_postmark_headers_extract_in_reply_to(self):
        """Regression test for a parser bug — the prior implementation
        called `.get("In-Reply-To")` on `Headers[0]` directly, but
        Postmark headers are `[{"Name": "X", "Value": "Y"}, ...]`.
        The fix builds a name-keyed lookup once and uses it for both
        `thread_id` and the new `in_reply_to_message_id` field."""
        payload = {
            "FromFull": {"Email": "user@example.com", "Name": "User"},
            "ToFull": [{"Email": "agent@example.com"}],
            "Subject": "Re: deploy",
            "TextBody": "thanks",
            "MessageID": "<msg-2@postmark>",
            "Headers": [
                # In-Reply-To is intentionally NOT first to catch the
                # original bug if it ever regresses.
                {"Name": "Content-Type", "Value": "text/plain"},
                {"Name": "In-Reply-To", "Value": "<msg-1@postmark>"},
                {"Name": "References", "Value": "<msg-0@postmark> <msg-1@postmark>"},
            ],
        }
        result = _parse_inbound_json(payload)
        assert result is not None
        assert result["thread_id"] == "<msg-1@postmark>"
        assert result["in_reply_to_message_id"] == "<msg-1@postmark>"
        assert result["headers"]["In-Reply-To"] == "<msg-1@postmark>"

    def test_postmark_without_in_reply_to_returns_none(self):
        payload = {
            "FromFull": {"Email": "user@example.com", "Name": "User"},
            "ToFull": [{"Email": "agent@example.com"}],
            "Subject": "Initial message",
            "TextBody": "Hi",
            "MessageID": "<msg-root@postmark>",
            "Headers": [{"Name": "Content-Type", "Value": "text/plain"}],
        }
        result = _parse_inbound_json(payload)
        assert result["thread_id"] is None
        assert result["in_reply_to_message_id"] is None

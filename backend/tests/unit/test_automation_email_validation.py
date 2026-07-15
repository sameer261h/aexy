"""US-6.2 (validate recipient email addresses) and US-6.4 (clear error on an
unresolved {{variable}}) for the live automation email action."""

from aexy.services.crm_automation_service import (
    is_valid_email,
    find_unresolved_variables,
)


class TestEmailValidation:
    def test_accepts_well_formed_addresses(self):
        assert is_valid_email("alice@example.com")
        assert is_valid_email("  bob.smith+tag@sub.example.co.uk  ")  # trimmed

    def test_rejects_malformed_addresses(self):
        for bad in ["", "notanemail", "a@", "@b.com", "a b@c.com", "two@@at.com"]:
            assert not is_valid_email(bad), f"{bad!r} should be rejected"

    def test_rejects_non_string_junk(self):
        assert not is_valid_email("None")


class TestUnresolvedVariables:
    def test_none_when_all_resolved(self):
        assert find_unresolved_variables("Hi Alice", "Welcome to Acme") == []

    def test_flags_leftover_double_brace_tokens(self):
        found = find_unresolved_variables("Hi {{record.first_name}}", "at {{record.company}}")
        assert found == ["{{record.first_name}}", "{{record.company}}"]

    def test_dedupes_and_preserves_order(self):
        found = find_unresolved_variables(
            "{{trigger.x}} then {{record.y}}", "{{trigger.x}} again"
        )
        assert found == ["{{trigger.x}}", "{{record.y}}"]

    def test_ignores_single_brace_literals(self):
        # single braces are ambiguous (could be legit content), only {{...}} is a variable
        assert find_unresolved_variables("a {literal} brace") == []

    def test_handles_empty_and_none_text(self):
        assert find_unresolved_variables("", None) == []

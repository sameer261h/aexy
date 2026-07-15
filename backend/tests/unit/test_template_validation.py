"""E2.2: template validation rejects bad merge tags.

`validate_template` caught syntax errors but not *unknown* merge tags — the
Jinja env used lenient Undefined, so a typo'd `{{ frist_name }}` rendered blank
instead of being flagged. These tests lock detection of undeclared variables.
"""

from aexy.models.email_marketing import EmailTemplate
from aexy.services.template_service import TemplateService


def _tmpl(subject="Hi", html="<p>Hello</p>", text=None, variables=None, ttype="html"):
    return EmailTemplate(
        subject_template=subject, body_html=html, body_text=text,
        template_type=ttype, variables=variables or [],
    )


def test_validate_flags_unknown_merge_tag():
    svc = TemplateService(db=None)
    t = _tmpl(html="<p>Hi {{ first_name }}</p>", variables=[])
    errors = svc.validate_template(t)
    assert any("first_name" in e for e in errors), errors


def test_validate_accepts_declared_variable():
    svc = TemplateService(db=None)
    t = _tmpl(
        html="<p>Hi {{ first_name }}</p>",
        variables=[{"name": "first_name", "type": "string"}],
    )
    assert svc.validate_template(t) == []


def test_validate_catches_syntax_error():
    svc = TemplateService(db=None)
    t = _tmpl(html="<p>Hi {{ first_name </p>", variables=[{"name": "first_name"}])
    assert svc.validate_template(t) != []


def test_validate_flags_unknown_tag_in_subject():
    svc = TemplateService(db=None)
    t = _tmpl(subject="Welcome {{ company }}", variables=[])
    errors = svc.validate_template(t)
    assert any("company" in e for e in errors), errors

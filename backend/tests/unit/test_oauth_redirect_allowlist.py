"""Tests for the post-OAuth redirect allowlist (token-exfiltration guard).

`is_allowed_redirect_url` decides whether the developer JWT may be appended to a
given redirect_url. Allowed: the configured frontend, local dev, ops-configured
extras, and native-app loopback. Everything else is rejected.
"""

import pytest

from aexy.api.auth import is_allowed_redirect_url


def test_none_is_allowed_default_callback():
    assert is_allowed_redirect_url(None) is True


def test_frontend_origin_allowed():
    # Test settings default frontend_url = http://localhost:3000
    assert is_allowed_redirect_url("http://localhost:3000/auth/callback") is True
    assert is_allowed_redirect_url("http://localhost:3003/projects/x") is True


def test_loopback_any_port_allowed():
    assert is_allowed_redirect_url("http://127.0.0.1:55123/callback") is True
    assert is_allowed_redirect_url("http://localhost:61000/callback") is True


@pytest.mark.parametrize(
    "url",
    [
        "https://evil.com",
        "https://evil.com/auth/callback",
        "http://127.0.0.1.evil.com/callback",   # not loopback
        "http://localhost.evil.com/callback",    # not loopback
        "http://localhost@evil.com/callback",    # userinfo trick → host is evil.com
        "ftp://localhost:3000",                  # bad scheme
        "javascript:alert(1)",
        "https://127.0.0.1:9000/callback",       # loopback must be http, not https
    ],
)
def test_disallowed_targets_rejected(url):
    assert is_allowed_redirect_url(url) is False


@pytest.mark.asyncio
async def test_github_login_rejects_evil_redirect(client):
    resp = await client.get(
        "/api/v1/auth/github/login",
        params={"redirect_url": "https://evil.com"},
        follow_redirects=False,
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_github_login_allows_loopback_redirect(client):
    # Loopback passes the allowlist, so we should NOT get the 400 (it proceeds to
    # the provider redirect).
    resp = await client.get(
        "/api/v1/auth/github/login",
        params={"redirect_url": "http://127.0.0.1:54321/callback"},
        follow_redirects=False,
    )
    assert resp.status_code != 400

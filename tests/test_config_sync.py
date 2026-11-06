import pytest
from pydantic import ValidationError

from link_mcp.config import Settings
from link_mcp.sync import document_url


def test_config_parsing_and_repr_do_not_expose_credentials():
    settings = Settings.from_env(
        {
            "LINK_TOKEN": "private-fixture",
            "LINK_CUSTOMER_KEY": "private-key-fixture",
            "LINK_READ_ONLY": "true",
            "LINK_SERVICES": "lms,finance,lms",
            "LINK_API_BASE_URL": "https://example.invalid/api/",
        }
    )
    assert settings.services == ("lms", "finance")
    assert settings.read_only
    assert settings.api_base_url == "https://example.invalid/api"
    assert "private-fixture" not in repr(settings)


@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "https://user:secret@example.invalid/api",
        "https://example.invalid/api?token=secret",
        "https://example.invalid/api#token",
        "https://example.invalid:wrong/api",
        "",
    ],
)
def test_invalid_base_urls_are_rejected(url):
    with pytest.raises(ValidationError):
        Settings(api_base_url=url)


@pytest.mark.parametrize(
    "path",
    [
        "/lmsservice/v3/api-docs/open-api",
        "/api/lmsservice/v3/api-docs/open-api",
        "https://example.invalid/api/lmsservice/v3/api-docs/open-api",
    ],
)
def test_document_url_follows_webpage_routing(path):
    assert document_url("https://example.invalid/api", path) == (
        "https://example.invalid/api/lmsservice/v3/api-docs/open-api"
    )


@pytest.mark.parametrize(
    "url", ["https://other.invalid/docs", "https://example.invalid/docs?token=x"]
)
def test_sync_rejects_external_or_access_bearing_document_urls(url):
    with pytest.raises(ValueError):
        document_url("https://example.invalid/api", url)

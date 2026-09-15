import pytest

import fulltext_article_downloader.tools as tools


@pytest.fixture(autouse=True)
def no_tls_fallback(monkeypatch):
    """Tests monkeypatch requests.get; keep the curl_cffi fallback from making
    real network calls behind their back."""
    monkeypatch.setattr(tools, "_cffi_requests", None)

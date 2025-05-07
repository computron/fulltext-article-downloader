import builtins
import os
import types
import sys
import importlib

import fulltext_article_downloader.tools as tools


class DummyResponse:
    def __init__(self, status_code=200, content=None, json_data=None, url=None):
        self.status_code = status_code
        if isinstance(content, str):
            # store both text and content
            self._text = content
            self.content = content.encode('utf-8')
        else:
            # bytes or None
            self.content = content or b""
            try:
                self._text = self.content.decode('utf-8')
            except Exception:
                self._text = ""
        self._json_data = json_data
        # Simulate final URL after redirects
        self.url = url if url is not None else ""

    @property
    def text(self):
        return self._text

    def json(self):
        if self._json_data is not None:
            return self._json_data
        # If no json_data provided, try to parse content as JSON if content exists
        import json
        try:
            return json.loads(self._text)
        except Exception:
            raise ValueError("No JSON available")

    def iter_content(self, chunk_size=8192):
        # Yield content in one chunk for simplicity
        yield self.content


class DummySession:
    def __init__(self, dummy_get_func):
        self._dummy_get = dummy_get_func
        self.cookies = {}  # dummy cookie jar

    def get(self, url, headers=None, params=None, stream=None,
            allow_redirects=None):
        return self._dummy_get(url, headers=headers, params=params,
                               stream=stream, allow_redirects=allow_redirects)

    def cookies_update(self, cookies):
        # dummy update for compatibility
        self.cookies.update(cookies)


def test_elsevier_api_success(tmp_path, monkeypatch):
    # Setup dummy Elsevier API response
    sample_xml = b"<full-text>Example</full-text>"

    def dummy_get(url, headers=None, params=None, **kwargs):
        # Expect correct URL and API key header
        assert "api.elsevier.com" in url and "/doi/" in url
        assert headers and "X-ELS-APIKey" in headers
        # Simulate success response
        return DummyResponse(status_code=200, content=sample_xml)

    monkeypatch.setattr(tools.requests, "get", dummy_get)
    # Provide API key in env
    os.environ["ELSEVIER_API_KEY"] = "TESTKEY"
    out_file = tmp_path / "article.xml"
    result_path = tools.download_via_elsevier("10.1234/testdoi", str(out_file))
    # The function should return the output path
    assert result_path == str(out_file)
    # The file should have been written with the sample content
    with open(result_path, "rb") as f:
        data = f.read()
    assert data == sample_xml


def test_elsevier_api_errors(monkeypatch):
    # 403 Forbidden error
    def dummy_get_403(url, headers=None, params=None, **kwargs):
        return DummyResponse(status_code=403)

    monkeypatch.setattr(tools.requests, "get", dummy_get_403)
    os.environ["ELSEVIER_API_KEY"] = "TESTKEY"
    try:
        tools.download_via_elsevier("10.1234/testdoi", "out.xml")
    except Exception as e:
        msg = str(e)
        assert "Access denied" in msg

    # 404 Not found error
    def dummy_get_404(url, headers=None, params=None, **kwargs):
        return DummyResponse(status_code=404)

    monkeypatch.setattr(tools.requests, "get", dummy_get_404)
    try:
        tools.download_via_elsevier("10.1234/testdoi", "out.xml")
    except Exception as e:
        msg = str(e)
        assert "not found" in msg


def test_springerpdf_download(monkeypatch, tmp_path):
    # Simulate direct PDF link retrieval for Springer
    dummy_pdf_content = b"PDFDATA"

    def dummy_get(url, headers=None, **kwargs):
        # Should be called with direct content/pdf URL
        assert url.endswith(".pdf")
        return DummyResponse(status_code=200, content=dummy_pdf_content)

    monkeypatch.setattr(tools.requests, "get", dummy_get)
    out_file = tmp_path / "springer.pdf"
    result_path = tools.download_via_springerpdf("10.xxxx/123456",
                                                 str(out_file))
    assert result_path == str(out_file)
    with open(result_path, "rb") as f:
        content = f.read()
    assert content == dummy_pdf_content


def test_wiley_download_success(monkeypatch, tmp_path):
    dummy_pdf = b"WILEYPDF"

    def dummy_get(url, headers=None, **kwargs):
        assert "api.wiley.com" in url
        # Simulate success
        return DummyResponse(status_code=200, content=dummy_pdf)

    monkeypatch.setattr(tools.requests, "get", dummy_get)
    os.environ["WILEY_API_KEY"] = "TESTWILEYKEY"
    out_file = tmp_path / "wiley.pdf"
    result_path = tools.download_via_wiley("10.1002/testdoi", str(out_file))
    with open(result_path, "rb") as f:
        data = f.read()
    assert data == dummy_pdf


def test_wiley_download_failure(monkeypatch):
    def dummy_get_fail(url, headers=None, **kwargs):
        return DummyResponse(status_code=403)

    monkeypatch.setattr(tools.requests, "get", dummy_get_fail)
    os.environ["WILEY_API_KEY"] = "TESTWILEYKEY"
    try:
        tools.download_via_wiley("10.1002/testdoi", "out.pdf")
    except Exception as e:
        assert "Ensure your API key is correct" in str(e)


def test_plos_download(monkeypatch, tmp_path):
    dummy_pdf = b"PLOS_PDF"

    def dummy_get(url, headers=None, **kwargs):
        # The URL should contain PLOS base
        assert "journals.plos.org" in url and "printable" in url
        return DummyResponse(status_code=200, content=dummy_pdf)

    monkeypatch.setattr(tools.requests, "get", dummy_get)
    out_file = tmp_path / "plos.pdf"
    result_path = tools.download_via_plos("10.1371/journal.pone.0000001",
                                          str(out_file))
    with open(result_path, "rb") as f:
        data = f.read()
    assert data == dummy_pdf


def test_unpaywall_no_pdf(monkeypatch):
    # Simulate Unpaywall API returning no PDF link
    def dummy_get_api(url, **kwargs):
        # Should be called for unpaywall API
        if "api.unpaywall.org" in url:
            return DummyResponse(status_code=200,
                                 json_data={"best_oa_location": None})
        # Should not reach here if logic correct
        return DummyResponse(status_code=404)

    monkeypatch.setattr(tools.requests, "get", dummy_get_api)
    os.environ["UNPAYWALL_EMAIL"] = "test@example.com"
    try:
        tools.download_via_unpaywall("10.1234/nopdf", "out.pdf")
    except Exception as e:
        assert "No open-access PDF found" in str(e)


def test_unpaywall_success(monkeypatch, tmp_path):
    dummy_pdf = b"OAPDF"

    def dummy_get(url, headers=None, **kwargs):
        if "api.unpaywall.org" in url:
            # Provide a link in the JSON
            return DummyResponse(status_code=200, json_data={
                "best_oa_location": {
                    "url_for_pdf": "http://example.com/oa.pdf"}})
        if "example.com/oa.pdf" in url:
            return DummyResponse(status_code=200, content=dummy_pdf)
        return DummyResponse(status_code=404)

    monkeypatch.setattr(tools.requests, "get", dummy_get)
    os.environ["UNPAYWALL_EMAIL"] = "test@example.com"
    out_file = tmp_path / "oa.pdf"
    result_path = tools.download_via_unpaywall("10.1234/someoa", str(out_file))
    with open(result_path, "rb") as f:
        data = f.read()
    assert data == dummy_pdf


def test_springeropen_no_key():
    # Ensure environment key is not set
    if "SPRINGER_API_KEY" in os.environ:
        del os.environ["SPRINGER_API_KEY"]
    try:
        tools.download_via_springeropen("10.1007/someid", "out.xml")
    except Exception as e:
        assert "SPRINGER_API_KEY is not set" in str(e)


def test_crossref_tdm_no_pdf(monkeypatch):
    # Simulate crossref returning no PDF links
    def dummy_get(url, **kwargs):
        return DummyResponse(status_code=200, json_data={"message": {"link": [
            {"URL": "http://example.com/landing",
             "content-type": "text/html"}]}})

    monkeypatch.setattr(tools.requests, "get", dummy_get)
    try:
        tools.download_via_crossref_tdm("10.1234/nopdf", "out.pdf")
    except Exception as e:
        assert "No PDF link found via CrossRef" in str(e)


def test_crossref_tdm_success(monkeypatch, tmp_path):
    dummy_pdf = b"PDFDATA_CROSSREF"

    def dummy_get(url, **kwargs):
        if "api.crossref.org" in url:
            return DummyResponse(status_code=200, json_data={"message": {
                "link": [{"URL": "http://example.com/test.pdf",
                          "content-type": "application/pdf"}]}})
        if "example.com/test.pdf" in url:
            return DummyResponse(status_code=200, content=dummy_pdf)
        return DummyResponse(status_code=404)

    monkeypatch.setattr(tools.requests, "get", dummy_get)
    out_file = tmp_path / "crossref.pdf"
    result_path = tools.download_via_crossref_tdm("10.1234/haspdf",
                                                  str(out_file))
    with open(result_path, "rb") as f:
        data = f.read()
    assert data == dummy_pdf


def test_arxiv_download(monkeypatch, tmp_path):
    dummy_pdf = b"ARXIVPDF"

    def dummy_get(url, **kwargs):
        assert "arxiv.org/pdf" in url
        return DummyResponse(status_code=200, content=dummy_pdf)

    monkeypatch.setattr(tools.requests, "get", dummy_get)
    out_file = tmp_path / "arxiv.pdf"
    # Use a DOI format with arXiv prefix
    result_path = tools.download_via_arxiv("10.48550/arXiv.1234.5678",
                                           str(out_file))
    with open(result_path, "rb") as f:
        data = f.read()
    assert data == dummy_pdf


def test_elife_download(monkeypatch, tmp_path):
    html_with_pdf = '<html><body><a href="/articles/12345/download-pdf">PDF</a></body></html>'
    dummy_pdf_content = b"ELIFEPDF"

    def dummy_get(url, headers=None, **kwargs):
        if url.startswith("https://doi.org/"):
            # Simulate redirect to eLife article page
            return DummyResponse(status_code=200, content=html_with_pdf,
                                 url="https://elifesciences.org/articles/12345")
        if "elifesciences.org/articles/12345/download-pdf" in url:
            return DummyResponse(status_code=200, content=dummy_pdf_content)
        return DummyResponse(status_code=404)

    monkeypatch.setattr(tools.requests, "get", dummy_get)
    out_file = tmp_path / "elife.pdf"
    result_path = tools.download_via_elife("10.7554/eLife.12345", str(out_file))
    with open(result_path, "rb") as f:
        data = f.read()
    assert data == dummy_pdf_content


def test_paperscraper_not_installed(monkeypatch):
    # Simulate ImportError for paperscraper
    # Remove any existing paperscraper modules
    sys.modules.pop('paperscraper', None)
    # Monkeypatch import to raise ImportError when paperscraper is imported
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name.startswith('paperscraper'):
            raise ImportError("No module named paperscraper")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    try:
        tools.download_via_paperscraper("10.1101/2020.01.01.000001", "out.pdf")
    except Exception as e:
        assert "paperscraper" in str(e)
    # Restore import just in case
    monkeypatch.setattr(builtins, "__import__", real_import)


def test_aps_download(monkeypatch, tmp_path):
    dummy_pdf = b"APSPDF"
    # Monkeypatch browser_cookie3.load to return some dummy cookies without error
    monkeypatch.setattr(tools.browser_cookie3, "load",
                        lambda domain_name=None: {})

    # Dummy get for session
    def dummy_get(url, headers=None, **kwargs):
        if "api.crossref.org" in url:
            # Simulate crossref with APS link
            return DummyResponse(status_code=200, json_data={"message": {
                "link": [{"URL": "https://harvest.aps.org/test.pdf",
                          "content-type": "application/pdf"}]}})
        if "harvest.aps.org" in url:
            # simulate final pdf
            # Check that Accept header is present for pdf
            if headers:
                assert headers.get("Accept") == "application/pdf"
            return DummyResponse(status_code=200, content=dummy_pdf)
        if url.startswith("https://doi.org/"):
            # Simulate fallback DOI resolution (should not happen if above returns)
            return DummyResponse(status_code=200, content=dummy_pdf)
        return DummyResponse(status_code=404)

    # Monkeypatch requests.Session to use DummySession with our dummy_get
    monkeypatch.setattr(tools.requests, "Session",
                        lambda: DummySession(dummy_get))
    out_file = tmp_path / "aps.pdf"
    result_path = tools.download_via_aps("10.1103/PhysRevLett.120.123456",
                                         str(out_file))
    with open(result_path, "rb") as f:
        data = f.read()
    assert data == dummy_pdf


def test_cambridge_download(monkeypatch, tmp_path):
    dummy_pdf = b"CAMBPDF"
    article_url = "https://www.cambridge.org/core/journals/test-journal/article/12345"
    # HTML with a relative PDF link
    html = '<html><a href="/core/services/aop-cambridge-core/content/view/12345.pdf">PDF</a></html>'

    def dummy_get(url, headers=None, allow_redirects=None, **kwargs):
        if url.startswith("https://doi.org/"):
            # simulate redirect to article page
            return DummyResponse(status_code=200, url=article_url)
        if url == article_url:
            return DummyResponse(status_code=200, content=html)
        if "cambridge.org/core/services" in url and url.endswith(".pdf"):
            return DummyResponse(status_code=200, content=dummy_pdf)
        return DummyResponse(status_code=404)

    monkeypatch.setattr(tools.requests, "get", dummy_get)
    out_file = tmp_path / "camb.pdf"
    result_path = tools.download_via_cambridge("10.1111/abcd.12345",
                                               str(out_file))
    with open(result_path, "rb") as f:
        data = f.read()
    assert data == dummy_pdf


def test_cambridge_no_pdf(monkeypatch):
    # Simulate no PDF link found
    article_url = "https://www.cambridge.org/core/journals/test/article/999"
    html = "<html><body>No PDF here</body></html>"

    def dummy_get(url, **kwargs):
        if url.startswith("https://doi.org/"):
            return DummyResponse(status_code=200, url=article_url)
        if url == article_url:
            return DummyResponse(status_code=200, content=html)
        return DummyResponse(status_code=404)

    monkeypatch.setattr(tools.requests, "get", dummy_get)
    try:
        tools.download_via_cambridge("10.1111/xxxx.999", "out.pdf")
    except Exception as e:
        assert "find PDF link" in str(e)


if __name__ == "__main__":
    import pytest
    import sys

    sys.exit(pytest.main([__file__]))

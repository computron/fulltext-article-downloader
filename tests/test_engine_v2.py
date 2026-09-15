"""Tests for identifier parsing, download verification, the new routes and fetch()."""
import os

import pytest

import fulltext_article_downloader.tools as tools
from fulltext_article_downloader import downloader, identifiers, verify
from tests.test_downloaders import DummyResponse

PDF = b"%PDF-1.4 fake"


def make_pdf(path, text, pages=1):
    """Write a minimal PDF whose pages each carry `text` as extractable Helvetica."""
    safe = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
    objs = ["<< /Type /Catalog /Pages 2 0 R >>", None,
            "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    kids = []
    for _ in range(pages):
        page_no = len(objs) + 1
        objs.append(f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
                    f"/Resources << /Font << /F1 3 0 R >> >> /Contents {page_no + 1} 0 R >>")
        stream = f"BT /F1 12 Tf 72 720 Td ({safe}) Tj ET"
        objs.append(f"<< /Length {len(stream)} >>\nstream\n{stream}\nendstream")
        kids.append(f"{page_no} 0 R")
    objs[1] = f"<< /Type /Pages /Kids [{' '.join(kids)}] /Count {pages} >>"
    out = b"%PDF-1.4\n"; offsets = []
    for i, body in enumerate(objs, start=1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n{body}\nendobj\n".encode()
    xref = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode()
    out += b"".join(f"{o:010d} 00000 n \n".encode() for o in offsets)
    out += f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    with open(path, "wb") as f:
        f.write(out)
    return str(path)


# -- identifiers -------------------------------------------------------------

@pytest.mark.parametrize("raw, kind, value", [
    ("10.1103/PhysRevB.54.11169", "doi", "10.1103/PhysRevB.54.11169"),
    ("https://doi.org/10.1016/j.jpowsour.2013.04.078", "doi", "10.1016/j.jpowsour.2013.04.078"),
    ("doi:10.1002/advs.201900808", "doi", "10.1002/advs.201900808"),
    ("10.48550/arXiv.2504.00812", "arxiv", "2504.00812"),
    ("arXiv:1710.10324", "arxiv", "1710.10324"),
    ("https://arxiv.org/abs/1710.10324v2", "arxiv", "1710.10324v2"),
    ("https://arxiv.org/pdf/1710.10324.pdf", "arxiv", "1710.10324"),
    ("cond-mat/9712061", "arxiv", "cond-mat/9712061"),
    ("PMC6561843", "pmc", "PMC6561843"),
    ("https://pmc.ncbi.nlm.nih.gov/articles/PMC6561843/", "pmc", "PMC6561843"),
    ("fNyXCCZ0g6", "openreview", "fNyXCCZ0g6"),
])
def test_parse_identifiers(raw, kind, value):
    assert identifiers.parse(raw) == (kind, value)


@pytest.mark.parametrize("word", ["not an id", "downloads", "Papers", "output_dir", "custom.pdf"])
def test_parse_rejects_words_and_paths(word):
    with pytest.raises(ValueError):
        identifiers.parse(word)


def test_parse_accepts_real_openreview_ids():
    for rid in ("fNyXCCZ0g6", "BTeWafMOyt", "https://openreview.net/forum?id=fNyXCCZ0g6"):
        assert identifiers.parse(rid)[0] == "openreview"


# -- verification --------------------------------------------------------------

def test_check_pdf_accepts_matching_title(tmp_path):
    p = make_pdf(tmp_path / "a.pdf", "Crystal Graph Convolutional Neural Networks for Materials")
    ok, _ = verify.check_pdf(p, "Crystal Graph <i>Convolutional</i> Neural Networks for an Accurate Materials Model")
    assert ok


def test_check_pdf_rejects_wrong_paper(tmp_path):
    p = make_pdf(tmp_path / "a.pdf", "Assessing Ghana Trade Competitiveness Real Exchange Rate Index")
    ok, reason = verify.check_pdf(p, "Effect of Redox-Active Quinoline on the Hydrogen Evolution Reaction")
    assert not ok and "title" in reason


@pytest.mark.parametrize("first_page", [
    "S1 Supporting Information for Examining the Effects of Monomer Structure",
    "Examining the Effects of Monomer Structure In the format provided by the authors and unedited",
])
def test_check_pdf_rejects_supporting_information(tmp_path, first_page):
    p = make_pdf(tmp_path / "si.pdf", first_page)
    ok, reason = verify.check_pdf(p, "Examining the Effects of Monomer Structure")
    assert not ok and "supporting" in reason


def test_check_pdf_passes_scanned_pdf_without_text(tmp_path):
    from pypdf import PdfWriter
    w = PdfWriter()
    for _ in range(3):
        w.add_blank_page(612, 792)
    with open(tmp_path / "scan.pdf", "wb") as f:
        w.write(f)
    assert verify.check_pdf(str(tmp_path / "scan.pdf"), "Any title")[0]


def test_check_xml_rejects_abstract_only_elsevier(tmp_path):
    p = tmp_path / "a.xml"
    p.write_bytes(b"<full-text-retrieval-response><coredata><dc:title>T</dc:title></coredata></full-text-retrieval-response>")
    assert not verify.check_xml(str(p))[0]
    p.write_bytes(b"<full-text-retrieval-response><coredata/><body><ce:para>Body text</ce:para></body></full-text-retrieval-response>")
    assert verify.check_xml(str(p))[0]


# -- download fallbacks --------------------------------------------------------

def test_download_file_retries_with_plain_user_agent_on_html(monkeypatch, tmp_path):
    seen = []

    def dummy_get(url, headers=None, **kwargs):
        seen.append(headers["User-Agent"])
        if headers["User-Agent"] == tools.BROWSER_USER_AGENT:
            return DummyResponse(status_code=200, content=b"<html>viewer page</html>")
        return DummyResponse(status_code=200, content=PDF)

    monkeypatch.setattr(tools.requests, "get", dummy_get)
    out = tmp_path / "hal.pdf"
    assert tools._download_file("https://hal.science/x/document", str(out), expect_pdf=True) == str(out)
    assert seen == [tools.BROWSER_USER_AGENT, tools.PLAIN_USER_AGENT]


def test_download_file_retries_with_plain_user_agent_on_406(monkeypatch, tmp_path):
    def dummy_get(url, headers=None, **kwargs):
        if headers["User-Agent"] == tools.BROWSER_USER_AGENT:
            return DummyResponse(status_code=406)
        return DummyResponse(status_code=200, content=PDF)

    monkeypatch.setattr(tools.requests, "get", dummy_get)
    assert tools._download_file("https://repo.example/x.pdf", str(tmp_path / "r.pdf"), expect_pdf=True)


def test_download_file_keeps_caller_user_agent_single_attempt(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(tools.requests, "get",
                        lambda url, headers=None, **kw: calls.append(headers["User-Agent"]) or DummyResponse(status_code=200, content=b"<html/>"))
    with pytest.raises(Exception, match="non-PDF"):
        tools._download_file("https://x/y.pdf", str(tmp_path / "y.pdf"), headers={"User-Agent": "custom"}, expect_pdf=True)
    assert calls == ["custom"]


# -- new routes ----------------------------------------------------------------

def test_europepmc_uses_repository_fulltext_link(monkeypatch, tmp_path):
    record = {"doi": "10.1038/s41557-022-00933-0", "pmcid": None, "isOpenAccess": "N",
              "fullTextUrlList": {"fullTextUrl": [
                  {"documentStyle": "pdf", "availability": "Open access", "site": "UNIGE", "url": "https://archive.unige.ch/x.pdf"},
                  {"documentStyle": "doi", "availability": "Subscription required", "url": "https://doi.org/10.1038/s41557-022-00933-0"}]}}

    def dummy_get(url, **kw):
        if "europepmc/webservices" in url:
            return DummyResponse(status_code=200, json_data={"resultList": {"result": [record]}})
        if "archive.unige.ch" in url:
            return DummyResponse(status_code=200, content=PDF)
        return DummyResponse(status_code=404)

    monkeypatch.setattr(tools.requests, "get", dummy_get)
    out = tmp_path / "e.pdf"
    r = tools.download_via_europepmc("10.1038/s41557-022-00933-0", str(out))
    assert r == str(out) and r.source == "europepmc" and "UNIGE" in r.note


def test_europepmc_falls_back_to_pmc_author_manuscript_xml(monkeypatch, tmp_path):
    record = {"doi": "10.1038/s41593-020-0623-9", "pmcid": "PMC7195223", "inEPMC": "Y", "isOpenAccess": "N", "fullTextUrlList": {"fullTextUrl": []}}

    def dummy_get(url, **kw):
        if "europepmc/webservices/rest/search" in url:
            return DummyResponse(status_code=200, json_data={"resultList": {"result": [record]}})
        if "pdf=render" in url:
            return DummyResponse(status_code=403)
        if url.endswith("/PMC7195223/fullTextXML"):
            return DummyResponse(status_code=200, content=b"<article><body><p>manuscript text</p></body></article>")
        return DummyResponse(status_code=404)

    monkeypatch.setattr(tools.requests, "get", dummy_get)
    r = tools.download_via_europepmc("10.1038/s41593-020-0623-9", str(tmp_path / "e.pdf"))
    assert r.endswith("e.xml") and r.source == "europepmc" and "author manuscript" in r.note


def test_europepmc_ignores_records_for_other_dois(monkeypatch, tmp_path):
    record = {"doi": "10.1000/other", "fullTextUrlList": {"fullTextUrl": [
        {"documentStyle": "pdf", "availability": "Open access", "url": "https://x/other.pdf"}]}}
    monkeypatch.setattr(tools.requests, "get",
                        lambda url, **kw: DummyResponse(status_code=200, json_data={"resultList": {"result": [record]}}))
    with pytest.raises(Exception, match="no open-access PDF"):
        tools.download_via_europepmc("10.1000/mine", str(tmp_path / "e.pdf"))


def test_semantic_scholar_notes_green_copies(monkeypatch, tmp_path):
    def dummy_get(url, **kw):
        if "semanticscholar" in url:
            return DummyResponse(status_code=200, json_data={"openAccessPdf": {"url": "https://arxiv.org/pdf/2210.15702", "status": "GREEN"}})
        return DummyResponse(status_code=200, content=PDF)

    monkeypatch.setattr(tools.requests, "get", dummy_get)
    r = tools.download_via_semantic("10.1038/s41565-023-01515-y", str(tmp_path / "s.pdf"))
    assert r.source == "semantic" and "preprint" in r.note


def test_chemrxiv_uses_open_engage_api(monkeypatch, tmp_path):
    def dummy_get(url, **kw):
        if "cambridge.org/engage/coe/public-api" in url:
            return DummyResponse(status_code=200, json_data={"asset": {"original": {"url": "https://www.cambridge.org/engage/api-gateway/x.pdf"}}})
        if "api-gateway" in url:
            return DummyResponse(status_code=200, content=PDF)
        return DummyResponse(status_code=404)

    monkeypatch.setattr(tools.requests, "get", dummy_get)
    r = tools.download_via_chemrxiv("10.26434/chemrxiv-2024-xbgq5", str(tmp_path / "c.pdf"))
    assert r.source == "chemrxiv" and "preprint" in r.note


def test_biorxiv_resolves_server_and_retries_503(monkeypatch, tmp_path):
    calls = []

    def dummy_get(url, **kw):
        calls.append(url)
        if "api.biorxiv.org/details/biorxiv/" in url:
            return DummyResponse(status_code=200, json_data={"collection": []})
        if "api.biorxiv.org/details/medrxiv/" in url:
            return DummyResponse(status_code=200, json_data={"collection": [{"version": "1"}, {"version": "2"}]})
        if url.endswith("v2.full.pdf"):
            n = calls.count(url)
            # each _download_file call retries a 5xx/429 once itself, so pairs are consumed per attempt
            return DummyResponse(status_code=200, content=PDF) if n > 4 else DummyResponse(status_code=[503, 503, 429, 429][n - 1])
        return DummyResponse(status_code=404)

    slept = []
    monkeypatch.setattr(tools.requests, "get", dummy_get)
    monkeypatch.setattr(tools.time, "sleep", slept.append)
    r = tools.download_via_biorxiv("10.1101/2024.01.01.000001", str(tmp_path / "b.pdf"))
    assert r.source == "biorxiv" and "medrxiv" in r.note
    assert calls.count("https://www.medrxiv.org/content/10.1101/2024.01.01.000001v2.full.pdf") == 5
    assert tools.BIORXIV_RETRY_AFTER in slept  # the 429 answer waited for bioRxiv's Retry-After


def test_biorxiv_falls_back_to_unversioned_url_when_api_is_throttled(monkeypatch, tmp_path):
    def dummy_get(url, **kw):
        if "api.biorxiv.org" in url:
            return DummyResponse(status_code=200, content=b"")  # throttled: empty body, not JSON
        if url == "https://www.biorxiv.org/content/10.1101/2024.01.01.000002.full.pdf":
            return DummyResponse(status_code=200, content=PDF)
        return DummyResponse(status_code=404)

    monkeypatch.setattr(tools.requests, "get", dummy_get)
    monkeypatch.setattr(tools.time, "sleep", lambda s: None)
    r = tools.download_via_biorxiv("10.1101/2024.01.01.000002", str(tmp_path / "b.pdf"))
    assert r.source == "biorxiv" and "biorxiv preprint" in r.note


def test_mdpi_builds_cdn_path_and_tries_title_slug(monkeypatch, tmp_path):
    seen = []

    def dummy_get(url, **kw):
        seen.append(url)
        if "api.crossref.org" in url:
            return DummyResponse(status_code=200, json_data={"message": {"container-title": ["Energies"], "volume": "7", "article-number": "7732"}})
        if url.endswith("energies-07-07732.pdf"):
            return DummyResponse(status_code=200, content=PDF)
        return DummyResponse(status_code=404)

    monkeypatch.setattr(tools.requests, "get", dummy_get)
    tools.download_via_mdpi("10.3390/en7117732", str(tmp_path / "m.pdf"))
    assert seen[1:] == ["https://mdpi-res.com/d_attachment/en/en-07-07732/article_deploy/en-07-07732.pdf",
                        "https://mdpi-res.com/d_attachment/energies/energies-07-07732/article_deploy/energies-07-07732.pdf"]


def test_unpaywall_follows_repository_landing_page_to_pdf(monkeypatch, tmp_path):
    data = {"best_oa_location": None, "oa_locations": [
        {"host_type": "repository", "url_for_pdf": None, "url": "https://hal.science/hal-1", "version": "acceptedVersion"}]}
    html = '<html><head><meta name="citation_pdf_url" content="/hal-1/document"></head></html>'

    def dummy_get(url, **kw):
        if "api.unpaywall.org" in url:
            return DummyResponse(status_code=200, json_data=data)
        if url == "https://hal.science/hal-1":
            return DummyResponse(status_code=200, content=html.encode(), headers={"Content-Type": "text/html"})
        if url == "https://hal.science/hal-1/document":
            return DummyResponse(status_code=200, content=PDF)
        return DummyResponse(status_code=404)

    monkeypatch.setattr(tools.requests, "get", dummy_get)
    monkeypatch.setenv("UNPAYWALL_EMAIL", "a@b.c")
    r = tools.download_via_unpaywall("10.1000/landing", str(tmp_path / "l.pdf"))
    assert open(r, "rb").read(5) == b"%PDF-" and "acceptedVersion" in r.note


def test_check_pdf_rejects_textless_stub(tmp_path):
    from pypdf import PdfWriter
    w = PdfWriter(); w.add_blank_page(612, 792); w.add_blank_page(612, 792)
    with open(tmp_path / "stub.pdf", "wb") as f:
        w.write(f)
    ok, reason = verify.check_pdf(str(tmp_path / "stub.pdf"), "Any title")
    assert not ok and "fewer than three pages" in reason


def test_pmc_falls_back_to_europepmc_xml_when_render_refuses(monkeypatch, tmp_path):
    def dummy_get(url, **kw):
        if "pdf=render" in url:
            return DummyResponse(status_code=403)
        if url.endswith("/PMC1/fullTextXML"):
            return DummyResponse(status_code=200, content=b"<article><front/><body><p>Full text</p></body></article>")
        return DummyResponse(status_code=404)

    monkeypatch.setattr(tools.requests, "get", dummy_get)
    r = tools.download_via_pmc("PMC1", str(tmp_path / "p.pdf"))
    assert r.endswith("p.xml") and r.source == "pmc" and "XML" in r.note and verify.check_xml(r)[0]


def test_pmc_falls_back_to_ncbi_efetch_for_author_manuscripts(monkeypatch, tmp_path):
    def dummy_get(url, **kw):
        if "pdf=render" in url or url.endswith("/fullTextXML"):
            return DummyResponse(status_code=403 if "render" in url else 404)
        if "efetch.fcgi" in url and kw.get("params", {}).get("id") == "8189344":
            return DummyResponse(status_code=200, content=b"<pmc-articleset><article><body><p>manuscript</p></body></article></pmc-articleset>")
        return DummyResponse(status_code=404)

    monkeypatch.setattr(tools.requests, "get", dummy_get)
    r = tools.download_via_pmc("PMC8189344", str(tmp_path / "p.pdf"))
    assert r.endswith("p.xml") and "NCBI" in r.note and verify.check_xml(r)[0]


def test_zenodo_downloads_first_pdf_of_record(monkeypatch, tmp_path):
    def dummy_get(url, **kw):
        if url == "https://zenodo.org/api/records/8425709":
            return DummyResponse(status_code=200, json_data={"files": [
                {"key": "data.csv", "links": {"self": "https://zenodo.org/api/records/8425709/files/data.csv/content"}},
                {"key": "paper.pdf", "links": {"self": "https://zenodo.org/api/records/8425709/files/paper.pdf/content"}}]})
        if url.endswith("paper.pdf/content"):
            return DummyResponse(status_code=200, content=PDF)
        return DummyResponse(status_code=404)

    monkeypatch.setattr(tools.requests, "get", dummy_get)
    assert open(tools.download_via_zenodo("10.5281/zenodo.8425709", str(tmp_path / "z.pdf")), "rb").read(5) == b"%PDF-"


def test_semantic_searches_by_title_only_with_key(monkeypatch, tmp_path):
    calls = []

    def dummy_get(url, **kw):
        calls.append(url)
        if "/paper/DOI:" in url:
            return DummyResponse(status_code=200, json_data={"title": "Entropy Shocks in Euler Systems", "openAccessPdf": None})
        if url.endswith("/paper/search"):
            return DummyResponse(status_code=200, json_data={"data": [
                {"title": "Unrelated Paper", "openAccessPdf": {"url": "https://arxiv.org/pdf/0.1"}},
                {"title": "Entropy shocks in Euler systems", "openAccessPdf": {"url": "https://arxiv.org/pdf/1.2", "status": "green"}}]})
        if url == "https://arxiv.org/pdf/1.2":
            return DummyResponse(status_code=200, content=PDF)
        return DummyResponse(status_code=404)

    monkeypatch.setattr(tools.requests, "get", dummy_get)
    monkeypatch.delenv("SEMANTIC_SCHOLAR_API_KEY", raising=False)
    with pytest.raises(Exception, match="no open-access copy"):
        tools.download_via_semantic("10.1007/x", str(tmp_path / "s.pdf"))
    assert not any(u.endswith("/paper/search") for u in calls)
    monkeypatch.setenv("SEMANTIC_SCHOLAR_API_KEY", "k")
    r = tools.download_via_semantic("10.1007/x", str(tmp_path / "s.pdf"))
    assert r.source == "semantic" and "preprint" in r.note and "https://arxiv.org/pdf/1.2" in calls


def test_semantic_uses_arxiv_id_when_record_has_no_pdf(monkeypatch, tmp_path):
    def dummy_get(url, **kw):
        if "/paper/DOI:" in url:
            return DummyResponse(status_code=200, json_data={"title": "T", "openAccessPdf": {"url": ""}, "externalIds": {"ArXiv": "2401.06446"}})
        if "arxiv.org" in url:
            return DummyResponse(status_code=200, content=PDF)
        return DummyResponse(status_code=404)

    monkeypatch.setattr(tools.requests, "get", dummy_get)
    monkeypatch.delenv("SEMANTIC_SCHOLAR_API_KEY", raising=False)
    r = tools.download_via_semantic("10.1214/x", str(tmp_path / "s.pdf"))
    assert r.source == "semantic" and "arXiv version" in r.note and open(r, "rb").read(5) == b"%PDF-"


def test_unpaywall_prefers_version_of_record_then_repositories(monkeypatch, tmp_path):
    data = {"best_oa_location": {"host_type": "repository", "url_for_pdf": "https://repo/sub.pdf", "version": "submittedVersion"},
            "oa_locations": [
                {"host_type": "repository", "url_for_pdf": "https://repo/sub.pdf", "version": "submittedVersion"},
                {"host_type": "publisher", "url_for_pdf": "https://pub/x.pdf", "version": "publishedVersion"},
                {"host_type": "repository", "url_for_pdf": "https://repo/x.pdf", "version": "publishedVersion"}]}
    seen = []

    def dummy_get(url, **kw):
        seen.append(url)
        if "unpaywall" in url:
            return DummyResponse(status_code=200, json_data=data)
        return DummyResponse(status_code=200, content=PDF)

    monkeypatch.setattr(tools.requests, "get", dummy_get)
    monkeypatch.setenv("UNPAYWALL_EMAIL", "e@example.org")
    r = tools.download_via_unpaywall("10.1000/x", str(tmp_path / "u.pdf"))
    assert seen[1] == "https://repo/x.pdf" and r.note is None  # published version, repository host first
    data["oa_locations"] = [data["oa_locations"][0]]; seen.clear()
    r = tools.download_via_unpaywall("10.1000/y", str(tmp_path / "v.pdf"))
    assert "submittedVersion" in r.note


def test_elsevier_rejects_abstract_only_xml(monkeypatch, tmp_path):
    monkeypatch.setenv("ELSEVIER_API_KEY", "k")

    def dummy_get(url, headers=None, params=None, **kw):
        if headers["Accept"] == "application/pdf":
            return DummyResponse(status_code=200, content=PDF, headers={"X-ELS-Status": "WARNING - not entitled"})
        return DummyResponse(status_code=200, content=b"<full-text-retrieval-response><coredata><dc:title>T</dc:title></coredata></full-text-retrieval-response>")

    monkeypatch.setattr(tools.requests, "get", dummy_get)
    with pytest.raises(Exception, match="abstract-only"):
        tools.download_via_elsevier("10.1016/j.x", str(tmp_path / "e.pdf"))


def test_elsevier_writes_markdown_next_to_full_xml(monkeypatch, tmp_path):
    monkeypatch.setenv("ELSEVIER_API_KEY", "k")
    xml = (b'<full-text-retrieval-response xmlns:ce="http://www.elsevier.com/xml/common/dtd" '
           b'xmlns:dc="http://purl.org/dc/elements/1.1/"><coredata><dc:title>A title</dc:title>'
           b'<dc:creator>A. Author</dc:creator></coredata><body><ce:para>First paragraph.</ce:para>'
           b'<ce:para>Second paragraph.</ce:para></body></full-text-retrieval-response>')

    def dummy_get(url, headers=None, params=None, **kw):
        if headers["Accept"] == "application/pdf":
            return DummyResponse(status_code=200, content=PDF, headers={"X-ELS-Status": "WARNING - not entitled"})
        return DummyResponse(status_code=200, content=xml)

    monkeypatch.setattr(tools.requests, "get", dummy_get)
    r = tools.download_via_elsevier("10.1016/j.x", str(tmp_path / "e.pdf"))
    assert r.endswith(".xml") and os.path.exists(tmp_path / "e.md")
    md = (tmp_path / "e.md").read_text()
    assert md.startswith("# A title") and "Second paragraph." in md and "A. Author" in md


# -- fetch() -------------------------------------------------------------------

def test_fetch_dispatches_arxiv_ids_without_crossref(monkeypatch, tmp_path):
    monkeypatch.setattr(downloader, "get_publisher_from_doi", lambda doi: pytest.fail("Crossref queried"))

    def fake_arxiv(value, output_path):
        assert value == "1710.10324"
        make_pdf(output_path, "Crystal Graph Convolutional Neural Networks"); return output_path

    monkeypatch.setitem(downloader.TOOL_FUNCTIONS, "arxiv", fake_arxiv)
    r = downloader.fetch("https://arxiv.org/abs/1710.10324", str(tmp_path))
    assert r["success"] and r["path"].endswith("1710.10324.pdf") and r["source"] == "arxiv"


def test_fetch_rejects_wrong_paper_and_tries_next_tool(monkeypatch, tmp_path):
    doi = "10.1021/acscatal.4c03819"
    downloader._crossref_metadata[doi] = {"publisher": "American Chemical Society (ACS)",
                                          "title": "Effect of Redox-Active Quinoline on the Hydrogen Evolution Reaction"}

    def wrong(value, output_path):
        make_pdf(output_path, "Assessing Ghana Trade Competitiveness Real Exchange Rate Index"); return output_path

    def right(value, output_path):
        make_pdf(output_path, "Effect of Redox-Active Quinoline on the Hydrogen Evolution Reaction")
        return tools.Fetched(output_path, source="osti", note="OSTI accepted manuscript")

    monkeypatch.setitem(downloader.TOOL_FUNCTIONS, "unpaywall", wrong)
    monkeypatch.setitem(downloader.TOOL_FUNCTIONS, "osti", right)
    r = downloader.fetch(doi, str(tmp_path), tools=["unpaywall", "osti"])
    assert r["success"] and r["source"] == "osti" and r["note"] == "OSTI accepted manuscript"
    assert r["attempts"][0]["tool"] == "unpaywall" and "rejected" in r["attempts"][0]["error"]


def test_fetch_reports_all_attempts_on_failure(monkeypatch, tmp_path):
    monkeypatch.setitem(downloader.TOOL_FUNCTIONS, "unpaywall", lambda v, p: (_ for _ in ()).throw(Exception("not OA")))
    monkeypatch.setitem(downloader.TOOL_FUNCTIONS, "osti", lambda v, p: (_ for _ in ()).throw(Exception("no record")))
    r = downloader.fetch("10.1000/x", str(tmp_path), tools=["unpaywall", "osti"])
    assert not r["success"] and [a["tool"] for a in r["attempts"]] == ["unpaywall", "osti"]
    assert "not OA" in r["error"] and "no record" in r["error"]


def test_fetch_reuses_existing_file(monkeypatch, tmp_path):
    make_pdf(tmp_path / "10.1000_x.pdf", "Some Title Words Here")
    monkeypatch.setitem(downloader.TOOL_FUNCTIONS, "unpaywall", lambda v, p: pytest.fail("network used"))
    r = downloader.fetch("10.1000/x", str(tmp_path), tools=["unpaywall"])
    assert r["success"] and r["source"] == "cache"


def test_download_article_raises_with_last_error(monkeypatch, tmp_path):
    monkeypatch.setitem(downloader.TOOL_FUNCTIONS, "unpaywall", lambda v, p: (_ for _ in ()).throw(Exception("not OA")))
    with pytest.raises(Exception, match="All download methods failed for DOI 10.1000/x. Last error: not OA"):
        downloader.download_article("10.1000/x", str(tmp_path), tools=["unpaywall"])


def test_fetch_many_keeps_order_and_dedupes(monkeypatch, tmp_path):
    monkeypatch.setitem(downloader.TOOL_FUNCTIONS, "arxiv",
                        lambda v, p: make_pdf(p, "Paper " + v) and p)
    r = downloader.fetch_many(["2401.00001", "2401.00002", "2401.00001"], str(tmp_path), workers=2)
    assert list(r) == ["2401.00001", "2401.00002"] and all(x["success"] for x in r.values())


def test_fetch_skips_title_check_for_publisher_routes(monkeypatch, tmp_path):
    doi = "10.1002/adfm.202270139"
    downloader._crossref_metadata[doi] = {"publisher": "Wiley", "title": "Macro- and Nano-Porous 3D-Hierarchical Carbon Lattices (Adv. Funct. Mater. 24/2022)"}

    def cover_item(value, output_path):  # a one-page cover feature whose text is not the title
        make_pdf(output_path, "In article number 2201544, the authors show that 3D-printed electrodes"); return output_path

    monkeypatch.setitem(downloader.TOOL_FUNCTIONS, "wiley", cover_item)
    monkeypatch.setitem(downloader.TOOL_FUNCTIONS, "unpaywall", cover_item)
    assert downloader.fetch(doi, str(tmp_path), tools=["wiley"])["success"]
    assert not downloader.fetch(doi, str(tmp_path / "b"), tools=["unpaywall"])["success"]

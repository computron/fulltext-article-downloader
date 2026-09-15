"""Tests for the opt-in supplementary-file download."""
import io
import zipfile

from fulltext_article_downloader import downloader, supplements
from tests.test_downloaders import DummyResponse

PDF = b"%PDF-1.4 fake"


def test_links_from_html_recognises_publisher_patterns():
    html = """<a href="https://static-content.springer.com/esm/art%3A10.1038%2Fs41563-024-01875-3/MediaObjects/41563_2024_1875_MOESM1_ESM.pdf">SI</a>
    <a href="/action/downloadSupplement?doi=10.1002%2Fadvs.202002866&file=advs2198-sup-0001-SuppMat.pdf">Wiley</a>
    <a href="https://pubs.acs.org/doi/suppl/10.1021/jacs.0c07013/suppl_file/ja0c07013_si_001.pdf">ACS</a>
    <a href="/plosone/article/file?id=10.1371/journal.pone.0171501.s001&type=supplementary">PLOS</a>
    <a href="/content/biorxiv/early/2024/01/22/2024.01.22.576596/DC1/embed/media-1.pdf?download=true">bioRxiv</a>
    <a href="https://journals.aps.org/prl/supplemental/10.1103/PhysRevLett.1.1/supp.pdf">APS</a>
    <a href="https://iopscience.iop.org/1748-9326/17/9/094010/media/ERL_17_9_094010_suppdata.pdf">IOP</a>
    <a href="https://ars.els-cdn.com/content/image/1-s2.0-S0022-mmc1.pdf">Elsevier</a>
    <a href="https://cdn.elifesciences.org/articles/64909/elife-64909-supp1-v2.xlsx">eLife</a>
    <a href="https://www.mdpi.com/2075-4701/15/3/308/s1">MDPI</a>
    <a href="https://www.mdpi.com/2075-4701/15/3/308/s1?version=1">MDPI again</a>
    <a href="https://www.nature.com/articles/s41563-024-01875-3.pdf">the article itself</a>
    <a href="https://www.mdpi.com/2075-4701/15/3/308/notes">not a supplement</a>
    <a href="/action/downloadSupplement?doi=10.1002%2Fadvs.202002866&file=advs2198-sup-0001-SuppMat.pdf">again</a>"""
    links = supplements._links_from_html(html, "https://www.example.org/x")
    assert len(links) == 11 and links[1] == "https://www.example.org/action/downloadSupplement?doi=10.1002%2Fadvs.202002866&file=advs2198-sup-0001-SuppMat.pdf"
    assert not any(l.endswith("s41563-024-01875-3.pdf") for l in links)


def test_extension_from_url_query_then_content_type():
    r = DummyResponse(status_code=200, headers={"Content-Type": "application/zip"})
    assert supplements._extension("https://x/downloadSupplement?doi=1&file=a-sup-0001.xlsx", r) == ".xlsx"
    assert supplements._extension("https://x/media-1.pdf?download=true", r) == ".pdf"
    assert supplements._extension("https://x/content/asset/1234", r) == ".zip"


def test_download_supplements_numbers_files_and_skips_html(monkeypatch, tmp_path):
    def dummy_get(url, **kw):
        if url == "https://doi.org/10.1000/x":
            return DummyResponse(status_code=200, headers={"Content-Type": "text/html"}, url="https://pub.example/article/x",
                                 content='<a href="/sup/a_si_001.pdf">a</a><a href="/sup/b_si_002.xlsx">b</a><a href="/sup/c_si_003.pdf">c</a>')
        if url.endswith("a_si_001.pdf"):
            return DummyResponse(status_code=200, content=PDF)
        if url.endswith("b_si_002.xlsx"):
            return DummyResponse(status_code=200, content=b"<html>please log in</html>")
        if url.endswith("c_si_003.pdf"):
            return DummyResponse(status_code=200, content=PDF)
        return DummyResponse(status_code=404)

    monkeypatch.setattr(supplements.requests, "get", dummy_get)
    monkeypatch.setattr(supplements.tools, "_cffi_requests", None)
    paths = supplements.download_supplements("doi", "10.1000/x", str(tmp_path), "10.1000_x")
    assert [p.rsplit("/", 1)[1] for p in paths] == ["10.1000_x_si1.pdf", "10.1000_x_si2.pdf"]


def test_pmc_supplements_come_from_europepmc_zip(monkeypatch, tmp_path):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("Table_S1.xlsx", b"x"); z.writestr("readme.html", b"<html/>"); z.writestr("Figure_S1.pdf", PDF)
    monkeypatch.setattr(supplements.requests, "get",
                        lambda url, **kw: DummyResponse(status_code=200, content=buf.getvalue()) if url.endswith("/PMC1/supplementaryFiles") else DummyResponse(status_code=404))
    paths = supplements.download_supplements("pmc", "PMC1", str(tmp_path), "PMC1")
    assert [p.rsplit("/", 1)[1] for p in paths] == ["PMC1_si1.xlsx", "PMC1_si2.pdf"]


def test_fetch_reports_supplements_only_when_asked(monkeypatch, tmp_path):
    monkeypatch.setattr(downloader.supplements_module, "download_supplements", lambda *a: ["/tmp/x_si1.pdf"])
    monkeypatch.setattr(downloader, "TOOL_FUNCTIONS", {"arxiv": lambda v, out: open(out, "wb").write(PDF) and out})
    r = downloader.fetch("2301.00001", str(tmp_path), check=False)
    assert r["supplements"] == []
    r = downloader.fetch("2301.00001", str(tmp_path), check=False, skip_existing=False, supplements=True)
    assert r["supplements"] == ["/tmp/x_si1.pdf"]

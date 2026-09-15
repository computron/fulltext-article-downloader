"""Supplementary files (supporting information) for an article.

Opt-in: `fetch(..., supplements=True)`. Publishers keep supplements apart from
the article, as separate files (PDF, spreadsheets, archives, videos) that are
usually free even when the article is not. Open-access indexes do not list
them, so they are found where the publisher puts them: an API when there is
one (ChemRxiv, Elsevier, Europe PMC), otherwise the article's landing page.
Files land next to the article as <base>_si1.<ext>, <base>_si2.<ext>, ...
A missing supplement never affects the article's result.
"""
import io
import os
import re
import zipfile
from urllib.parse import parse_qs, urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from . import tools

# Links on a landing page that point at supplementary files, by publisher habit:
# Springer Nature (MOESM1_ESM), Wiley (downloadSupplement), ACS, Science, PNAS,
# Taylor & Francis, SAGE (suppl_file), RSC and IOP (suppdata), APS
# (/supplemental/), AIP (article-supplement), OUP (supplementary_data),
# bioRxiv (DC1/embed/media-1), PLOS (file?id=...s001), Elsevier (mmc1),
# eLife (-supp1-), Frontiers (articles/<id>/file/), MDPI (/s1), figshare
# downloads, arXiv ancillary files, and generic -sup-1 / _si_1 / .s001 names.
SI_LINK = re.compile(r"MOESM\d+_ESM|downloadSupplement\?|/suppl_file/|suppdata|/supplemental/|article-supplement|"
                     r"supplementary[_-]?data|/DC\d+/embed/media-|article/file\?id=[^\"'&]+\.s\d{3}|mmc\d+\.|"
                     r"-supp\d+-|/api/v\d/articles/\d+/file/|/s\d{1,2}(?:$|\?)|ndownloader\.figshare\.com|/anc/|"
                     r"-sup-\d+|_si_?\d+\.|\.s\d{3}\.(?:pdf|zip|xlsx?|docx?|csv|txt)", re.I)
MAX_BYTES = 500 * 1024 * 1024  # skip supplements larger than this (raw microscopy videos, data dumps)
SI_TEXT = re.compile(r"supplementa|supporting information|supplementary|appendix", re.I)
FILE_EXTENSIONS = (".pdf", ".zip", ".xlsx", ".xls", ".docx", ".doc", ".csv", ".txt", ".mp4", ".avi", ".mov",
                   ".cif", ".xyz", ".mol", ".sdf", ".pptx", ".json", ".tsv", ".gz", ".tar")
CONTENT_TYPES = {"application/pdf": ".pdf", "application/zip": ".zip", "application/x-zip-compressed": ".zip",
                 "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": ".xlsx",
                 "application/vnd.ms-excel": ".xls", "application/msword": ".doc",
                 "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
                 "text/csv": ".csv", "text/plain": ".txt", "video/mp4": ".mp4"}
MAX_FILES = 20


def _get_html(url):
    """Landing page as (final_url, html): browser User-Agent, then a Chrome TLS
    fingerprint for hosts that refuse plain clients. None when neither works."""
    for get, extra in ((requests.get, {}), (tools._cffi_requests.get if tools._cffi_requests else None, {"impersonate": "chrome"})):
        if get is None:
            continue
        try:
            r = get(url, headers={"User-Agent": tools.BROWSER_USER_AGENT}, timeout=tools.REQUEST_TIMEOUT, **extra)
        except Exception:
            continue
        if r.status_code == 200 and "html" in (r.headers.get("Content-Type") or ""):
            return r.url or url, r.text
    return None, None


def _links_from_html(html, base_url):
    """Supplement links on a page, absolute, in page order, without duplicates."""
    soup = BeautifulSoup(html, "html.parser")
    seen, out = set(), []
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        # a link is a supplement when its URL follows a publisher pattern, or when its text says so
        # and it points at a file rather than another page
        text = a.get_text(" ", strip=True).lower()
        if not (SI_LINK.search(href) or (SI_TEXT.search(text) and urlparse(href).path.lower().endswith(FILE_EXTENSIONS))):
            continue
        url = urljoin(base_url, href)
        if url not in seen:
            seen.add(url); out.append(url)
    return out


def _chemrxiv_links(doi):
    r = tools._get_with_retry(requests.get, f"https://www.cambridge.org/engage/coe/public-api/v1/items/doi/{doi}",
                              headers={"User-Agent": tools.BROWSER_USER_AGENT}, timeout=tools.REQUEST_TIMEOUT)
    if r.status_code != 200:
        return []
    return [s["asset"]["original"]["url"] for s in r.json().get("suppItems") or []
            if (s.get("asset") or {}).get("original", {}).get("url")]


def _elsevier_links(doi):
    """Multimedia-component attachments (mmc1, mmc2, ...) named in the
    full-text XML, served by the object API to the same key. Entitled keys
    only; figures and the article's own PDF are not attachments."""
    api_key = os.getenv("ELSEVIER_API_KEY")
    if not api_key:
        return []
    r = tools._get_with_retry(requests.get, f"https://api.elsevier.com/content/article/doi/{doi}",
                              headers={"X-ELS-APIKey": api_key, "Accept": "text/xml"}, timeout=tools.REQUEST_TIMEOUT)
    if r.status_code != 200:
        return []
    eids = dict.fromkeys(e for e in re.findall(r"<xocs:attachment-eid>([^<]+)<", r.text) if re.search(r"-mmc\d+\.", e))
    return [f"https://api.elsevier.com/content/object/eid/{e}?httpAccept=*/*" for e in eids]


def _europepmc_zip(pmcid, output_dir, base_name):
    """Europe PMC bundles an article's supplements as one zip; its members are
    written out as the numbered files."""
    r = tools._get_with_retry(requests.get, f"https://www.ebi.ac.uk/europepmc/webservices/rest/{pmcid}/supplementaryFiles",
                              timeout=tools.REQUEST_TIMEOUT)
    if r.status_code != 200 or not r.content.startswith(b"PK"):
        return []
    paths = []
    with zipfile.ZipFile(io.BytesIO(r.content)) as z:
        for member in z.infolist():
            ext = os.path.splitext(member.filename)[1].lower()
            if member.is_dir() or ext not in FILE_EXTENSIONS or len(paths) >= MAX_FILES:
                continue
            path = os.path.join(output_dir, f"{base_name}_si{len(paths) + 1}{ext}")
            with open(path, "wb") as f:
                f.write(z.read(member))
            paths.append(path)
    return paths


def _pmcid_for_doi(doi):
    r = tools._get_with_retry(requests.get, "https://www.ebi.ac.uk/europepmc/webservices/rest/search",
                              params={"query": f"DOI:{doi}", "format": "json"}, timeout=tools.REQUEST_TIMEOUT)
    for rec in (r.json().get("resultList") or {}).get("result") or [] if r.status_code == 200 else []:
        if (rec.get("doi") or "").lower() == doi.lower() and rec.get("pmcid"):
            return rec["pmcid"]
    return None


def find_supplement_links(kind, value):
    """Candidate supplement URLs for an identifier, best source first."""
    if kind == "doi":
        prefix = value.split("/")[0]
        if prefix == "10.26434":
            return _chemrxiv_links(value)
        if prefix == "10.1101":  # the unversioned URL redirects to the current version's page
            final, _ = _get_html(f"https://www.biorxiv.org/content/{value}")
            if not final or not re.search(r"v\d+$", final):
                return []
            final, html = _get_html(f"{final}.supplementary-material")
            return _links_from_html(html, final) if html else []
        links = _elsevier_links(value) if prefix == "10.1016" else []
        if not links:
            final, html = _get_html(f"https://doi.org/{value}")
            links = _links_from_html(html, final) if html else []
        return links
    if kind == "arxiv":
        final, html = _get_html(f"https://arxiv.org/abs/{value}")
        return _links_from_html(html, final) if html else []
    if kind == "openreview":
        return [f"https://openreview.net/attachment?id={value}&name=supplementary_material"]
    return []


def _extension(url, response):
    path = urlparse(url).path
    for candidate in (parse_qs(urlparse(url).query).get("file", [""])[0], path):
        ext = os.path.splitext(candidate)[1].lower()
        if ext in FILE_EXTENSIONS:
            return ext
    ctype = (response.headers.get("Content-Type") or "").split(";")[0].strip().lower()
    return CONTENT_TYPES.get(ctype, ".bin")


def _download(url, output_dir, base_name, index):
    headers = {"User-Agent": tools.BROWSER_USER_AGENT}
    if url.startswith("https://api.elsevier.com/"):
        headers["X-ELS-APIKey"] = os.getenv("ELSEVIER_API_KEY", "")
    if "biorxiv.org" in url or "medrxiv.org" in url:
        tools._biorxiv_pace()  # same per-address limit as the article downloads
    r = tools._get_with_retry(requests.get, url, headers=headers, timeout=tools.REQUEST_TIMEOUT, stream=True)
    if r.status_code != 200 or int(r.headers.get("Content-Length") or 0) > MAX_BYTES:
        return None
    head = next(r.iter_content(chunk_size=2048), b"")
    if b"<html" in head[:1024].lower() or b"<!doctype" in head[:1024].lower():
        return None  # a login or error page, not a file
    path = os.path.join(output_dir, f"{base_name}_si{index}{_extension(url, r)}")
    with open(path, "wb") as f:
        f.write(head)
        for chunk in r.iter_content(chunk_size=8192):
            f.write(chunk)
    return path


def download_supplements(kind, value, output_dir, base_name):
    """Fetch every supplement found for the identifier; returns the paths written."""
    if kind == "pmc":
        return _europepmc_zip(value, output_dir, base_name)
    try:
        links = find_supplement_links(kind, value)
    except Exception:
        links = []
    paths = []
    for url in links[:MAX_FILES]:
        try:
            path = _download(url, output_dir, base_name, len(paths) + 1)
        except Exception:
            path = None
        if path:
            paths.append(path)
    if not paths and kind == "doi":  # the PMC copy of the article carries its supplements too
        try:
            pmcid = _pmcid_for_doi(value)
            if pmcid:
                paths = _europepmc_zip(pmcid, output_dir, base_name)
        except Exception:
            pass
    return paths

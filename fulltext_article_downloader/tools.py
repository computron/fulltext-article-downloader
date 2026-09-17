import os
import re
import threading
import time
import requests
from bs4 import BeautifulSoup
from urllib.parse import quote, urljoin, urlparse

try:  # optional: Chrome TLS fingerprint for hosts that reject plain HTTPS clients
    from curl_cffi import requests as _cffi_requests
except ImportError:
    _cffi_requests = None
try:  # optional: only the APS route reads browser cookies
    import browser_cookie3
except ImportError:
    browser_cookie3 = None

# Seconds to wait for a connection / response. Without it a single stalled
# request hangs a bulk download forever.
REQUEST_TIMEOUT = 60
# Sent when a caller gives no User-Agent. Several repositories answer the
# python-requests default with an HTML interstitial instead of the PDF
# (eScholarship returns 202 + HTML), while any current browser UA gets the file.
BROWSER_USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)
# Some repositories do the opposite of nature.com: HAL serves an HTML viewer
# page to browser User-Agents and the PDF to non-browser clients, and a few
# DSpace hosts answer browsers with 406. Downloads therefore retry once with
# the plain python-requests User-Agent when the browser UA gets no PDF.
PLAIN_USER_AGENT = requests.utils.default_user_agent()
# Status codes worth one retry: rate limiting and transient server errors.
# Publisher and index APIs return these sporadically under concurrent load,
# and a single 2 s pause usually clears them.
RETRY_STATUS_CODES = (429, 500, 502, 503, 504)

# Some publishers put a commercial bot-management challenge in front of the
# article PDF. The challenge answers 200 with an HTML page (or redirects to the
# vendor's validation host), so without this check it looks identical to a
# landing page whose PDF link we failed to parse. It is not: no User-Agent,
# TLS fingerprint or link extraction reaches the file, and this package does
# not try to defeat these systems. Detecting them lets the error say so and
# stops us retrying a request that cannot succeed.
_BOT_WALL_MARKERS = (
    ("Radware Bot Manager", ("perfdrive.com", "bot manager captcha")),
    ("Cloudflare", ("/cdn-cgi/challenge-platform", "just a moment...",
                    "attention required! | cloudflare")),
    ("PerimeterX", ("perimeterx", "px-captcha")),
    ("Imperva Incapsula", ("_incapsula_", "incapsula incident")),
)


def _bot_wall(sample: bytes, final_url: str = ""):
    """Name the bot-management service when `sample` (the first bytes of a
    response that should have been a PDF) or the redirect target is one of
    their challenge pages, else None."""
    hay = (final_url or "").lower() + " " + sample[:4096].decode("utf-8", "ignore").lower()
    for service, markers in _BOT_WALL_MARKERS:
        if any(m in hay for m in markers):
            return service
    return None



class Fetched(str):
    """Path of a downloaded file. Behaves as a plain str; `note` carries a
    caveat when the file is not the publisher's version of record (preprint,
    accepted manuscript) and `source` names the route that produced it."""

    def __new__(cls, path, note=None, source=None):
        obj = super().__new__(cls, path)
        obj.note = note
        obj.source = source
        return obj


def _get_with_retry(get, url, **kwargs):
    """Call `get(url, **kwargs)`, retrying once on a connection error or a
    status in RETRY_STATUS_CODES, after the server's Retry-After (capped at
    30 s) or 2 s."""
    for attempt in (0, 1):
        try:
            response = get(url, **kwargs)
        except Exception:
            if attempt:
                raise
            time.sleep(2)
            continue
        if response.status_code in RETRY_STATUS_CODES and not attempt:
            retry_after = str(response.headers.get("Retry-After", ""))
            time.sleep(min(float(retry_after), 30) if retry_after.isdigit() else 2)
            continue
        return response
    return response


# Crossref's limits depend on the pool. With a contact email ("polite" pool)
# it allows 10 requests/s and 3 in flight; without one, 5/s and 1 in flight.
# Concurrent runs exceed the anonymous limit at once and get HTTP 429, and a
# failed publisher lookup silently drops the publisher-specific tools.
_crossref_slots = {True: threading.BoundedSemaphore(3), False: threading.BoundedSemaphore(1)}
_crossref_pace_lock = threading.Lock()
_crossref_last_call = [0.0]


def _crossref_get(url):
    """GET a Crossref API URL with the configured contact email (UNPAYWALL_EMAIL),
    paced to the pool's rate and concurrency limits."""
    email = os.getenv("UNPAYWALL_EMAIL")
    min_gap = 0.1 if email else 0.2
    with _crossref_slots[bool(email)]:
        with _crossref_pace_lock:
            wait = _crossref_last_call[0] + min_gap - time.time()
            if wait > 0:
                time.sleep(wait)
            _crossref_last_call[0] = time.time()
        return _get_with_retry(requests.get, url,
                               params={"mailto": email} if email else None,
                               timeout=REQUEST_TIMEOUT)

def _download_file(url: str, output_path: str, headers=None, session=None,
                   expect_pdf=False):
    """
    Download a URL to output_path using streaming. Raises on a non-200 status.
    With expect_pdf=True the file must start with the %PDF- magic bytes;
    publishers frequently serve an HTML error or landing page with status 200,
    which would otherwise be saved as a fake .pdf. On mismatch the file is
    removed and an Exception raised. Leave it False for routes that can
    legitimately return non-PDF full text (e.g. XML).

    A browser User-Agent is sent unless the caller sets one. When that yields
    no PDF (HTML body, 403 or 406) the request is retried with the plain
    python-requests User-Agent, then, if curl_cffi is installed and no session
    cookies are involved, with a Chrome TLS fingerprint.
    """
    req = session.get if session else requests.get
    caller = headers or {}
    browser_headers = {"User-Agent": BROWSER_USER_AGENT, **caller}
    try:
        return _fetch_once(req, url, output_path, browser_headers, expect_pdf)
    except _Retryable as e:
        last_error = e
    # A non-PDF body or 406 is what a UA-sniffing repository returns to browsers.
    if "User-Agent" not in caller and last_error.status in (200, 406):
        try:
            return _fetch_once(req, url, output_path, {"User-Agent": PLAIN_USER_AGENT, **caller}, expect_pdf)
        except _Retryable as e:
            last_error = e
    # 403 or an anti-bot page: try a real browser TLS fingerprint.
    if _cffi_requests is not None and session is None and last_error.status in (200, 403):
        try:
            return _fetch_once(_cffi_requests.get, url, output_path, browser_headers, expect_pdf,
                               impersonate="chrome")
        except Exception:
            pass
    raise Exception(str(last_error))


class _Retryable(Exception):
    """A failure that a different User-Agent or TLS fingerprint may fix."""

    def __init__(self, message, status):
        super().__init__(message)
        self.status = status


def _fetch_once(get, url, output_path, headers, expect_pdf, **extra):
    try:
        if extra:  # curl_cffi: no streaming, no retry wrapper
            response = get(url, headers=headers, timeout=REQUEST_TIMEOUT, **extra)
        else:
            response = _get_with_retry(get, url, headers=headers, stream=True,
                                       timeout=REQUEST_TIMEOUT)
    except Exception as e:
        raise Exception(f"Request error for {url}: {e}")
    if response.status_code != 200:
        msg = f"Failed to download {url} (status code: {response.status_code})"
        if response.status_code in (403, 406):
            raise _Retryable(msg, response.status_code)
        raise Exception(msg)
    try:
        with open(output_path, "wb") as f:
            if extra:
                f.write(response.content)
            else:
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
    except Exception as e:
        if os.path.exists(output_path):  # a connection dropped mid-stream leaves a truncated file
            os.remove(output_path)
        raise Exception(f"Error writing to file {output_path}: {e}")
    if expect_pdf:
        with open(output_path, "rb") as fh:
            head = fh.read(4096)
        if head[:5] != b"%PDF-":
            os.remove(output_path)
            service = _bot_wall(head, getattr(response, "url", "") or "")
            if service:
                # Not _Retryable: another User-Agent or TLS fingerprint will
                # meet the same challenge, and retrying only adds load.
                # No ";" in the message: the downloader joins attempts with "; ".
                raise Exception(
                    f"{url} is behind a {service} bot-protection challenge "
                    "and is not served to automated clients")
            raise _Retryable(f"{url} returned non-PDF content (expected a PDF)", 200)
    return output_path


def _pdf_link_from_landing_page(url):
    """Repository landing pages name their PDF in a citation_pdf_url meta tag
    (put there for Google Scholar); failing that, take the first link to a
    .pdf. HAL and Columbia's repository serve that markup to non-browser
    clients and a script shell to browsers, so the plain User-Agent goes
    first. Returns an absolute URL or None."""
    for agent in (PLAIN_USER_AGENT, BROWSER_USER_AGENT):
        try:
            r = _get_with_retry(requests.get, url, headers={"User-Agent": agent}, timeout=REQUEST_TIMEOUT)
        except Exception:
            continue
        if r.status_code != 200 or "html" not in r.headers.get("Content-Type", ""):
            continue
        soup = BeautifulSoup(r.text, "html.parser")
        meta = soup.find("meta", attrs={"name": "citation_pdf_url"})
        link = meta.get("content") if meta else None
        if not link:
            a = soup.find("a", href=re.compile(r"\.pdf(?:$|\?)", re.I))
            link = a.get("href") if a else None
        if link:
            return urljoin(r.url or url, link)
    return None


def _download_pdf_or_linked(url, output_path):
    """Download `url` as a PDF; when it is an HTML page instead (an open-access
    index listed the landing page, not the file), follow the PDF link that
    page advertises. Raises with both errors when neither works."""
    try:
        return _download_file(url, output_path, expect_pdf=True)
    except Exception as e:
        if "non-PDF content" not in str(e):
            raise
        first = e
    link = _pdf_link_from_landing_page(url)
    if not link or link == url:
        raise Exception(f"{first} and the page names no PDF")
    return _download_file(link, output_path, expect_pdf=True)


# Elsevier reports entitlement on the PDF route through the X-ELS-Status
# header. A requestor without PDF entitlement still gets HTTP 200 and a
# structurally valid PDF, but one carrying only the article's first page:
#   "WARNING - Response limited to first page because requestor not entitled
#    to resource"
# Text-mining agreements commonly cover the full-text XML where they do not
# cover the PDF, so such a PDF is strictly worse than the XML and is discarded
# rather than saved as if it were the article.
_ELS_NOT_ENTITLED = "not entitled"


def download_via_elsevier(doi: str, output_path: str):
    """
    Download the full text of an Elsevier article via the Elsevier API.
    Requires an Elsevier API key.

    Prefers the PDF when the key is entitled to it, since the XML carries no
    figures or page layout, and otherwise falls back to the full-text XML.
    The returned path always carries the extension of the format actually
    written, so a caller never receives XML under a ".pdf" name.
    """
    api_key = os.getenv("ELSEVIER_API_KEY")
    if not api_key:
        raise Exception(
            "ELSEVIER_API_KEY is not set. Please configure your Elsevier API key.")
    url = f"https://api.elsevier.com/content/article/doi/{doi}"
    base_path = os.path.splitext(output_path)[0]

    # No view=FULL: entitled requests get the full text without it, and for
    # articles the key is not entitled to the parameter turns the informative
    # X-ELS-Status answer into a bare HTTP 400.
    def _request(accept):
        try:
            return _get_with_retry(
                requests.get, url,
                headers={"X-ELS-APIKey": api_key, "Accept": accept},
                timeout=REQUEST_TIMEOUT)
        except Exception as e:
            raise Exception(f"Error connecting to Elsevier API: {e}")

    # Prefer a fully entitled PDF.
    pdf_response = _request("application/pdf")
    if pdf_response.status_code == 200:
        els_status = pdf_response.headers.get("X-ELS-Status", "") or ""
        if (_ELS_NOT_ENTITLED not in els_status.lower()
                and pdf_response.content[:5] == b"%PDF-"):
            pdf_path = base_path + ".pdf"
            with open(pdf_path, "wb") as f:
                f.write(pdf_response.content)
            return pdf_path

    # Otherwise take the full-text XML.
    response = _request("text/xml")
    if response.status_code == 200:
        content = response.content
        if b"<coredata>" in content and b"<ce:para" not in content and b"<xocs:rawtext" not in content:
            raise Exception("Elsevier returned abstract-only XML (key not entitled to full text)")
        xml_path = base_path + ".xml"
        with open(xml_path, "wb") as f:
            f.write(content)
        markdown = _elsevier_xml_to_markdown(content, doi)
        if markdown:
            with open(base_path + ".md", "w", encoding="utf-8") as f:
                f.write(markdown)
            return Fetched(xml_path, source="elsevier",
                           note="full-text XML (no figures); a markdown rendering was saved next to it as .md")
        return xml_path
    elif response.status_code == 403:
        # Access denied. Elsevier's X-ELS-Status header says why:
        # APIKEY_INVALID = bad key; AUTHORIZATION_ERROR = no subscription/IP
        # entitlement; AUTHENTICATION_ERROR = key not provisioned for the
        # Article Retrieval API (fix at dev.elsevier.com, not in the key file).
        detail = response.headers.get("X-ELS-Status", "").strip() \
            or response.text[:200]
        raise Exception(f"Access denied by Elsevier API ({detail}).")
    elif response.status_code == 404:
        raise Exception("DOI not found in Elsevier API.")
    else:
        raise Exception(
            f"Elsevier API request failed (status code {response.status_code}).")


def _elsevier_xml_to_markdown(content: bytes, doi: str):
    """Render Elsevier full-text XML as markdown (title, authors, abstract,
    body paragraphs). Returns None when the XML has no body paragraphs."""
    import xml.etree.ElementTree as ET
    ns = {"ce": "http://www.elsevier.com/xml/common/dtd", "dc": "http://purl.org/dc/elements/1.1/"}
    try:
        root = ET.fromstring(content)
    except ET.ParseError:
        return None
    paragraphs = ["".join(p.itertext()).strip() for p in root.iter(f"{{{ns['ce']}}}para")]
    paragraphs = [p for p in paragraphs if p]
    if not paragraphs:
        return None
    title = next((t.text for t in root.iter(f"{{{ns['dc']}}}title") if t.text), doi)
    authors = [a.text for a in root.iter(f"{{{ns['dc']}}}creator") if a.text]
    abstract = next((d.text for d in root.iter(f"{{{ns['dc']}}}description") if d.text), "")
    lines = [f"# {title.strip()}", "", f"**DOI**: {doi}"]
    if authors:
        lines.append(f"**Authors**: {', '.join(authors)}")
    if abstract:
        lines += ["", "## Abstract", "", abstract.strip()]
    lines += ["", "## Full text", ""]
    for p in paragraphs:
        lines += [p, ""]
    return "\n".join(lines)


def download_via_springerpdf(doi: str, output_path: str):
    """
    Download the PDF of a Springer Nature article from the publisher site.
    Nature-family DOIs (10.1038/...) are fetched from nature.com, which serves
    open-access PDFs to any client; everything else from SpringerLink. Works
    for paywalled articles only from an entitled network.
    """
    urls = []
    if doi.startswith("10.1038/"):
        urls.append(f"https://www.nature.com/articles/{doi.split('/', 1)[1]}.pdf")
    urls.append(f"https://link.springer.com/content/pdf/{doi}.pdf")
    errors = []
    for pdf_url in urls:
        try:
            return _download_file(pdf_url, output_path, expect_pdf=True)
        except Exception as e:
            errors.append(str(e))
    raise Exception("; ".join(errors))


# Wiley's published TDM limits are 3 requests per second and 60 per 10
# minutes, but the API starts answering HTTP 500 after about 35 requests
# in 10 minutes (measured, 403 answers count too), so requests are paced
# to 30 per window.
# Past the sustained limit the API answers HTTP 500 for every request until
# the window clears, so a bulk run without pacing loses the rest of its
# Wiley articles. Timestamps of recent calls, shared across threads.
WILEY_WINDOW_SECONDS = 600.0
WILEY_MAX_PER_WINDOW = 30
WILEY_MIN_GAP_SECONDS = 0.34
_wiley_calls = []
_wiley_lock = threading.Lock()


def _wiley_rate_limit():
    """Block until another Wiley TDM request fits within the published limits."""
    with _wiley_lock:
        now = time.time()
        _wiley_calls[:] = [t for t in _wiley_calls if now - t < WILEY_WINDOW_SECONDS]
        wait = 0.0
        if len(_wiley_calls) >= WILEY_MAX_PER_WINDOW:
            wait = WILEY_WINDOW_SECONDS - (now - _wiley_calls[0])
        elif _wiley_calls:
            wait = max(0.0, WILEY_MIN_GAP_SECONDS - (now - _wiley_calls[-1]))
        if wait > 0:
            time.sleep(wait)
        _wiley_calls.append(time.time())


def download_via_wiley(doi: str, output_path: str):
    """
    Download the PDF of a Wiley article via the Wiley TDM API.
    Requires a Wiley API key. Requests are paced to Wiley's published limits.
    """
    api_key = os.getenv("WILEY_API_KEY")
    if not api_key:
        raise Exception(
            "WILEY_API_KEY is not set. Please configure your Wiley API key.")
    base_url = "https://api.wiley.com/onlinelibrary/tdm/v1/articles/"
    url = base_url + quote(doi, safe="")
    headers = {"Wiley-TDM-Client-Token": api_key}
    _wiley_rate_limit()
    try:
        return _download_file(url, output_path, headers=headers, expect_pdf=True)
    except Exception as e:
        # Provide a more specific hint on failure
        raise Exception(
            f"Wiley API download failed: {e}. Ensure your API key is correct and you have access rights.")


def download_via_plos(doi: str, output_path: str):
    """
    Download the full-text PDF of a PLOS article using the PLOS article file API.
    """
    base_url = "https://journals.plos.org/plosone/article/file"
    params = {"id": doi, "type": "printable"}
    try:
        # Using requests directly since _download_file doesn't accept params, build URL manually
        pdf_url = f"{base_url}?id={doi}&type=printable"
        return _download_file(pdf_url, output_path, headers=None,
                              expect_pdf=True)
    except Exception as e:
        raise Exception(f"PLOS download failed: {e}")


def download_via_unpaywall(doi: str, output_path: str):
    """
    Download an open-access PDF via Unpaywall.
    Tries every OA location (best first), not only best_oa_location: publisher
    PDF links are often bot-blocked (403) while a PMC or repository copy of the
    same paper downloads fine. PMC-hosted copies usually carry no url_for_pdf,
    so those are fetched through Europe PMC's PDF render endpoint.
    Requires an email configured for Unpaywall (UNPAYWALL_EMAIL).
    """
    email = os.getenv("UNPAYWALL_EMAIL")
    if not email:
        raise Exception(
            "UNPAYWALL_EMAIL is not set. Please set this to use Unpaywall.")
    api_url = f"https://api.unpaywall.org/v2/{doi}?email={email}"
    try:
        r = _get_with_retry(requests.get, api_url, timeout=REQUEST_TIMEOUT)
    except Exception as e:
        raise Exception(f"Error connecting to Unpaywall API: {e}")
    if r.status_code != 200:
        raise Exception(
            f"Unpaywall API request failed (status code {r.status_code})")
    data = r.json()
    locations = []
    if data.get("best_oa_location"):
        locations.append(data["best_oa_location"])
    for loc in data.get("oa_locations") or []:
        if loc not in locations:
            locations.append(loc)
    # The publisher's version of record first, then accepted manuscripts, then
    # submitted ones; within a version, repository copies before publisher links,
    # which are the ones most often bot-blocked.
    rank = {"publishedVersion": 0, "acceptedVersion": 1, "submittedVersion": 2}
    locations.sort(key=lambda loc: (rank.get(loc.get("version"), 3), loc.get("host_type") == "publisher"))
    candidates = []  # (url, version)
    for loc in locations:
        version = loc.get("version") or ""
        pdf_url = loc.get("url_for_pdf")
        if pdf_url and pdf_url not in [c[0] for c in candidates]:
            candidates.append((pdf_url, version))
        # Repository records often carry only the landing page; the page itself
        # either serves the PDF or names it (HAL, DSpace, Columbia, TU Delft).
        landing = loc.get("url")
        if loc.get("host_type") == "repository" and landing and landing not in [c[0] for c in candidates]:
            candidates.append((landing, version))
        # PMC moved from www.ncbi.nlm.nih.gov/pmc/articles/ to
        # pmc.ncbi.nlm.nih.gov/articles/ in 2024; Unpaywall now reports both forms.
        m = re.search(
            r"(?:ncbi\.nlm\.nih\.gov/(?:pmc/)?articles/|europepmc\.org/articles/)(?:PMC)?(\d+)",
            loc.get("url") or "")
        if m:
            epmc_url = f"https://europepmc.org/articles/PMC{m.group(1)}?pdf=render"
            if epmc_url not in [c[0] for c in candidates]:
                candidates.append((epmc_url, version))
    if not candidates:
        raise Exception(f"No open-access PDF found for DOI: {doi}")
    errors = []
    for pdf_url, version in candidates:
        try:
            path = _download_pdf_or_linked(pdf_url, output_path)
        except Exception as e:
            errors.append(str(e))
            continue
        note = None
        if version and version != "publishedVersion":
            note = f"{version} from a repository, not the publisher's version of record"
        return Fetched(path, note=note, source="unpaywall")
    raise Exception(
        f"All OA locations failed for DOI {doi}: " + "; ".join(errors))


def download_via_springeropen(doi: str, output_path: str):
    """
    Retrieve full text for an open-access Springer Nature article using the Springer OpenAccess API.
    Requires a Springer API key.
    """
    api_key = os.getenv("SPRINGER_API_KEY")
    if not api_key:
        raise Exception(
            "SPRINGER_API_KEY is not set. Please configure your Springer API key.")
    try:
        import sprynger
        from sprynger import OpenAccess
    except ImportError:
        raise Exception(
            "sprynger library is not installed. Please install sprynger to use this tool.")
    try:
        sprynger.init(api_key=api_key)
        results = OpenAccess(doi=doi)
        # OpenAccess returns a list-like of results
        results_list = list(results)
    except Exception as e:
        raise Exception(f"Springer OpenAccess API error: {e}")
    if not results_list:
        raise Exception(
            f"No Open Access content found for DOI {doi} via Springer API.")
    doc = results_list[0]
    full_text = getattr(doc, "full_text", None)
    if full_text is None:
        raise Exception(
            f"Springer OpenAccess did not return full text for DOI {doi}.")
    # Write the XML content to output_path
    try:
        with open(output_path, "w", encoding="utf-8") as fh:
            fh.write(full_text)
    except Exception as e:
        raise Exception(
            f"Failed to write Springer OpenAccess content to file: {e}")
    return output_path


def download_via_crossref_tdm(doi: str, output_path: str):
    """
    Download a PDF via CrossRef Text and Data Mining links (if available).
    """
    api_url = f"https://api.crossref.org/works/{doi}"
    try:
        r = _crossref_get(api_url)
    except Exception as e:
        raise Exception(f"Error connecting to CrossRef API: {e}")
    if r.status_code != 200:
        raise Exception(f"CrossRef API request failed (status {r.status_code})")
    data = r.json().get("message", {})
    links = data.get("link", [])
    # Publishers rarely declare application/pdf here: APS (harvest.aps.org),
    # ACS and RSC all register their full-text links with content-type
    # "unspecified". Try every link that is not declared HTML, PDF-declared
    # ones first, and let expect_pdf reject anything that is not a PDF.
    candidates = [l.get("URL") for l in sorted(
        links, key=lambda l: not l.get("content-type", "").startswith("application/pdf"))
        if l.get("URL") and not l.get("content-type", "").startswith("text/html")]
    if not candidates:
        raise Exception(f"No PDF link found via CrossRef for DOI {doi}")
    errors = []
    for pdf_link in dict.fromkeys(candidates):
        try:
            return _download_file(pdf_link, output_path, expect_pdf=True)
        except Exception as e:
            errors.append(str(e))
    raise Exception(
        f"No CrossRef link returned a PDF for DOI {doi}: " + "; ".join(errors))


def download_via_arxiv(doi: str, output_path: str):
    """
    Download the PDF of an arXiv paper given its DOI (DataCite DOI for arXiv).
    """
    arxiv_id = doi
    if arxiv_id.lower().startswith("10.48550/"):
        arxiv_id = arxiv_id.split("/", 1)[1]
    for prefix in ("arxiv.", "arxiv:"):
        if arxiv_id.lower().startswith(prefix):
            arxiv_id = arxiv_id[len(prefix):]
    pdf_url = f"https://arxiv.org/pdf/{arxiv_id}"
    path = _download_file(pdf_url, output_path, expect_pdf=True)
    return Fetched(path, source="arxiv", note="arXiv preprint, not the publisher's version of record")


def download_via_elife(doi: str, output_path: str):
    """
    Download the PDF of an eLife article using its DOI by scraping the eLife site.
    """
    doi_url = f"https://doi.org/{doi}"
    headers = {
        "Accept": "text/html",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                      "AppleWebKit/537.36 (KHTML, like Gecko) "
                      "Chrome/90.0.4430.93 Safari/537.36"
    }
    try:
        response = requests.get(doi_url, headers=headers, allow_redirects=True,
                                timeout=REQUEST_TIMEOUT)
    except Exception as e:
        raise Exception(f"Failed to resolve DOI {doi}: {e}")
    if response.status_code != 200:
        raise Exception(
            f"Failed to resolve DOI: {doi} (Status code: {response.status_code})")
    soup = BeautifulSoup(response.text, 'html.parser')
    pdf_link = None
    for a_tag in soup.find_all('a', href=True):
        href = a_tag['href']
        if 'pdf' in href.lower():
            pdf_link = href
            break
    if not pdf_link:
        raise Exception(f"No PDF link found on eLife page for DOI: {doi}")
    if pdf_link.startswith("/"):
        pdf_link = "https://elifesciences.org" + pdf_link
    # Use the same headers and add referer
    headers["Referer"] = response.url
    return _download_file(pdf_link, output_path, headers=headers,
                          expect_pdf=True)


def download_via_paperscraper(doi: str, output_path: str):
    """
    Download a preprint PDF (e.g., bioRxiv, medRxiv, chemRxiv, arXiv) using the paperscraper library.
    """
    try:
        from paperscraper.pdf import save_pdf
    except ImportError:
        raise Exception(
            "paperscraper library is not installed. Please install paperscraper to use this tool.")
    try:
        save_pdf({'doi': doi}, filepath=output_path)
    except Exception as e:
        raise Exception(f"Paperscraper failed for DOI {doi}: {e}")
    if not os.path.exists(output_path):  # save_pdf reports some failures only in its log
        raise Exception(f"Paperscraper wrote no file for DOI {doi}")
    return output_path


def download_via_aps(doi: str, output_path: str):
    """
    Download a PDF from the American Physical Society (APS) publications by using stored browser cookies for authentication.
    Requires that the user is logged in to APS (e.g., via institution) and browser_cookie3 can retrieve the cookies.
    """
    # Create a session and load APS cookies from the default browser
    session = requests.Session()
    if browser_cookie3 is None:
        raise Exception("browser_cookie3 is not installed; install it to use the APS cookie route.")
    try:
        session.cookies.update(browser_cookie3.load(domain_name='aps.org'))
    except Exception as e:
        raise Exception(f"Failed to load APS cookies: {e}")
    # Try CrossRef metadata to find APS fulltext link
    crossref_url = f"https://api.crossref.org/works/{doi}"
    pdf_url = None
    try:
        r = session.get(crossref_url, timeout=REQUEST_TIMEOUT)
        if r.status_code == 200:
            data = r.json().get('message', {})
            for link in data.get('link', []):
                url = link.get('URL', '')
                if 'harvest.aps.org' in url or 'link.aps.org' in url:
                    pdf_url = url
                    break
    except Exception:
        # If CrossRef fails, we'll proceed with DOI resolution directly
        pdf_url = None
    # Use DOI resolver if no direct link from CrossRef
    target_url = pdf_url if pdf_url else f"https://doi.org/{doi}"
    headers = {"Accept": "application/pdf"}
    return _download_file(target_url, output_path, headers=headers,
                          session=session, expect_pdf=True)


def download_via_cambridge(doi: str, output_path: str):
    """
    Download the PDF of a Cambridge University Press article by scraping the article page.
    """
    # Ensure DOI is not a full URL
    if doi.startswith("http"):
        # Extract the DOI part after https://doi.org/
        if "/" in doi:
            doi = doi.split("doi.org/")[-1]
    doi_url = f"https://doi.org/{doi}"
    try:
        response = requests.get(doi_url, allow_redirects=True,
                                timeout=REQUEST_TIMEOUT)
    except Exception as e:
        raise Exception(f"Failed to resolve DOI {doi}: {e}")
    if response.status_code != 200:
        raise Exception(
            f"Failed to resolve DOI: {doi} (Status code: {response.status_code})")
    article_url = response.url
    html = None
    try:
        html = requests.get(article_url, timeout=REQUEST_TIMEOUT).text
    except Exception as e:
        raise Exception(f"Failed to load article page: {e}")
    soup = BeautifulSoup(html, "html.parser")
    pdf_link = None
    for link in soup.find_all("a", href=True):
        href = link["href"]
        if "/pdf/" in href or href.lower().endswith(".pdf"):
            pdf_link = href
            break
    if not pdf_link:
        raise Exception(
            "Could not find PDF link on the Cambridge article page.")
    if pdf_link.startswith("/"):
        parsed_url = urlparse(article_url)
        pdf_url = f"{parsed_url.scheme}://{parsed_url.netloc}{pdf_link}"
    else:
        pdf_url = pdf_link
    return _download_file(pdf_url, output_path, expect_pdf=True)


def download_via_biorxiv(doi: str, output_path: str):
    """
    Download a bioRxiv or medRxiv preprint. Both servers share the 10.1101
    prefix, so the bioRxiv API is asked which one holds the DOI and what its
    latest version is; when the API is throttling this host (it then answers
    with an empty or HTML body) the unversioned URL, which redirects to the
    current version, is tried on both servers. www.biorxiv.org sits behind
    Cloudflare and answers a share of requests with a transient 503, and with
    429 plus Retry-After after a burst, so every request is paced and retried
    accordingly. No credentials needed.
    """
    candidates = []  # (server, pdf_url)
    for server in ("biorxiv", "medrxiv"):
        _biorxiv_pace()
        try:
            r = _get_with_retry(requests.get, f"https://api.biorxiv.org/details/{server}/{doi}",
                                timeout=REQUEST_TIMEOUT)
            versions = r.json().get("collection") or [] if r.status_code == 200 else []
        except Exception:
            versions = []
        if versions:
            candidates = [(server, f"https://www.{server}.org/content/{doi}v{versions[-1].get('version', 1)}.full.pdf")]
            break
    if not candidates:
        candidates = [(s, f"https://www.{s}.org/content/{doi}.full.pdf") for s in ("biorxiv", "medrxiv")]
    errors = []
    waited = False
    for server, pdf_url in candidates:
        for attempt in range(3):
            _biorxiv_pace()
            try:
                path = _download_file(pdf_url, output_path, expect_pdf=True)
                return Fetched(path, source="biorxiv", note=f"{server} preprint, not a journal version of record")
            except Exception as e:
                errors.append(str(e))
                if "status code: 503" in str(e) and attempt < 2:
                    time.sleep(3 * (attempt + 1))
                elif "status code: 429" in str(e) and not waited:
                    time.sleep(BIORXIV_RETRY_AFTER)
                    waited = True
                else:
                    break
    raise Exception(f"bioRxiv/medRxiv download failed for DOI {doi}: " + "; ".join(errors[-2:]))


# bioRxiv rate-limits PDF downloads per address (HTTP 429 after roughly a
# dozen in quick succession), so requests are spaced out.
BIORXIV_MIN_GAP = 5.0
BIORXIV_RETRY_AFTER = 100
_biorxiv_last_call = [0.0]
_biorxiv_lock = threading.Lock()


def _biorxiv_pace():
    with _biorxiv_lock:
        wait = _biorxiv_last_call[0] + BIORXIV_MIN_GAP - time.time()
        if wait > 0:
            time.sleep(wait)
        _biorxiv_last_call[0] = time.time()


# www.mdpi.com refuses requests from cloud-provider address ranges (HTTP 403
# for every User-Agent and TLS fingerprint), which is where agents commonly
# run. The CDN that holds the article PDFs does not. Its path needs the
# journal's URL slug: for most journals the DOI's journal code (ijms, jcm,
# su), for the rest the title without spaces (energies, remotesensing), and
# for a few neither.
_MDPI_SLUGS = {"applied sciences": "applsci"}


def download_via_mdpi(doi: str, output_path: str):
    """Download an MDPI article from the publisher's CDN, built from the
    Crossref record (journal, volume, article number). No credentials needed."""
    m = re.match(r"10\.3390/([a-z]+)\d", doi.lower())
    if not m:
        raise Exception(f"Not an MDPI DOI: {doi}")
    try:
        r = _crossref_get(f"https://api.crossref.org/works/{doi}")
        msg = r.json()["message"]
    except Exception as e:
        raise Exception(f"Crossref lookup failed for DOI {doi}: {e}")
    title = (msg.get("container-title") or [""])[0].lower()
    volume = msg.get("volume")
    number = msg.get("article-number") or (msg.get("page") or "").split("-")[0]
    if not (volume and number and number.isdigit()):
        raise Exception(f"Crossref record for {doi} lacks a volume or article number")
    slugs = [s for s in dict.fromkeys([m.group(1), re.sub(r"[^a-z0-9]", "", title), _MDPI_SLUGS.get(title)]) if s]
    errors = []
    for slug in slugs:
        name = f"{slug}-{int(volume):02d}-{int(number):05d}"
        try:
            return _download_file(f"https://mdpi-res.com/d_attachment/{slug}/{name}/article_deploy/{name}.pdf",
                                  output_path, expect_pdf=True)
        except Exception as e:
            errors.append(str(e))
    raise Exception(f"No MDPI CDN path worked for DOI {doi}: " + "; ".join(errors))


def download_via_zenodo(doi: str, output_path: str):
    """Download the PDF attached to a Zenodo record (10.5281 DOIs; preprints,
    reports and postprints deposited there). A concept DOI resolves to the
    latest version. No credentials needed."""
    m = re.search(r"zenodo\.(\d+)$", doi.lower())
    if not m:
        raise Exception(f"Not a Zenodo record DOI: {doi}")
    try:
        r = _get_with_retry(requests.get, f"https://zenodo.org/api/records/{m.group(1)}", timeout=REQUEST_TIMEOUT)
    except Exception as e:
        raise Exception(f"Error connecting to Zenodo: {e}")
    if r.status_code != 200:
        raise Exception(f"Zenodo has no record {m.group(1)} (status code {r.status_code})")
    pdfs = [f for f in r.json().get("files") or [] if (f.get("key") or "").lower().endswith(".pdf")]
    if not pdfs:
        raise Exception(f"Zenodo record {m.group(1)} has no PDF file")
    return _download_file(pdfs[0]["links"]["self"], output_path, expect_pdf=True)


def download_via_osti(doi: str, output_path: str):
    """
    Download the accepted manuscript of a DOE-funded article from OSTI.
    DOE public-access policy places accepted manuscripts on osti.gov about a
    year after publication. Open-access indexes usually list only the OSTI
    landing page for these, but the OSTI API resolves a DOI to the PDF.
    No credentials needed. Returns the accepted manuscript, not the version
    of record.
    """
    api_url = "https://www.osti.gov/api/v1/records"
    try:
        r = _get_with_retry(requests.get, api_url, params={"doi": doi},
                            headers={"User-Agent": BROWSER_USER_AGENT},
                            timeout=REQUEST_TIMEOUT)
    except Exception as e:
        raise Exception(f"Error connecting to OSTI API: {e}")
    if r.status_code != 200:
        raise Exception(f"OSTI API request failed (status code {r.status_code})")
    records = r.json()
    if not records:
        raise Exception(f"No OSTI record for DOI {doi}")
    record = records[0]
    fulltext = [l["href"] for l in record.get("links", []) if l.get("rel") == "fulltext"]
    pdf_url = fulltext[0] if fulltext else f"https://www.osti.gov/servlets/purl/{record['osti_id']}"
    try:
        path = _download_file(pdf_url, output_path, expect_pdf=True)
    except Exception as e:
        # A record without full text is usually still under the 12-month embargo.
        raise Exception(f"OSTI record {record['osti_id']} has no downloadable full text: {e}")
    return Fetched(path, source="osti", note="OSTI accepted manuscript, not the publisher's version of record")


def download_via_europepmc(doi: str, output_path: str):
    """
    Download an open-access copy listed in Europe PMC's record for the DOI.
    Besides PMC-hosted articles, Europe PMC records carry `fullTextUrlList`
    entries pointing at repository copies (author manuscripts in institutional
    archives) that Unpaywall lists without a PDF link. No credentials needed.
    """
    api_url = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"
    try:
        r = _get_with_retry(requests.get, api_url,
                            params={"query": f"DOI:{doi}", "format": "json", "resultType": "core"},
                            headers={"User-Agent": BROWSER_USER_AGENT}, timeout=REQUEST_TIMEOUT)
    except Exception as e:
        raise Exception(f"Error connecting to Europe PMC: {e}")
    if r.status_code != 200:
        raise Exception(f"Europe PMC request failed (status code {r.status_code})")
    results = (r.json().get("resultList") or {}).get("result") or []
    candidates = []  # (url, note)
    pmc_copy = None  # (pmcid, is_open_access) when the article's full text is in PMC
    for rec in results:
        if (rec.get("doi") or "").lower() != doi.lower():
            continue
        pmcid = rec.get("pmcid")
        if pmcid and rec.get("inEPMC") == "Y":
            pmc_copy = (pmcid, rec.get("isOpenAccess") == "Y")
        if pmcid and rec.get("isOpenAccess") == "Y":
            candidates.append((f"https://europepmc.org/articles/{pmcid}?pdf=render", None))
        for u in (rec.get("fullTextUrlList") or {}).get("fullTextUrl") or []:
            if u.get("documentStyle") == "pdf" and (u.get("availability") or "").lower() in ("open access", "free") and u.get("url"):
                site = u.get("site") or ""
                where = f" (via {site})" if site and site.lower() != "unpaywall" else ""
                candidates.append((u["url"], f"open-access copy listed by Europe PMC{where}; may be an author manuscript"))
    if not candidates and not pmc_copy:
        raise Exception(f"Europe PMC lists no open-access PDF for DOI {doi}")
    errors = []
    for url, note in candidates:
        try:
            path = _download_file(url, output_path, expect_pdf=True)
        except Exception as e:
            errors.append(str(e))
            continue
        return Fetched(path, source="europepmc", note=note)
    if pmc_copy:
        # Author manuscripts deposited in PMC (NIH and other funder mandates) are in
        # Europe PMC as full text even when the article is not open access; the PMC
        # route gets the PDF render or, when that endpoint refuses, the JATS XML.
        pmcid, open_access = pmc_copy
        try:
            path = download_via_pmc(pmcid, output_path)
        except Exception as e:
            errors.append(str(e))
        else:
            note = getattr(path, "note", None) if open_access else \
                "PMC author manuscript, not the publisher's version of record"
            return Fetched(path, source="europepmc", note=note)
    raise Exception(f"Europe PMC locations failed for DOI {doi}: " + "; ".join(errors))


def download_via_semantic(doi: str, output_path: str):
    """
    Download the open-access copy Semantic Scholar knows for the DOI: the
    `openAccessPdf` link (mostly arXiv, Research Square and repository copies
    of subscription articles) or, when the record carries none, the arXiv id
    among its `externalIds`. With SEMANTIC_SCHOLAR_API_KEY a title search
    also finds a second record of the same paper (its arXiv version); without
    a key that endpoint answers 429. The file is usually a preprint.
    """
    headers = {"User-Agent": BROWSER_USER_AGENT}
    api_key = os.getenv("SEMANTIC_SCHOLAR_API_KEY")
    if api_key:
        headers["x-api-key"] = api_key
    try:
        r = _semantic_get(f"https://api.semanticscholar.org/graph/v1/paper/DOI:{doi}",
                          params={"fields": _SEMANTIC_FIELDS}, headers=headers, timeout=REQUEST_TIMEOUT)
    except Exception as e:
        raise Exception(f"Error connecting to Semantic Scholar: {e}")
    if r.status_code == 404:
        raise Exception(f"Semantic Scholar has no record for DOI {doi}")
    if r.status_code != 200:
        raise Exception(f"Semantic Scholar request failed (status code {r.status_code})")
    record = r.json()
    copy = _semantic_copy(record)
    if not copy and api_key and record.get("title"):
        copy = _semantic_search_by_title(doi, record["title"], headers)
    if not copy:
        raise Exception(f"Semantic Scholar lists no open-access copy for DOI {doi}")
    url, note = copy
    if url.startswith("arxiv:"):
        path = download_via_arxiv(url[6:], output_path)
        return Fetched(path, source="semantic", note=note)
    path = _download_pdf_or_linked(url, output_path)  # S2 lists some repository landing pages as PDFs
    return Fetched(path, source="semantic", note=note)


_SEMANTIC_FIELDS = "title,openAccessPdf,externalIds"


def _semantic_copy(record):
    """(url_or_arxiv_ref, note) for a Semantic Scholar paper record, or None."""
    oa = record.get("openAccessPdf") or {}
    if oa.get("url"):
        note = None if (oa.get("status") or "").lower() in ("gold", "hybrid", "bronze") else \
            "open-access copy found via Semantic Scholar, likely a preprint or author manuscript"
        return oa["url"], note
    arxiv_id = (record.get("externalIds") or {}).get("ArXiv")
    if arxiv_id:
        return f"arxiv:{arxiv_id}", "arXiv version listed by Semantic Scholar, not the publisher's version of record"
    return None


_semantic_lock = threading.Lock()
_semantic_last_call = [0.0]


def _semantic_get(url, **kwargs):
    """Semantic Scholar allows 1 request/s per key and answers 429 beyond it:
    requests are spaced 1 s apart across threads, and a 429 is retried with
    exponential backoff (2, 4, 8 s) before giving up."""
    for attempt in range(4):
        with _semantic_lock:
            wait = _semantic_last_call[0] + 1.0 - time.time()
            if wait > 0:
                time.sleep(wait)
            _semantic_last_call[0] = time.time()
        r = _get_with_retry(requests.get, url, **kwargs)
        if r.status_code != 429 or attempt == 3:
            return r
        time.sleep(2 ** (attempt + 1))
    return r


def _same_paper(hit, doi, title):
    """A search hit is the wanted paper when its DOI matches or, lacking a DOI,
    when the two titles share nearly all their words in both directions."""
    from . import verify
    hit_doi = ((hit.get("externalIds") or {}).get("DOI") or "").lower()
    if hit_doi:
        return hit_doi == doi.lower()
    hit_title = hit.get("title") or ""
    return verify.title_matches(hit_title, title, 0.9) and verify.title_matches(title, hit_title, 0.9)


def _semantic_search_by_title(doi, title, headers):
    try:
        r = _semantic_get("https://api.semanticscholar.org/graph/v1/paper/search",
                            params={"query": title, "fields": _SEMANTIC_FIELDS, "limit": 5},
                            headers=headers, timeout=REQUEST_TIMEOUT)
    except Exception:
        return None
    if r.status_code != 200:
        return None
    for hit in r.json().get("data") or []:
        if _same_paper(hit, doi, title) and _semantic_copy(hit):
            return _semantic_copy(hit)
    return None


def _open_engage_item(doi: str):
    api_url = f"https://www.cambridge.org/engage/coe/public-api/v1/items/doi/{doi}"
    try:
        r = _get_with_retry(requests.get, api_url, headers={"User-Agent": BROWSER_USER_AGENT},
                            timeout=REQUEST_TIMEOUT)
    except Exception as e:
        raise Exception(f"Error connecting to the Open Engage API: {e}")
    if r.status_code == 404:
        return None
    if r.status_code != 200:
        raise Exception(f"Open Engage API request failed (status code {r.status_code})")
    return r.json()


def download_via_chemrxiv(doi: str, output_path: str):
    """
    Download a ChemRxiv preprint through the Cambridge Open Engage public API.
    chemrxiv.org itself sits behind a bot check that blocks many hosts; the
    API on cambridge.org returns the asset URL, which downloads normally.
    The API resolves only the DOI of an item's latest version, so a base DOI
    or an older version is retried as v1, v2, ... until one resolves
    (suffix "-vN" for current DOIs, ".vN" for the older chemrxiv.NNNNNNNN form).
    """
    m = re.search(r"([.-])v\d+$", doi)
    base = doi[:m.start()] if m else doi
    sep = m.group(1) if m else ("." if "chemrxiv." in doi else "-")
    candidates = [doi] + [f"{base}{sep}v{n}" for n in range(1, 10) if f"{base}{sep}v{n}" != doi]
    for used in candidates:
        item = _open_engage_item(used)
        if item is not None:
            break
    else:
        raise Exception(f"ChemRxiv has no item for DOI {doi}")
    pdf_url = ((item.get("asset") or {}).get("original") or {}).get("url")
    if not pdf_url:
        raise Exception(f"ChemRxiv item for DOI {used} has no PDF asset")
    path = _download_file(pdf_url, output_path, expect_pdf=True)
    note = "ChemRxiv preprint, not the publisher's version of record"
    if used != doi:
        note += f" (latest version, {used})"
    return Fetched(path, source="chemrxiv", note=note)


def download_via_pmc(pmcid: str, output_path: str):
    """Download an open-access PubMed Central article by PMC id via Europe PMC's
    PDF render. When the render endpoint refuses (it throttles hosts that ask
    for many articles in a row), Europe PMC's REST service still serves the
    full-text JATS XML, which is written next to the intended PDF path."""
    try:
        path = _download_file(f"https://europepmc.org/articles/{pmcid}?pdf=render", output_path, expect_pdf=True)
        return Fetched(path, source="pmc")
    except Exception as e:
        pdf_error = e
    # Europe PMC's REST service has the JATS XML of open-access articles; NCBI's
    # efetch also serves the XML of author manuscripts, which Europe PMC does not.
    number = re.sub(r"^PMC", "", pmcid, flags=re.I)
    sources = [("Europe PMC", f"https://www.ebi.ac.uk/europepmc/webservices/rest/{pmcid}/fullTextXML", {}),
               ("NCBI", "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi",
                {"db": "pmc", "id": number, "retmode": "xml", **({"api_key": os.getenv("NCBI_API_KEY")} if os.getenv("NCBI_API_KEY") else {})})]
    errors = [str(pdf_error)]
    for name, url, params in sources:
        try:
            r = _get_with_retry(requests.get, url, params=params or None, timeout=REQUEST_TIMEOUT)
        except Exception as e:
            errors.append(f"{name} XML request failed: {e}")
            continue
        if r.status_code != 200 or b"<body" not in r.content:
            errors.append(f"{name} has no full-text XML for {pmcid} (status code {r.status_code})")
            continue
        xml_path = os.path.splitext(output_path)[0] + ".xml"
        with open(xml_path, "wb") as f:
            f.write(r.content)
        return Fetched(xml_path, source="pmc", note=f"full-text XML from {name}; the PDF render endpoint refused")
    raise Exception("; ".join(errors))


def download_via_openreview(review_id: str, output_path: str):
    """Download a submission PDF from OpenReview by its id."""
    headers = {"Referer": f"https://openreview.net/forum?id={review_id}"}
    path = _download_file(f"https://openreview.net/pdf?id={review_id}", output_path,
                          headers=headers, expect_pdf=True)
    return Fetched(path, source="openreview", note="OpenReview submission, not a journal version of record")

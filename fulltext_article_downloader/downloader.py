import os
import logging
import requests
import sys
import threading

from . import identifiers, supplements, tools, verify

# Log to stderr so the CLI's JSON on stdout stays parseable.
logging.basicConfig(stream=sys.stderr, level=logging.WARNING)
_log_setup_lock = threading.Lock()

# Tools tried, in order, for a DOI whose publisher is not listed below. The
# Elsevier API comes last: it also serves society journals Elsevier distributes
# (ASH's Blood, for one) under their own publisher name, and it answers a
# non-Elsevier DOI with a quick 404.
DEFAULT_TOOLS = ["unpaywall", "europepmc", "crossref_tdm", "osti", "semantic", "elsevier"]

# Mapping of publisher names to preferred tool order. Open-access indexes come
# before OSTI and Semantic Scholar, which usually return accepted manuscripts
# or preprints rather than the version of record.
PUBLISHER_TOOL_MAP = {
    "Elsevier BV": ["unpaywall", "elsevier", "europepmc", "osti", "semantic"],
    "Springer Science and Business Media LLC": ["springerpdf", "unpaywall", "europepmc", "springeropen", "osti", "semantic"],
    "Wiley": ["wiley", "unpaywall", "europepmc", "osti", "semantic"],
    "American Chemical Society (ACS)": ["unpaywall", "europepmc", "crossref_tdm", "osti", "semantic"],
    "Royal Society of Chemistry (RSC)": ["unpaywall", "europepmc", "crossref_tdm", "osti", "semantic"],
    "American Institute of Physics (AIP)": ["unpaywall", "europepmc", "crossref_tdm", "osti", "semantic"],
    "American Physical Society (APS)": ["aps", "unpaywall", "crossref_tdm", "europepmc", "osti", "semantic"],
    "Oxford University Press (OUP)": ["unpaywall", "europepmc", "osti", "semantic"],
    "Cambridge University Press (CUP)": ["cambridge", "unpaywall", "europepmc", "osti", "semantic"],
    "Taylor & Francis": ["unpaywall", "europepmc", "osti", "semantic"],
    "Public Library of Science (PLoS)": ["plos", "unpaywall"],
    "MDPI AG": ["mdpi", "unpaywall", "europepmc", "semantic"],
    "Zenodo": ["zenodo"],
    "bioRxiv": ["biorxiv", "unpaywall", "paperscraper"],
    "medRxiv": ["biorxiv", "unpaywall", "paperscraper"],
    "chemRxiv": ["chemrxiv", "paperscraper", "unpaywall"],
    "arXiv": ["arxiv", "unpaywall"],
    "eLife Sciences Publications, Ltd": ["elife", "unpaywall"],
    "Institute of Electrical and Electronics Engineers (IEEE)": ["unpaywall", "europepmc", "crossref_tdm", "osti", "semantic"]
}

# Mapping of DOI prefix to known preprint server (for quick identification without API calls)
PREPRINT_SERVER_PREFIXES = {
    "10.1101": "bioRxiv",
    "10.21203": "Research Square",
    "10.31219": "OSF Preprints",
    "10.20944": "Preprints.org",
    "10.26434": "chemRxiv",
    "10.22541": "Authorea",
    "10.31730": "EarthArXiv",
    "10.3886": "SSRN",
    "10.33774": "Cambridge Open Engage",
    "10.2139": "SSRN",
    "10.53731": "arXiv",
    "10.48550": "arXiv",
    "10.57967": "engRxiv",
    "10.3389": "Frontiers Media SA",
    "10.4175": "Frontiers Media SA",
    "10.5281": "Zenodo"
}

# Crossref metadata seen so far: doi -> {"publisher": ..., "title": ...}. The
# title is what the verification step compares a downloaded PDF against.
_crossref_metadata = {}


def get_publisher_from_doi(doi: str):
    """
    Resolve a DOI to get the publisher or source name, by querying CrossRef (and DataCite as fallback).
    Returns the publisher name or preprint server name if identified, or None if not found.
    """
    # Check prefix if it's a known preprint server
    prefix = doi.split('/')[0]
    if prefix in PREPRINT_SERVER_PREFIXES:
        return PREPRINT_SERVER_PREFIXES[prefix]
    if doi in _crossref_metadata:
        return _crossref_metadata[doi]["publisher"]
    # Query CrossRef for metadata
    crossref_url = f"https://api.crossref.org/works/{doi}"
    try:
        r = tools._crossref_get(crossref_url)
        if r.status_code == 404:
            # Try DataCite if not found on CrossRef
            datacite_url = f"https://api.datacite.org/dois/{doi}"
            r2 = requests.get(datacite_url, timeout=tools.REQUEST_TIMEOUT)
            if r2.status_code == 200:
                attrs = r2.json().get("data", {}).get("attributes", {})
                titles = attrs.get("titles") or []
                _crossref_metadata[doi] = {"publisher": attrs.get("publisher"),
                                           "title": (titles[0].get("title") if titles else None)}
                return attrs.get("publisher")
            else:
                return None
        r.raise_for_status()
        message = r.json().get("message", {})
        publisher = message.get("publisher")
        _crossref_metadata[doi] = {"publisher": publisher,
                                   "title": " ".join(message.get("title") or []) or None,
                                   # society journals whose full text a big publisher hosts: Crossref's
                                   # links point at wiley.com (AGU and others) or elsevier.com (ASH's Blood)
                                   "hosted_by": _hosting_publisher(message.get("link") or [])}
        return publisher
    except Exception as e:
        logging.error(f"Failed to resolve DOI {doi} to publisher: {e}")
        return None


def _hosting_publisher(links):
    urls = " ".join(l.get("URL") or "" for l in links)
    if "wiley.com" in urls:
        return "wiley"
    if "elsevier.com" in urls or "sciencedirect.com" in urls:
        return "elsevier"
    return None


def get_title_from_doi(doi: str):
    """Title from Crossref, if it was fetched by get_publisher_from_doi."""
    return (_crossref_metadata.get(doi) or {}).get("title")


# Map tool name to function
TOOL_FUNCTIONS = {
    "elsevier": tools.download_via_elsevier,
    "springerpdf": tools.download_via_springerpdf,
    "wiley": tools.download_via_wiley,
    "plos": tools.download_via_plos,
    "unpaywall": tools.download_via_unpaywall,
    "europepmc": tools.download_via_europepmc,
    "springeropen": tools.download_via_springeropen,
    "crossref_tdm": tools.download_via_crossref_tdm,
    "arxiv": tools.download_via_arxiv,
    "chemrxiv": tools.download_via_chemrxiv,
    "biorxiv": tools.download_via_biorxiv,
    "mdpi": tools.download_via_mdpi,
    "zenodo": tools.download_via_zenodo,
    "semantic": tools.download_via_semantic,
    "elife": tools.download_via_elife,
    "paperscraper": tools.download_via_paperscraper,
    "aps": tools.download_via_aps,
    "cambridge": tools.download_via_cambridge,
    "osti": tools.download_via_osti,
    "pmc": tools.download_via_pmc,
    "openreview": tools.download_via_openreview,
}

# Tools whose only output is XML rather than PDF.
XML_TOOLS = ("elsevier", "springeropen")

# Routes that address the publisher's own copy by identifier and therefore
# cannot return a different paper. Their files skip the title check (which
# would wrongly reject one-page items such as cover features); the check is
# for third-party indexes, which occasionally map a DOI to the wrong document.
TRUSTED_TOOLS = ("wiley", "elsevier", "springerpdf", "springeropen", "crossref_tdm", "arxiv",
                 "chemrxiv", "biorxiv", "zenodo", "pmc", "openreview", "plos", "elife", "cambridge", "aps")

# Tool lists for identifiers that are not DOIs.
_KIND_TOOLS = {"arxiv": ["arxiv"], "pmc": ["pmc"], "openreview": ["openreview"]}


def _setup_logger(log_file):
    logger = logging.getLogger(__name__)
    if log_file:
        with _log_setup_lock:
            # Avoid adding multiple handlers for the same log file
            file_path = os.path.abspath(log_file)
            add_handler = True
            for h in logger.handlers:
                if isinstance(h, logging.FileHandler):
                    # If a file handler for the same file already exists, don't add another
                    if hasattr(h, 'baseFilename') and os.path.abspath(
                            getattr(h, 'baseFilename', '')) == file_path:
                        add_handler = False
                        break
            if add_handler:
                file_handler = logging.FileHandler(file_path, mode='a')
                file_handler.setLevel(logging.INFO)
                formatter = logging.Formatter(
                    '%(asctime)s - %(levelname)s - %(message)s')
                file_handler.setFormatter(formatter)
                logger.addHandler(file_handler)
            logger.setLevel(logging.INFO)
    return logger


def _output_path(output_dir, output_filename, base_name, tool):
    """Path for one attempt: the caller's name, or <base_name>.<pdf|xml>."""
    if output_filename:
        name, ext = os.path.splitext(output_filename)
        if ext == "":
            ext = ".xml" if tool in XML_TOOLS else ".pdf"
            return os.path.join(output_dir, name + ext)
        return os.path.join(output_dir, output_filename)
    ext = ".xml" if tool in XML_TOOLS else ".pdf"
    return os.path.join(output_dir, base_name + ext)


def _verify(path, title, tool=None):
    if str(path).lower().endswith(".pdf"):
        return verify.check_pdf(path, None if tool in TRUSTED_TOOLS else title)
    if str(path).lower().endswith(".xml"):
        return verify.check_xml(path)
    return True, "not checked"


def fetch(identifier: str, output_dir: str, output_filename: str = None,
          tools: list = None, log_file: str = None, check: bool = True,
          skip_existing: bool = True, supplements: bool = False) -> dict:
    """
    Download the full text for one identifier and describe the outcome.

    - identifier: DOI (bare, doi:, or doi.org URL), arXiv id or URL, PMC id, or OpenReview id.
    - output_dir: directory to save the downloaded file.
    - output_filename: optional explicit filename (including extension).
    - tools: optional list of tool names to try, overriding the publisher-based default.
    - log_file: optional path to a log file to append logging information.
    - check: verify each downloaded PDF against the Crossref title and reject
      supporting-information files; a rejected file is deleted and the next
      tool is tried.
    - skip_existing: reuse a valid file already present under the default name.
    - supplements: also fetch the article's supplementary files, saved next to
      it as <name>_si1.<ext>, <name>_si2.<ext>, ... and listed in `supplements`.
      Off by default: it costs a landing-page request per article.

    Returns a dict:
      {"identifier", "success", "path", "source", "note", "error", "attempts", "supplements"}
    where `note` is set when the file is not the publisher's version of record
    and `attempts` lists every tool tried with its error.
    """
    logger = _setup_logger(log_file)
    result = {"identifier": identifier, "success": False, "path": None,
              "source": None, "note": None, "error": None, "attempts": [], "supplements": []}
    try:
        kind, value = identifiers.parse(identifier)
    except ValueError as e:
        result["error"] = str(e)
        return result
    os.makedirs(output_dir, exist_ok=True)
    base_name = identifiers.safe_filename(value)
    if supplements:
        result["supplements"] = supplements_module.download_supplements(kind, value, output_dir, base_name)
        logger.info(f"{len(result['supplements'])} supplementary files for {identifier}")

    if skip_existing and not output_filename:
        existing = os.path.join(output_dir, base_name + ".pdf")
        if os.path.isfile(existing) and _verify(existing, None)[0]:
            result.update(success=True, path=existing, source="cache",
                          note="file already present; not downloaded again")
            return result

    title = None
    if tools is None:
        if kind == "doi":
            publisher = get_publisher_from_doi(value)
            method_list = PUBLISHER_TOOL_MAP.get(publisher, DEFAULT_TOOLS) if publisher else DEFAULT_TOOLS
            host = (_crossref_metadata.get(value) or {}).get("hosted_by")
            if host and host not in method_list:
                method_list = [host] + method_list if host == "wiley" else method_list[:1] + [host] + method_list[1:]
        else:
            method_list = _KIND_TOOLS[kind]
    else:
        method_list = tools
    if kind == "doi":
        title = get_title_from_doi(value)

    for tool in method_list:
        if tool not in TOOL_FUNCTIONS:
            result["attempts"].append({"tool": tool, "error": "unknown tool"})
            continue
        output_path = _output_path(output_dir, output_filename, base_name, tool)
        try:
            logger.info(f"Attempting {identifier} with tool: {tool}")
            path = TOOL_FUNCTIONS[tool](value, output_path)
        except Exception as e:
            logger.warning(f"Tool {tool} failed for {identifier}: {e}")
            result["attempts"].append({"tool": tool, "error": str(e)})
            continue
        if check:
            ok, reason = _verify(path, title, tool)
            if not ok:
                logger.warning(f"Tool {tool} returned an unusable file for {identifier}: {reason}")
                result["attempts"].append({"tool": tool, "error": f"rejected: {reason}"})
                try:
                    os.remove(path)
                except OSError:
                    pass
                continue
        logger.info(f"Success with {tool} for {identifier} -> {path}")
        result.update(success=True, path=str(path), source=getattr(path, "source", None) or tool,
                      note=getattr(path, "note", None))
        return result

    tried = "; ".join(f"{a['tool']}: {a['error']}" for a in result["attempts"])
    result["error"] = f"All download methods failed for {identifier}. Attempts: {tried}"
    logger.error(result["error"])
    return result


def download_article(doi: str, output_dir: str, output_filename: str = None,
                     tools: list = None, log_file: str = None) -> str:
    """
    Download the full text of an article given its DOI (or arXiv/PMC/OpenReview id),
    using available tools in a fallback sequence.
    Returns the path to the downloaded file on success. Raises an Exception if all methods fail.
    The returned path is a str; when the file is not the publisher's version of
    record it also carries a `.note` attribute saying so.
    """
    result = fetch(doi, output_dir, output_filename=output_filename, tools=tools,
                   log_file=log_file, skip_existing=False)
    if result["success"]:
        return tools_module.Fetched(result["path"], note=result["note"], source=result["source"])
    last = result["attempts"][-1]["error"] if result["attempts"] else result["error"]
    raise Exception(f"All download methods failed for DOI {doi}. Last error: {last}")


tools_module = tools  # the `tools` name is shadowed by the parameter above
supplements_module = supplements  # likewise `supplements`


def fetch_many(identifiers_list: list, output_dir: str, workers: int = 4,
               tools: list = None, log_file: str = None, check: bool = True,
               supplements: bool = False) -> dict:
    """Download several identifiers concurrently. Returns {identifier: fetch() result}
    in input order; duplicates are collapsed."""
    from concurrent.futures import ThreadPoolExecutor
    ids = list(dict.fromkeys(i.strip() for i in identifiers_list if i and i.strip()))
    if not ids:
        return {}
    with ThreadPoolExecutor(max_workers=max(1, min(workers, len(ids)))) as pool:
        results = list(pool.map(lambda i: fetch(i, output_dir, tools=tools, log_file=log_file, check=check,
                                                supplements=supplements), ids))
    return dict(zip(ids, results))


def bulk_download_articles(dois: list, output_dir: str, log_file: str = None,
                           sleep: float = 0.0, workers: int = 1):
    """
    Download multiple articles given a list of DOIs, saving them to the specified output directory.
    - dois: list of DOI strings to download.
    - output_dir: directory to save the downloaded files.
    - log_file: optional path to a log file for logging progress and errors.
    - sleep: optional number of seconds to sleep after each download (default 0, no pause).
    - workers: number of concurrent downloads (default 1, sequential). Most of the
      wall time is spent waiting on publisher and index APIs, so a handful of
      threads gives a near-linear speedup; publisher rate limits still apply.
    Returns a dict mapping each DOI to the output file path or to an error message if failed.
    """
    import time
    from concurrent.futures import ThreadPoolExecutor
    total = len(dois)
    use_tqdm = total > 1
    if use_tqdm:
        try:
            from tqdm import tqdm
        except ImportError:
            use_tqdm = False

    def one(doi):
        try:
            result = download_article(doi, output_dir, output_filename=None,
                                      tools=None, log_file=log_file)
        except Exception as e:
            result = f"ERROR: {e}"
            if not use_tqdm:
                print(f"Failed to download {doi}: {e}")
        if sleep > 0:
            time.sleep(sleep)
        return doi, result

    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        iterator = pool.map(one, dois)
        if use_tqdm:
            iterator = tqdm(iterator, total=total, desc="Downloading articles", unit="article")
        results = dict(iterator)
    if use_tqdm:
        # After completing, print summary of failures (if any)
        failed = [d for d, res in results.items() if
                  isinstance(res, str) and res.startswith("ERROR")]
        if failed:
            print(f"\nThe following DOIs could not be downloaded:")
            for d in failed:
                print(f"  - {d}: {results[d]}")
    return results

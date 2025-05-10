import os
import logging
import requests
import sys

logging.basicConfig(stream=sys.stdout, level=logging.WARNING)

# Mapping of publisher names to preferred tool order
PUBLISHER_TOOL_MAP = {
    "Elsevier BV": ["unpaywall", "elsevier"],
    "Springer Science and Business Media LLC": ["springerpdf", "unpaywall", "springeropen"],
    "Wiley": ["wiley", "unpaywall"],
    "American Chemical Society (ACS)": ["unpaywall"],
    "Royal Society of Chemistry (RSC)": ["unpaywall"],
    "American Institute of Physics (AIP)": ["unpaywall"],
    "American Physical Society (APS)": ["aps", "unpaywall"],
    "Oxford University Press (OUP)": ["unpaywall"],
    "Cambridge University Press (CUP)": ["cambridge", "unpaywall"],
    "Taylor & Francis": ["unpaywall"],
    "Public Library of Science (PLoS)": ["plos", "unpaywall"],
    "bioRxiv": ["paperscraper", "unpaywall"],
    "medRxiv": ["paperscraper", "unpaywall"],
    "chemRxiv": ["paperscraper", "unpaywall"],
    "arXiv": ["paperscraper", "arxiv", "unpaywall"],
    "eLife Sciences Publications, Ltd": ["elife", "unpaywall"],
    "Institute of Electrical and Electronics Engineers (IEEE)": ["unpaywall"]
}

# Mapping of DOI prefix to known preprint server (for quick identification without API calls)
PREPRINT_SERVER_PREFIXES = {
    "10.1101": "bioRxiv",
    "10.21203": "Research Square",
    "10.31219": "OSF Preprints",
    "10.20944": "Preprints.org",
    "10.26434": "chemRxiv",
    "10.22541": "medRxiv",
    "10.31730": "EarthArXiv",
    "10.1149": "ECSarXiv",
    "10.3886": "SSRN",
    "10.33774": "Cambridge Open Engage",
    "10.2139": "SSRN",
    "10.53731": "arXiv",
    "10.48550": "arXiv",
    "10.57967": "engRxiv",
    "10.3389": "Frontiers Media SA",
    "10.4175": "Frontiers Media SA"
}


def get_publisher_from_doi(doi: str):
    """
    Resolve a DOI to get the publisher or source name, by querying CrossRef (and DataCite as fallback).
    Returns the publisher name or preprint server name if identified, or None if not found.
    """
    # Check prefix if it's a known preprint server
    prefix = doi.split('/')[0]
    if prefix in PREPRINT_SERVER_PREFIXES:
        return PREPRINT_SERVER_PREFIXES[prefix]
    # Query CrossRef for metadata
    crossref_url = f"https://api.crossref.org/works/{doi}"
    try:
        r = requests.get(crossref_url)
        if r.status_code == 404:
            # Try DataCite if not found on CrossRef
            datacite_url = f"https://api.datacite.org/dois/{doi}"
            r2 = requests.get(datacite_url)
            if r2.status_code == 200:
                data = r2.json()
                publisher = data.get("data", {}).get("attributes", {}).get(
                    "publisher")
                return publisher
            else:
                return None
        r.raise_for_status()
        data = r.json()
        publisher = data.get("message", {}).get("publisher")
        return publisher
    except Exception as e:
        logging.error(f"Failed to resolve DOI {doi} to publisher: {e}")
        return None


# Import the tool-specific download functions
from . import tools

# Map tool name to function
TOOL_FUNCTIONS = {
    "elsevier": tools.download_via_elsevier,
    "springerpdf": tools.download_via_springerpdf,
    "wiley": tools.download_via_wiley,
    "plos": tools.download_via_plos,
    "unpaywall": tools.download_via_unpaywall,
    "springeropen": tools.download_via_springeropen,
    "crossref_tdm": tools.download_via_crossref_tdm,
    "arxiv": tools.download_via_arxiv,
    "elife": tools.download_via_elife,
    "paperscraper": tools.download_via_paperscraper,
    "aps": tools.download_via_aps,
    "cambridge": tools.download_via_cambridge
}


def download_article(doi: str, output_dir: str, output_filename: str = None,
                     tools: list = None, log_file: str = None) -> str:
    """
    Download the full text of an article given its DOI, using available tools in a fallback sequence.
    - doi: The DOI of the article.
    - output_dir: Directory to save the downloaded file.
    - output_filename: Optional explicit filename for the output (including extension). 
                       If not provided, will use a name derived from the DOI.
    - tools: Optional list of tool names to try (overrides the default mapping based on publisher).
    - log_file: Optional path to a log file to append logging information.
    Returns the path to the downloaded file on success. Raises an Exception if all methods fail.
    """
    # Configure logging if log_file is provided
    logger = logging.getLogger(__name__)
    if log_file:
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
    # Ensure output directory exists
    os.makedirs(output_dir, exist_ok=True)
    # Determine the list of tools to use
    if tools is None:
        publisher = get_publisher_from_doi(doi)
        if publisher:
            method_list = PUBLISHER_TOOL_MAP.get(publisher, ["unpaywall", "crossref_tdm"])
        else:
            method_list = ["unpaywall", "crossref_tdm"]
    else:
        method_list = tools
    # Sanitize DOI for use in file name (replace disallowed characters with '_')
    import re
    base_name = re.sub(r'[^A-Za-z0-9._-]', '_', doi)
    last_exception = None
    for tool in method_list:
        # Determine appropriate file extension for this tool
        if output_filename:
            # Use provided name, but if no extension in provided name, add one based on tool
            name, ext = os.path.splitext(output_filename)
            if ext == "":
                # Choose extension: .xml for certain tools, otherwise .pdf
                ext = ".xml" if tool in ["elsevier", "springeropen"] else ".pdf"
                out_name = name + ext
            else:
                out_name = output_filename
        else:
            ext = ".xml" if tool in ["elsevier", "springeropen"] else ".pdf"
            out_name = base_name + ext
        output_path = os.path.join(output_dir, out_name)
        try:
            logger.info(f"Attempting DOI {doi} with tool: {tool}")
            result_path = TOOL_FUNCTIONS[tool](doi, output_path)
            logger.info(f"Success with {tool} for DOI {doi} -> {result_path}")
            return result_path
        except Exception as e:
            last_exception = e
            logger.warning(f"Tool {tool} failed for DOI {doi}: {e}")
            continue
    # If loop completes without returning, all tools failed
    error_msg = f"All download methods failed for DOI {doi}."
    logger.error(error_msg)
    if last_exception:
        error_msg += f" Last error: {last_exception}"
    # If no specific exception from tools, raise a general one
    raise Exception(error_msg)


def bulk_download_articles(dois: list, output_dir: str, log_file: str = None,
                           sleep: float = 0.0):
    """
    Download multiple articles given a list of DOIs, saving them to the specified output directory.
    - dois: list of DOI strings to download.
    - output_dir: directory to save the downloaded files.
    - log_file: optional path to a log file for logging progress and errors.
    - sleep: optional number of seconds to sleep between each download (default 0, no pause).
    Returns a dict mapping each DOI to the output file path or to an error message if failed.
    """
    results = {}
    total = len(dois)
    use_tqdm = total > 1
    if use_tqdm:
        try:
            from tqdm import tqdm
        except ImportError:
            use_tqdm = False
    iterator = dois
    if use_tqdm:
        iterator = tqdm(dois, desc="Downloading articles", unit="article")
    for doi in iterator:
        try:
            path = download_article(doi, output_dir, output_filename=None,
                                    tools=None, log_file=log_file)
            results[doi] = path
        except Exception as e:
            results[doi] = f"ERROR: {e}"
            # If not using tqdm, print error immediately
            if not use_tqdm:
                print(f"Failed to download {doi}: {e}")
        if sleep > 0:
            import time
            time.sleep(sleep)
    if use_tqdm:
        # After completing, print summary of failures (if any)
        failed = [d for d, res in results.items() if
                  isinstance(res, str) and res.startswith("ERROR")]
        if failed:
            print(f"\nThe following DOIs could not be downloaded:")
            for d in failed:
                print(f"  - {d}: {results[d]}")
    return results

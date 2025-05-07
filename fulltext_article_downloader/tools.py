import os
import requests
import browser_cookie3
from bs4 import BeautifulSoup
from urllib.parse import urlparse

def _download_file(url: str, output_path: str, headers=None, session=None):
    """
    Helper to download a file from a URL to the given output path using streaming.
    Raises an Exception if the HTTP status is not 200.
    """
    req = session.get if session else requests.get
    # Provide default headers if none given? (We won't set a default UA here, let caller provide if needed)
    try:
        response = req(url, headers=headers, stream=True)
    except Exception as e:
        raise Exception(f"Request error for {url}: {e}")
    if response.status_code != 200:
        raise Exception(
            f"Failed to download {url} (status code: {response.status_code})")
    try:
        with open(output_path, "wb") as f:
            for chunk in response.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)
    except Exception as e:
        raise Exception(f"Error writing to file {output_path}: {e}")
    return output_path


def download_via_elsevier(doi: str, output_path: str):
    """
    Download the full-text XML of an Elsevier article via the Elsevier API.
    Requires an Elsevier API key.
    """
    api_key = os.getenv("ELSEVIER_API_KEY")
    if not api_key:
        raise Exception(
            "ELSEVIER_API_KEY is not set. Please configure your Elsevier API key.")
    url = f"https://api.elsevier.com/content/article/doi/{doi}"
    headers = {
        "X-ELS-APIKey": api_key,
        "Accept": "text/xml"
    }
    params = {"view": "FULL"}
    try:
        response = requests.get(url, headers=headers, params=params)
    except Exception as e:
        raise Exception(f"Error connecting to Elsevier API: {e}")
    if response.status_code == 200:
        # Save XML content
        with open(output_path, 'wb') as f:
            f.write(response.content)
        return output_path
    elif response.status_code == 403:
        # Access denied (likely API key or no institutional access)
        raise Exception(
            "Access denied by Elsevier API. Verify API key and access rights.")
    elif response.status_code == 404:
        raise Exception("DOI not found in Elsevier API.")
    else:
        raise Exception(
            f"Elsevier API request failed (status code {response.status_code}).")


def download_via_springerpdf(doi: str, output_path: str):
    """
    Download the PDF of a Springer article (including Nature) by constructing the direct PDF URL.
    Note: This method mimics a browser and may not work for bulk or for closed-access content.
    """
    pdf_url = f"https://link.springer.com/content/pdf/{doi}.pdf"
    headers = {
        "User-Agent": "Mozilla/5.0",
        "Referer": f"https://link.springer.com/article/{doi}"
    }
    return _download_file(pdf_url, output_path, headers=headers)


def download_via_wiley(doi: str, output_path: str):
    """
    Download the PDF of a Wiley article via the Wiley TDM API.
    Requires a Wiley API key.
    """
    api_key = os.getenv("WILEY_API_KEY")
    if not api_key:
        raise Exception(
            "WILEY_API_KEY is not set. Please configure your Wiley API key.")
    base_url = "https://api.wiley.com/onlinelibrary/tdm/v1/articles/"
    url = base_url + doi
    headers = {"Wiley-TDM-Client-Token": api_key}
    try:
        return _download_file(url, output_path, headers=headers)
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
        return _download_file(pdf_url, output_path, headers=None)
    except Exception as e:
        raise Exception(f"PLOS download failed: {e}")


def download_via_unpaywall(doi: str, output_path: str):
    """
    Download an open-access PDF via Unpaywall.
    Requires an email configured for Unpaywall (UNPAYWALL_EMAIL).
    """
    email = os.getenv("UNPAYWALL_EMAIL")
    if not email:
        raise Exception(
            "UNPAYWALL_EMAIL is not set. Please set this to use Unpaywall.")
    api_url = f"https://api.unpaywall.org/v2/{doi}?email={email}"
    try:
        r = requests.get(api_url)
    except Exception as e:
        raise Exception(f"Error connecting to Unpaywall API: {e}")
    if r.status_code != 200:
        raise Exception(
            f"Unpaywall API request failed (status code {r.status_code})")
    data = r.json()
    pdf_url = None
    if data.get("best_oa_location"):
        pdf_url = data["best_oa_location"].get("url_for_pdf")
    if not pdf_url:
        raise Exception(f"No open-access PDF found for DOI: {doi}")
    # Download the PDF from the obtained URL
    return _download_file(pdf_url, output_path)


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
        r = requests.get(api_url)
    except Exception as e:
        raise Exception(f"Error connecting to CrossRef API: {e}")
    if r.status_code != 200:
        raise Exception(f"CrossRef API request failed (status {r.status_code})")
    data = r.json().get("message", {})
    links = data.get("link", [])
    pdf_link = None
    for link in links:
        if link.get("content-type", "").startswith("application/pdf"):
            pdf_link = link.get("URL")
            break
    if not pdf_link:
        raise Exception(f"No PDF link found via CrossRef for DOI {doi}")
    # Download the PDF from the found link
    return _download_file(pdf_link, output_path)


def download_via_arxiv(doi: str, output_path: str):
    """
    Download the PDF of an arXiv paper given its DOI (DataCite DOI for arXiv).
    """
    # Extract arXiv identifier from DOI
    arxiv_id = doi.split("/")[-1]
    if arxiv_id.lower().startswith("arxiv."):
        arxiv_id = arxiv_id[len("arXiv."):]
    if arxiv_id.lower().startswith("arxiv:"):
        arxiv_id = arxiv_id[len("arXiv:"):]
    pdf_url = f"https://arxiv.org/pdf/{arxiv_id}.pdf"
    return _download_file(pdf_url, output_path)


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
        response = requests.get(doi_url, headers=headers, allow_redirects=True)
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
    return _download_file(pdf_link, output_path, headers=headers)


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
    return output_path


def download_via_aps(doi: str, output_path: str):
    """
    Download a PDF from the American Physical Society (APS) publications by using stored browser cookies for authentication.
    Requires that the user is logged in to APS (e.g., via institution) and browser_cookie3 can retrieve the cookies.
    """
    # Create a session and load APS cookies from the default browser
    session = requests.Session()
    try:
        session.cookies.update(browser_cookie3.load(domain_name='aps.org'))
    except Exception as e:
        raise Exception(f"Failed to load APS cookies: {e}")
    # Try CrossRef metadata to find APS fulltext link
    crossref_url = f"https://api.crossref.org/works/{doi}"
    pdf_url = None
    try:
        r = session.get(crossref_url)
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
                          session=session)


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
        response = requests.get(doi_url, allow_redirects=True)
    except Exception as e:
        raise Exception(f"Failed to resolve DOI {doi}: {e}")
    if response.status_code != 200:
        raise Exception(
            f"Failed to resolve DOI: {doi} (Status code: {response.status_code})")
    article_url = response.url
    html = None
    try:
        html = requests.get(article_url).text
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
    return _download_file(pdf_url, output_path)

# fulltext-article-downloader

**fulltext-article-downloader** is a Python package for **programmatically downloading the full text of research articles from their DOIs**. It chains together publisher APIs, open‑access aggregators, and polite web scraping in a fallback sequence so you can collect large corpora of PDFs or XML for text mining and analysis.

---

## Features

* **Multiple retrieval methods** – Elsevier, Wiley, Springer Open Access, CrossRef TDM links, Unpaywall, and direct scraping for publishers that lack easy APIs (e.g. PLOS, eLife, Cambridge, APS).
* **Automatic fallback logic** – The package selects the best method based on the DOI’s publisher; if one fails, the next is tried automatically.
* **Configurable tool order** – Per‑publisher method sequences are configurable; defaults cover most major publishers and preprint servers.
* **Batch downloads with progress** – Sequentially download large DOI lists with a `tqdm` progress bar and optional sleep between requests.
* **Integrated logging** – Console progress plus detailed file logs that record which tool succeeded or why a DOI failed.
* **Easy API‑key management** – Store credentials via environment variables or the interactive `fulltext-config` script.
* **Command‑line interface (CLI)** – `fulltext-download` lets you fetch an article without writing Python.

---

## Installation

### Option 1 - quick install from github

```
pip install git+https://github.com/computron/fulltext-article-downloader.git
```

Make sure to **configure** your installation afterwards (see next section).

### Option 2 - editable clone (recommended for development)

```
git clone https://github.com/computron/fulltext-article-downloader.git
cd fulltext-article-downloader
pip install -e .
```

Make sure to **configure** your installation afterwards (see next section).

## Configuration (API keys & email)

Some methods need credentials:

| Service                         | Environment variable |
| ------------------------------- | -------------------- |
| Elsevier API                    | `ELSEVIER_API_KEY`   |
| Springer Open Access API        | `SPRINGER_API_KEY`   |
| Wiley TDM API                   | `WILEY_API_KEY`      |
| Unpaywall (valid email address) | `UNPAYWALL_EMAIL`    |

Set these environment variables **or** run the interactive helper:

```bash
fulltext-config
```

The script stores keys in `~/.fulltext_keys`, which are loaded automatically on import. If a required key is missing, the corresponding tool is skipped and the downloader falls back to other methods.

---

## Usage

### 1. Command‑line interface (CLI)

```text
fulltext-download <DOI> <OUTPUT_DIR> [OUTPUT_FILENAME]
```

Examples:

```bash
# DOI‑based filename
fulltext-download 10.1371/journal.pone.0171501 papers

# Custom filename
fulltext-download 10.1002/advs.201900808 papers wiley_article.pdf
```

If the download succeeds, the file (PDF or XML) is saved and a success message printed; otherwise an error is sent to `stderr`. The CLI uses the same fallback logic as the Python API.

### 2. Python API

#### Download a single article

```python
from fulltext_article_downloader import download_article

doi = "10.1371/journal.pone.0171501"  # PLOS ONE example
output_path = download_article(doi, output_dir="papers")
print(f"Downloaded to: {output_path}")
```

Custom filename:

```python
from fulltext_article_downloader import download_article
doi = "10.1371/journal.pone.0171501"  # PLOS ONE example
download_article(doi, output_dir="papers", output_filename="my_article.pdf")
```

Logging:

```python
from fulltext_article_downloader import download_article
doi = "10.1371/journal.pone.0171501"  # PLOS ONE example
download_article(doi, output_dir="papers", log_file="download.log")
```

Example log excerpt:

```
2025‑05‑06 15:55:10,123 INFO  Attempting DOI 10.1002/advs.201900808 with tool: wiley
2025‑05‑06 15:55:11,456 WARN  Tool wiley failed: …
2025‑05‑06 15:55:12,789 INFO  Success with unpaywall → downloads/10.1002_advs.201900808.pdf
```
#### Download multiple articles (bulk)

```python
from fulltext_article_downloader import bulk_download_articles

dois = [
    "10.1371/journal.pone.0171501",  # PLOS (open access)
    "10.1002/advs.201900808",  # Wiley (may need API key)
    "10.1101/2025.01.06.631505",  # bioRxiv preprint
    "10.48550/arXiv.2207.03928",  # arXiv preprint
]

results = bulk_download_articles(
    dois,
    output_dir="papers",
    log_file="download.log",
    sleep=0.2,  # seconds between downloads
)
```

---

## Failures

Many articles are not open-access, and publishers explicitly restrict or discourage text and data mining. The following are examples of failures:

Command line example of **unsupported** article - this example is expected to FAIL:
```bash
fulltext-download 10.1109/GROUP4.2007.4347715 papers
```

Python example of **unsupported** article - this example is expected to FAIL:
```python
from fulltext_article_downloader import download_article

doi = "10.1109/GROUP4.2007.4347715"
output_path = download_article(doi, output_dir="papers")
print(f"Downloaded to: {output_path}")
```

If you see an error like ``Failed to load APS cookies``, please make sure you are running Python using an application that has full disk access.

See next section (Methods and fallback logic) for details on tools implemented.

## Methods and fallback logic

The tool is composed of multiple sub-tools intended to support various publishers. The tool order depends on the publisher.


| Publisher / source | Default tool order                                                  |
| ------------------ | --------------------------------------------------------------------|
| Elsevier           | `unpaywall` → `elsevier` (XML)                                      |
| Springer / Nature  | `crossref_tdm` → `springerpdf` → `unpaywall` → `springeropen` (XML) |
| Wiley              | `wiley` → `unpaywall`                                               |
| PLOS               | `plos`                                                              |
| Preprint servers   | `paperscraper`                                                      |
| arXiv              | `paperscraper` → `arxiv`                                            |
| eLife              | `elife`                                                             |
| Cambridge          | `cambridge`                                                         |
| APS                | `aps`                                                               |
| Others             | `unpaywall`                                                         |

See the ``PUBLISHER_TOOL_MAP`` in ``downloader.py``.

> **Tip** – Scraping‑based methods (`springerpdf`, `elife`, `cambridge`, etc.) can break if sites change layout or due to access limits; favour official APIs and Unpaywall for large‑scale downloads.

### Customising the tool sequence

```python
from fulltext_article_downloader import download_article
doi = "10.1017/S0885715624000484"  # Cambridge University Press
download_article(
    doi,
    output_dir="papers",
    tools=["unpaywall", "cambridge"],  # override default order
)
```

### Override at runtime:

```python
from fulltext_article_downloader import PUBLISHER_TOOL_MAP
PUBLISHER_TOOL_MAP["Elsevier BV"] = ["elsevier", "unpaywall"]
```

---

## License and Disclaimer.

BSD 3‑Clause. See the `LICENSE` file.

Use this tool **only** for content you are legally entitled to access. Respect publisher terms and copyright laws. The authors are **not** responsible for misuse.

Speed-coded by computron on vibes (ChatGPT 4.0) and caffeine.

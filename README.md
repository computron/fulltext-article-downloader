# fulltext-article-downloader
<!-- mcp-name: io.github.computron/fulltext-article-downloader -->

**fulltext-article-downloader** is a Python package for **programmatically downloading the full text of research articles** from a DOI, arXiv id, PubMed Central id or OpenReview id. It chains together publisher APIs, open-access indexes and repositories in a fallback sequence, checks that what came back is really the requested article, and can be used from Python, from the command line, or by an AI agent through an MCP server or a Claude Code skill.

**Video tutorial**: https://youtu.be/fTtc4QWMYzE

---

## Features

* **Multiple retrieval methods** – Elsevier, Wiley and Springer Nature APIs, CrossRef TDM links, Unpaywall, Europe PMC, OSTI (accepted manuscripts of DOE-funded articles), Semantic Scholar's open-access index, arXiv, ChemRxiv, bioRxiv/medRxiv, Zenodo, MDPI's CDN, and direct scraping for publishers that lack easy APIs (PLOS, eLife, Cambridge, APS).
* **Automatic fallback logic** – The package selects the best method based on the DOI's publisher; if one fails, the next is tried automatically.
* **Verification** – Every PDF is checked against the article's title, and supporting-information files and abstract-only records are rejected, so a returned file is the paper you asked for.
* **Honest results** – Each download reports which route produced the file and carries a note when it is a preprint or accepted manuscript rather than the publisher's version of record.
* **Configurable tool order** – Per-publisher method sequences are configurable; defaults cover most major publishers and preprint servers.
* **Batch downloads** – Concurrent downloads with publisher rate limits enforced, a `tqdm` progress bar, and file logs that record which tool succeeded or why an identifier failed.
* **Easy API-key management** – Store credentials via environment variables or the interactive `fulltext-config` script.
* **Four entry points, one engine** – Python API, `fulltext-download` CLI, `fulltext-mcp` server for any MCP client, and a Claude Code plugin with a ready-made skill.

---

## 1. Installation

```bash
pip install fulltext-article-downloader
```

Optional extras enable additional routes and the MCP server:

| Extra | Adds |
| --- | --- |
| `mcp` | the `fulltext-mcp` server (fastmcp) |
| `tls` | a Chrome TLS fingerprint fallback for hosts that reject plain HTTPS clients (curl-cffi) |
| `springer` | the Springer Nature open-access XML route (sprynger) |
| `preprints` | bioRxiv/medRxiv downloads through paperscraper |
| `aps` | the APS route that reuses your browser's login cookies (browser-cookie3) |
| `all` | everything above |

`tls` and `aps` both work by making a request look more like your own browser than a script: `tls` matches Chrome's TLS fingerprint for hosts that turn away plain HTTPS clients, and `aps` reuses the APS session cookie you are already signed in with. Neither opens anything you are not licensed for, but both go a step beyond a plain API client, so they are worth checking against your institution's agreements before you enable them. A default install has neither; `all` includes them.

```bash
pip install "fulltext-article-downloader[mcp,tls]"
```

For development, clone the repository and run `pip install -e ".[dev,all]"`. Make sure to **configure** your installation afterwards (see next section).

## 2. Configuration (API keys & email)

All credentials are optional; each one unlocks a route. Without keys, and off campus, expect open-access papers, preprints and DOE-funded manuscripts to work and most paywalled articles to fail.

| Service | Environment variable | Where to get the key |
| --- | --- | --- |
| Unpaywall and Crossref contact email (your own address) | `UNPAYWALL_EMAIL` | (enter your email address) |
| Elsevier API | `ELSEVIER_API_KEY` | https://dev.elsevier.com |
| Wiley TDM API | `WILEY_API_KEY` | https://onlinelibrary.wiley.com/library-info/resources/text-and-datamining |
| Springer Open Access API | `SPRINGER_API_KEY` | https://dev.springernature.com |
| Semantic Scholar (optional; raises the rate limit and enables the title search that finds arXiv copies of papers whose DOI record has no PDF) | `SEMANTIC_SCHOLAR_API_KEY` | https://www.semanticscholar.org/product/api (free, approved by email in a few days) |

`UNPAYWALL_EMAIL` is sent only to Unpaywall and Crossref, which ask API users for a contact address; Crossref serves requests that carry one from its faster "polite" pool. Keys and the email stay on your machine.

Set these environment variables **or** run the interactive helper:

```bash
fulltext-config
```

The script stores keys in `~/.fulltext_keys`, which are loaded automatically on import. If a required key is missing, the corresponding tool is skipped and the downloader falls back to other methods. Publisher keys return paywalled content only when the key or the network is entitled; the package detects truncated or abstract-only responses and moves on.

---

## 3. Usage

### Identifiers

Any of these forms is accepted everywhere an identifier is expected:

* DOI: `10.1021/jacs.3c13302`, `https://doi.org/10.1021/jacs.3c13302`, `doi:10.1021/jacs.3c13302`
* arXiv: `2310.19377`, `arXiv:2310.19377`, `https://arxiv.org/abs/2310.19377`, `cond-mat/9712061`, `10.48550/arXiv.2310.19377`
* PubMed Central: `PMC6561843`
* OpenReview: `fNyXCCZ0g6`

### Command-line interface (CLI)

```text
fulltext-download <ID> [<ID> ...] [-o DIR] [--tools a,b,c] [--workers N] [--no-check] [--log-file FILE]
```

```bash
fulltext-download 10.1371/journal.pone.0171501 -o papers
fulltext-download 10.1021/jacs.3c13302 arXiv:1710.10324 PMC6561843 -o papers --workers 4
```

The command prints one JSON object per identifier and exits 0 only when every download succeeded:

```json
[
 {
  "identifier": "10.1021/jacs.3c13302",
  "success": true,
  "path": "papers/10.1021_jacs.3c13302.pdf",
  "source": "osti",
  "note": "OSTI accepted manuscript, not the publisher's version of record",
  "error": null,
  "attempts": [],
  "supplements": []
 }
]
```

The original form `fulltext-download <DOI> <OUTPUT_DIR> [<FILENAME>]` still works.

### Python API

`fetch` returns the same structure the CLI prints; `fetch_many` downloads a list concurrently:

```python
from fulltext_article_downloader import fetch, fetch_many

r = fetch("10.1371/journal.pone.0171501", "papers")
if r["success"]:
    print(r["path"], r["source"], r["note"])
else:
    print(r["error"])           # every route tried, with its reason

rs = fetch_many(["10.1002/advs.201900808", "10.48550/arXiv.2207.03928"], "papers", workers=4)
```

The earlier functions are unchanged: `download_article(doi, output_dir, ...)` returns the path or raises, and `bulk_download_articles(dois, output_dir, log_file=..., sleep=..., workers=...)` returns a dict of paths or `"ERROR: ..."` strings with a progress bar.

Options shared by all of them: `output_filename` (single download), `tools` (a list of route names that overrides the publisher default), `log_file` (append a download log), and for `fetch` also `check=False` to skip verification and `skip_existing=False` to re-download a file that is already present.

### Supplementary files

`fetch(..., supplements=True)`, `fetch_many(..., supplements=True)`, `fulltext-download --supplements` and the MCP tools' `supplements=true` also fetch the article's supplementary files (supporting information, data tables, videos). They are separate files from separate places, so they are saved next to the article as `<name>_si1.pdf`, `<name>_si2.xlsx`, ... and listed in the result's `supplements`. Sources: the ChemRxiv and Elsevier APIs, Europe PMC's supplement bundle for PMC articles, and otherwise the article's landing page (Springer Nature, Wiley, bioRxiv, ACS, RSC, PLOS and others link them there; most publishers serve supplements without a subscription). Off by default because it costs one more request per article; a missing supplement never fails the download.

### MCP server (for agents)

`fulltext-mcp` exposes two tools, `get_paper(identifier, output_dir="", tools=None, supplements=False)` and `get_papers(identifiers, output_dir="", max_workers=4, supplements=False)`, returning the structure shown above. It needs the `mcp` extra and reads the same keys as the CLI. `FULLTEXT_OUTPUT_DIR` sets where files go when a call gives no output directory (default `./papers`).

Claude Code:

```bash
claude mcp add fulltext-article-downloader -- uvx --from "fulltext-article-downloader[mcp]" fulltext-mcp
```

Any other MCP client, in its server configuration:

```json
{
  "mcpServers": {
    "fulltext-article-downloader": {
      "command": "uvx",
      "args": ["--from", "fulltext-article-downloader[mcp]", "fulltext-mcp"],
      "env": { "UNPAYWALL_EMAIL": "you@example.org", "FULLTEXT_OUTPUT_DIR": "/abs/path/papers" }
    }
  }
}
```

`uvx` fetches the package from PyPI into an isolated environment on first use, so nothing needs to be installed beforehand. The server is also listed in the official MCP registry as `io.github.computron/fulltext-article-downloader`.

### Claude Code plugin and skill

This repository is also a Claude Code plugin. It installs a skill that teaches Claude when and how to use `fulltext-download`, plus the MCP server above:

```text
/plugin marketplace add computron/fulltext-article-downloader
/plugin install fulltext-article-downloader@fulltext-article-downloader
```

The skill alone (no MCP) is enough inside Claude Code: it runs the CLI and reads the JSON. The MCP server is for clients that cannot run shell commands, and for other agent frameworks.

---

## 4. Failures and tools

### Failure examples

Many articles are not open-access, and publishers explicitly restrict or discourage text and data mining. This example is expected to FAIL:

```bash
fulltext-download 10.1109/GROUP4.2007.4347715 -o papers
```

The `error` field lists every route tried and why it failed. A failure almost always means the article is paywalled with no open-access copy, or that a host blocked automated access.

If you see an error like ``Failed to load APS cookies``, please make sure you are running Python using an application that has full disk access.

### Verification

A file that starts with `%PDF-` is not proof of anything: open-access indexes occasionally map a DOI to an unrelated document, and a supporting-information file can carry the article's title. After every route the package extracts the first two pages and checks that the Crossref title is there, rejects files that open with a Supporting Information heading, and rejects Elsevier XML records that contain no body text. A rejected file is deleted and the next route is tried. `--no-check` / `check=False` turns this off.

### Methods and fallback logic

The tool is composed of multiple sub-tools intended to support various publishers. The tool order depends on the publisher.

| Publisher / source | Default tool order |
| ------------------ | ------------------ |
| Elsevier           | `unpaywall` → `elsevier` (PDF when entitled, else XML) → `europepmc` → `osti` → `semantic` |
| Springer / Nature  | `springerpdf` (nature.com, SpringerLink) → `unpaywall` → `europepmc` → `springeropen` (XML) → `osti` → `semantic` |
| Wiley              | `wiley` → `unpaywall` → `europepmc` → `osti` → `semantic` |
| APS                | `aps` → `unpaywall` → `crossref_tdm` → `europepmc` → `osti` → `semantic` |
| ACS, RSC, AIP      | `unpaywall` → `europepmc` → `crossref_tdm` → `osti` → `semantic` |
| PLOS               | `plos` → `unpaywall` |
| eLife              | `elife` → `unpaywall` |
| Cambridge          | `cambridge` → `unpaywall` → `europepmc` → `osti` → `semantic` |
| arXiv              | `arxiv` → `unpaywall` |
| ChemRxiv           | `chemrxiv` → `paperscraper` → `unpaywall` |
| bioRxiv, medRxiv   | `biorxiv` → `unpaywall` → `paperscraper` |
| MDPI               | `mdpi` → `unpaywall` → `europepmc` → `semantic` |
| Zenodo             | `zenodo` |
| Others             | `unpaywall` → `europepmc` → `crossref_tdm` → `osti` → `semantic` → `elsevier` |

arXiv, PMC and OpenReview ids go straight to `arxiv`, `pmc` and `openreview`. `pmc` fetches Europe PMC's PDF render and, when that endpoint refuses (it throttles hosts that ask for many articles in a row), the full-text JATS XML from Europe PMC's REST service or from NCBI's efetch, which also serves author manuscripts (`NCBI_API_KEY` is optional and raises NCBI's rate limit).

What the less obvious tools do:

* `elsevier` asks for the PDF first and keeps it only when the API key is entitled to the full PDF; Elsevier otherwise answers with HTTP 200 and a PDF containing only the article's first page, so the tool discards that and takes the full-text XML instead, writing a markdown rendering next to it. Abstract-only XML is rejected. The returned path always carries the extension of the format actually written.
* `crossref_tdm` tries every full-text link registered with Crossref, including the `unspecified` content-type links that APS, ACS and RSC use; they return the PDF on an entitled network.
* `europepmc` downloads PMC-hosted open-access articles and the repository copies (usually author manuscripts) listed in Europe PMC's record for the DOI. When the record says the article's full text is in PMC (author manuscripts deposited under funder mandates), it takes the PMC copy: the PDF render, or the JATS XML when that endpoint refuses.
* `osti` queries the OSTI API for the DOI and downloads the accepted manuscript that DOE-funded articles receive on osti.gov about a year after publication. It needs no credentials; records still under embargo have no full text and the tool moves on.
* `semantic` downloads the open-access PDF Semantic Scholar has indexed for the DOI, mostly arXiv and institutional-repository copies of subscription articles.
* `unpaywall` and `semantic` also accept repository landing pages: when an index lists the page rather than the file (HAL, DSpace, Columbia Academic Commons), the tool reads the `citation_pdf_url` tag the page carries for Google Scholar and downloads that.
* `chemrxiv` goes through the Cambridge Open Engage API, which works from hosts that chemrxiv.org itself blocks. The API resolves only the DOI of an item's latest version, so a base DOI or an older version is retried with the version suffixes.
* `biorxiv` asks the bioRxiv API which server (bioRxiv or medRxiv) holds the DOI and which version is current, then fetches that PDF. Requests are paced (the site answers 429 with a 100 s Retry-After after a burst) and the transient 503s it returns are retried; when the API itself is throttling, the unversioned URL, which redirects to the current version, is tried on both servers.
* `mdpi` builds the article's path on MDPI's CDN (`mdpi-res.com`) from the Crossref record; www.mdpi.com itself refuses requests from cloud-provider address ranges.
* `zenodo` downloads the PDF attached to a Zenodo record (10.5281 DOIs); a concept DOI resolves to the latest version.
* `wiley` is also used for society journals hosted on Wiley Online Library (AGU and others): Crossref lists their full-text links on wiley.com, and the TDM API serves them. Likewise `elsevier` is added for journals whose Crossref links point at Elsevier, and it closes the default list because Elsevier's API also serves society journals it distributes (ASH's Blood) under their own publisher name; a non-Elsevier DOI costs one quick 404.
* `semantic` also downloads the arXiv version named in a record's `externalIds` when the record lists no PDF, and with `SEMANTIC_SCHOLAR_API_KEY` searches by title for a second record of the same paper (the search endpoint answers 429 without a key). Requests are spaced one second apart, Semantic Scholar's limit.

Downloads send a browser User-Agent, retry with a plain one for repositories that serve PDFs only to non-browser clients, and, with the `tls` extra, once more with a Chrome TLS fingerprint. Wiley requests are paced to 30 per 10 minutes (the published limit is 60, but the API answers HTTP 500 from about 35 on), Crossref requests to its polite-pool limit, and transient 429/5xx responses are retried once.

Routes that return preprints or accepted manuscripts (`arxiv`, `chemrxiv`, `biorxiv`, `osti`, `semantic`, repository copies from `unpaywall` and `europepmc`) set `note` in the result. See ``PUBLISHER_TOOL_MAP`` in ``downloader.py``.

> **Tip** – Scraping-based methods (`springerpdf`, `elife`, `cambridge`, etc.) can break if sites change layout or due to access limits; favour official APIs and Unpaywall for large-scale downloads.

### Regression set

`benchmark/` holds 178 identifiers with known outcomes and a runner for checking a release candidate:
`python benchmark/run_regression.py` prints how many of the `known_good`, `needs_institution` and `expected_fail`
identifiers downloaded and exits non-zero when a `known_good` one failed. See `benchmark/README.md`.

### Customising the tool sequence

```python
from fulltext_article_downloader import fetch
fetch("10.1017/S0885715624000484", "papers", tools=["unpaywall", "cambridge"])  # override default order
```

### Override at runtime:

```python
from fulltext_article_downloader import PUBLISHER_TOOL_MAP
PUBLISHER_TOOL_MAP["Elsevier BV"] = ["elsevier", "unpaywall"]
```

---

## 5. License and Disclaimer.

BSD 3-Clause. See the `LICENSE` file.

Use this tool **only** for content you are legally entitled to access. Respect publisher terms and copyright laws. It does not use Sci-Hub or any similar site, and retrieves only what your own subscriptions, API keys and open-access licenses already permit; the optional `tls` and `aps` routes present your requests as a browser would, as described under Installation. The authors are **not** responsible for misuse.

Speed-coded by computron on vibes (ChatGPT 4.0) and caffeine; extended by Xu Huang with Claude.

---
name: fulltext-download
description: Download the full text of a research article (PDF, or XML with a markdown rendering when that is all the publisher allows) from a DOI, arXiv id, PubMed Central id or OpenReview id, using the fulltext-article-downloader package. Use when a task needs the actual paper rather than an abstract, for example to read the methods, check a number, quote a passage, or extract data. Needs the package installed; paywalled publishers additionally need the user's API keys or a campus network.
---

# Downloading a paper's full text

This skill wraps the `fulltext-download` command from the `fulltext_article_downloader` package. Given an identifier, the package tries sources in a fixed order and stops at the first one that returns a real file: the publisher's text-and-data-mining API when a key is configured, links registered with Crossref, open-access copies via Unpaywall and Europe PMC, the preprint servers' own APIs (arXiv, ChemRxiv, bioRxiv/medRxiv), MDPI's CDN, OSTI for DOE-funded work, and Semantic Scholar's open-access index for preprints and author manuscripts. Every PDF is checked against the paper's title and rejected if it is a different document or a supporting-information file.

Accepted identifiers: a DOI in any form (`10.1021/jacs.3c13302`, `https://doi.org/...`, `doi:...`), an arXiv id or URL (`2310.19377`, `arXiv:2310.19377`, `cond-mat/9712061`), a PubMed Central id (`PMC6561843`), or an OpenReview id. If you only have a title, find the DOI first (Crossref, Semantic Scholar, or a web search), then come back here.

## Before the first download

Check that the command exists:

```bash
fulltext-download --help
```

If it is missing, install the package:

```bash
pip install fulltext-article-downloader
```

Then check which credentials are configured. They come from environment variables or from `~/.fulltext_keys`, which `fulltext-config` writes interactively:

| Variable | What it unlocks |
|---|---|
| `UNPAYWALL_EMAIL` | Open-access lookups and Crossref's faster request pool. Any real email; set this at minimum. |
| `WILEY_API_KEY` | Wiley journals (paywalled full text if the token is entitled) |
| `ELSEVIER_API_KEY` | Elsevier journals (full PDF on an entitled network; otherwise XML or nothing) |
| `SPRINGER_API_KEY` | Springer Nature open-access XML |
| `SEMANTIC_SCHOLAR_API_KEY` | Optional; raises the Semantic Scholar rate limit and enables the title search that finds arXiv copies of closed papers |

Do not ask the user to paste keys into the chat. If a key is missing, say which source it would unlock and let them run `fulltext-config` themselves. Without keys, and off campus, expect open-access papers and DOE-funded manuscripts to work and most paywalled ones to fail.

## Downloading

One or several identifiers, any mix of forms:

```bash
fulltext-download 10.1021/jacs.3c13302 arXiv:1710.10324 PMC6561843 -o ./papers
```

The command prints one JSON object per identifier and exits 0 only if all of them succeeded:

```json
{"identifier": "10.1021/jacs.3c13302", "success": true,
 "path": "papers/10.1021_jacs.3c13302.pdf", "source": "osti",
 "note": "OSTI accepted manuscript, not the publisher's version of record",
 "error": null, "attempts": [], "supplements": []}
```

- `path` is the file. Files are named after the identifier with `/` replaced by `_`.
- `source` is the route that worked.
- `note`, when present, means the file is not the publisher's version of record (a preprint or accepted manuscript). Say so whenever you cite or quote from it.
- A `.xml` path means Elsevier or Springer full text as XML; a markdown rendering with the same name and `.md` is written next to it. The text is complete and quotable, but figures and rendered equations are not there. Tell the user when you are working from it.

Several identifiers download concurrently (`--workers`, default 4). Keep it at 6 or below and never run two batches at once: publisher APIs rate-limit per key, and Wiley answers every request with HTTP 500 once its quota (about 35 requests per 10 minutes; the package paces itself to 30) is spent. If you see Wiley errors mentioning 500, wait ten minutes rather than retrying in a loop.

`--tools unpaywall,osti` restricts or reorders the routes for one call, for example to skip publisher APIs when the user has no keys. `--no-check` disables the title verification; only use it when the user asks. `--supplements` also fetches the supplementary files (supporting information, data tables, videos) next to the article as `<name>_si1.<ext>`, ... and lists them in `supplements`; use it when the user needs the SI or the methods and data it holds.

## When it fails

`success` is false and `error` lists every route tried with its reason. A failure almost always means one of two things:

1. The paper is paywalled and no open-access copy exists. Nothing in this package will change that; only an entitled key or a campus network will.
2. A host blocked the request. Some publisher and repository sites reject automated clients or cloud IP ranges.

What to do next, in order:

- If the task needs verbatim text from the published version, stop and ask the user for the PDF. Do not substitute a summary from a web page for the paper.
- Otherwise, a preprint found by title on arXiv or a repository can serve for understanding the work; download it by its own identifier and say clearly that it is a preprint.
- Do not use Sci-Hub, LibGen, or any site that redistributes papers without the publisher's permission, and do not try to get around access controls.

## From Python

The same function is available in code, which is what the MCP server also calls:

```python
from fulltext_article_downloader import fetch, fetch_many

r = fetch("10.1103/PhysRevB.54.11169", "papers")          # one result dict, as above
rs = fetch_many(["10.1021/jacs.3c13302", "2310.19377"], "papers", workers=4)
```

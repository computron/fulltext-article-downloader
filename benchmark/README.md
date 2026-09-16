# Regression set

178 identifiers in three groups, drawn from a larger benchmark run made from a network without subscriptions. Each
row carries `id`, `group`, `expected`, `publisher`, and for the two failure groups a `reason`.

- `known_good` (56): download from any network, spread over the package's routes and identifier types. A failure is a regression.
- `needs_institution` (101): closed articles the publisher refused from an unsubscribed address. For Elsevier and Wiley
  the API answers without entitlement (API keys alone do not grant access; entitlement follows the network); for
  Springer Nature the site serves a paywall page; ACS, RSC, AIP, AAAS, IOP, JAMA, NEJM, SAGE, Taylor & Francis and a
  few others answer 403 or an HTML page to a datacenter client even for open articles, so whether a subscribed campus
  address unlocks them is what a campus run tells. Reported, never a failure; after a campus run, move whatever still
  fails there to `expected_fail`.
- `expected_fail` (21): nothing in the package can reach these: no PDF link from Crossref or Unpaywall, IEEE's
  staging host, a malformed link, a cover-page stub. A success here is a gain; check the file is
  the right article before updating the expectation.

    pip install fulltext-article-downloader
    export UNPAYWALL_EMAIL=you@example.org        # plus ELSEVIER_API_KEY, WILEY_API_KEY, SPRINGER_API_KEY, SEMANTIC_SCHOLAR_API_KEY if you have them
    python run_regression.py                      # about six minutes; exit code 1 on a regression; report in regression_out/report.json

A failed `known_good` item is tried once more at the end, so a transient outage of one source does not fail the run.
Per-source pacing (Wiley, bioRxiv, Semantic Scholar) is in-process, so the default six workers stay inside every quota;
one run makes six Wiley TDM requests (quota about 30 per ten minutes for each key) and three bioRxiv requests. Run one
instance at a time; several runs within an hour from the same address can make bioRxiv answer 429 for a while.
OpenReview is not in the set because openreview.net refuses cloud-provider addresses; test it by hand from a laptop.

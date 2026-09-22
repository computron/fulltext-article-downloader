# Regression set

178 identifiers in three groups. They come from a larger benchmark run made from a network without subscriptions,
and the two failure groups were then sorted by a run from a subscribed campus network (LBL, 2026-09-17). Each row
carries `id`, `group`, `expected`, `publisher`, a `reason` for the two failure groups, and `campus_run` where the
campus run unlocked it.

- `known_good` (56): download from any network, spread over the package's routes and identifier types. `route` records
  which route produced the file in the original run; any route counts. A failure is a regression.
- `needs_institution` (34): closed articles that fail from an unsubscribed address and that the campus run unlocked:
  Elsevier (API entitlement follows the network; the key alone does not grant access), Wiley (same), Springer Nature
  and Project MUSE (the site serves the PDF to a subscribed address), one University of Chicago Press item. Reported,
  never a failure.
- `expected_fail` (88): nothing in the package reaches these, from the campus address either. ACS, RSC, AIP, AAAS,
  IOP, JAMA, NEJM, SAGE, Taylor & Francis and a few others refuse a scripted client whatever the address; the rest
  have no PDF link from Crossref or Unpaywall, sit behind IEEE's staging host, or are a malformed link or a
  cover-page stub. A success here is a gain; check the file is the right article before updating the expectation.

    pip install fulltext-article-downloader
    export UNPAYWALL_EMAIL=you@example.org        # plus ELSEVIER_API_KEY, WILEY_API_KEY, SPRINGER_API_KEY, SEMANTIC_SCHOLAR_API_KEY if you have them
    python run_regression.py --label "where you ran it"   # about six minutes; exit code 1 on a regression; report in regression_out/report.json

Before the run the Elsevier key is tried on one closed article; a key that is missing, rejected or unreachable skips
the known_good items that depend on it (and the Wiley ones when that key is missing), and the report says so.
A failed `known_good` item is tried once more at the end, so a transient outage of one source does not fail the run.
`report.json` carries a provenance block (package version, commit, date, label, which keys were configured), the full
error text of every failed identifier, and `failure_signatures`: per group and publisher, which host answered what.

Per-source pacing (Wiley, bioRxiv, Semantic Scholar) is in-process, so the default six workers stay inside every quota;
one run makes six Wiley TDM requests (quota about 30 per ten minutes for each key) and three bioRxiv requests. Run one
instance at a time; several runs within an hour from the same address can make bioRxiv answer 429 for a while.
OpenReview is not in the set because openreview.net refuses cloud-provider addresses; test it by hand from a laptop.

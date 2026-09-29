# Regression set

178 identifiers with known outcomes, in three groups:

- `known_good` (56): download from any network. A failure is a regression.
- `needs_institution` (34): closed articles that a subscribed network unlocks. Reported, never a failure.
  `unlocked` lists the campus runs in which the item downloaded.
- `expected_fail` (88): the package does not reach these from any network tested; `reason` says why
  (a bot-protection challenge, no PDF link, and so on). A success is a gain: check the file, then update the row.

```
pip install fulltext-article-downloader
python run_regression.py --label "where you ran it"
```

Keys are read from the environment or `~/.fulltext_keys`. `UNPAYWALL_EMAIL` is required. Items that need an
Elsevier or Wiley key are skipped when the key is missing or rejected. A run takes about six minutes, exits 1 on a
regression, and writes `regression_out/report.json`.

Counts vary by a few items between runs, because what publisher sites serve to automated clients and what an
institution subscribes to both change over time. A `known_good` item that a site declines to serve is listed, not
counted as a regression.

Run one instance at a time. Several runs within an hour from the same address can make bioRxiv answer 429.

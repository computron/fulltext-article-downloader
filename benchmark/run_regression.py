"""Regression check for fulltext-article-downloader.

Runs the identifiers in regression_ids.json and compares each outcome with its group:

  known_good         must download; a failure is a regression
  needs_institution  closed articles a subscribed network unlocks; reported only
  expected_fail      not reachable; a success is a gain

  python run_regression.py [--workers 6] [--out regression_out] [--label "network"]

Exit code 1 when a known_good identifier fails for a reason other than a
bot-protection challenge. Writes <out>/report.json.
"""
import argparse, collections, datetime, json, os, re, subprocess, sys, time
from concurrent.futures import ThreadPoolExecutor

from fulltext_article_downloader import fetch

HERE = os.path.dirname(os.path.abspath(__file__))
KEY_FOR_ROUTE = {"elsevier": "ELSEVIER_API_KEY", "wiley": "WILEY_API_KEY"}
ELSEVIER_PROBE = "10.1016/j.nanoen.2019.03.005"  # a closed article


def provenance(label):
    try:
        from importlib.metadata import version
        pkg = version("fulltext-article-downloader")
    except Exception:
        pkg = "unknown"
    try:
        commit = subprocess.run(["git", "-C", HERE, "rev-parse", "--short", "HEAD"], capture_output=True, text=True, timeout=10).stdout.strip() or None
    except Exception:
        commit = None
    return {"package_version": pkg, "commit": commit, "date": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
            "label": label, "keys_configured": sorted(k for k in ("ELSEVIER_API_KEY", "WILEY_API_KEY", "SPRINGER_API_KEY", "SEMANTIC_SCHOLAR_API_KEY") if os.getenv(k))}


def elsevier_key_usable(papers):
    """None when no key is set; True when the key is accepted (entitled or not); otherwise the reason it is unusable."""
    if not os.getenv("ELSEVIER_API_KEY"):
        return None
    r = fetch(ELSEVIER_PROBE, papers, tools=["elsevier"], skip_existing=False)
    err = r["error"] or ""
    if r["success"] or "abstract-only" in err or "AUTHORIZATION_ERROR" in err or "not entitled" in err:
        return True
    return err.split("elsevier: ")[-1][:200]


def signature(error):
    """Compact description of why an identifier failed: host and status of each publisher-side attempt."""
    sigs = []
    for m in re.finditer(r"https?://([^/\s]+)\S*\s*(?:\(status code: (\d+)\)|returned non-PDF content)", error):
        sigs.append(f"{m.group(1)} {m.group(2) or 'html'}")
    for m in re.finditer(r"https?://([^/\s]+)\S* is behind an? (.+?) bot-protection challenge", error):
        sigs.append(f"{m.group(1)} {m.group(2)} challenge")
    if "abstract-only" in error: sigs.append("elsevier abstract-only")
    if "not followed" in error: sigs.append("redirect refused")
    return sorted(set(sigs)) or ["no publisher link tried"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--out", default="regression_out")
    ap.add_argument("--label", default="", help="free text describing the network, kept in the report")
    a = ap.parse_args()
    rows = json.load(open(os.path.join(HERE, "regression_ids.json")))
    if not os.getenv("UNPAYWALL_EMAIL"):
        sys.exit("UNPAYWALL_EMAIL is not set (environment or ~/.fulltext_keys); the unpaywall route needs it")
    papers = os.path.join(a.out, "papers"); os.makedirs(papers, exist_ok=True)
    t0 = time.time()

    unusable = {}
    els = elsevier_key_usable(papers)
    if els not in (None, True):
        unusable["ELSEVIER_API_KEY"] = els
        print(f"ELSEVIER_API_KEY is set but not accepted ({els}); Elsevier items are skipped")
    skipped = [r for r in rows if r["group"] == "known_good" and KEY_FOR_ROUTE.get(r.get("route"))
               and (not os.getenv(KEY_FOR_ROUTE[r["route"]]) or KEY_FOR_ROUTE[r["route"]] in unusable)]
    if skipped:
        print(f"skipping {len(skipped)} known_good items whose key is missing or not accepted:", sorted({KEY_FOR_ROUTE[r["route"]] for r in skipped}))
        rows = [r for r in rows if r not in skipped]

    def one(r):
        t = time.time(); res = fetch(r["id"], papers, skip_existing=False)
        return {**r, "success": res["success"], "source": res["source"], "note": res["note"], "error": res["error"] or "", "seconds": round(time.time() - t, 1)}

    with ThreadPoolExecutor(max_workers=a.workers) as pool:
        results = list(pool.map(one, rows))
    # retry failed known_good items once
    for i, r in enumerate(results):
        if r["group"] == "known_good" and not r["success"]:
            time.sleep(30); results[i] = {**one(rows[i]), "retried": True}
    by = collections.defaultdict(list)
    for r in results:
        by[r["group"]].append(r)
    failed = [r for r in by["known_good"] if not r["success"]]
    blocked = [r for r in failed if "bot-protection challenge" in r["error"]]  # the site's doing, not ours
    regressions = [r for r in failed if r not in blocked]
    gains = [r for r in by["expected_fail"] if r["success"]]
    unlocked = [r for r in by["needs_institution"] if r["success"]]
    signatures = collections.defaultdict(lambda: collections.defaultdict(collections.Counter))
    for r in results:
        if not r["success"]:
            for s in signature(r["error"]):
                signatures[r["group"]][r["publisher"]][s] += 1
    report = {"provenance": provenance(a.label), "elapsed_s": round(time.time() - t0),
              "skipped_for_missing_keys": [r["id"] for r in skipped], "keys_not_accepted": unusable,
              "counts": {g: f"{sum(r['success'] for r in rs)}/{len(rs)}" for g, rs in by.items()},
              "regressions": [{"id": r["id"], "error": r["error"]} for r in regressions],
              "blocked_by_bot_protection": [r["id"] for r in blocked],
              "unlocked_with_institution": [{"id": r["id"], "source": r["source"], "publisher": r["publisher"], "reason": r.get("reason")} for r in unlocked],
              "gains_in_expected_fail": [{"id": r["id"], "source": r["source"]} for r in gains],
              "failure_signatures": {g: {p: dict(c) for p, c in ps.items()} for g, ps in signatures.items()},
              "results": results}
    json.dump(report, open(os.path.join(a.out, "report.json"), "w"), indent=1)
    for g in ("known_good", "needs_institution", "expected_fail"):
        print(f"{g:18s} {report['counts'].get(g, '0/0')}")
    if unlocked:
        print(f"unlocked with institutional access: {len(unlocked)} ({collections.Counter(r['publisher'] for r in unlocked).most_common()})")
    if gains:
        print("expected_fail items that now download (update the expectation):", [r["id"] for r in gains])
    for g in ("needs_institution", "expected_fail"):
        for pub, c in sorted(signatures[g].items()):
            print(f"  {g} {pub}: " + ", ".join(f"{s} x{n}" for s, n in c.most_common(3)))
    if blocked:
        print("known_good items behind a bot-protection challenge today:", [r["id"] for r in blocked])
    if regressions:
        print("REGRESSIONS:", [r["id"] for r in regressions]); sys.exit(1)
    print("no regressions")


if __name__ == "__main__":
    main()

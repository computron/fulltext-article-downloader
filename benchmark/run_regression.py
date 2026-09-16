"""Pre-release regression check for fulltext-article-downloader.

Runs the identifiers in regression_ids.json (three groups) and compares the outcome with
what is expected:

  known_good         must download from any network; a failure here is a regression
  needs_institution  closed articles a subscribed campus network is expected to unlock;
                     reported, never a failure
  expected_fail      nothing in the package can reach these; a success here is a gain and
                     the expectation should be updated

  python run_regression.py [--workers 6] [--out regression_out]

Failed known_good identifiers are tried a second time, sequentially, before being
reported. Exit code 1 when one still fails. Writes <out>/report.json.
"""
import argparse, collections, json, os, sys, time
from concurrent.futures import ThreadPoolExecutor

from fulltext_article_downloader import fetch

HERE = os.path.dirname(os.path.abspath(__file__))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--out", default="regression_out")
    a = ap.parse_args()
    rows = json.load(open(os.path.join(HERE, "regression_ids.json")))
    papers = os.path.join(a.out, "papers"); os.makedirs(papers, exist_ok=True)
    t0 = time.time()

    def one(r):
        t = time.time(); res = fetch(r["id"], papers, skip_existing=False)
        return {**r, "success": res["success"], "source": res["source"], "note": res["note"], "error": (res["error"] or "")[:300], "seconds": round(time.time() - t, 1)}

    with ThreadPoolExecutor(max_workers=a.workers) as pool:
        results = list(pool.map(one, rows))
    # a second, sequential try for failed known_good items so a transient outage is not reported as a regression
    for i, r in enumerate(results):
        if r["group"] == "known_good" and not r["success"]:
            time.sleep(30); results[i] = {**one(rows[i]), "retried": True}
    by = collections.defaultdict(list)
    for r in results:
        by[r["group"]].append(r)
    regressions = [r for r in by["known_good"] if not r["success"]]
    gains = [r for r in by["expected_fail"] if r["success"]]
    unlocked = [r for r in by["needs_institution"] if r["success"]]
    report = {"elapsed_s": round(time.time() - t0), "counts": {g: f"{sum(r['success'] for r in rs)}/{len(rs)}" for g, rs in by.items()},
              "regressions": [{"id": r["id"], "error": r["error"]} for r in regressions],
              "unlocked_with_institution": [{"id": r["id"], "source": r["source"], "publisher": r["publisher"], "reason": r.get("reason")} for r in unlocked],
              "gains_in_expected_fail": [{"id": r["id"], "source": r["source"]} for r in gains],
              "results": results}
    json.dump(report, open(os.path.join(a.out, "report.json"), "w"), indent=1)
    for g in ("known_good", "needs_institution", "expected_fail"):
        print(f"{g:18s} {report['counts'].get(g, '0/0')}")
    if unlocked:
        print(f"unlocked with institutional access: {len(unlocked)} ({collections.Counter(r['publisher'] for r in unlocked).most_common()})")
    if gains:
        print("expected_fail items that now download (update the expectation):", [r["id"] for r in gains])
    if regressions:
        print("REGRESSIONS:", [r["id"] for r in regressions]); sys.exit(1)
    print("no regressions")


if __name__ == "__main__":
    main()

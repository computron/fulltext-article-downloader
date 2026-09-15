"""Command-line entry point.

    fulltext-download <id> [<id> ...] [-o DIR] [--tools a,b] [--workers N]

Prints one JSON object per identifier (the same structure the MCP tools and
`fetch()` return) and exits 0 when every download succeeded. The original
form `fulltext-download <doi> <output_dir> [<filename>]` still works.
"""
import argparse
import json
import os
import sys

from . import identifiers
from .downloader import DEFAULT_TOOLS, TOOL_FUNCTIONS, fetch, fetch_many


def _is_identifier(value: str) -> bool:
    try:
        identifiers.parse(value)
        return True
    except ValueError:
        return False


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="fulltext-download",
        description="Download the full text of research articles by DOI, arXiv id, PMC id or OpenReview id.")
    parser.add_argument("items", nargs="+", metavar="ID",
                        help="identifiers; the legacy form ID OUTPUT_DIR [FILENAME] is also accepted")
    parser.add_argument("-o", "--output-dir", default="papers", help="where files go (default: ./papers)")
    parser.add_argument("--filename", help="explicit file name (single identifier only)")
    parser.add_argument("--tools", help=f"comma-separated tool order, e.g. unpaywall,osti; known: {', '.join(TOOL_FUNCTIONS)}")
    parser.add_argument("--workers", type=int, default=4, help="concurrent downloads (default 4)")
    parser.add_argument("--no-check", action="store_true", help="skip title / supporting-information verification")
    parser.add_argument("--supplements", action="store_true", help="also fetch supplementary files, saved next to the article as <name>_si1.<ext>, ...")
    parser.add_argument("--log-file", help="append a download log to this file")
    args = parser.parse_args(argv)

    items = list(args.items)
    # Legacy positional form: ID OUTPUT_DIR [FILENAME]
    if len(items) >= 2 and _is_identifier(items[0]) and (os.path.isdir(items[1]) or not _is_identifier(items[1])):
        args.output_dir = items[1]
        if len(items) == 3 and not _is_identifier(items[2]):
            args.filename = items[2]
        items = items[:1]
    tools = args.tools.split(",") if args.tools else None
    unknown = [t for t in tools or [] if t not in TOOL_FUNCTIONS]
    if unknown:
        parser.error(f"unknown tools: {', '.join(unknown)}")

    if len(items) == 1:
        results = [fetch(items[0], args.output_dir, output_filename=args.filename, tools=tools,
                         log_file=args.log_file, check=not args.no_check, supplements=args.supplements)]
    else:
        if args.filename:
            parser.error("--filename only applies to a single identifier")
        results = list(fetch_many(items, args.output_dir, workers=args.workers, tools=tools,
                                  log_file=args.log_file, check=not args.no_check, supplements=args.supplements).values())
    print(json.dumps(results, indent=1))
    sys.exit(0 if all(r["success"] for r in results) else 1)


if __name__ == "__main__":
    main()

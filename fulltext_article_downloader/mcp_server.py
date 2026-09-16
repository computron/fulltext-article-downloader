"""MCP server exposing the downloader to agents.

    fulltext-mcp            # stdio transport, for Claude Code, Claude Desktop, Cursor, ...

Needs the `mcp` extra: pip install "fulltext-article-downloader[mcp]".
Credentials come from the environment or ~/.fulltext_keys exactly as for the
CLI. FULLTEXT_OUTPUT_DIR sets where files go when a call gives no output_dir
(default ./papers under the server's working directory).
"""
import os
import sys

from .downloader import TOOL_FUNCTIONS, fetch, fetch_many


def _output_dir(output_dir: str) -> str:
    return output_dir.strip() or os.environ.get("FULLTEXT_OUTPUT_DIR") or "papers"


def get_paper(identifier: str, output_dir: str = "", tools: list[str] | None = None, supplements: bool = False) -> dict:
    """Download the full text of one paper.

    identifier: a DOI (bare, doi:, or doi.org URL), an arXiv id or URL, a
    PubMed Central id (PMC1234567) or an OpenReview id. If you only have a
    title, find the DOI first.

    Returns {"success", "path", "source", "note", "error", "attempts"}.
    `path` is the downloaded file: a PDF, or for some Elsevier/Springer routes
    an XML file with a markdown rendering saved next to it (text only, no
    figures). `note` is set when the file is not the publisher's version of
    record (preprint, accepted manuscript): repeat that caveat when you cite
    it. On failure `error` lists every route tried; a failure means the paper
    is paywalled with no open-access copy, or a host blocked the request.
    Then look for a preprint by title, or ask the user for the PDF.

    tools: optional list of route names to try instead of the publisher
    default, e.g. ["unpaywall", "osti"].
    supplements: also fetch the supplementary files (supporting information,
    data tables, videos), saved next to the article as <name>_si1.<ext>, ...
    and listed in `supplements`. Off by default; turn it on when the user
    needs the SI or the methods and data it holds.
    """
    return fetch(identifier, _output_dir(output_dir), tools=tools, supplements=supplements)


def get_papers(identifiers: list[str], output_dir: str = "", max_workers: int = 4, supplements: bool = False) -> dict:
    """Download several papers concurrently; returns {identifier: result} with
    the same result structure as get_paper. Use this instead of calling
    get_paper in a loop. Publisher rate limits are enforced across workers."""
    return fetch_many(identifiers, _output_dir(output_dir), workers=max_workers, supplements=supplements)


def build_server():
    try:
        from fastmcp import FastMCP
    except ImportError:
        sys.exit("fastmcp is not installed. Install the MCP extra: pip install 'fulltext-article-downloader[mcp]'")
    from . import __version__
    mcp = FastMCP("fulltext-article-downloader", version=__version__)
    mcp.tool(get_paper)
    mcp.tool(get_papers)
    return mcp


def main():
    build_server().run()


if __name__ == "__main__":
    main()

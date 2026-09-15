"""Parse the identifier forms people paste: DOIs, arXiv ids, PubMed Central ids
and OpenReview ids, with or without URL prefixes."""
import re

_ARXIV_ID = r"(\d{4}\.\d{4,5}(?:v\d+)?|[a-z-]+(?:\.[A-Z]{2})?/\d{7}(?:v\d+)?)"
_ARXIV_RE = re.compile(r"^(?:arxiv:|https?://arxiv\.org/(?:abs|pdf)/)?" + _ARXIV_ID + r"(?:\.pdf)?$", re.I)
_ARXIV_DOI_RE = re.compile(r"^10\.48550/arxiv\.(.+)$", re.I)
_DOI_RE = re.compile(r"^(?:https?://(?:dx\.)?doi\.org/|doi:)?(10\.\d{4,9}/\S+)$", re.I)
_PMC_RE = re.compile(
    r"^(?:https?://(?:www\.)?(?:pmc\.)?ncbi\.nlm\.nih\.gov/(?:pmc/)?articles/)?(PMC\d+)/?$", re.I)
# OpenReview ids are short random strings of mixed case ("fNyXCCZ0g6"). Requiring
# an upper-case letter after the first character keeps ordinary words and
# directory names ("downloads", "Papers") from being taken for ids.
_OPENREVIEW_RE = re.compile(r"^(?:https?://openreview\.net/(?:forum|pdf)\?id=)?([A-Za-z0-9_-]{8,20})$")
_OPENREVIEW_SHAPE = re.compile(r"^[A-Za-z0-9_-][A-Za-z0-9_-]*[A-Z][A-Za-z0-9_-]*$")


def parse(identifier: str):
    """Return (kind, value) with kind in {"doi", "arxiv", "pmc", "openreview"}.

    arXiv DOIs (10.48550/arXiv.<id>) come back as kind "arxiv". Raises
    ValueError for anything unrecognised.
    """
    s = (identifier or "").strip()
    m = _DOI_RE.match(s)
    if m:
        doi = m.group(1).rstrip(".,;)")
        am = _ARXIV_DOI_RE.match(doi)
        return ("arxiv", am.group(1)) if am else ("doi", doi)
    m = _ARXIV_RE.match(s)
    if m:
        return "arxiv", m.group(1)
    m = _PMC_RE.match(s)
    if m:
        return "pmc", m.group(1).upper()
    m = _OPENREVIEW_RE.match(s)
    if m and _OPENREVIEW_SHAPE.match(m.group(1)) and any(c.islower() for c in m.group(1)):
        return "openreview", m.group(1)
    raise ValueError(f"Not a DOI, arXiv id, PMC id or OpenReview id: {identifier!r}")


def safe_filename(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]", "_", value)

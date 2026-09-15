"""Checks that a downloaded file really is the article that was asked for.

Open-access indexes occasionally map a DOI to an unrelated document, and a
supporting-information file can carry the article's title, so a file that
starts with %PDF- is not proof of anything. These checks are cheap (two pages
of text extraction) and are applied by the downloader after every route.
"""
import re

_MARKUP = re.compile(r"<[^>]+>|&[a-z]+;|&#\d+;")
_WORD = re.compile(r"[a-z0-9]{3,}")
_SUPPORTING = re.compile(r"supporting information|supplementary (?:information|materials?|data|text|note)|electronic supplementary|reporting summary", re.I)
# Springer Nature supplements open with the article title and this cover line.
_NATURE_SI = re.compile(r"in\s+the\s+format\s+provided\s+by\s+the\s+authors", re.I)


def clean_title(title):
    """Crossref titles often contain MathML or HTML markup."""
    return _MARKUP.sub(" ", title or "")


def _words(text):
    return set(_WORD.findall(text.lower()))


def title_matches(text, title, threshold=0.6):
    """True when most title words appear in `text`. Matching is also tried on
    the text with all spacing removed, because PDF text extraction frequently
    splits words ("deliv er")."""
    wanted = _words(clean_title(title))
    if not wanted:
        return True
    by_word = len(wanted & _words(text)) / len(wanted)
    squashed = re.sub(r"[^a-z0-9]", "", text.lower())
    long_words = [w for w in wanted if len(w) >= 4] or list(wanted)
    by_substring = sum(w in squashed for w in long_words) / len(long_words)
    return max(by_word, by_substring) >= threshold


def check_pdf(path, title=None):
    """Return (ok, reason) for a PDF on disk.

    Fails for unreadable files, for files whose first page opens with a
    Supporting Information heading, and, when `title` is given, for files
    whose first two pages do not contain the title. A PDF without a text layer
    (a scan) passes, since nothing can be checked.
    """
    try:
        from pypdf import PdfReader
    except ImportError:
        return True, "pypdf not installed, check skipped"
    try:
        reader = PdfReader(path, strict=False)
        pages = len(reader.pages)
        text = " ".join((reader.pages[i].extract_text() or "") for i in range(min(2, pages)))
    except Exception as e:
        return False, f"unreadable PDF: {e}"
    if pages == 0:
        return False, "PDF has no pages"
    if _SUPPORTING.search(text.lstrip()[:250]) or _NATURE_SI.search(text[:800]):
        return False, "supporting information, not the article"
    if not text.strip():  # a scan; a text-less file of one or two pages is a cover or a stub
        return (True, "no text layer") if pages >= 3 else (False, "no text layer and fewer than three pages")
    if title and not title_matches(text, title):
        return False, "title not found in the first pages"
    return True, "ok"


def check_xml(path):
    """Full-text XML must carry body text. Elsevier answers abstract-only
    requests with a valid record that has no <ce:para> elements."""
    with open(path, "rb") as f:
        head = f.read(2_000_000)
    if b"<coredata>" in head and b"<ce:para" not in head and b"<xocs:rawtext" not in head:
        return False, "Elsevier XML has no body text (abstract-only entitlement)"
    if b"<article" in head and b"<body" not in head:
        return False, "JATS XML has no body"
    return True, "ok"

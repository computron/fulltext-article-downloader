"""CLI argument handling / JSON output, and the MCP wrappers (no network)."""
import asyncio
import json

import pytest

from fulltext_article_downloader import cli, mcp_server


def _ok(identifier, path="/tmp/x.pdf"):
    return {"identifier": identifier, "success": True, "path": path, "source": "unpaywall",
            "note": None, "error": None, "attempts": []}


def test_cli_single_identifier_prints_json(monkeypatch, capsys):
    seen = {}
    monkeypatch.setattr(cli, "fetch", lambda ident, out, **kw: seen.update(ident=ident, out=out, kw=kw) or _ok(ident))
    with pytest.raises(SystemExit) as e:
        cli.main(["10.1000/x", "-o", "/tmp/papers", "--tools", "unpaywall,osti"])
    assert e.value.code == 0
    assert seen["ident"] == "10.1000/x" and seen["out"] == "/tmp/papers" and seen["kw"]["tools"] == ["unpaywall", "osti"]
    out = json.loads(capsys.readouterr().out)
    assert out[0]["success"] and out[0]["source"] == "unpaywall"


def test_cli_legacy_positional_form(monkeypatch, capsys):
    seen = {}
    monkeypatch.setattr(cli, "fetch", lambda ident, out, **kw: seen.update(ident=ident, out=out, kw=kw) or _ok(ident))
    with pytest.raises(SystemExit):
        cli.main(["10.1000/x", "downloads", "custom.pdf"])
    assert seen["out"] == "downloads" and seen["kw"]["output_filename"] == "custom.pdf"


def test_cli_many_identifiers_use_fetch_many_and_exit_1_on_failure(monkeypatch, capsys):
    def fake_many(ids, out, **kw):
        return {ids[0]: _ok(ids[0]), ids[1]: {**_ok(ids[1]), "success": False, "path": None, "error": "paywalled"}}
    monkeypatch.setattr(cli, "fetch_many", fake_many)
    with pytest.raises(SystemExit) as e:
        cli.main(["10.1000/a", "arXiv:2401.00001", "--workers", "2"])
    assert e.value.code == 1
    out = json.loads(capsys.readouterr().out)
    assert [r["success"] for r in out] == [True, False]


def test_cli_rejects_unknown_tool(capsys):
    with pytest.raises(SystemExit) as e:
        cli.main(["10.1000/x", "--tools", "nosuchtool"])
    assert e.value.code == 2 and "unknown tools" in capsys.readouterr().err


def test_mcp_server_exposes_two_tools():
    pytest.importorskip("fastmcp")
    names = [t.name for t in asyncio.run(mcp_server.build_server().list_tools())]
    assert names == ["get_paper", "get_papers"]


def test_mcp_get_paper_uses_env_output_dir(monkeypatch):
    seen = {}
    monkeypatch.setattr(mcp_server, "fetch", lambda ident, out, tools=None, supplements=False: seen.update(out=out) or _ok(ident))
    monkeypatch.setenv("FULLTEXT_OUTPUT_DIR", "/data/papers")
    assert mcp_server.get_paper("10.1000/x")["success"] and seen["out"] == "/data/papers"
    mcp_server.get_paper("10.1000/x", output_dir="/elsewhere")
    assert seen["out"] == "/elsewhere"

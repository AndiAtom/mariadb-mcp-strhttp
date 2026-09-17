"""
Tests fuer die MCP-Spec-2026-07-28-Schicht (src/mcp_spec.py + POST /mcp).

Abgedeckt:
- server/discover (Pflicht-Methode)
- tools/list (deterministische Ordnung, ttlMs/cacheScope)
- tools/call (Header-Routing Mcp-Method/Mcp-Name, alle 5 Tools, DB gemockt)
- ping
- Header-Validierung: MCP-Protocol-Version vs. _meta (-32020),
  fehlende Header, unbekannte Version (-32022)
- Unbekannte Methode: HTTP 404 + -32601 (Era-Detection)
- Notifications: HTTP 202 ohne Body
- Base64-Sentinel-Dekodierung fuer Mcp-Name
- Tool-Fehler: isError=true, -32602 Invalid params
- Era-Detection am Endpunkt: Legacy-OWUI-Format bleibt intakt
"""

import base64
import json
import sys
import os

import pytest
from fastapi.testclient import TestClient

# Authentifizierung in Tests deaktivieren
os.environ["DISABLE_API_AUTH"] = "true"

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

import server
from server import app, db_connection

# Rate Limiting deterministisch
import rate_limiting
rate_limiting.rate_limit_config.enabled = False

PV = "2026-07-28"


def _meta():
    return {
        "io.modelcontextprotocol/protocolVersion": PV,
        "io.modelcontextprotocol/clientInfo": {"name": "pytest", "version": "1.0"},
        "io.modelcontextprotocol/clientCapabilities": {},
    }


def _rpc(method, params=None, req_id=1):
    p = dict(params or {})
    p["_meta"] = _meta()
    return {"jsonrpc": "2.0", "id": req_id, "method": method, "params": p}


def _headers(method, name=None):
    h = {
        "MCP-Protocol-Version": PV,
        "Mcp-Method": method,
        "Accept": "application/json, text/event-stream",
    }
    if name is not None:
        h["Mcp-Name"] = name
    return h


class _FakeCursor:
    def __init__(self, rows, columns):
        self._rows = rows
        self.description = [(c, None) for c in columns]
        self.rowcount = len(rows)

    def execute(self, *a, **kw):
        pass

    def fetchall(self):
        return self._rows

    def close(self):
        pass


@pytest.fixture
def client():
    return TestClient(app)


class TestDiscover:
    def test_discover(self, client):
        r = client.post("/mcp", json=_rpc("server/discover"), headers=_headers("server/discover"))
        assert r.status_code == 200
        body = r.json()
        assert body["jsonrpc"] == "2.0" and body["id"] == 1
        result = body["result"]
        assert result["supportedVersions"] == [PV]
        assert "tools" in result["capabilities"]
        assert result["_meta"]["io.modelcontextprotocol/serverInfo"]["name"] == "mariadb-mcp-strhttp"
        assert "instructions" in result
        assert "ttlMs" in result and "cacheScope" in result


class TestToolsList:
    def test_tools_list(self, client):
        r = client.post("/mcp", json=_rpc("tools/list"), headers=_headers("tools/list"))
        assert r.status_code == 200
        result = r.json()["result"]
        names = [t["name"] for t in result["tools"]]
        # Deterministische Ordnung: gleiche Reihenfolge wie in mcp_spec.TOOLS
        assert names == [t["name"] for t in __import__("mcp_spec").TOOLS]
        assert set(names) == {
            "execute_query", "validate_query", "list_tables",
            "list_databases", "get_table_schema",
        }
        assert result["ttlMs"] == 0
        assert result["cacheScope"] == "private"
        for t in result["tools"]:
            assert t["inputSchema"]["type"] == "object"


class TestPing:
    def test_ping(self, client):
        r = client.post("/mcp", json=_rpc("ping"), headers=_headers("ping"))
        assert r.status_code == 200
        assert r.json()["result"] == {}


class TestHeaderValidation:
    def test_missing_protocol_version_header(self, client):
        h = _headers("tools/list")
        del h["MCP-Protocol-Version"]
        r = client.post("/mcp", json=_rpc("tools/list"), headers=h)
        assert r.status_code == 400
        assert r.json()["error"]["code"] == -32020

    def test_header_body_version_mismatch(self, client):
        h = _headers("tools/list")
        h["MCP-Protocol-Version"] = "2025-11-25"
        r = client.post("/mcp", json=_rpc("tools/list"), headers=h)
        assert r.status_code == 400
        assert r.json()["error"]["code"] == -32020
        assert "does not match" in r.json()["error"]["message"]

    def test_missing_meta_version(self, client):
        req = _rpc("tools/list")
        del req["params"]["_meta"]["io.modelcontextprotocol/protocolVersion"]
        r = client.post("/mcp", json=req, headers=_headers("tools/list"))
        assert r.status_code == 400
        assert r.json()["error"]["code"] == -32020

    def test_unsupported_version(self, client):
        req = _rpc("tools/list")
        req["params"]["_meta"]["io.modelcontextprotocol/protocolVersion"] = "1999-01-01"
        h = _headers("tools/list")
        h["MCP-Protocol-Version"] = "1999-01-01"
        r = client.post("/mcp", json=req, headers=h)
        assert r.status_code == 400
        body = r.json()
        assert body["error"]["code"] == -32022
        assert body["error"]["data"]["supported"] == [PV]
        assert body["error"]["data"]["requested"] == "1999-01-01"

    def test_method_header_mismatch(self, client):
        h = _headers("tools/list")
        h["Mcp-Method"] = "tools/call"
        r = client.post("/mcp", json=_rpc("tools/list"), headers=h)
        assert r.status_code == 400
        assert r.json()["error"]["code"] == -32020

    def test_unknown_method_404(self, client):
        r = client.post("/mcp", json=_rpc("resources/list"), headers=_headers("resources/list"))
        assert r.status_code == 404
        assert r.json()["error"]["code"] == -32601


class TestNotifications:
    def test_notification_202(self, client):
        req = _rpc("notifications/initialized")
        del req["id"]
        r = client.post("/mcp", json=req, headers=_headers("notifications/initialized"))
        assert r.status_code == 202
        assert r.content == b""


class TestToolsCall:
    def test_validate_query_tool(self, client):
        r = client.post(
            "/mcp",
            json=_rpc("tools/call", {"name": "validate_query", "arguments": {"query": "SELECT 1"}}),
            headers=_headers("tools/call", name="validate_query"),
        )
        assert r.status_code == 200
        result = r.json()["result"]
        assert result["isError"] is False
        assert result["resultType"] == "complete"
        sc = result["structuredContent"]
        assert sc["valid"] is True
        assert result["content"][0]["type"] == "text"

    def test_execute_query_blocked_write(self, client):
        r = client.post(
            "/mcp",
            json=_rpc("tools/call", {"name": "execute_query", "arguments": {"query": "DELETE FROM x"}}),
            headers=_headers("tools/call", name="execute_query"),
        )
        assert r.status_code == 200
        result = r.json()["result"]
        assert result["isError"] is True
        assert "Schreiboperationen" in result["content"][0]["text"]

    def test_execute_query_success(self, client, monkeypatch):
        rows = [{"id": 1, "name": "andi"}]
        cols = ["id", "name"]

        def fake_exec(self, query, params=None, query_timeout=None, database=None):
            return {"success": True, "results": rows, "columns": cols,
                    "row_count": len(rows), "query": query}

        monkeypatch.setattr(type(db_connection), "execute_query", fake_exec)
        r = client.post(
            "/mcp",
            json=_rpc("tools/call", {"name": "execute_query", "arguments": {"query": "SELECT * FROM users"}}),
            headers=_headers("tools/call", name="execute_query"),
        )
        assert r.status_code == 200
        result = r.json()["result"]
        assert result["isError"] is False
        sc = result["structuredContent"]
        assert sc["row_count"] == 1
        assert sc["columns"] == cols

    def test_missing_mcp_name_header(self, client):
        r = client.post(
            "/mcp",
            json=_rpc("tools/call", {"name": "validate_query", "arguments": {"query": "SELECT 1"}}),
            headers=_headers("tools/call"),  # ohne Mcp-Name
        )
        assert r.status_code == 400
        assert r.json()["error"]["code"] == -32020

    def test_name_header_mismatch(self, client):
        r = client.post(
            "/mcp",
            json=_rpc("tools/call", {"name": "validate_query", "arguments": {"query": "SELECT 1"}}),
            headers=_headers("tools/call", name="execute_query"),
        )
        assert r.status_code == 400
        assert r.json()["error"]["code"] == -32020

    def test_name_header_base64_sentinel(self, client):
        name = "validate_query"
        encoded = "=?base64?" + base64.b64encode(name.encode()).decode() + "?="
        r = client.post(
            "/mcp",
            json=_rpc("tools/call", {"name": name, "arguments": {"query": "SELECT 1"}}),
            headers=_headers("tools/call", name=encoded),
        )
        assert r.status_code == 200
        assert r.json()["result"]["isError"] is False

    def test_unknown_tool_invalid_params(self, client):
        r = client.post(
            "/mcp",
            json=_rpc("tools/call", {"name": "no_such_tool", "arguments": {}}),
            headers=_headers("tools/call", name="no_such_tool"),
        )
        assert r.status_code == 200
        assert r.json()["error"]["code"] == -32602

    def test_missing_query_invalid_params(self, client):
        r = client.post(
            "/mcp",
            json=_rpc("tools/call", {"name": "validate_query", "arguments": {}}),
            headers=_headers("tools/call", name="validate_query"),
        )
        assert r.status_code == 200
        assert r.json()["error"]["code"] == -32602

    def test_get_table_schema(self, client, monkeypatch):
        rows = [{"Field": "id", "Type": "int", "Null": "NO", "Key": "PRI", "Default": None, "Extra": ""}]

        def fake_exec(self, query, params=None, query_timeout=None, database=None):
            return {"success": True, "results": rows, "columns": ["Field"], "row_count": 1, "query": query}

        monkeypatch.setattr(type(db_connection), "execute_query", fake_exec)
        r = client.post(
            "/mcp",
            json=_rpc("tools/call", {"name": "get_table_schema", "arguments": {"table": "users"}}),
            headers=_headers("tools/call", name="get_table_schema"),
        )
        assert r.status_code == 200
        sc = r.json()["result"]["structuredContent"]
        assert sc["table"] == "users"
        assert sc["columns"][0]["Field"] == "id"

    def test_system_database_blocked(self, client):
        r = client.post(
            "/mcp",
            json=_rpc("tools/call", {"name": "list_tables", "arguments": {"database": "mysql"}}),
            headers=_headers("tools/call", name="list_tables"),
        )
        assert r.status_code == 200
        assert r.json()["result"]["isError"] is True
        assert "nicht erlaubt" in r.json()["result"]["content"][0]["text"]


class TestEraDetection:
    def test_legacy_owui_format_untouched(self, client):
        """Legacy-Pfad: kein jsonrpc-Feld -> Open-WebUI-Format."""
        r = client.post("/mcp", json={"method": "validate_query", "params": {"query": "SELECT 1"}})
        assert r.status_code == 200
        assert r.json()["valid"] is True

    def test_legacy_direct_query_untouched(self, client, monkeypatch):
        def fake_exec(self, query, params=None, query_timeout=None, database=None):
            return {"success": True, "results": [{"1": 1}], "columns": ["1"], "row_count": 1, "query": query}

        monkeypatch.setattr(type(db_connection), "execute_query", fake_exec)
        r = client.post("/mcp", json={"query": "SELECT 1"})
        assert r.status_code == 200
        assert "result" in r.json()

    def test_invalid_jsonrpc_version_falls_to_legacy(self, client):
        r = client.post("/mcp", json={"jsonrpc": "1.0", "method": "x"})
        # Kein valider 2.0-Envelope -> Legacy-Pfad -> Unknown method
        assert r.status_code == 200
        assert r.json().get("error") == "Unknown method: x"


class TestUnitSpec:
    """Isolierte Unit-Tests ohne HTTP-Layer."""

    def test_decode_header_value_plain(self):
        import mcp_spec
        assert mcp_spec.decode_header_value("execute_query") == "execute_query"

    def test_decode_header_value_sentinel(self):
        import mcp_spec
        raw = "wörter táb lé"
        enc = "=?base64?" + base64.b64encode(raw.encode()).decode() + "?="
        assert mcp_spec.decode_header_value(enc) == raw

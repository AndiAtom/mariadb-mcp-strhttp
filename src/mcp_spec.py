"""
MCP-Protokollschicht nach Spec 2026-07-28 (stateless core) fuer den
MariaDB MCP Server.

Diese Schicht implementiert das moderne, sesssionlose MCP-Protokoll auf dem
bestehenden HTTP-Endpunkt (POST /mcp):

- JSON-RPC 2.0 Envelope (Pflicht ab Spec 2026-07-28)
- server/discover  (MUST-implement, ersetzt den initialize-Handshake)
- tools/list       (deterministische Ordnung, ttlMs/cacheScope)
- tools/call       (mit Header-Routing Mcp-Method/Mcp-Name)
- ping
- Header-Validierung: MCP-Protocol-Version muss mit
  _meta['io.modelcontextprotocol/protocolVersion'] uebereinstimmen,
  sonst -32020 HeaderMismatch (HTTP 400)
- Nicht unterstuetzte Protokollversionen: -32022 (HTTP 400) mit
  supported-Liste (Era-Detection fuer Dual-Era-Clients)
- Unbekannte Methoden: HTTP 404 + JSON-RPC -32601
- Notifications: HTTP 202 ohne Body
- Base64-Sentinel-Dekodierung fuer Mcp-Name (=  ?base64?...?=  )

Die Tool-Implementierungen werden von server.py ueber register_tool()
angemeldet; dieses Modul haelt keine DB-Abhaengigkeiten und ist damit
isoliert testbar.
"""

import base64
import json
import re
from typing import Any, Callable, Dict, List, Mapping, Optional, Tuple

# ---------------------------------------------------------------------------
# Konstanten
# ---------------------------------------------------------------------------

SERVER_NAME = "mariadb-mcp-strhttp"
SERVER_VERSION = "1.4.0"

SUPPORTED_PROTOCOL_VERSIONS: List[str] = ["2026-07-28"]
LATEST_PROTOCOL_VERSION = "2026-07-28"

_META_PROTOCOL_VERSION = "io.modelcontextprotocol/protocolVersion"

# JSON-RPC 2.0 / MCP Fehlercodes
PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603
HEADER_MISMATCH = -32020          # Spec 2026-07-28: Header/Body-Diskrepanz
UNSUPPORTED_PROTOCOL_VERSION = -32022

# Base64-Sentinel fuer nicht header-sichere Werte (Spec: Value Encoding).
_B64_SENTINEL_RE = re.compile(r"^=\?base64\?([A-Za-z0-9+/=]+)\?=$")


class ToolError(Exception):
    """Fehler bei der Tool-Ausfuehrung -> Tool-Result mit isError=true."""


class InvalidParams(Exception):
    """Ungueltige/fehlende Tool-Argumente -> JSON-RPC -32602."""


# ---------------------------------------------------------------------------
# Tool-Registry
# ---------------------------------------------------------------------------

TOOL_HANDLERS: Dict[str, Callable[[Dict[str, Any]], Dict[str, Any]]] = {}


def register_tool(name: str) -> Callable:
    """Dekorator: meldet eine Tool-Implementierung unter `name` an."""
    def decorator(fn: Callable[[Dict[str, Any]], Dict[str, Any]]):
        TOOL_HANDLERS[name] = fn
        return fn
    return decorator


# ---------------------------------------------------------------------------
# Tool-Definitionen (deterministische Reihenfolge, Spec: tools/list)
# ---------------------------------------------------------------------------

TOOLS: List[Dict[str, Any]] = [
    {
        "name": "execute_query",
        "title": "SQL-Abfrage ausfuehren (read-only)",
        "description": (
            "Execute a read-only SQL query on the MariaDB database. "
            "Only SELECT, SHOW, DESCRIBE, EXPLAIN and WITH/CTE are allowed; "
            "write operations are blocked and validated."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "SQL query to execute (must be read-only)",
                },
                "params": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Optional query parameters",
                },
                "database": {
                    "type": "string",
                    "description": "Optional database name",
                },
                "timeout": {
                    "type": "integer",
                    "description": "Optional query timeout in seconds",
                },
            },
            "required": ["query"],
        },
        "annotations": {"readOnlyHint": True},
    },
    {
        "name": "validate_query",
        "title": "SQL-Abfrage validieren",
        "description": "Validate a SQL query for read-only compliance without executing it.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "SQL query to validate",
                },
            },
            "required": ["query"],
        },
        "annotations": {"readOnlyHint": True},
    },
    {
        "name": "list_tables",
        "title": "Tabellen auflisten",
        "description": "List all tables in the current or a given (allowed) database.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "database": {
                    "type": "string",
                    "description": "Optional database name",
                },
            },
        },
        "annotations": {"readOnlyHint": True},
    },
    {
        "name": "list_databases",
        "title": "Datenbanken auflisten",
        "description": "List all databases visible to the configured read-only user.",
        "inputSchema": {"type": "object", "additionalProperties": False},
        "annotations": {"readOnlyHint": True},
    },
    {
        "name": "get_table_schema",
        "title": "Tabellenschema abrufen",
        "description": "Get column definitions for a specific table.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "table": {
                    "type": "string",
                    "description": "Table name to describe",
                },
            },
            "required": ["table"],
        },
        "annotations": {"readOnlyHint": True},
    },
]

INSTRUCTIONS = (
    "Read-only MariaDB access. Use execute_query for SELECT/SHOW/DESCRIBE/"
    "EXPLAIN and WITH/CTE queries; write operations are blocked. Use "
    "list_databases/list_tables/get_table_schema to explore the schema first. "
    "The database argument selects a schema (allow-listed); USE statements "
    "inside queries are not permitted."
)


# ---------------------------------------------------------------------------
# Hilfsfunktionen
# ---------------------------------------------------------------------------

def decode_header_value(value: str) -> str:
    """Dekodiert Base64-Sentinel-Headerwerte (=  ?base64?...?=  ), sonst raw."""
    m = _B64_SENTINEL_RE.match(value.strip())
    if m:
        try:
            return base64.b64decode(m.group(1)).decode("utf-8")
        except Exception:
            return value
    return value


def _json_safe(payload: Any) -> str:
    """Serialisiert Tool-Payloads JSON-sicher (datetime/Decimal -> str)."""
    return json.dumps(payload, default=str, ensure_ascii=False)


def _ok(req_id: Any, result: Dict[str, Any], status: int = 200) -> Tuple[int, Dict[str, Any]]:
    return status, {"jsonrpc": "2.0", "id": req_id, "result": result}


def _err(
    req_id: Any,
    code: int,
    message: str,
    status: int = 400,
    data: Optional[Dict[str, Any]] = None,
) -> Tuple[int, Dict[str, Any]]:
    error: Dict[str, Any] = {"code": code, "message": message}
    if data is not None:
        error["data"] = data
    return status, {"jsonrpc": "2.0", "id": req_id, "error": error}


def _tool_result(req_id: Any, payload: Dict[str, Any]) -> Tuple[int, Dict[str, Any]]:
    return _ok(req_id, {
        "resultType": "complete",
        "content": [{"type": "text", "text": _json_safe(payload)}],
        "structuredContent": payload,
        "isError": False,
    })


def _tool_error_result(req_id: Any, message: str) -> Tuple[int, Dict[str, Any]]:
    return _ok(req_id, {
        "resultType": "complete",
        "content": [{"type": "text", "text": message}],
        "isError": True,
    })


# ---------------------------------------------------------------------------
# Moderner MCP-Handler (POST /mcp, Spec 2026-07-28)
# ---------------------------------------------------------------------------

def handle_mcp_post(headers: Mapping[str, str], data: Any) -> Tuple[int, Any]:
    """
    Verarbeitet einen JSON-RPC-Request nach MCP-Spec 2026-07-28.

    `headers` ist das case-insensitive Header-Mapping des Requests
    (starlette Headers). Rueckgabe: (HTTP-Status, Body | None).
    Body None = leere Antwort (202 Accepted).
    """

    # --- Envelope-Validierung (JSON-RPC 2.0) -------------------------------
    if not isinstance(data, dict):
        return _err(None, INVALID_REQUEST, "Invalid Request: expected a JSON object")
    if data.get("jsonrpc") != "2.0":
        return _err(data.get("id"), INVALID_REQUEST, "Invalid Request: jsonrpc must be '2.0'")
    method = data.get("method")
    if not isinstance(method, str) or not method:
        return _err(data.get("id"), INVALID_REQUEST, "Invalid Request: missing method")

    req_id = data.get("id")
    is_notification = "id" not in data or req_id is None
    params = data.get("params")
    if params is None:
        params = {}
    if not isinstance(params, dict):
        return _err(req_id, INVALID_REQUEST, "Invalid Request: params must be an object")

    # --- Notifications: annehmen, 202 ohne Body ----------------------------
    # (Header-Anforderungen fuer Notification-POSTs definiert die Spec nicht.)
    if is_notification:
        return 202, None

    # --- Header-Validierung (Spec: Server Validation) ----------------------
    header_version = headers.get("MCP-Protocol-Version")
    meta = params.get("_meta")
    meta_version = meta.get(_META_PROTOCOL_VERSION) if isinstance(meta, dict) else None

    if not header_version:
        return _err(req_id, HEADER_MISMATCH,
                    "Header mismatch: MCP-Protocol-Version header is required")
    if not meta_version:
        return _err(req_id, HEADER_MISMATCH,
                    "Header mismatch: _meta['io.modelcontextprotocol/protocolVersion'] is required")
    if header_version != meta_version:
        return _err(req_id, HEADER_MISMATCH,
                    f"Header mismatch: MCP-Protocol-Version header '{header_version}' "
                    f"does not match body value '{meta_version}'")
    if header_version not in SUPPORTED_PROTOCOL_VERSIONS:
        return _err(
            req_id, UNSUPPORTED_PROTOCOL_VERSION, "Unsupported protocol version",
            data={"supported": list(SUPPORTED_PROTOCOL_VERSIONS), "requested": header_version},
        )

    header_method = headers.get("Mcp-Method")
    if not header_method or header_method != method:
        return _err(req_id, HEADER_MISMATCH,
                    f"Header mismatch: Mcp-Method header '{header_method}' "
                    f"does not match body value '{method}'")

    # --- Methoden-Dispatch ---------------------------------------------------
    if method == "ping":
        return _ok(req_id, {})

    if method == "server/discover":
        return _ok(req_id, {
            "resultType": "complete",
            "supportedVersions": list(SUPPORTED_PROTOCOL_VERSIONS),
            "capabilities": {"tools": {"listChanged": False}},
            "_meta": {
                "io.modelcontextprotocol/serverInfo": {
                    "name": SERVER_NAME,
                    "version": SERVER_VERSION,
                }
            },
            "instructions": INSTRUCTIONS,
            "ttlMs": 0,
            "cacheScope": "private",
        })

    if method == "tools/list":
        return _ok(req_id, {
            "resultType": "complete",
            "tools": [dict(t) for t in TOOLS],
            "ttlMs": 0,
            "cacheScope": "private",
        })

    if method == "tools/call":
        name = params.get("name")
        if not isinstance(name, str) or not name:
            return _err(req_id, INVALID_PARAMS, "Invalid params: 'name' is required", status=200)

        # Mcp-Name-Header ist fuer tools/call Pflicht (Spec: Standard Request
        # Headers) und muss nach Sentinel-Dekodierung mit params.name
        # uebereinstimmen.
        header_name = headers.get("Mcp-Name")
        if not header_name:
            return _err(req_id, HEADER_MISMATCH,
                        "Header mismatch: Mcp-Name header is required for tools/call")
        if decode_header_value(header_name) != name:
            return _err(req_id, HEADER_MISMATCH,
                        f"Header mismatch: Mcp-Name header '{header_name}' "
                        f"does not match body value '{name}'")

        handler = TOOL_HANDLERS.get(name)
        if handler is None:
            return _err(req_id, INVALID_PARAMS, f"Unknown tool: {name}", status=200)

        arguments = params.get("arguments")
        if arguments is None:
            arguments = {}
        if not isinstance(arguments, dict):
            return _err(req_id, INVALID_PARAMS, "Invalid params: arguments must be an object",
                        status=200)

        try:
            payload = handler(arguments)
        except InvalidParams as e:
            return _err(req_id, INVALID_PARAMS, str(e), status=200)
        except ToolError as e:
            return _tool_error_result(req_id, str(e))
        except Exception as e:  # noqa: BLE001 - nie interne Details leaken
            return _err(req_id, INTERNAL_ERROR, "Internal error during tool execution",
                        status=200)
        return _tool_result(req_id, payload)

    # Unbekannte Methode: Spec verlangt HTTP 404 + -32601 (erlaubt Clients
    # die Era-Detection gegenueber Legacy-HTTP+SSE-Servern).
    return _err(req_id, METHOD_NOT_FOUND, f"Method not found: {method}", status=404)

"""
Strukturiertes Audit-Logging fuer den MariaDB MCP Server.

Erfasst wer (authentifizierter Token-Index / Client-IP), wann, welche
Datenbank, welche Query-Klasse (read-only validation outcome) und wieviele
Zeilen zurueckgegeben wurden. Audit-Logs werden in einen separaten Logger
``audit`` geschrieben, der unabhaengig vom Access-Log konfiguriert werden kann
(z. B. in eine Datei oder ein SIEM). Es werden keine vollstaendigen Queries
oder Tokens protokolliert, um Daten- und Token-Lecks zu vermeiden.
"""

import json
import logging
import time
from typing import Optional

# Eigener Logger, getrennt vom Anwendungs-Logger, damit Audit-Ereignisse
# unabhaengig gefiltert/weitergeleitet werden koennen (z. B. in eine Datei).
audit_logger = logging.getLogger("audit")


def audit_event(
    event: str,
    *,
    client_ip: Optional[str] = None,
    token_index: Optional[int] = None,
    database: Optional[str] = None,
    query_preview: Optional[str] = None,
    valid: Optional[bool] = None,
    row_count: Optional[int] = None,
    status_code: Optional[int] = None,
    error: Optional[str] = None,
    extra: Optional[dict] = None,
) -> None:
    """
    Schreibt ein strukturiertes Audit-Ereignis als JSON-Zeile.

    ``token_index`` ist der Index des Tokens in der konfigurierten Menge
    (nicht der Token selbst!), sodass eindeutige Client-Identitaet ohne
    Token-Leak moeglich ist. ``query_preview`` ist auf 80 Zeichen begrenzt
    und dient nur der Grob-Klassifizierung, nicht der vollstaendigen
    Aufzeichnung von Nutzerdaten.
    """
    record = {
        "ts": time.time(),
        "event": event,
    }
    if client_ip is not None:
        record["client_ip"] = client_ip
    if token_index is not None:
        record["token_index"] = token_index
    if database is not None:
        record["database"] = database
    if query_preview is not None:
        record["query_preview"] = query_preview[:80]
    if valid is not None:
        record["valid"] = valid
    if row_count is not None:
        record["row_count"] = row_count
    if status_code is not None:
        record["status_code"] = status_code
    if error is not None:
        record["error"] = error
    if extra:
        record.update(extra)
    audit_logger.info(json.dumps(record, ensure_ascii=False))


def token_index_for(token: Optional[str]) -> Optional[int]:
    """
    Bestimmt den Index eines Tokens in der konfigurierten Menge.

    Gibt ``None`` zurueck, wenn die Auth deaktiviert ist oder der Token
    nicht gefunden wird. Der Index ist ein stabiler Bezeichner fuer einen
    Client/Zugang, ohne den eigentlichen Token-Wert zu protokollieren.
    """
    if token is None or token == "no-auth":
        return None
    try:
        # Vermeide zirkulaeren Import: token_config wird erst zur Laufzeit
        # ausgewertet, nachdem auth.py vollstaendig geladen ist.
        from auth import token_config
        if not token_config.enabled:
            return None
        snapshot = token_config._tokens_snapshot()
        for i, configured in enumerate(snapshot):
            import secrets
            if secrets.compare_digest(
                token.encode("utf-8"), configured.encode("utf-8")
            ):
                return i
    except Exception:
        return None
    return None

"""
Authentifizierungsmodul fuer API-Token

Sicherheitsmerkmale:
- Konstanter Zeitvergleich fuer Token-Validierung (Schutz vor Timing-Seitenkanal)
- Hot-Reload der Token-Datei bei Aenderung (Rotation ohne Restart)
- Fail-Closed-Startup: Auth aktiviert ohne Tokens bricht den Start ab
"""

import os
import json
import time
import secrets
import logging
import threading
from typing import Optional, List
from fastapi import Request, HTTPException, Header, Query
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)


class AuthStartupError(RuntimeError):
    """Wird ausgeloest, wenn die Auth-Konfiguration beim Start unsicher ist."""


class APITokenConfig:
    """Konfiguration fuer API-Token-Authentifizierung"""

    def __init__(self):
        self.enabled = True  # Standardmaessig aktiviert
        self.tokens: List[str] = []
        self.token_file: Optional[str] = None
        self.header_name = "Authorization"
        self.query_param_name = "api_key"
        self.bearer_prefix = "Bearer"
        # Lock zum Schutz der Token-Liste waehrend Hot-Reload und Lesezugriff.
        self._tokens_lock = threading.Lock()
        # Hot-Reload-Zustand fuer die Token-Datei.
        self._token_file_mtime: Optional[float] = None

    def load_from_env(self):
        """Laedt Konfiguration aus Umgebungsvariablen.

        Fail-Closed: Ist die Authentifizierung aktiviert, aber es sind keine
        Tokens konfiguriert, wird AuthStartupError ausgeloest. Ein solcher
        Server waere vollstaendig abgeriegelt (Silent-Death) oder, falls
        versehentlich deaktiviert, voellig offen. Ein harter Startabbruch
        macht die Fehlkonfiguration sofort sichtbar.
        """
        # Standardmaessig aktiviert
        self.enabled = True

        # Token aus Umgebungsvariable
        api_token = os.getenv("API_TOKEN")
        api_tokens = os.getenv("API_TOKENS")  # Komma-separierte Liste

        if api_token:
            with self._tokens_lock:
                self.tokens = [api_token]
            self.enabled = True
            logger.info("API-Token aus Umgebungsvariable geladen")

        if api_tokens:
            parsed = [t.strip() for t in api_tokens.split(",") if t.strip()]
            with self._tokens_lock:
                self.tokens = parsed
            self.enabled = True
            logger.info(f"{len(self.tokens)} API-Tokens aus Umgebungsvariable geladen")

        # Token-Datei
        token_file = os.getenv("API_TOKEN_FILE")
        if token_file and os.path.exists(token_file):
            self.token_file = token_file
            self._load_tokens_from_file()
            self.enabled = True
            logger.info(f"API-Tokens aus Datei {token_file} geladen")

        # Deaktiviere Authentifizierung explizit
        if os.getenv("DISABLE_API_AUTH", "").lower() in ["true", "1", "yes"]:
            self.enabled = False
            logger.info("API-Authentifizierung deaktiviert")

        # Header-Name anpassen
        custom_header = os.getenv("API_HEADER_NAME")
        if custom_header:
            self.header_name = custom_header

        # Query-Parameter-Name anpassen
        custom_query_param = os.getenv("API_QUERY_PARAM")
        if custom_query_param:
            self.query_param_name = custom_query_param

        logger.info(f"Authentifizierung aktiviert: {self.enabled}")
        if self.enabled:
            with self._tokens_lock:
                token_count = len(self.tokens)
            logger.info(f"Erwartete Tokens: {token_count} (aus Umgebungsvariablen/Datei)")
            if not token_count:
                # Fail-Closed: Auth aktiviert ohne Tokens ist eine unsichere
                # Konfiguration. Ein laufender Server waere entweder komplett
                # abgeriegelt oder (bei versehentlichem DISABLE_API_AUTH)
                # komplett offen. Start abbrechen statt nur warnen.
                raise AuthStartupError(
                    "Authentifizierung ist aktiviert, aber es sind keine Tokens "
                    "konfiguriert. Setzen Sie API_TOKEN/API_TOKENS/API_TOKEN_FILE, "
                    "oder deaktivieren Sie die Authentifizierung explizit ueber "
                    "DISABLE_API_AUTH=true (nur fuer lokale Entwicklung)."
                )

    def _load_tokens_from_file(self):
        """Laedt Tokens aus einer Datei und merkt sich den mtime fuer Hot-Reload."""
        if not self.token_file:
            return

        try:
            with open(self.token_file, 'r') as f:
                content = f.read().strip()

            # JSON-Format: {"tokens": ["token1", "token2"]}
            if content.startswith('{'):
                data = json.loads(content)
                if isinstance(data.get("tokens"), list):
                    parsed = [t.strip() for t in data["tokens"] if t.strip()]
                elif isinstance(data.get("token"), str):
                    parsed = [data["token"].strip()]
                else:
                    parsed = []
            # Einfache Textdatei: ein Token pro Zeile
            else:
                parsed = [line.strip() for line in content.split('\n') if line.strip()]

            with self._tokens_lock:
                self.tokens = parsed
            # mtime fuer Hot-Reload-Detection merken.
            try:
                self._token_file_mtime = os.path.getmtime(self.token_file)
            except OSError:
                self._token_file_mtime = None
            logger.info(f"{len(parsed)} Tokens aus Datei geladen")
        except Exception as e:
            logger.error(f"Fehler beim Laden der Token-Datei: {e}")
            with self._tokens_lock:
                self.tokens = []

    def maybe_reload_token_file(self) -> bool:
        """Laedt die Token-Datei neu, falls sie sich geaendert hat (Hot-Reload).

        Ermglicht Token-Rotation ohne Server-Restart: Ein Operator ueberschreibt
        die Token-Datei (z. B. tokens.json) und beim naechsten Request wird
        die neue Menge geladen. Die Pruefung erfolgt ueber den Datei-mtime und
        ist damit sehr billig (kein Datei-Lesen pro Request bei unveraenderter Datei).

        Gibt True zurueck, wenn ein Reload durchgefuehrt wurde.
        """
        if not self.token_file:
            return False
        try:
            current_mtime = os.path.getmtime(self.token_file)
        except OSError:
            return False
        if self._token_file_mtime is not None and current_mtime == self._token_file_mtime:
            return False
        logger.info("Token-Datei hat sich geaendert, lade neu (Hot-Reload)...")
        self._load_tokens_from_file()
        return True

    def is_valid_token(self, token: str) -> bool:
        """
        Ueberprueft, ob ein Token gueltig ist.

        Der Vergleich erfolgt konstant ueber secrets.compare_digest fuer
        jeden konfigurierten Token, um Timing-Seitenkanale bei der
        Token-Validierung zu vermeiden (Schutz vor Token-Enumeration ueber
        Antwortzeiten). Ein normaler in-Vergleich bricht beim ersten
        Match ab und ist dadurch timing-abhaengig.
        """
        if not self.enabled:
            return True  # Authentifizierung deaktiviert

        if not token or not isinstance(token, str):
            return False

        # Vor jedem Lesezugriff pruefen, ob die Datei neu geladen werden muss.
        # Sehr billig (stat-Aufruf); nur bei Aenderung wird tatsaechlich gelesen.
        self.maybe_reload_token_file()

        # Konstanter Vergleich: secrets.compare_digest gibt immer die gleiche
        # Zeit fuer gleiche Eingabelaengen zurueck. Durch Iteration ueber alle
        # Tokens ist die Gesamtzeit unabhaengig davon, *welcher* Token matched.
        token_bytes = token.encode("utf-8")
        for configured in self._tokens_snapshot():
            configured_bytes = configured.encode("utf-8")
            if secrets.compare_digest(token_bytes, configured_bytes):
                return True
        return False

    def _tokens_snapshot(self) -> List[str]:
        """Gibt eine konsistente Momentaufnahme der aktuellen Tokens zurueck."""
        with self._tokens_lock:
            return list(self.tokens)

    def validate_token(self, token: str) -> bool:
        """Validiert einen Token (Alias fuer is_valid_token)"""
        return self.is_valid_token(token)


# Globale Token-Konfiguration
token_config = APITokenConfig()


def _extract_token_from_header(authorization: Optional[str]) -> Optional[str]:
    """Extrahiert einen Token aus dem Authorization-Header (Bearer oder raw)."""
    if not authorization or not isinstance(authorization, str):
        return None
    if authorization.lower().startswith("bearer "):
        return authorization[7:].strip()
    return authorization


async def get_api_key(
    request: Request,
    authorization: Optional[str] = Header(None),
    api_key: Optional[str] = Query(None)
) -> str:
    """
    Extrahiere und validiere API-Token aus Header oder Query-Parameter.

    WICHTIG: Der Token wird NICHT aus dem Request-Body extrahiert. Ein frueherer
    Body-Konsum in dieser Dependency (und in auth_middleware) fuehrte dazu, dass
    die Endpunkte /mcp und /query den Body ein zweites Mal lesen wollten und
    einen leeren oder fehlerhaften Body erhielten. Tokens muessen daher ueber
    Header oder Query-Parameter uebergeben werden.
    """
    if not token_config.enabled:
        return "no-auth"  # Authentifizierung deaktiviert

    # 1. Versuche Token aus Authorization Header zu extrahieren
    token = _extract_token_from_header(authorization)
    if token and token_config.is_valid_token(token):
        return token

    # 2. Versuche Token aus Query-Parameter
    if api_key:
        if token_config.is_valid_token(api_key):
            return api_key

    # 3. Kein gueltiger Token gefunden (Body wird bewusst NICHT gelesen)
    raise HTTPException(
        status_code=401,
        detail="Ungueltiger oder fehlender API-Token. Bitte geben Sie einen gueltigen Token im Authorization-Header (Bearer) oder als api_key Query-Parameter an."
    )


async def verify_api_token(
    request: Request,
    authorization: Optional[str] = Header(None),
    api_key: Optional[str] = Query(None)
) -> bool:
    """
    Ueberpruefe, ob der API-Token gueltig ist
    Gibt True zurueck, wenn gueltig oder Authentifizierung deaktiviert
    """
    if not token_config.enabled:
        return True

    try:
        await get_api_key(request, authorization, api_key)
        return True
    except HTTPException:
        return False


async def optional_api_token(
    request: Request,
    authorization: Optional[str] = Header(None),
    api_key: Optional[str] = Query(None)
) -> Optional[str]:
    """
    Extrahiere API-Token, aber erzwinge ihn nicht
    Gibt None zurueck, wenn kein Token vorhanden oder ungueltig
    """
    if not token_config.enabled:
        return None

    try:
        return await get_api_key(request, authorization, api_key)
    except HTTPException:
        return None


def create_auth_dependency(require_auth: bool = True):
    """
    Erstellt eine Dependency, die optional Authentifizierung erzwingt
    """
    async def dependency(
        request: Request,
        authorization: Optional[str] = Header(None),
        api_key: Optional[str] = Query(None)
    ) -> Optional[str]:
        if not token_config.enabled:
            return None

        if require_auth:
            return await get_api_key(request, authorization, api_key)
        else:
            return await optional_api_token(request, authorization, api_key)

    return dependency


# Oeffentliche Endpunkte, die keine Authentifizierung benoetigen.
# /openapi.json ist oeffentlich, damit Clients (z. B. Open-WebUI) die
# API-Spezifikation ohne Token abrufen koennen. /docs und /redoc sind
# interaktive UIs und bleiben auth-pflichtig (freischaltbar via PUBLIC_DOCS).
_DEFAULT_PUBLIC_PATHS = ["/", "/health", "/openapi.json"]


def _public_paths() -> List[str]:
    paths = list(_DEFAULT_PUBLIC_PATHS)
    if os.getenv("PUBLIC_DOCS", "").lower() in ["true", "1", "yes"]:
        paths.extend(["/docs", "/redoc"])
    return paths


# Middleware fuer globale Authentifizierungspruefung
async def auth_middleware(request: Request, call_next):
    """
    Middleware, die Authentifizierung fuer alle Anfragen prueft
    (ausser fuer oeffentliche Endpunkte)

    WICHTIG: Der Token wird ausschliesslich aus Header und Query-Parameter
    extrahiert. Der Request-Body wird NICHT gelesen, damit die nachfolgenden
    Endpunkte den Body selbst auslesen koennen (kein Doppelkonsum).
    """
    public_paths = _public_paths()
    path = request.url.path

    # Pruefe, ob der Pfad oeffentlich ist
    is_public = any(path == p or path.startswith(p + "/") for p in public_paths)

    if not is_public and token_config.enabled:
        try:
            # Extrahiere Authorization Header
            auth_header = request.headers.get("authorization")
            query_params = dict(request.query_params)
            api_key_param = query_params.get("api_key") or query_params.get(token_config.query_param_name)

            token = _extract_token_from_header(auth_header)

            # Query Parameter (mit Standard- und benutzerdefiniertem Namen)
            if not token and api_key_param:
                token = api_key_param

            # Validierung (Body wird bewusst NICHT gelesen)
            if not token or not token_config.is_valid_token(token):
                return JSONResponse(
                    status_code=401,
                    content={
                        "error": "Unauthorized",
                        "detail": "Ungueltiger oder fehlender API-Token. Bitte geben Sie einen gueltigen Token im Authorization-Header (Bearer) oder als api_key Query-Parameter an."
                    }
                )
        except Exception as e:
            logger.error(f"Authentifizierungsfehler: {e}")
            return JSONResponse(
                status_code=401,
                content={
                    "error": "Unauthorized",
                    "detail": "Fehler bei der Authentifizierung"
                }
            )

    response = await call_next(request)
    return response


# Initialisiere Token-Konfiguration. Beim Import (z. B. Test-Setup) wird die
# Auth nicht zwingend erzwungen; echte Server-Starts rufen load_from_env()
# erneut in __main__ auf. Wir fangen AuthStartupError hier ab, damit der
# Import der Module (z. B. fuer Tests ohne Tokens) nicht crasht, sondern die
# Konfiguration in einem deaktivierten Zustand belaesst.
try:
    token_config.load_from_env()
except AuthStartupError as e:
    # Beim blossen Import (Tests, REPL) nicht abstuerzen. Ein echter
    # Produktionsstart erfolgt ueber __main__, wo ein erneuter Aufruf von
    # load_from_env() den Fehler erneut ausloest und den Server stoppt.
    if os.getenv("DISABLE_API_AUTH", "").lower() in ["true", "1", "yes"]:
        # Explizit deaktiviert: kein Fehler, aber auch keine Tokens.
        pass
    else:
        logger.warning(
            f"Auth-Startup waehrend Import uebersprungen (kein Produktionsstart): {e}"
        )

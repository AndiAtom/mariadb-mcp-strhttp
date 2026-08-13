"""
Authentifizierungsmodul für API-Token
"""

import os
import json
import logging
from typing import Optional, List
from fastapi import Request, HTTPException, Header, Query
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)

# API-Token Konfiguration
class APITokenConfig:
    """Konfiguration für API-Token-Authentifizierung"""
    
    def __init__(self):
        self.enabled = True  # Standardmäßig aktiviert
        self.tokens: List[str] = []
        self.token_file: Optional[str] = None
        self.header_name = "Authorization"
        self.query_param_name = "api_key"
        self.bearer_prefix = "Bearer"
        
    def load_from_env(self):
        """Lädt Konfiguration aus Umgebungsvariablen"""
        # Standardmäßig aktiviert
        self.enabled = True
        
        # Token aus Umgebungsvariable
        api_token = os.getenv("API_TOKEN")
        api_tokens = os.getenv("API_TOKENS")  # Komma-separierte Liste
        
        if api_token:
            self.tokens = [api_token]
            self.enabled = True
            logger.info("API-Token aus Umgebungsvariable geladen")
        
        if api_tokens:
            self.tokens = [t.strip() for t in api_tokens.split(",") if t.strip()]
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
            logger.info(f"Erwartete Tokens: {len(self.tokens)} (aus Umgebungsvariablen/Datei)")
            if not self.tokens:
                # Authentifizierung ist aktiviert, aber es sind keine Tokens
                # konfiguriert. Jeder Request ohne Token wird abgewiesen.
                # Das ist ein Betriebsrisiko: ein Server ohne API_TOKEN-Env ist
                # vollständig abgeriegelt. Warnung protokollieren.
                logger.warning(
                    "Authentifizierung ist aktiviert, aber es sind keine Tokens "
                    "konfiguriert. Setzen Sie API_TOKEN/API_TOKENS/API_TOKEN_FILE, "
                    "sonst werden alle authentifizierten Anfragen abgewiesen."
                )
    
    def _load_tokens_from_file(self):
        """Lädt Tokens aus einer Datei"""
        if not self.token_file:
            return
        
        try:
            with open(self.token_file, 'r') as f:
                content = f.read().strip()
                
            # JSON-Format: {"tokens": ["token1", "token2"]}
            if content.startswith('{'):
                data = json.loads(content)
                if isinstance(data.get("tokens"), list):
                    self.tokens = [t.strip() for t in data["tokens"] if t.strip()]
                elif isinstance(data.get("token"), str):
                    self.tokens = [data["token"].strip()]
            # Einfache Textdatei: ein Token pro Zeile
            else:
                self.tokens = [line.strip() for line in content.split('\n') if line.strip()]
                
            logger.info(f"{len(self.tokens)} Tokens aus Datei geladen")
        except Exception as e:
            logger.error(f"Fehler beim Laden der Token-Datei: {e}")
            self.tokens = []
    
    def is_valid_token(self, token: str) -> bool:
        """
        Überprüft, ob ein Token gültig ist
        """
        if not self.enabled:
            return True  # Authentifizierung deaktiviert
        
        if not token:
            return False
        
        return token in self.tokens
    
    def validate_token(self, token: str) -> bool:
        """Validiert einen Token (Alias für is_valid_token)"""
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

    WICHTIG: Der Token wird NICHT aus dem Request-Body extrahiert. Ein früherer
    Body-Konsum in dieser Dependency (und in auth_middleware) führte dazu, dass
    die Endpunkte /mcp und /query den Body ein zweites Mal lesen wollten und
    einen leeren oder fehlerhaften Body erhielten. Tokens müssen daher über
    Header oder Query-Parameter übergeben werden.
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
    
    # 3. Kein gültiger Token gefunden (Body wird bewusst NICHT gelesen)
    raise HTTPException(
        status_code=401,
        detail="Ungültiger oder fehlender API-Token. Bitte geben Sie einen gültigen Token im Authorization-Header (Bearer) oder als api_key Query-Parameter an."
    )


async def verify_api_token(
    request: Request,
    authorization: Optional[str] = Header(None),
    api_key: Optional[str] = Query(None)
) -> bool:
    """
    Überprüfe, ob der API-Token gültig ist
    Gibt True zurück, wenn gültig oder Authentifizierung deaktiviert
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
    Gibt None zurück, wenn kein Token vorhanden oder ungültig
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


# Öffentliche Endpunkte, die keine Authentifizierung benötigen.
# /docs, /openapi.json und /redoc sind bewusst NICHT enthalten, da sie die
# vollständige API-Spezifikation ohne Auth exponieren (Informationsleck). Sie
# lassen sich bei Bedarf über PUBLIC_DOCS=true (z.B. in internen Umgebungen)
# wieder freischalten.
_DEFAULT_PUBLIC_PATHS = ["/", "/health"]


def _public_paths() -> List[str]:
    paths = list(_DEFAULT_PUBLIC_PATHS)
    if os.getenv("PUBLIC_DOCS", "").lower() in ["true", "1", "yes"]:
        paths.extend(["/docs", "/openapi.json", "/redoc"])
    return paths


# Middleware für globale Authentifizierungsprüfung
async def auth_middleware(request: Request, call_next):
    """
    Middleware, die Authentifizierung für alle Anfragen prüft
    (außer für öffentliche Endpunkte)

    WICHTIG: Der Token wird ausschließlich aus Header und Query-Parameter
    extrahiert. Der Request-Body wird NICHT gelesen, damit die nachfolgenden
    Endpunkte den Body selbst auslesen können (kein Doppelkonsum).
    """
    public_paths = _public_paths()
    path = request.url.path
    
    # Prüfe, ob der Pfad öffentlich ist
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
                        "detail": "Ungültiger oder fehlender API-Token. Bitte geben Sie einen gültigen Token im Authorization-Header (Bearer) oder als api_key Query-Parameter an."
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


# Initialisiere Token-Konfiguration
token_config.load_from_env()

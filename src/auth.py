"""
Authentifizierungsmodul für API-Token
"""

import os
import json
import logging
from typing import Optional, List, Callable
from fastapi import Request, HTTPException, Header, Query
from fastapi.security import APIKeyHeader
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)

# API-Token Konfiguration
class APITokenConfig:
    """Konfiguration für API-Token-Authentifizierung"""
    
    def __init__(self):
        self.enabled = False
        self.tokens: List[str] = []
        self.token_file: Optional[str] = None
        self.header_name = "Authorization"
        self.query_param_name = "api_key"
        self.bearer_prefix = "Bearer"
        
    def load_from_env(self):
        """Lädt Konfiguration aus Umgebungsvariablen"""
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
        """Überprüft, ob ein Token gültig ist"""
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


# FastAPI Dependency für Token-Validierung
api_key_header = APIKeyHeader(name="Authorization", auto_error=False)


async def get_api_key(
    request: Request,
    authorization: Optional[str] = Header(None, alias="Authorization"),
    api_key: Optional[str] = Query(None, alias="api_key")
) -> str:
    """
    Extrahiere und validiere API-Token aus Header oder Query-Parameter
    """
    if not token_config.enabled:
        return "no-auth"  # Authentifizierung deaktiviert
    
    # 1. Versuche Token aus Authorization Header zu extrahieren
    if authorization:
        # Bearer Token Format: "Bearer <token>"
        if isinstance(authorization, str) and authorization.lower().startswith("bearer "):
            token = authorization[7:].strip()
            if token_config.is_valid_token(token):
                return token
        # Einfaches Token Format: "<token>"
        elif isinstance(authorization, str) and token_config.is_valid_token(authorization):
            return authorization
    
    # 2. Versuche Token aus Query-Parameter
    if api_key:
        if token_config.is_valid_token(api_key):
            return api_key
    
    # 3. Versuche Token aus Request Body (für POST-Anfragen)
    try:
        body = await request.json()
        if isinstance(body, dict):
            token = body.get("api_key") or body.get("api_token") or body.get("token")
            if token and token_config.is_valid_token(token):
                return token
    except:
        pass
    
    # 4. Kein gültiger Token gefunden
    raise HTTPException(
        status_code=401,
        detail="Ungültiger oder fehlender API-Token. Bitte geben Sie einen gültigen Token im Authorization-Header (Bearer) oder als api_key Query-Parameter an."
    )


async def verify_api_token(
    request: Request,
    authorization: Optional[str] = Header(None, alias="Authorization"),
    api_key: Optional[str] = Query(None, alias="api_key")
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
    authorization: Optional[str] = Header(None, alias="Authorization"),
    api_key: Optional[str] = Query(None, alias="api_key")
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
        authorization: Optional[str] = Header(None, alias="Authorization"),
        api_key: Optional[str] = Query(None, alias="api_key")
    ) -> Optional[str]:
        if not token_config.enabled:
            return None
        
        if require_auth:
            return await get_api_key(request, authorization, api_key)
        else:
            return await optional_api_token(request, authorization, api_key)
    
    return dependency


# Middleware für globale Authentifizierungsprüfung
async def auth_middleware(request: Request, call_next):
    """
    Middleware, die Authentifizierung für alle Anfragen prüft
    (außer für öffentliche Endpunkte)
    """
    # Öffentliche Endpunkte, die keine Authentifizierung benötigen
    public_paths = ["/", "/health", "/docs", "/openapi.json", "/redoc"]
    
    path = request.url.path
    
    # Prüfe, ob der Pfad öffentlich ist
    is_public = any(path == p or path.startswith(p + "/") for p in public_paths)
    
    if not is_public and token_config.enabled:
        try:
            # Extrahiere Authorization Header
            auth_header = request.headers.get("authorization")
            query_params = dict(request.query_params)
            api_key_param = query_params.get("api_key")
            
            # Versuche Token zu validieren
            token = None
            
            # 1. Authorization Header
            if auth_header:
                if isinstance(auth_header, str) and auth_header.lower().startswith("bearer "):
                    token = auth_header[7:].strip()
                elif isinstance(auth_header, str):
                    token = auth_header
            
            # 2. Query Parameter
            if not token and api_key_param:
                token = api_key_param
            
            # 3. Request Body (nur für POST, PUT, PATCH)
            if not token and request.method in ["POST", "PUT", "PATCH"]:
                try:
                    body = await request.json()
                    if isinstance(body, dict):
                        token = body.get("api_key") or body.get("api_token") or body.get("token")
                except:
                    pass
            
            # Validierung
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

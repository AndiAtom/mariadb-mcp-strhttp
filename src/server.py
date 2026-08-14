"""
MariaDB MCP Server mit streamable HTTP für Open-WebUI

Nur lesende Abfragen erlaubt - alle Schreiboperationen werden blockiert
Verwendet mysql-connector-python für bessere Docker-Kompatibilität
MCP-kompatibel für Open-WebUI Integration
Mit API-Token-Authentifizierung
"""

import re
import json
import logging
import sys
import os
import time
import threading
from contextlib import asynccontextmanager, contextmanager
from typing import Dict, List, Any, Optional, Generator

# Füge das src-Verzeichnis zum Python-Pfad hinzu
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from fastapi import FastAPI, HTTPException, Request, Query, Form, Body, Depends
from fastapi.responses import StreamingResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

import mysql.connector
from mysql.connector import Error as MySQLError

# Importiere Authentifizierungsmodul
from auth import token_config, get_api_key, verify_api_token, optional_api_token, auth_middleware

# Importiere Rate Limiting
from rate_limiting import rate_limiter, rate_limit_config

# Konfigurieren des Loggings
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class SensitiveQueryFilter(logging.Filter):
    """Maskiert api_key/api_token/token-Werte in uvicorn-Access-Log-Zeilen.

    Query-Parameter mit Tokens sind in Logs, Proxy-Logs, Browser-Historie
    und Referer-Headern sichtbar. Dieser Filter ersetzt den Token-Wert
    durch '***', damit keine echten Tokens im Access-Log auftauchen.
    """
    _PATTERN = re.compile(
        r"((?:api_key|api_token|token)=[^&\s]+)",
        re.IGNORECASE,
    )

    def filter(self, record: logging.LogRecord) -> bool:
        msg = record.getMessage()
        masked = self._PATTERN.sub(
            lambda m: m.group(1).split("=", 1)[0] + "=***", msg
        )
        if masked != msg:
            record.msg = masked
            record.args = ()
        return True


# Filter auf den uvicorn-access-Logger anwenden (wirkt in jedem Startmodus:
# 'python3 -m src.server' und 'uvicorn src.server:app').
logging.getLogger("uvicorn.access").addFilter(SensitiveQueryFilter())

# Liste der blockierten SQL-Befehle (Schreiboperationen)
BLOCKED_KEYWORDS = [
    # DDL (Data Definition Language) - Schema-Änderungen
    'CREATE', 'ALTER', 'DROP', 'TRUNCATE', 'RENAME',
    
    # DML (Data Manipulation Language) - Datenänderungen
    'INSERT', 'UPDATE', 'DELETE', 'REPLACE', 'LOAD', 'MERGE',
    
    # DCL (Data Control Language) - Berechtigungen
    'GRANT', 'REVOKE', 'DENY',
    
    # Transaktionssteuerung (Schreiboperationen)
    'COMMIT', 'ROLLBACK', 'SAVEPOINT', 'RELEASE',
    
    # Administrative Befehle
    'SHUTDOWN', 'KILL', 'PURGE', 'RESET', 'FLUSH',
    r'SET\s+PASSWORD', r'SET\s+GLOBAL',
    
    # Replikation
    r'CHANGE\s+MASTER', r'START\s+SLAVE', r'STOP\s+SLAVE',
    
    # Backup
    'BACKUP', 'RESTORE',
    
    # Sonstige gefährliche Befehle
    'EXECUTE', 'PREPARE', 'DEALLOCATE',
    
    # MariaDB/MySQL-spezifische Schreiboperationen
    'OPTIMIZE', 'REPAIR', 'ANALYZE TABLE', 'CHECK TABLE', 'CHECKSUM',
]

# Liste der erlaubten lesenden Befehle
ALLOWED_READ_ONLY_KEYWORDS = [
    # Datenabfragen
    'SELECT',
    
    # Metadaten-Abfragen
    'SHOW', 'DESCRIBE', 'DESC', 'EXPLAIN',
    
    # Informationsschema
    'INFORMATION_SCHEMA',
    
    # Transaktionssteuerung (nur lesend)
    r'START\s+TRANSACTION\s+READ\s+ONLY', r'BEGIN\s+READ\s+ONLY',
    r'SET\s+TRANSACTION\s+READ\s+ONLY',
    
    # Sonstige lesende Befehle
    'HELP',
]
# 'USE' ist bewusst NICHT in den erlaubten Keywords. Ein Datenbankwechsel
# per USE auf der geteilten Verbindung war eine Privilegieneskalation
# (Zugriff auf mysql, information_schema, ...). Datenbankwechsel erfolgen
# jetzt ausschließlich über den database-Parameter der Endpunkte, der
# gegen is_allowed_database validiert wird.

# Compile regex patterns für bessere Performance
BLOCKED_PATTERNS = [re.compile(r'\b' + keyword + r'\b', re.IGNORECASE) 
                    for keyword in BLOCKED_KEYWORDS]

ALLOWED_PATTERNS = [re.compile(r'\b' + keyword + r'\b', re.IGNORECASE)
                    for keyword in ALLOWED_READ_ONLY_KEYWORDS]

# Gültige SQL-Bezeichner (Datenbank-/Tabellen-/Spaltennamen): nur Buchstaben,
# Ziffern und Unterstrich. Verhindert SQL-Injection über Pfad- und Body-
# Parameter, die per f-String in SQL eingefügt werden (DESCRIBE, SHOW TABLE
# STATUS, SHOW INDEX, ...).
_IDENT_RE = re.compile(r'^[A-Za-z0-9_]+$')


def validate_identifier(identifier: str, name: str = "Bezeichner") -> str:
    """
    Validiert einen SQL-Bezeichner (Datenbank-/Tabellenname) und gibt ihn
    zurück, wenn er sicher ist. Andernfalls wird HTTPException 400 ausgelöst.

    Bezeichner werden an mehreren Stellen per f-String in SQL eingebettet
    (DESCRIBE, SHOW TABLE STATUS, SHOW INDEX). Backtick-Escaping reicht
    hier nicht aus, da einige Anweisungen den Wert als String-Literal
    erwarten (SHOW TABLE STATUS LIKE '...'). Daher strenge
    Positiv-Validierung.
    """
    if not identifier or not _IDENT_RE.match(identifier):
        raise HTTPException(
            status_code=400,
            detail=f"Ungültiger {name}: '{identifier}'. Nur Buchstaben, Ziffern und Unterstrich erlaubt."
        )
    return identifier


def is_allowed_database(database: str) -> bool:
    """
    Prüft, ob eine Datenbank vom Client angefordert werden darf.

    System-Schemata (mysql, information_schema, performance_schema, sys)
    und andere privilegierte Datenbanken dürfen nicht angesteuert werden,
    da dies eine Privilegieneskalation ermöglicht. Ist ALLOWED_DATABASES
    gesetzt (Komma-separiert), wird zusätzlich eine Positiv-Liste
    durchgesetzt.
    """
    if not database:
        return False

    # Grundlegende Bezeichner-Validierung verhindert Injektion.
    if not _IDENT_RE.match(database):
        return False

    # Privilegierte System-Schemata immer sperren.
    if database.lower() in {"mysql", "information_schema", "performance_schema", "sys"}:
        return False

    # Positiv-Liste erlaubter Datenbanken, falls konfiguriert.
    allowed_env = os.getenv("ALLOWED_DATABASES")
    if allowed_env:
        allowed = {d.strip() for d in allowed_env.split(",") if d.strip()}
        return database in allowed

    # Ohne explizite Positiv-Liste sind nicht-system-Schemata erlaubt,
    # sofern der Bezeichner gültig ist. System-Schemata bleiben gesperrt.
    return True



class DatabasePool:
    """
    Verwaltet Datenbankverbindungen mit Isolation pro Request.

    Die frühere einzelne, global geteilte Verbindung führte bei gleichzeitigen
    Requests mit USE-Wechseln zu Race Conditions und Daten-Lecks zwischen
    Requests/Tenants. Stattdessen öffnet dieser Pool pro Request eine frische,
    isolierte Verbindung. ``database`` wird direkt beim Connect übergeben statt
    per ``USE`` auf einer geteilten Verbindung umzuschalten.
    """

    def __init__(self, **config):
        self.host = config.get("host")
        self.port = int(config.get("port", 3306))
        self.user = config.get("user")
        self.password = config.get("password")
        self.database = config.get("database")
        self.timeout = int(config.get("timeout", 30))
        self.config = config

    def _new_connection(self, database=None):
        conn = mysql.connector.connect(
            host=self.host,
            port=self.port,
            user=self.user,
            password=self.password,
            database=database if database else self.database,
            autocommit=False,
            connection_timeout=self.timeout,
        )
        cursor = conn.cursor()
        # read_only auf Session-Ebene als Defense-in-Depth. Ein dedizierter,
        # privileg-minimierter DB-User ohne Schreibrechte ist die primäre
        # Schutzmaßnahme (siehe README / docker-compose.yml). SET SESSION
        # read_only erfordert SUPER/SYSTEM_VARIABLES_ADMIN-Rechte; ein
        # privileg-minimierter User hat diese nicht. Ein Fehlschlag darf die
        # Verbindung nicht blockieren (Defense-in-Depth, nicht primärer Schutz).
        try:
            cursor.execute("SET SESSION read_only=ON")
        except Exception as e:
            logger.debug(f"SET SESSION read_only=ON fehlgeschlagen (erwartet für nicht-privilegierte User): {e}")
        finally:
            cursor.close()
        return conn

    @contextmanager
    def get_connection(self, database=None):
        """
        Kontext-Manager für eine isolierte Verbindung.

        Wenn ``database`` angegeben ist, wird direkt gegen diese Datenbank
        verbunden, anstatt per ``USE`` auf einer geteilten Verbindung
        umzuschalten. Das vermeidet jeglichen shared State.
        """
        conn = None
        try:
            conn = self._new_connection(database=database)
            yield conn
        finally:
            if conn is not None:
                try:
                    conn.close()
                except Exception:
                    pass

    def execute_query(self, query: str, params: tuple = None, query_timeout: int = None, database: str = None) -> Dict[str, Any]:
        """
        Führt eine Abfrage auf einer frischen, isolierten Verbindung aus.

        Die Verbindung wird pro Request geöffnet und geschlossen, sodass sich
        gleichzeitige Requests keinen Verbindungszustand (insbesondere den per
        ``USE`` gesetzten Datenbank-Kontext) teilen.
        """
        cursor = None
        timeout = query_timeout if query_timeout is not None else self.timeout
        try:
            with self.get_connection(database=database) as conn:
                cursor = conn.cursor(dictionary=True)
                start_time = time.time()
                if params:
                    cursor.execute(query, params)
                else:
                    cursor.execute(query)
                elapsed = time.time() - start_time
                if elapsed > timeout:
                    logger.error(f"Abfrage-Timeout nach {timeout} Sekunden: {query[:100]}...")
                    return {
                        "success": False,
                        "error": f"Query timeout after {timeout} seconds",
                        "query": query
                    }
                results = cursor.fetchall()
                columns = [desc[0] for desc in cursor.description] if cursor.description else []
                return {
                    "success": True,
                    "results": results,
                    "columns": columns,
                    "row_count": len(results),
                    "query": query
                }
        except MySQLError as e:
            logger.error(f"Abfragefehler: {e}")
            return {
                "success": False,
                "error": str(e),
                "query": query
            }
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Allgemeiner Fehler bei Abfrage: {e}")
            return {
                "success": False,
                "error": str(e),
                "query": query
            }
        finally:
            if cursor:
                try:
                    cursor.close()
                except Exception:
                    pass

    def execute_streaming(self, query: str, params: tuple = None, query_timeout: int = None, database: str = None) -> Generator[Dict[str, Any], None, None]:
        """Führt eine Abfrage aus und streamt die Ergebnisse auf einer isolierten Verbindung."""
        cursor = None
        timeout = query_timeout if query_timeout is not None else self.timeout
        try:
            with self.get_connection(database=database) as conn:
                cursor = conn.cursor(dictionary=True)
                start_time = time.time()
                if params:
                    cursor.execute(query, params)
                else:
                    cursor.execute(query)
                columns = [desc[0] for desc in cursor.description] if cursor.description else []
                yield {
                    "type": "metadata",
                    "columns": columns,
                    "query": query,
                    "timeout": timeout
                }
                row_count = 0
                while True:
                    elapsed = time.time() - start_time
                    if elapsed > timeout:
                        logger.error(f"Streaming-Timeout nach {timeout} Sekunden: {query[:100]}...")
                        yield {
                            "type": "error",
                            "error": f"Streaming timeout after {timeout} seconds",
                            "query": query,
                            "rows_streamed": row_count
                        }
                        break
                    row = cursor.fetchone()
                    if row is None:
                        break
                    yield {
                        "type": "row",
                        "data": row
                    }
                    row_count += 1
                    if row_count >= 10000:
                        logger.warning(f"Maximale Zeilenanzahl (10000) erreicht für Abfrage: {query[:100]}...")
                        yield {
                            "type": "warning",
                            "message": "Maximum row limit (10000) reached",
                            "rows_streamed": row_count
                        }
                        break
                yield {
                    "type": "complete",
                    "total_rows": cursor.rowcount
                }
        except MySQLError as e:
            logger.error(f"Streaming-Abfragefehler: {e}")
            yield {
                "type": "error",
                "error": str(e),
                "query": query
            }
        except Exception as e:
            logger.error(f"Allgemeiner Streaming-Fehler: {e}")
            yield {
                "type": "error",
                "error": str(e),
                "query": query
            }
        finally:
            if cursor:
                try:
                    cursor.close()
                except Exception:
                    pass


# Globale Datenbankverbindungskonfiguration und Pool.
DB_CONFIG = {
    "host": os.getenv("DB_HOST", "localhost"),
    "port": int(os.getenv("DB_PORT", 3306)),
    "user": os.getenv("DB_USER", "root"),
    "password": os.getenv("DB_PASSWORD", ""),
    "database": os.getenv("DB_DATABASE", None),
    "timeout": int(os.getenv("DB_TIMEOUT", 30))
}

db_connection = DatabasePool(**DB_CONFIG)

def is_read_only_query(query: str) -> bool:
    """
    Überprüft, ob eine SQL-Abfrage nur lesend ist.
    Gibt True zurück, wenn die Abfrage erlaubt ist, False wenn blockiert.
    """
    if not query or not query.strip():
        return False
    
    # Entferne Kommentare
    query_clean = re.sub(r'--[^\n]*', '', query)  # Einzeilige Kommentare
    query_clean = re.sub(r'/\*.*?\*/', '', query_clean, flags=re.DOTALL)  # Mehrzeilige Kommentare
    
    # Überprüfe auf blockierte Keywords
    for pattern in BLOCKED_PATTERNS:
        if pattern.search(query_clean):
            logger.warning(f"Blockierte Abfrage erkannt: {query[:100]}...")
            return False
    
    # Überprüfe spezielle SET-Befehle
    if re.search(r'\bSET\b', query_clean, re.IGNORECASE):
        # Erlaube nur SET TRANSACTION READ ONLY
        if not re.search(r'\bSET\s+TRANSACTION\s+READ\s+ONLY\b', query_clean, re.IGNORECASE):
            return False
    
    # Überprüfe Transaktionsbefehle
    if re.search(r'\bSTART\s+TRANSACTION\b', query_clean, re.IGNORECASE):
        if not re.search(r'\bSTART\s+TRANSACTION\s+READ\s+ONLY\b', query_clean, re.IGNORECASE):
            return False
    
    if re.search(r'\bBEGIN\b', query_clean, re.IGNORECASE):
        if not re.search(r'\bBEGIN\s+READ\s+ONLY\b', query_clean, re.IGNORECASE):
            return False
    
    if re.search(r'\bSET\s+TRANSACTION\b', query_clean, re.IGNORECASE):
        if not re.search(r'\bSET\s+TRANSACTION\s+READ\s+ONLY\b', query_clean, re.IGNORECASE):
            return False
    
    # CALL-Befehle: Generell blockieren, da wir nicht wissen, ob die Prozedur lesend ist
    if re.search(r'\bCALL\b', query_clean, re.IGNORECASE):
        return False
    
    # USE-Befehle blockieren: Datenbankwechsel darf nur über den database-
    # Parameter der Endpunkte erfolgen (mit Allow-List-Prüfung), nicht per
    # rohem USE in der Abfrage.
    if re.search(r'\bUSE\b', query_clean, re.IGNORECASE):
        return False
    
    return True


def validate_query(query: str) -> Dict[str, Any]:
    """
    Validiert eine SQL-Abfrage und gibt Rückmeldung.
    """
    if not query or not query.strip():
        return {"valid": False, "error": "Leere Abfrage"}
    
    if not is_read_only_query(query):
        return {
            "valid": False, 
            "error": "Abfrage enthält Schreiboperationen. Nur lesende Abfragen sind erlaubt.",
            "blocked_keywords": [kw for kw in BLOCKED_KEYWORDS 
                               if isinstance(kw, str) and re.search(r'\b' + re.escape(kw) + r'\b', query, re.IGNORECASE)]
        }
    
    return {"valid": True, "message": "Abfrage ist lesend und erlaubt"}


# Lifespan Events für FastAPI
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan Event Handler für Startup und Shutdown"""
    # Startup: Der DatabasePool öffnet Verbindungen pro Request bei Bedarf,
    # daher ist hier kein globaler connect()-Aufruf nötig. Wir prüfen nur,
    # ob die Konfiguration plausibel ist.
    logger.info("Server startet (DatabasePool: Verbindungen pro Request)...")
    yield
    # Shutdown: Nichts zu schließen, da jede Verbindung pro Request geschlossen wird.
    logger.info("Server wird beendet...")


# Erstelle FastAPI App
app = FastAPI(
    title="MariaDB MCP Server",
    description="Read-only MariaDB interface for Open-WebUI with streamable HTTP and API Token Authentication",
    version="1.3.0",
    lifespan=lifespan
)

# Füge CORS-Middleware hinzu.
# allow_origins=["*"] mit allow_credentials=True ist eine bekannte
# Fehlkonfiguration. Für einen internen MCP-Server mit Token-Auth werden die
# erlaubten Origins über CORS_ALLOWED_ORIGINS (Komma-separiert) konfiguriert.
# Ohne Konfiguration ist nur der gleiche Origin erlaubt (leere Liste +
# Credentials deaktiviert). Siehe README.
_cors_origins_env = os.getenv("CORS_ALLOWED_ORIGINS", "")
if _cors_origins_env:
    _cors_origins = [o.strip() for o in _cors_origins_env.split(",") if o.strip()]
    _cors_credentials = True
else:
    # Keine Origins konfiguriert: restriktivster Default.
    _cors_origins = []
    _cors_credentials = False
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=_cors_credentials,
    allow_methods=["GET", "POST"],
    allow_headers=["Authorization", "Content-Type", "Accept"],
)

# Füge Authentifizierungs-Middleware hinzu
app.middleware("http")(auth_middleware)

# Füge Rate Limiting Middleware hinzu
if rate_limit_config.enabled:
    from rate_limiting import rate_limit_middleware
    app.middleware("http")(rate_limit_middleware)


# ============================================================================
# MCP Server Endpunkte für Open-WebUI
# ============================================================================

@app.get("/")
async def root():
    """Root-Endpoint mit Server-Informationen"""
    return {
        "server": "MariaDB MCP Server",
        "version": "1.3.0",
        "description": "Read-only MariaDB interface for Open-WebUI with API Token Authentication",
        "status": "running",
        "database_connected": True,  # DatabasePool verbindet on-demand
        "authentication": {
            "enabled": token_config.enabled,
            "type": "api_token",
            "header_name": token_config.header_name,
            "query_param_name": token_config.query_param_name
        },
        "rate_limiting": {
            "enabled": rate_limit_config.enabled,
            "requests_per_minute": rate_limit_config.requests_per_minute,
            "burst_requests": rate_limit_config.burst_requests
        },
        "endpoints": {
            "/": "Server-Informationen",
            "/mcp": "MCP-kompatibler Endpunkt für Open-WebUI",
            "/health": "Health-Check",
            "/query": "SQL-Abfrage ausführen (POST)",
            "/query/validate": "SQL-Abfrage validieren",
            "/query/stream": "Streamende Abfrage",
            "/tables": "Tabellen auflisten",
            "/databases": "Datenbanken auflisten",
            "/schema/{table}": "Tabellenschema abrufen",
            "/columns/{table}": "Spalten einer Tabelle abrufen",
            "/query/examples": "Beispiele für erlaubte Abfragen"
        },
        "read_only": True,
        "mcp_compatible": True,
        "allowed_commands": [
            "SELECT", "SHOW", "DESCRIBE", "EXPLAIN", "WITH/CTE",
            "START TRANSACTION READ ONLY", "SET TRANSACTION READ ONLY"
        ],
        "blocked_commands": [kw for kw in BLOCKED_KEYWORDS if isinstance(kw, str)][:10] + ["..."]
    }


@app.get("/mcp")
async def get_mcp_info():
    """
    MCP Server Information Endpunkt
    Gibt die MCP-Spezifikation für Open-WebUI zurück
    """
    return {
        "name": "MariaDB MCP Server",
        "version": "1.3.0",
        "description": "Read-only MariaDB database access for Open-WebUI with API Token Authentication",
        "readOnly": True,
        "authentication": {
            "required": token_config.enabled,
            "type": "api_token",
            "methods": ["header", "query_parameter"]
        },
        "tools": [
            {
                "name": "execute_query",
                "description": "Execute a read-only SQL query on MariaDB database",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "SQL query to execute (must be read-only)",
                            "example": "SELECT * FROM customers LIMIT 10"
                        },
                        "params": {
                            "type": "array",
                            "description": "Optional query parameters",
                            "items": {"type": "string"}
                        },
                        "database": {
                            "type": "string",
                            "description": "Optional database name",
                            "example": "mydatabase"
                        },
                        "api_key": {
                            "type": "string",
                            "description": "Optional API token for authentication"
                        }
                    },
                    "required": ["query"]
                }
            },
            {
                "name": "validate_query",
                "description": "Validate a SQL query for read-only compliance",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "SQL query to validate",
                            "example": "SELECT * FROM users"
                        }
                    },
                    "required": ["query"]
                }
            },
            {
                "name": "list_tables",
                "description": "List all tables in the current database",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "database": {
                            "type": "string",
                            "description": "Optional database name"
                        }
                    }
                }
            },
            {
                "name": "list_databases",
                "description": "List all available databases",
                "inputSchema": {
                    "type": "object",
                    "properties": {}
                }
            },
            {
                "name": "get_table_schema",
                "description": "Get schema information for a specific table",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "table": {
                            "type": "string",
                            "description": "Table name to get schema for",
                            "example": "customers"
                        }
                    },
                    "required": ["table"]
                }
            }
        ],
        "resources": [],
        "capabilities": {
            "query": True,
            "stream": True,
            "validate": True,
            "list_resources": False,
            "read_resource": False
        }
    }


@app.post("/mcp")
async def mcp_endpoint(request: Request):
    """
    MCP-kompatibler Endpunkt für Open-WebUI
    Verarbeitet alle MCP-Anfragen
    """
    try:
        # Authentifizierung prüfen
        if token_config.enabled:
            try:
                await get_api_key(request)
            except HTTPException as e:
                if e.status_code == 401:
                    return {"error": "Unauthorized", "detail": str(e.detail)}
                raise
        
        # Anfragedaten extrahieren
        raw_body = await request.body()
        logger.debug(f"MCP Request Body (raw): {raw_body[:500]}")
        
        # Versuche JSON zu parsen
        data = {}
        try:
            data = await request.json()
            logger.debug(f"MCP Request JSON: {data}")
        except Exception as e:
            logger.debug(f"JSON parse failed: {e}")
            # Versuche Formular-Daten
            try:
                form_data = await request.form()
                data = dict(form_data)
                logger.debug(f"MCP Request Form: {data}")
            except:
                data = {}
                logger.debug("No form data either")
        
        # Open-WebUI sendet Anfragen mit "method" und "params"
        method = data.get("method", "")
        params = data.get("params", {})
        
        # Falls die Daten anders strukturiert sind
        if not method and "query" in data:
            # Direkte Abfrage
            query = data.get("query", "")
            if query:
                validation = validate_query(query)
                if not validation["valid"]:
                    return {"error": validation["error"]}
                
                result = db_connection.execute_query(query)
                if not result["success"]:
                    return {"error": result["error"]}
                
                return {
                    "result": result["results"],
                    "columns": result["columns"],
                    "row_count": result["row_count"]
                }
        
        # Standard MCP-Format
        if method == "execute_query":
            query = params.get("query", "")
            if not query:
                query = params.get("q", "")
                if not query:
                    query = data.get("query", "")
                    if not query:
                        # Open-WebUI sendet manchmal die Abfrage direkt
                        if isinstance(data, dict) and len(data) == 1:
                            query = list(data.values())[0] if data else ""
                        elif raw_body:
                            try:
                                query = raw_body.decode('utf-8')
                            except:
                                query = str(raw_body)
            
            query_params = params.get("params", None)
            database = params.get("database", None)
            
            # Validierung
            validation = validate_query(query)
            if not validation["valid"]:
                return {
                    "error": validation["error"],
                    "blocked_keywords": validation.get("blocked_keywords", [])
                }
            
            # Datenbank validieren und als Parameter an die isolierte
            # Verbindung übergeben (kein ``USE`` auf geteilter Verbindung).
            if database:
                validate_identifier(database, "Datenbankname")
                if not is_allowed_database(database):
                    return {"error": f"Zugriff auf Datenbank '{database}' nicht erlaubt."}
            
            # Führe die Abfrage aus
            if query_params:
                result = db_connection.execute_query(query, tuple(query_params), database=database)
            else:
                result = db_connection.execute_query(query, database=database)
            
            if not result["success"]:
                return {"error": result["error"]}
            
            return {
                "result": result["results"],
                "columns": result["columns"],
                "row_count": result["row_count"]
            }
        
        elif method == "validate_query":
            query = params.get("query", "")
            if not query:
                query = data.get("query", "")
            return validate_query(query)
        
        elif method == "list_tables":
            database = params.get("database", None)
            if database:
                validate_identifier(database, "Datenbankname")
                if not is_allowed_database(database):
                    return {"error": f"Zugriff auf Datenbank '{database}' nicht erlaubt."}
            
            result = db_connection.execute_query("SHOW TABLES", database=database)
            if result["success"]:
                if result["results"]:
                    first_row = result["results"][0]
                    table_key = list(first_row.keys())[0]
                    tables = [row[table_key] for row in result["results"]]
                else:
                    tables = []
                return {"tables": tables, "count": len(tables)}
            else:
                return {"error": result["error"]}
        
        elif method == "list_databases":
            result = db_connection.execute_query("SHOW DATABASES")
            if result["success"]:
                databases = [row["Database"] for row in result["results"]]
                return {"databases": databases, "count": len(databases)}
            else:
                return {"error": result["error"]}
        
        elif method == "get_table_schema":
            table = params.get("table", "")
            if not table:
                table = data.get("table", "")
            if not table:
                return {"error": "Table name is required"}
            
            validate_identifier(table, "Tabellenname")
            result = db_connection.execute_query(f"DESCRIBE `{table}`")
            if result["success"]:
                return {"table": table, "columns": result["results"]}
            else:
                return {"error": result["error"]}
        
        else:
            return {"error": f"Unknown method: {method}"}
    
    except Exception as e:
        logger.error(f"MCP Endpoint Error: {e}")
        import traceback
        logger.error(f"Traceback: {traceback.format_exc()}")
        return {"error": str(e)}


# ============================================================================
# Standard API Endpunkte (für direkte Nutzung)
# ============================================================================

@app.get("/health")
async def health_check():
    """Health-Check Endpunkt"""
    # Der DatabasePool hält keine dauerhafte Verbindung; ein Health-Check
    # führt eine Probe-Abfrage aus, um die Erreichbarkeit zu prüfen.
    try:
        result = db_connection.execute_query("SELECT 1")
        db_ok = result.get("success", False)
        db_connected = db_ok
    except Exception:
        db_ok = False
        db_connected = False
    
    return {
        "status": "healthy" if db_ok else "degraded",
        "database_connected": db_connected,
        "database_ok": db_ok,
        "authentication": {
            "enabled": token_config.enabled,
            "type": "api_token"
        },
        "rate_limiting": {
            "enabled": rate_limit_config.enabled,
            "requests_per_minute": rate_limit_config.requests_per_minute
        }
    }


@app.post("/query")
async def execute_query(
    request: Request,
    query: str = Body(None, description="SQL Abfrage"),
    database: str = Body(None, description="Datenbankname (optional)"),
    timeout: int = Body(None, description="Query Timeout in Sekunden (optional)"),
    api_key: Optional[str] = Depends(optional_api_token)
):
    """
    Führt eine SQL-Abfrage aus.
    Akzeptiert:
    - JSON Body: {"query": "SELECT * FROM table"}
    - Formular-Daten: query=SELECT * FROM table
    - Query-Parameter: ?query=SELECT * FROM table
    - API-Token: Authorization Header oder api_key Parameter
    """
    try:
        # Falls query bereits als Parameter da ist
        if query and query.strip():
            pass
        else:
            # Versuche JSON Body
            try:
                body_data = await request.json()
                query = body_data.get("query", "") or body_data.get("sql", "") or body_data.get("q", "")
                database = body_data.get("database", database)
                timeout = body_data.get("timeout", timeout)
            except:
                # Versuche Formular-Daten
                form_data = await request.form()
                query = form_data.get("query", "") or form_data.get("sql", "") or form_data.get("q", "")
                database = form_data.get("database", database)
        
        if not query or not query.strip():
            raw_body = await request.body()
            logger.error(f"Leere Abfrage erhalten. Rohdaten: {raw_body[:500]}")
            raise HTTPException(
                status_code=400, 
                detail="Leere Abfrage. Bitte geben Sie eine SQL-Abfrage an."
            )
        
        # Falls eine Datenbank angegeben ist: validieren und als Parameter
        # an die isolierte Verbindung übergeben (kein ``USE``).
        if database:
            validate_identifier(database, "Datenbankname")
            if not is_allowed_database(database):
                raise HTTPException(
                    status_code=403,
                    detail=f"Zugriff auf Datenbank '{database}' nicht erlaubt."
                )
        
        # Validierung
        validation = validate_query(query)
        if not validation["valid"]:
            raise HTTPException(
                status_code=403, 
                detail=validation["error"]
            )
        
        # Führe die Abfrage aus
        query_timeout = timeout if timeout is not None else None
        result = db_connection.execute_query(query, query_timeout=query_timeout, database=database)
        
        if not result["success"]:
            raise HTTPException(status_code=400, detail=result["error"])
        
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Query Execution Error: {e}")
        import traceback
        logger.error(f"Traceback: {traceback.format_exc()}")
        # Keine internen Details (DB-Interna/Treiberfehler) an den Client leaken.
        raise HTTPException(status_code=500, detail="Interner Serverfehler bei der Abfrageausführung.")


@app.get("/query/validate")
async def validate_query_get(
    query: str = Query(...),
    api_key: Optional[str] = Depends(optional_api_token)
):
    """Validiert eine SQL-Abfrage (GET-Version)"""
    validation = validate_query(query)
    return validation


@app.post("/query/validate")
async def validate_query_post(
    request: Request,
    api_key: Optional[str] = Depends(optional_api_token)
):
    """Validiert eine SQL-Abfrage (POST-Version)"""
    try:
        data = await request.json()
        query = data.get("query", "") or data.get("sql", "") or data.get("q", "")
    except:
        form_data = await request.form()
        query = form_data.get("query", "") or form_data.get("sql", "") or form_data.get("q", "")
    
    if not query:
        raise HTTPException(status_code=400, detail="Leere Abfrage")
    
    validation = validate_query(query)
    return validation


@app.get("/query/stream")
async def stream_query(
    query: str = Query(...),
    timeout: int = Query(None, description="Query Timeout in Sekunden"),
    api_key: Optional[str] = Depends(optional_api_token)
):
    """
    Führt eine SQL-Abfrage aus und streamt die Ergebnisse.
    Ideal für große Resultsets.
    """
    if not query or not query.strip():
        raise HTTPException(status_code=400, detail="Leere Abfrage")
    
    # Validierung
    validation = validate_query(query)
    if not validation["valid"]:
        raise HTTPException(
            status_code=403, 
            detail=validation["error"]
        )
    
    # Streaming-Antwort
    def generate():
        try:
            query_timeout = timeout if timeout is not None else None
            for chunk in db_connection.execute_streaming(query, query_timeout=query_timeout):
                yield f"data: {json.dumps(chunk)}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'type': 'error', 'error': str(e)})}\n\n"
    
    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive"
        }
    )


@app.get("/tables")
async def list_tables(
    database: str = Query(None),
    api_key: Optional[str] = Depends(optional_api_token)
):
    """Liste aller Tabellen in der aktuellen oder angegebenen Datenbank"""
    try:
        if database:
            validate_identifier(database, "Datenbankname")
            if not is_allowed_database(database):
                raise HTTPException(
                    status_code=403,
                    detail=f"Zugriff auf Datenbank '{database}' nicht erlaubt."
                )
        
        result = db_connection.execute_query("SHOW TABLES", database=database)
        if result["success"]:
            if result["results"]:
                first_row = result["results"][0]
                table_key = list(first_row.keys())[0]
                tables = [row[table_key] for row in result["results"]]
            else:
                tables = []
            return {"tables": tables, "count": len(tables)}
        else:
            raise HTTPException(status_code=400, detail="Fehler beim Abrufen der Tabellen.")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"List Tables Error: {e}")
        raise HTTPException(status_code=500, detail="Interner Serverfehler.")


@app.get("/databases")
async def list_databases(
    api_key: Optional[str] = Depends(optional_api_token)
):
    """Liste aller verfügbaren Datenbanken"""
    try:
        result = db_connection.execute_query("SHOW DATABASES")
        if result["success"]:
            databases = [row["Database"] for row in result["results"]]
            return {"databases": databases, "count": len(databases)}
        else:
            raise HTTPException(status_code=400, detail="Fehler beim Abrufen der Datenbanken.")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"List Databases Error: {e}")
        raise HTTPException(status_code=500, detail="Interner Serverfehler.")


@app.get("/schema/{table}")
async def get_table_schema(
    table: str,
    api_key: Optional[str] = Depends(optional_api_token)
):
    """Schema einer Tabelle abrufen"""
    try:
        # Bezeichner streng validieren, bevor er in SQL eingefügt wird.
        validate_identifier(table, "Tabellenname")
        
        # Tabelleninformationen (Bezeichner ist validiert, Backticks sicher)
        table_info = db_connection.execute_query(f"DESCRIBE `{table}`")
        
        # Tabellenstatus (parametrisiert statt String-Interpolation)
        table_status = db_connection.execute_query(
            "SHOW TABLE STATUS LIKE %s", params=(table,)
        )
        
        # Indizes
        indexes = db_connection.execute_query(f"SHOW INDEX FROM `{table}`")
        
        # Fremdschlüssel (parametrisiert)
        foreign_keys = db_connection.execute_query("""
            SELECT 
                COLUMN_NAME,
                REFERENCED_TABLE_NAME,
                REFERENCED_COLUMN_NAME
            FROM INFORMATION_SCHEMA.KEY_COLUMN_USAGE 
            WHERE TABLE_NAME = %s 
            AND REFERENCED_TABLE_NAME IS NOT NULL
        """, params=(table,))
        
        if table_info["success"]:
            return {
                "table": table,
                "columns": table_info["results"],
                "status": table_status["results"][0] if table_status["results"] else None,
                "indexes": indexes["results"],
                "foreign_keys": foreign_keys["results"]
            }
        else:
            raise HTTPException(status_code=400, detail="Fehler beim Abrufen des Tabellenschemas.")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Table Schema Error: {e}")
        raise HTTPException(status_code=500, detail="Interner Serverfehler.")


@app.get("/columns/{table}")
async def get_table_columns(
    table: str,
    api_key: Optional[str] = Depends(optional_api_token)
):
    """Spalten einer Tabelle abrufen"""
    try:
        validate_identifier(table, "Tabellenname")
        result = db_connection.execute_query(f"DESCRIBE `{table}`")
        if result["success"]:
            return {"table": table, "columns": result["results"]}
        else:
            raise HTTPException(status_code=400, detail="Fehler beim Abrufen der Spalten.")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Table Columns Error: {e}")
        raise HTTPException(status_code=500, detail="Interner Serverfehler.")


@app.get("/query/examples")
async def get_query_examples(
    api_key: Optional[str] = Depends(optional_api_token)
):
    """Gibt Beispiele für erlaubte Abfragen zurück"""
    examples = {
        "basic_select": {
            "description": "Einfache SELECT-Abfrage",
            "query": "SELECT * FROM customers LIMIT 10"
        },
        "select_with_where": {
            "description": "SELECT mit WHERE-Bedingung",
            "query": "SELECT * FROM orders WHERE status = 'completed'"
        },
        "select_with_join": {
            "description": "SELECT mit JOIN",
            "query": "SELECT o.*, c.name FROM orders o JOIN customers c ON o.customer_id = c.id"
        },
        "show_tables": {
            "description": "Alle Tabellen anzeigen",
            "query": "SHOW TABLES"
        },
        "describe_table": {
            "description": "Struktur einer Tabelle anzeigen",
            "query": "DESCRIBE customers"
        },
        "explain_query": {
            "description": "Ausführungsplan einer Abfrage anzeigen",
            "query": "EXPLAIN SELECT * FROM orders WHERE customer_id = 1"
        },
        "show_databases": {
            "description": "Alle Datenbanken anzeigen",
            "query": "SHOW DATABASES"
        },
        "show_columns": {
            "description": "Spalten einer Tabelle anzeigen",
            "query": "SHOW COLUMNS FROM customers"
        },
        "select_with_group_by": {
            "description": "SELECT mit GROUP BY",
            "query": "SELECT customer_id, COUNT(*) as order_count FROM orders GROUP BY customer_id"
        },
        "select_with_order_by": {
            "description": "SELECT mit ORDER BY",
            "query": "SELECT * FROM products ORDER BY price DESC LIMIT 5"
        },
        "read_only_transaction": {
            "description": "Read-Only Transaktion starten",
            "query": "START TRANSACTION READ ONLY"
        },
        "show_table_status": {
            "description": "Status einer Tabelle anzeigen",
            "query": "SHOW TABLE STATUS LIKE 'customers'"
        },
        "show_indexes": {
            "description": "Indizes einer Tabelle anzeigen",
            "query": "SHOW INDEX FROM customers"
        },
        "information_schema": {
            "description": "Informationen aus dem Information Schema",
            "query": "SELECT * FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_SCHEMA = DATABASE()"
        }
    }
    
    return {
        "examples": examples,
        "authentication": {
            "enabled": token_config.enabled,
            "header_example": f"Authorization: Bearer YOUR_API_TOKEN",
            "query_param_example": "?api_key=YOUR_API_TOKEN"
        },
        "note": "Alle diese Abfragen sind lesend und daher erlaubt. Schreiboperationen wie INSERT, UPDATE, DELETE werden blockiert."
    }


if __name__ == "__main__":
    import uvicorn
    
    # Lade Konfiguration aus Umgebungsvariablen
    config = {
        "host": os.getenv("DB_HOST", "localhost"),
        "port": int(os.getenv("DB_PORT", 3306)),
        "user": os.getenv("DB_USER", "root"),
        "password": os.getenv("DB_PASSWORD", ""),
        "database": os.getenv("DB_DATABASE", None),
        "timeout": int(os.getenv("DB_TIMEOUT", 30))
    }
    
    # Aktualisiere die Datenbankkonfiguration
    DB_CONFIG.update(config)
    db_connection = DatabasePool(**DB_CONFIG)
    
    # Lade Token-Konfiguration neu
    token_config.load_from_env()
    
    # Lade Rate Limiting Konfiguration neu
    rate_limit_config.load_from_env()
    
    # Starte den Server
    uvicorn.run(
        app,
        host=os.getenv("SERVER_HOST", "0.0.0.0"),
        port=int(os.getenv("SERVER_PORT", 8000)),
        log_level=os.getenv("LOG_LEVEL", "info")
    )

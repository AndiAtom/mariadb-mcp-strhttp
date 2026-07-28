"""
MariaDB MCP Server mit streamable HTTP für Open-WebUI
Nur lesende Abfragen erlaubt - alle Schreiboperationen werden blockiert
Verwendet mysql-connector-python für bessere Docker-Kompatibilität
"""

import re
import json
import logging
from typing import Dict, List, Any, Optional, Generator
from fastapi import FastAPI, HTTPException, Request, Query
from fastapi.responses import StreamingResponse
import mysql.connector
from mysql.connector import Error as MySQLError
import sys

# Konfigurieren des Loggings
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="MariaDB MCP Server",
    description="Read-only MariaDB interface for Open-WebUI with streamable HTTP",
    version="1.0.0"
)

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
    r'SET\s+PASSWORD', r'SET\s+GLOBAL', r'SET\s+SESSION',
    
    # Replikation
    r'CHANGE\s+MASTER', r'START\s+SLAVE', r'STOP\s+SLAVE',
    
    # Backup
    'BACKUP', 'RESTORE',
    
    # Sonstige gefährliche Befehle
    'EXECUTE', 'PREPARE', 'DEALLOCATE',
]

# Liste der erlaubten lesenden Befehle
ALLOWED_READ_ONLY_KEYWORDS = [
    # Datenabfragen
    'SELECT',
    
    # Metadaten-Abfragen
    'SHOW', 'DESCRIBE', 'DESC', 'EXPLAIN', 'ANALYZE',
    
    # Informationsschema
    'INFORMATION_SCHEMA',
    
    # Transaktionssteuerung (nur lesend)
    r'START\s+TRANSACTION\s+READ\s+ONLY', r'BEGIN\s+READ\s+ONLY',
    r'SET\s+TRANSACTION\s+READ\s+ONLY',
    
    # Sonstige lesende Befehle
    'HELP', 'USE',
]

# Compile regex patterns für bessere Performance
BLOCKED_PATTERNS = [re.compile(r'\b' + keyword + r'\b', re.IGNORECASE) 
                    for keyword in BLOCKED_KEYWORDS]

ALLOWED_PATTERNS = [re.compile(r'\b' + keyword + r'\b', re.IGNORECASE)
                    for keyword in ALLOWED_READ_ONLY_KEYWORDS]


class DatabaseConnection:
    """Verwaltet die Datenbankverbindung"""
    
    def __init__(self, host: str, port: int, user: str, password: str, database: str = None):
        self.host = host
        self.port = port
        self.user = user
        self.password = password
        self.database = database
        self.connection = None
        
    def connect(self):
        """Stellt eine Verbindung zur Datenbank her"""
        try:
            self.connection = mysql.connector.connect(
                host=self.host,
                port=self.port,
                user=self.user,
                password=self.password,
                database=self.database,
                autocommit=False,  # Wir verwalten Transaktionen manuell
                read_only=True  # Verbindung als read-only markieren
            )
            logger.info("Erfolgreich mit MariaDB verbunden")
            return True
        except MySQLError as e:
            logger.error(f"Verbindungsfehler: {e}")
            return False
    
    def close(self):
        """Schließt die Verbindung"""
        if self.connection:
            self.connection.close()
            self.connection = None
            logger.info("Verbindung geschlossen")
    
    def execute_query(self, query: str, params: tuple = None) -> Dict[str, Any]:
        """Führt eine Abfrage aus und gibt die Ergebnisse zurück"""
        if not self.connection:
            raise Exception("Keine aktive Datenbankverbindung")
        
        cursor = None
        try:
            cursor = self.connection.cursor(dictionary=True)
            
            # Setze die Transaktion auf read-only
            cursor.execute("SET TRANSACTION READ ONLY")
            
            # Führe die Abfrage aus
            if params:
                cursor.execute(query, params)
            else:
                cursor.execute(query)
            
            # Hole die Ergebnisse
            results = cursor.fetchall()
            
            # Hole Metadaten
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
        finally:
            if cursor:
                cursor.close()
    
    def execute_streaming(self, query: str, params: tuple = None) -> Generator[Dict[str, Any], None, None]:
        """Führt eine Abfrage aus und streamt die Ergebnisse"""
        if not self.connection:
            raise Exception("Keine aktive Datenbankverbindung")
        
        cursor = None
        try:
            cursor = self.connection.cursor(dictionary=True)
            
            # Setze die Transaktion auf read-only
            cursor.execute("SET TRANSACTION READ ONLY")
            
            # Führe die Abfrage aus
            if params:
                cursor.execute(query, params)
            else:
                cursor.execute(query)
            
            # Stream die Ergebnisse
            columns = [desc[0] for desc in cursor.description] if cursor.description else []
            
            # Erstes Metadata-Paket
            yield {
                "type": "metadata",
                "columns": columns,
                "query": query
            }
            
            # Stream die Daten zeilenweise
            while True:
                row = cursor.fetchone()
                if row is None:
                    break
                yield {
                    "type": "row",
                    "data": row
                }
            
            # Abschluss-Paket
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
        finally:
            if cursor:
                cursor.close()


# Globale Datenbankverbindung
DB_CONFIG = {
    "host": "localhost",
    "port": 3306,
    "user": "root",
    "password": "",
    "database": None
}

db_connection = DatabaseConnection(**DB_CONFIG)


def is_read_only_query(query: str) -> bool:
    """
    Überprüft, ob eine SQL-Abfrage nur lesend ist.
    Gibt True zurück, wenn die Abfrage erlaubt ist, False wenn blockiert.
    """
    # Entferne Kommentare
    query_clean = re.sub(r'--[^\n]*', '', query)  # Einzeilige Kommentare
    query_clean = re.sub(r'/\*.*?\*/', '', query_clean, flags=re.DOTALL)  # Mehrzeilige Kommentare
    
    # Überprüfe auf blockierte Keywords
    for pattern in BLOCKED_PATTERNS:
        if pattern.search(query_clean):
            logger.warning(f"Blockierte Abfrage erkannt: {query[:100]}...")
            return False
    
    # Überprüfe, ob es sich um eine erlaubte lesende Abfrage handelt
    # Wir erlauben alle Abfragen, die mit erlaubten Keywords beginnen
    # oder diese enthalten, solange keine blockierten Keywords vorhanden sind
    
    # Spezielle Fälle: Transaktionssteuerung
    if re.search(r'\bSTART\s+TRANSACTION\b', query_clean, re.IGNORECASE):
        # Nur START TRANSACTION READ ONLY ist erlaubt
        if not re.search(r'\bSTART\s+TRANSACTION\s+READ\s+ONLY\b', query_clean, re.IGNORECASE):
            return False
    
    if re.search(r'\bBEGIN\b', query_clean, re.IGNORECASE):
        # Nur BEGIN READ ONLY ist erlaubt
        if not re.search(r'\bBEGIN\s+READ\s+ONLY\b', query_clean, re.IGNORECASE):
            return False
    
    if re.search(r'\bSET\s+TRANSACTION\b', query_clean, re.IGNORECASE):
        # Nur SET TRANSACTION READ ONLY ist erlaubt
        if not re.search(r'\bSET\s+TRANSACTION\s+READ\s+ONLY\b', query_clean, re.IGNORECASE):
            return False
    
    # SET-Befehle sind generell blockiert, außer SET TRANSACTION READ ONLY
    if re.search(r'\bSET\b', query_clean, re.IGNORECASE):
        # Erlaube nur SET TRANSACTION READ ONLY
        if not re.search(r'\bSET\s+TRANSACTION\s+READ\s+ONLY\b', query_clean, re.IGNORECASE):
            return False
    
    # CALL-Befehle: Nur erlaubt, wenn es sich um lesende Prozeduren handelt
    # Da wir das nicht sicher bestimmen können, blockieren wir CALL generell
    if re.search(r'\bCALL\b', query_clean, re.IGNORECASE):
        return False
    
    # Wenn keine blockierten Keywords gefunden wurden, ist die Abfrage erlaubt
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
                               if re.search(r'\b' + kw + r'\b', query, re.IGNORECASE)]
        }
    
    return {"valid": True, "message": "Abfrage ist lesend und erlaubt"}


@app.on_event("startup")
async def startup_event():
    """Wird beim Start des Servers ausgeführt"""
    # Verbindung zur Datenbank herstellen
    if not db_connection.connect():
        logger.error("Konnte keine Verbindung zur Datenbank herstellen")
        # Server startet trotzdem, aber Abfragen werden fehlschlagen


@app.on_event("shutdown")
async def shutdown_event():
    """Wird beim Beenden des Servers ausgeführt"""
    db_connection.close()


@app.get("/")
async def root():
    """Root-Endpoint mit Server-Informationen"""
    return {
        "server": "MariaDB MCP Server",
        "version": "1.0.0",
        "description": "Read-only MariaDB interface for Open-WebUI",
        "status": "running",
        "database_connected": db_connection.connection is not None,
        "endpoints": {
            "/query": "Führe eine SQL-Abfrage aus (POST)",
            "/query/validate": "Validiere eine SQL-Abfrage (GET/POST)",
            "/query/stream": "Streamende Abfrage (GET)",
            "/tables": "Liste aller Tabellen in der aktuellen Datenbank",
            "/databases": "Liste aller verfügbaren Datenbanken",
            "/schema/{table}": "Schema einer Tabelle abrufen",
            "/health": "Health-Check Endpoint"
        },
        "read_only": True,
        "allowed_commands": [
            "SELECT", "SHOW", "DESCRIBE", "EXPLAIN", "ANALYZE",
            "START TRANSACTION READ ONLY", "SET TRANSACTION READ ONLY"
        ],
        "blocked_commands": BLOCKED_KEYWORDS[:10] + ["..."]  # Zeige nur erste 10
    }


@app.get("/health")
async def health_check():
    """Health-Check Endpoint"""
    db_connected = db_connection.connection is not None
    
    if db_connected:
        try:
            # Teste eine einfache Abfrage
            result = db_connection.execute_query("SELECT 1")
            db_ok = result.get("success", False)
        except:
            db_ok = False
    else:
        db_ok = False
    
    return {
        "status": "healthy" if db_ok else "degraded",
        "database_connected": db_connected,
        "database_ok": db_ok
    }


@app.post("/query")
async def execute_query(request: Request):
    """
    Führt eine SQL-Abfrage aus.
    Erwartet JSON mit {"query": "SELECT * FROM table"}
    """
    try:
        data = await request.json()
        query = data.get("query", "")
        params = data.get("params", None)
    except:
        raise HTTPException(status_code=400, detail="Ungültige Anfrage. JSON mit 'query'-Feld erwartet.")
    
    if not query or not query.strip():
        raise HTTPException(status_code=400, detail="Leere Abfrage")
    
    # Validierung
    validation = validate_query(query)
    if not validation["valid"]:
        raise HTTPException(
            status_code=403, 
            detail=validation["error"]
        )
    
    # Führe die Abfrage aus
    try:
        if params:
            result = db_connection.execute_query(query, tuple(params))
        else:
            result = db_connection.execute_query(query)
        
        if not result["success"]:
            raise HTTPException(status_code=400, detail=result["error"])
        
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/query/validate")
async def validate_query_get(query: str = Query(...)):
    """Validiert eine SQL-Abfrage (GET-Version)"""
    validation = validate_query(query)
    return validation


@app.post("/query/validate")
async def validate_query_post(request: Request):
    """Validiert eine SQL-Abfrage (POST-Version)"""
    try:
        data = await request.json()
        query = data.get("query", "")
    except:
        raise HTTPException(status_code=400, detail="Ungültige Anfrage")
    
    validation = validate_query(query)
    return validation


@app.get("/query/stream")
async def stream_query(query: str = Query(...)):
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
            for chunk in db_connection.execute_streaming(query):
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
async def list_tables(database: str = Query(None)):
    """Liste aller Tabellen in der aktuellen oder angegebenen Datenbank"""
    try:
        if database:
            query = f"SHOW TABLES FROM `{database}`"
        else:
            query = "SHOW TABLES"
        
        result = db_connection.execute_query(query)
        if result["success"]:
            # Extrahiere Tabellennamen - der Spaltenname kann variieren
            if result["results"]:
                first_row = result["results"][0]
                table_key = list(first_row.keys())[0]  # Erster Schlüssel ist der Tabellenname
                tables = [row[table_key] for row in result["results"]]
            else:
                tables = []
            return {"tables": tables, "count": len(tables)}
        else:
            raise HTTPException(status_code=400, detail=result["error"])
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/databases")
async def list_databases():
    """Liste aller verfügbaren Datenbanken"""
    try:
        result = db_connection.execute_query("SHOW DATABASES")
        if result["success"]:
            databases = [row["Database"] for row in result["results"]]
            return {"databases": databases, "count": len(databases)}
        else:
            raise HTTPException(status_code=400, detail=result["error"])
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/schema/{table}")
async def get_table_schema(table: str):
    """Schema einer Tabelle abrufen"""
    try:
        # Tabelleninformationen
        table_info = db_connection.execute_query(f"DESCRIBE `{table}`")
        
        # Tabellenstatus
        table_status = db_connection.execute_query(f"SHOW TABLE STATUS LIKE '{table}'")
        
        # Indizes
        indexes = db_connection.execute_query(f"SHOW INDEX FROM `{table}`")
        
        # Fremdschlüssel
        foreign_keys = db_connection.execute_query(f"""
            SELECT 
                COLUMN_NAME,
                REFERENCED_TABLE_NAME,
                REFERENCED_COLUMN_NAME
            FROM INFORMATION_SCHEMA.KEY_COLUMN_USAGE 
            WHERE TABLE_NAME = '{table}' 
            AND REFERENCED_TABLE_NAME IS NOT NULL
        """)
        
        if table_info["success"]:
            return {
                "table": table,
                "columns": table_info["results"],
                "status": table_status["results"][0] if table_status["results"] else None,
                "indexes": indexes["results"],
                "foreign_keys": foreign_keys["results"]
            }
        else:
            raise HTTPException(status_code=400, detail=table_info["error"])
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/columns/{table}")
async def get_table_columns(table: str):
    """Spalten einer Tabelle abrufen"""
    try:
        result = db_connection.execute_query(f"DESCRIBE `{table}`")
        if result["success"]:
            return {"table": table, "columns": result["results"]}
        else:
            raise HTTPException(status_code=400, detail=result["error"])
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/query/examples")
async def get_query_examples():
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
        "note": "Alle diese Abfragen sind lesend und daher erlaubt. Schreiboperationen wie INSERT, UPDATE, DELETE werden blockiert."
    }


if __name__ == "__main__":
    import uvicorn
    
    # Lade Konfiguration aus Umgebungsvariablen
    import os
    
    config = {
        "host": os.getenv("DB_HOST", "localhost"),
        "port": int(os.getenv("DB_PORT", 3306)),
        "user": os.getenv("DB_USER", "root"),
        "password": os.getenv("DB_PASSWORD", ""),
        "database": os.getenv("DB_DATABASE", None)
    }
    
    # Aktualisiere die Datenbankkonfiguration
    DB_CONFIG.update(config)
    db_connection = DatabaseConnection(**DB_CONFIG)
    
    # Starte den Server
    uvicorn.run(
        app,
        host=os.getenv("SERVER_HOST", "0.0.0.0"),
        port=int(os.getenv("SERVER_PORT", 8000)),
        log_level=os.getenv("LOG_LEVEL", "info")
    )

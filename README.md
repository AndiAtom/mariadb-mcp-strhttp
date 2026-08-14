# MariaDB MCP Server mit streamable HTTP für Open-WebUI

Ein **read-only** MCP Server, der als Schnittstelle zwischen einer MariaDB Datenbank und Open-WebUI dient. Der Server erlaubt **ausschließlich lesende Abfragen** und blockiert alle Schreiboperationen wie INSERT, UPDATE, DELETE, CREATE, ALTER, DROP usw.

> **Hinweis:** Der Server verwendet `mysql-connector-python`, der vollständig mit MariaDB kompatibel ist und keine externen Systembibliotheken benötigt. Der Server ist **MCP-kompatibel** und implementiert die notwendigen Endpunkte für Open-WebUI. Aktuellste Version verwendet Python 3.12 als Base Image.

---

## :rocket: Schnellstart

### Mit Docker (empfohlen)

```bash
# Klone das Repository
git clone https://github.com/AndiAtom/mariadb-mcp-strhttp.git
cd mariadb-mcp-strhttp

# Starte mit Docker Compose (enthält MariaDB + MCP Server)
docker-compose up -d

# Der Server ist jetzt unter http://localhost:8000 verfügbar
```

### Ohne Docker

```bash
# Installiere Abhängigkeiten
pip install -r requirements.txt

# Starte den Server
python -m src.server

# Oder direkt
python src/server.py
```

---

## :gear: Konfiguration

### Umgebungsvariablen

Der Server kann über Umgebungsvariablen oder eine `config.json`-Datei konfiguriert werden.

#### Datenbank-Konfiguration

| Variable | Beschreibung | Standardwert | Beispiel |
|----------|--------------|--------------|----------|
| `DB_HOST` | MariaDB Hostname | `localhost` | `192.168.1.100` |
| `DB_PORT` | MariaDB Port | `3306` | `3306` |
| `DB_USER` | MariaDB Benutzername | `mcpuser` | `mcp_user` |
| `DB_PASSWORD` | MariaDB Passwort | `""` | `securepassword` |
| `DB_DATABASE` | Standard-Datenbank | `None` | `mydatabase` |
| `DB_TIMEOUT` | Timeout für Datenbankabfragen (Sekunden) | `30` | `60` |

#### Server-Konfiguration

| Variable | Beschreibung | Standardwert | Beispiel |
|----------|--------------|--------------|----------|
| `SERVER_HOST` | Server Host | `0.0.0.0` | `0.0.0.0` |
| `SERVER_PORT` | Server Port | `8000` | `8000` |
| `LOG_LEVEL` | Log-Level | `info` | `debug` |

#### API-Token-Authentifizierung

| Variable | Beschreibung | Standardwert | Beispiel |
|----------|--------------|--------------|----------|
| `API_TOKEN` | Einzelner API-Token | `None` | `my-secret-token` |
| `API_TOKENS` | Mehrere API-Tokens (komma-separiert) | `None` | `token1,token2` |
| `API_TOKEN_FILE` | Pfad zur Token-Datei | `None` | `/app/tokens.json` |
| `DISABLE_API_AUTH` | Authentifizierung deaktivieren | `false` | `true` |
| `API_HEADER_NAME` | Name des Authorization Headers | `Authorization` | `X-API-Key` |
| `API_QUERY_PARAM` | Name des Query-Parameters | `api_key` | `token` |

> **Hinweis:** Der Token wird **nicht** mehr aus dem Request-Body extrahiert. Dies verhindert einen Doppelkonsum des Bodies durch die Auth-Middleware. Verwende stattdessen den `Authorization`-Header oder den `api_key`-Query-Parameter.

#### CORS

| Variable | Beschreibung | Standardwert | Beispiel |
|----------|--------------|--------------|----------|
| `CORS_ALLOWED_ORIGINS` | Erlaubte CORS-Origins (komma-separiert) | `""` (keine) | `https://openwebui.example.com` |

> **Sicherheit:** `allow_origins=["*"]` mit `allow_credentials=True` ist eine bekannte Fehlkonfiguration. Ohne Konfiguration von `CORS_ALLOWED_ORIGINS` sind keine Cross-Origin-Requests mit Credentials möglich.

#### Datenbank-Zugriffskontrolle

| Variable | Beschreibung | Standardwert | Beispiel |
|----------|--------------|--------------|----------|
| `ALLOWED_DATABASES` | Positiv-Liste erlaubter Datenbanken (komma-separiert) | `""` (nicht gesetzt) | `testdb,analytics` |

> **Sicherheit:** System-Schemata (`mysql`, `information_schema`, `performance_schema`, `sys`) sind immer gesperrt. Ohne `ALLOWED_DATABASES` sind alle nicht-System-Schemata erlaubt; mit gesetzter Variable nur die gelisteten.

#### API-Dokumentation

| Variable | Beschreibung | Standardwert | Beispiel |
|----------|--------------|--------------|----------|
| `PUBLIC_DOCS` | `/docs`, `/openapi.json`, `/redoc` ohne Auth freischalten | `false` | `true` |

> **Sicherheit:** Die API-Dokumentation ist standardmäßig auth-pflichtig, um kein Informationsleck zu erzeugen. Nur in vertrauenswürdigen internen Umgebungen auf `true` setzen.

#### Rate Limiting

| Variable | Beschreibung | Standardwert | Beispiel |
|----------|--------------|--------------|----------|
| `RATE_LIMITING_ENABLED` | Rate Limiting aktivieren | `true` | `false` |
| `RATE_LIMIT_REQUESTS_PER_MINUTE` | Anfragen pro Minute | `100` | `200` |
| `RATE_LIMIT_BURST_REQUESTS` | Burst-Anfragen | `10` | `20` |
| `RATE_LIMIT_WHITELIST` | Whitelisted Pfade | `/health,/`, etc. | `/health,/info` |

### Konfigurationsdatei

Erstelle oder bearbeite `config.json`:

```json
{
  "server": {
    "host": "0.0.0.0",
    "port": 8000,
    "log_level": "info"
  },
  "database": {
    "host": "localhost",
    "port": 3306,
    "user": "mcpuser",
    "password": "securepassword",
    "database": "mydatabase",
    "timeout": 30
  },
  "security": {
    "read_only": true,
    "block_write_operations": true,
    "validate_queries": true
  },
  "authentication": {
    "enabled": true,
    "type": "api_token",
    "tokens": ["token1", "token2"],
    "token_file": null,
    "header_name": "Authorization",
    "query_param_name": "api_key"
  },
  "rate_limiting": {
    "enabled": true,
    "requests_per_minute": 100,
    "burst_requests": 10,
    "whitelist": ["/health", "/"]
  }
}
```

> **Hinweis:** Die Konfiguration kann auch über Umgebungsvariablen überschrieben werden.

---

## :key: API-Token-Authentifizierung

Der Server unterstützt optionale API-Token-Authentifizierung, um den Zugriff auf die API zu schützen.

### Token-Generierung

Das Projekt enthält ein Skript `generate_token.py` zur Generierung sicherer API-Tokens:

```bash
# Einzelnen Token generieren
python generate_token.py

# Mehrere Tokens generieren
python generate_token.py --num 5

# Token mit bestimmter Länge generieren (Standard: 32 Zeichen)
python generate_token.py --length 64

# Token in Datei speichern
python generate_token.py --file tokens.json

# Tokens nur anzeigen (nicht speichern)
python generate_token.py --no-file
```

### Authentifizierung aktivieren

Es gibt mehrere Möglichkeiten, die Authentifizierung zu konfigurieren:

#### 1. Einzelner Token über Umgebungsvariable

```bash
# In docker-compose.yml oder beim Starten
API_TOKEN=your-secure-token-here
```

#### 2. Mehrere Tokens über Umgebungsvariable (komma-separiert)

```bash
API_TOKENS=token1,token2,token3
```

#### 3. Token aus Datei laden

Erstelle eine JSON-Datei `tokens.json`:

```json
{
  "tokens": [
    "your-secure-token-1",
    "your-secure-token-2"
  ]
}
```

Oder eine einfache Textdatei (ein Token pro Zeile):
```
token1
token2
token3
```

Dann in docker-compose.yml:
```yaml
environment:
  - API_TOKEN_FILE=/app/tokens.json
volumes:
  - ./tokens.json:/app/tokens.json:ro
```

#### 4. Authentifizierung deaktivieren (Standard)

```bash
DISABLE_API_AUTH=true
```

### Token verwenden

Es gibt drei Möglichkeiten, den Token zu übergeben:

#### 1. Authorization Header (empfohlen)

```bash
curl -X POST http://localhost:8000/query \
  -H "Authorization: Bearer your-secure-token" \
  -H "Content-Type: application/json" \
  -d '{"query": "SELECT * FROM customers LIMIT 10"}'
```

#### 2. Query Parameter

```bash
curl -X POST http://localhost:8000/query?api_key=your-secure-token \
  -H "Content-Type: application/json" \
  -d '{"query": "SELECT * FROM customers LIMIT 10"}'
```

> **Hinweis:** Die Token-Übertragung im Request-Body wird aus Sicherheitsgründen nicht mehr unterstützt (Doppelkonsum des Bodies). Verwende Header oder Query-Parameter.

### Öffentliche Endpunkte

Die folgenden Endpunkte benötigen **keine** Authentifizierung:
- `GET /` - Server-Informationen
- `GET /health` - Health-Check

> **Hinweis:** `/docs`, `/openapi.json` und `/redoc` sind standardmäßig **auth-pflichtig** (Informationsschutz). Sie können über die Umgebungsvariable `PUBLIC_DOCS=true` ohne Authentifizierung freigeschaltet werden.

Alle anderen Endpunkte erfordern einen gültigen API-Token, wenn die Authentifizierung aktiviert ist.

---

## :desktop_computer: Open-WebUI Integration

### MCP Server in Open-WebUI hinzufügen

1. **Öffne Open-WebUI** (z.B. `http://localhost:8080`)
2. **Gehe zu Einstellungen** --> **MCP Server** oder **Externe Tool-Server**
3. **Klicke auf "Add MCP Server"** oder **"Neuer Server"**
4. **Füge folgende Konfiguration ein:**

```json
{
  "name": "MariaDB Read-Only",
  "type": "http",
  "url": "http://localhost:8000",
  "readOnly": true,
  "headers": {
    "Authorization": "Bearer your-api-token-here"
  },
  "capabilities": {
    "query": true,
    "stream": true,
    "validate": true,
    "list_resources": false,
    "read_resource": false
  },
  "timeout": 60
}
```

> **:bulb: Hinweis:** Open-WebUI erkennt automatisch den MCP-kompatiblen Endpunkt. Die URL kann einfach `http://localhost:8000` sein, der Server hat sowohl den Standard- als auch den `/mcp`-Endpunkt.

### Verbindung testen

Frage Open-WebUI:
```
"Was sind die Tabellen in der Datenbank?"
```

Erwartete Antwort: Eine Liste aller Tabellen aus deiner MariaDB.

---

## :shield: Sicherheitsfeatures

### Read-Only Implementierung

Der Server implementiert **mehrere Ebenen** von Read-Only-Schutz:

1. **DB-User-Ebene (primär):** Verwende einen dedizierten DB-User ohne Schreibrechte (`GRANT SELECT ON ...`). Dies ist die wichtigste Schutzmaßnahme.
2. **Session-Ebene:** `SET SESSION read_only=ON` wird auf **jeder Verbindung** des Pools gesetzt (Defense-in-Depth)
3. **Abfrage-Ebene:** Jede Abfrage wird vor der Ausführung auf Schreiboperationen geprüft (`is_read_only_query`)
4. **Identifier-Validierung:** Tabellen- und Datenbanknamen werden per Regex (`^[A-Za-z0-9_]+$`) validiert, bevor sie in SQL eingefügt werden (SQL-Injection-Schutz)

> **Hinweis:** Die frühere einzelne, global geteilte Verbindung wurde durch einen Connection-Pool ersetzt, der pro Request eine isolierte Verbindung öffnet. Das verhindert Race Conditions durch `USE`-Wechsel auf geteilten Verbindungen.

### Query Timeout Schutz

- **Standard-Timeout:** Alle Datenbankabfragen haben einen Standard-Timeout von 30 Sekunden
- **Individueller Timeout:** Kann pro Abfrage über den `timeout`-Parameter angepasst werden
- **Streaming-Limit:** Streaming-Abfragen sind auf 10.000 Zeilen begrenzt, um sehr große Resultsets zu verhindern
- **Konfigurierbar:** Timeout kann über die Umgebungsvariable `DB_TIMEOUT` oder in der Konfigurationsdatei angepasst werden

### Blockierte Befehle

Der Server blockiert **alle** Schreiboperationen, einschließlich:

#### DDL (Data Definition Language)
- `CREATE` - Tabellen, Datenbanken, Indizes erstellen
- `ALTER` - Objekte ändern
- `DROP` - Objekte löschen
- `TRUNCATE` - Tabellen leeren
- `RENAME` - Objekte umbenennen

#### DML (Data Manipulation Language)
- `INSERT` - Daten einfügen
- `UPDATE` - Daten aktualisieren
- `DELETE` - Daten löschen
- `REPLACE` - Daten ersetzen
- `LOAD` - Daten laden
- `MERGE` - Daten zusammenführen

#### DCL (Data Control Language)
- `GRANT` - Berechtigungen erteilen
- `REVOKE` - Berechtigungen entziehen
- `DENY` - Berechtigungen verweigern

#### Transaktionssteuerung
- `COMMIT` - Transaktionen bestätigen
- `ROLLBACK` - Transaktionen zurücksetzen
- `SAVEPOINT` - Speicherpunkte erstellen
- `RELEASE` - Speicherpunkte freigeben

#### Administrative Befehle
- `SHUTDOWN` - Server herunterfahren
- `KILL` - Verbindungen beenden
- `PURGE` - Logs bereinigen
- `RESET` - Zurücksetzen
- `FLUSH` - Caches leeren
- `SET PASSWORD` - Passwort ändern
- `SET GLOBAL` - Globale Variablen setzen
- `SET SESSION` - Sitzungsvariablen setzen (außer read_only)

#### Replikation
- `CHANGE MASTER` - Master ändern
- `START SLAVE` - Slave starten
- `STOP SLAVE` - Slave stoppen

#### MariaDB/MySQL-spezifische Befehle
- `OPTIMIZE TABLE` - Tabellen defragmentieren (Schreiboperation)
- `REPAIR TABLE` - Tabellen reparieren (Schreiboperation)
- `ANALYZE TABLE` - Statistiken aktualisieren (Schreiboperation)
- `CHECK TABLE` - Tabellen prüfen (kann Reparaturen auslösen)
- `CHECKSUM TABLE` - Prüfsummen berechnen

### Erlaubte Befehle

Nur folgende Befehle sind erlaubt:

#### Datenabfragen
- `SELECT` - Daten abfragen
- `WITH` / `CTE` - Common Table Expressions

#### Metadaten-Abfragen
- `SHOW` - Informationen anzeigen (TABLES, DATABASES, COLUMNS, INDEX, etc.)
- `DESCRIBE` / `DESC` - Tabellenstruktur anzeigen
- `EXPLAIN` - Ausführungsplan anzeigen

#### Informationsschema
- `INFORMATION_SCHEMA` - Metadaten abfragen

#### Transaktionssteuerung (nur lesend)
- `START TRANSACTION READ ONLY` - Read-Only Transaktion starten
- `BEGIN READ ONLY` - Read-Only Transaktion beginnen
- `SET TRANSACTION READ ONLY` - Transaktion als read-only setzen

#### Sonstige
- `HELP` - Hilfe anzeigen

> **Hinweis:** `USE` ist nicht mehr als direkte Abfrage erlaubt. Ein Datenbankwechsel erfolgt über den `database`-Parameter der Endpunkte (z. B. `{"query": "...", "database": "mydb"}`). System-Schemata wie `mysql` oder `information_schema` sind gesperrt.

---

## :satellite: API Endpunkte

### MCP Endpunkte (für Open-WebUI)

| Methode | Endpunkt | Beschreibung |
|---------|----------|--------------|
| GET | `/mcp` | MCP Server Information (Tools, Capabilities) |
| POST | `/mcp` | MCP Anfragen verarbeiten |

### Standard API Endpunkte (für direkte Nutzung)

| Methode | Endpunkt | Beschreibung | Parameter |
|---------|----------|--------------|-----------|
| GET | `/` | Server-Informationen | - |
| GET | `/health` | Health-Check | - |
| POST | `/query` | SQL-Abfrage ausführen | `query`, `database` (optional), `timeout` (optional) |
| GET | `/query/validate` | SQL-Abfrage validieren | `query` |
| POST | `/query/validate` | SQL-Abfrage validieren | `query` |
| GET | `/query/stream` | SQL-Abfrage mit Streaming | `query`, `timeout` (optional) |
| GET | `/tables` | Alle Tabellen auflisten | `database` (optional) |
| GET | `/databases` | Alle Datenbanken auflisten | - |
| GET | `/schema/{table}` | Schema einer Tabelle abrufen | `table` |
| GET | `/columns/{table}` | Spalten einer Tabelle abrufen | `table` |
| GET | `/query/examples` | Beispiele für erlaubte Abfragen | - |
| GET | `/openapi.json` | OpenAPI-Spezifikation (auth-pflichtig¹) | - |
| GET | `/docs` | Swagger UI Dokumentation (auth-pflichtig¹) | - |
| GET | `/redoc` | ReDoc Dokumentation (auth-pflichtig¹) | - |

> ¹ Auth-pflichtig, außer `PUBLIC_DOCS=true` ist gesetzt.

---

## :computer: API Beispiele

### Einfache Abfrage mit Authentifizierung

```bash
# Mit Authorization Header
curl -X POST http://localhost:8000/query \
  -H "Authorization: Bearer your-api-token" \
  -H "Content-Type: application/json" \
  -d '{"query": "SELECT * FROM customers LIMIT 10"}'

# Mit Query Parameter
curl -X POST http://localhost:8000/query?api_key=your-api-token \
  -H "Content-Type: application/json" \
  -d '{"query": "SELECT * FROM customers LIMIT 10"}'

# Mit Datenbank-Angabe
curl -X POST http://localhost:8000/query \
  -H "Authorization: Bearer your-api-token" \
  -H "Content-Type: application/json" \
  -d '{"query": "SELECT * FROM mails LIMIT 5", "database": "tanss"}'
```

### MCP Endpunkt testen

```bash
# MCP Server Info abrufen (keine Authentifizierung nötig)
curl http://localhost:8000/mcp

# MCP Anfrage ausführen (mit Authentifizierung)
curl -X POST http://localhost:8000/mcp \
  -H "Authorization: Bearer your-api-token" \
  -H "Content-Type: application/json" \
  -d '{"method": "execute_query", "params": {"query": "SELECT * FROM customers LIMIT 5"}}'
```

### Streaming Abfrage

```bash
curl -H "Authorization: Bearer your-api-token" \
  http://localhost:8000/query/stream?query=SELECT%20*%20FROM%20large_table
```

Antwort (Server-Sent Events):
```
data: {"type": "metadata", "columns": ["id", "name"], "query": "SELECT * FROM large_table"}

data: {"type": "row", "data": {"id": 1, "name": "Row 1"}}

data: {"type": "row", "data": {"id": 2, "name": "Row 2"}}

data: {"type": "complete", "total_rows": 1000}
```

### Abfrage validieren

```bash
curl -X POST http://localhost:8000/query/validate \
  -H "Authorization: Bearer your-api-token" \
  -H "Content-Type: application/json" \
  -d '{"query": "INSERT INTO users VALUES (1, \"test\")"}'
```

Antwort:
```json
{
  "valid": false,
  "error": "Abfrage enthält Schreiboperationen. Nur lesende Abfragen sind erlaubt.",
  "blocked_keywords": ["INSERT"]
}
```

### Tabellen auflisten

```bash
# Alle Tabellen in der aktuellen Datenbank
curl -H "Authorization: Bearer your-api-token" \
  http://localhost:8000/tables

# Tabellen in einer bestimmten Datenbank
curl -H "Authorization: Bearer your-api-token" \
  http://localhost:8000/tables?database=tanss
```

### Schema einer Tabelle abrufen

```bash
curl -H "Authorization: Bearer your-api-token" \
  http://localhost:8000/schema/customers
```

---

## :hourglass: Rate Limiting

Der Server implementiert Rate Limiting, um die API vor übermäßiger Nutzung zu schützen.

### Standard-Konfiguration

- **Aktiviert:** Ja (standardmäßig)
- **Anfragen pro Minute:** 100
- **Burst-Anfragen:** 10
- **Whitelist:** `/`, `/health`

### Rate Limit Header

Jede Antwort enthält folgende Header:
- `X-RateLimit-Limit`: Maximale Anfragen pro Minute
- `X-RateLimit-Remaining`: Verbleibende Anfragen
- `X-RateLimit-Reset`: Zeitstempel, wann das Limit zurückgesetzt wird

### Fehlerbehandlung

Bei Überschreitung des Rate Limits:
- **HTTP Status:** 429 Too Many Requests
- **Header:** `Retry-After: 60` (Sekunden bis zum nächsten Versuch)
- **Body:**
  ```json
  {
    "error": "Too Many Requests",
    "detail": "Rate Limit überschritten. Maximale Anfragen: 100 pro Minute",
    "retry_after": 60
  }
  ```

---

## :test_tube: Testen

### Automatisierte Tests

```bash
# Installiere Test-Abhängigkeiten
pip install pytest httpx

# Führe Tests aus
pytest tests/
```

### Manuelles Testen

1. **Verbindung testen:**
   ```bash
   curl http://localhost:8000/health
   ```

2. **MCP Endpunkt testen:**
   ```bash
   curl http://localhost:8000/mcp
   ```

3. **Erlaubte Abfrage testen:**
   ```bash
   curl -X POST http://localhost:8000/query \
     -H "Authorization: Bearer your-token" \
     -d '{"query": "SELECT 1"}'
   ```

4. **Blockierte Abfrage testen:**
   ```bash
   curl -X POST http://localhost:8000/query \
     -H "Authorization: Bearer your-token" \
     -d '{"query": "INSERT INTO test VALUES (1)"}'
   ```
   --> Sollte Fehler 403 zurückgeben

5. **Authentifizierung testen:**
   ```bash
   # Ohne Token (sollte 401 zurückgeben, wenn Auth aktiviert)
   curl -X POST http://localhost:8000/query \
     -d '{"query": "SELECT 1"}'
   
   # Mit falschem Token (sollte 401 zurückgeben)
   curl -X POST http://localhost:8000/query \
     -H "Authorization: Bearer wrong-token" \
     -d '{"query": "SELECT 1"}'
   
   # Mit richtigem Token (sollte funktionieren)
   curl -X POST http://localhost:8000/query \
     -H "Authorization: Bearer your-correct-token" \
     -d '{"query": "SELECT 1"}'
   ```

---

## :wrench: Fehlerbehebung

### Häufige Probleme und Lösungen

#### 1. Open-WebUI erkennt den MCP Server nicht
- **Ursache:** Falsche URL oder Server nicht erreichbar
- **Lösung:** 
  - URL in Open-WebUI auf `http://localhost:8000` setzen
  - Server-Status prüfen: `curl http://localhost:8000/health`
  - MCP-Endpunkt testen: `curl http://localhost:8000/mcp`

#### 2. "Leere Abfrage" Fehler
- **Ursache:** Open-WebUI sendet die Abfrage in einem anderen Format
- **Lösung:** Der Server unterstützt jetzt:
  - JSON Body: `{"query": "SELECT ..."}`
  - Formular-Daten: `query=SELECT ...`
  - Alternative Feldnamen: `query`, `sql`, `q`
  - Datenbank-Angabe: `{"query": "...", "database": "tanss"}`

#### 3. Verbindung zur Datenbank scheitert
- **Ursache:** Falsche Credentials oder MariaDB nicht für Remote-Zugriff konfiguriert
- **Lösung:**
  - Prüfe `DB_HOST`, `DB_USER`, `DB_PASSWORD` in `docker-compose.yml`
  - MariaDB für Remote-Zugriff konfigurieren:
    ```ini
    # In /etc/mysql/mariadb.conf.d/50-server.cnf
    bind-address = 0.0.0.0
    ```
  - Benutzer berechtigen:
    ```sql
    GRANT SELECT ON *.* TO 'mcp_user'@'%';
    FLUSH PRIVILEGES;
    ```
  - `network_mode: host` in `docker-compose.yml` verwenden

#### 4. Server nicht erreichbar
- **Ursache:** Port Konflikt oder Firewall
- **Lösung:**
  - Prüfe mit `curl http://localhost:8000/health`
  - Port 8000 freigeben: `sudo ufw allow 8000`
  - Andere Dienste auf Port 8000 beenden: `sudo lsof -i :8000`

#### 5. Docker-Container startet nicht
- **Ursache:** Berechtigungsprobleme oder fehlende Abhängigkeiten
- **Lösung:**
  ```bash
  docker-compose down
  docker-compose up -d --build
  docker-compose logs mariadb-mcp-server
  ```

#### 6. Abfragen werden blockiert
- **Ursache:** Abfrage enthält Schreiboperationen
- **Lösung:**
  - Validierung prüfen: `curl -X POST http://localhost:8000/query/validate -d '{"query": "DEINE_ABFRAGE"}'`
  - Nur lesende Abfragen verwenden (SELECT, SHOW, DESCRIBE, etc.)

#### 7. 401 Unauthorized Fehler
- **Ursache:** API-Token-Authentifizierung aktiviert, aber kein oder falscher Token angegeben
- **Lösung:**
  - Token in Authorization Header angeben: `-H "Authorization: Bearer your-token"`
  - Token als Query Parameter angeben: `?api_key=your-token`
  - Token im Request Body angeben: `{"api_key": "your-token"}`
  - Authentifizierung deaktivieren: `DISABLE_API_AUTH=true`

---

## :package: Abhängigkeiten

Der Server verwendet folgende Python-Pakete:

| Paket | Version | Zweck |
|-------|---------|-------|
| fastapi | >=0.104.0 | Web-Framework für die API |
| uvicorn | >=0.24.0 | ASGI-Server |
| mysql-connector-python | >=8.0.0 | MariaDB/MySQL Connector |
| sse-starlette | >=1.6.0 | Server-Sent Events Unterstützung |
| pydantic | >=2.5.0 | Datenvalidierung |
| python-multipart | >=0.0.6 | Formular-Daten Unterstützung |

> **:bulb: Hinweis:** Wir verwenden `mysql-connector-python` statt `mariadb`, da dieser Connector keine externen Systembibliotheken benötigt und damit Docker-freundlicher ist. Er ist vollständig kompatibel mit MariaDB.

---

## :bookmark: Versionshistorie

| Version | Datum | Änderungen |
|---------|-------|------------|
| v1.0.0 | 2026-07-30 | Erste stabile Version |
| | | Read-only SQL-Validierung |
| | | Streaming-Unterstützung |
| | | Docker-Unterstützung |
| | | Wechsel zu mysql-connector-python |
| | | MCP-kompatibler Endpunkt |
| v1.0.1 | 2026-08-03 | Bugfixes |
| | | Behebe "Leere Abfrage" Fehler |
| | | Behebe TRANSACTION READ ONLY Fehler |
| | | Unterstützung für alternative Anfrage-Formate |
| | | Verbesserte Docker-Netzwerk-Konfiguration |
| v1.1.0 | 2026-08-05 | API-Token-Authentifizierung |
| | | Unterstützung für einzelne und mehrere Tokens |
| | | Token aus Datei laden |
| | | Flexible Token-Übertragung (Header, Query) |
| | | Benutzerdefinierte Header/Parameter Namen |
| | | Öffentliche Endpunkte ohne Authentifizierung |
| v1.2.0 | 2026-08-13 | Erweiterte Sicherheit |
| | | Thread-sicheres Rate Limiting |
| | | Korrigierte asyncio-Probleme |
| | | Verbesserte Fehlerbehandlung |
| | | Aktualisierte Dokumentation |
| v1.3.0 | 2026-08-14 | Sicherheits-Härtung |
| | | SQL-Injection-Schutz: Identifier-Validierung, parametrisierte Queries |
| | | USE blockiert, Datenbank-Allow-Liste (ALLOWED_DATABASES) |
| | | Connection-Pool statt globaler Verbindung (Race Condition) |
| | | Auth-Middleware liest Request-Body nicht mehr (kein Doppelkonsum) |
| | | CORS restriktiviert (CORS_ALLOWED_ORIGINS) |
| | | /docs, /openapi.json, /redoc auth-pflichtig (PUBLIC_DOCS) |
| | | Fehlermeldungen leaken keine DB-Interna |
| | | Testsuite repariert (119 Tests) |

---

## :busts_in_silhouette: Mitwirken

1. Fork das Repository
2. Erstelle einen Feature-Branch (`git checkout -b feature/AmazingFeature`)
3. Commit deine Änderungen (`git commit -m 'Add some AmazingFeature'`)
4. Push zum Branch (`git push origin feature/AmazingFeature`)
5. Öffne einen Pull Request

---

## :memo: Lizenz

Dieses Projekt ist unter der MIT-Lizenz lizenziert - siehe [LICENSE](LICENSE) für Details.

---

## :email: Kontakt

- **GitHub:** [AndiAtom/mariadb-mcp-strhttp](https://github.com/AndiAtom/mariadb-mcp-strhttp)
- **Issues:** [GitHub Issues](https://github.com/AndiAtom/mariadb-mcp-strhttp/issues)

---

**Hinweis:** Dieser Server ist **ausschließlich für lesende Abfragen** konzipiert. Alle Versuche, Schreiboperationen auszuführen, werden blockiert und führen zu einem Fehler.

**Technischer Hinweis:** Der Server verwendet `mysql-connector-python`, der vollständig mit MariaDB kompatibel ist und keine externen C-Bibliotheken benötigt, was die Docker-Installation deutlich vereinfacht. Der Server implementiert einen MCP-kompatiblen Endpunkt (`/mcp`) für nahtlose Integration mit Open-WebUI und unterstützt sowohl JSON- als auch Formular-Daten-Anfragen. Die Read-Only-Funktionalität wird auf Session-Ebene (`SET SESSION read_only=ON`) und auf Abfrage-Ebene (Validierung) sichergestellt. Die API-Token-Authentifizierung bietet eine zusätzliche Sicherheitsebene für den Zugriff auf die API.

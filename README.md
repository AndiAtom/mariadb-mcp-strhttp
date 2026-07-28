# MariaDB MCP Server mit streamable HTTP für Open-WebUI

Ein **read-only** MCP Server, der als Schnittstelle zwischen einer MariaDB Datenbank und Open-WebUI dient. Der Server erlaubt **ausschließlich lesende Abfragen** und blockiert alle Schreiboperationen wie INSERT, UPDATE, DELETE, CREATE, ALTER, DROP usw.

> **Hinweis:** Der Server verwendet `mysql-connector-python`, der vollständig mit MariaDB kompatibel ist und keine externen Systembibliotheken benötigt. Der Server ist **MCP-kompatibel** und implementiert die notwendigen Endpunkte für Open-WebUI.

## 🚀 Schnellstart

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
./start_server.sh

# Oder direkt mit Python
python -m src.server
```

## 🔌 Open-WebUI Integration

### MCP Server in Open-WebUI hinzufügen

1. **Öffne Open-WebUI** (z.B. `http://localhost:8080`)
2. **Gehe zu Einstellungen** → **MCP Server** oder **Externe Tool-Server**
3. **Klicke auf "Add MCP Server"** oder **"Neuer Server"**
4. **Füge folgende Konfiguration ein:**

```json
{
  "name": "MariaDB Read-Only",
  "type": "http",
  "url": "http://localhost:8000",
  "readOnly": true,
  "headers": {},
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

> **💡 Hinweis:** Open-WebUI erkennt automatisch den MCP-kompatiblen Endpunkt. Die URL kann einfach `http://localhost:8000` sein, der Server hat sowohl den Standard- als auch den `/mcp`-Endpunkt. Falls Probleme auftreten, versuche `http://localhost:8000/mcp`.

### Verbindung testen

Frage Open-WebUI:
```
"Was sind die Tabellen in der Datenbank?"
```

Erwartete Antwort: Eine Liste aller Tabellen aus deiner MariaDB.

## 📋 Konfiguration

### Umgebungsvariablen

| Variable | Beschreibung | Standardwert |
|----------|--------------|--------------|
| `DB_HOST` | MariaDB Hostname | `localhost` |
| `DB_PORT` | MariaDB Port | `3306` |
| `DB_USER` | MariaDB Benutzername | `root` |
| `DB_PASSWORD` | MariaDB Passwort | `""` |
| `DB_DATABASE` | Standard-Datenbank | `None` |
| `SERVER_HOST` | Server Host | `0.0.0.0` |
| `SERVER_PORT` | Server Port | `8000` |
| `LOG_LEVEL` | Log-Level | `info` |

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
    "database": "mydatabase"
  }
}
```

### Docker Konfiguration für externe MariaDB

Falls deine MariaDB auf einem **externen Host** läuft (z.B. `192.168.222.120`), musst du die `docker-compose.yml` anpassen:

```yaml
services:
  mariadb-mcp-server:
    build: .
    container_name: mariadb-mcp-server
    ports:
      - "8000:8000"
    environment:
      - DB_HOST=192.168.222.120  # Externe IP
      - DB_PORT=3306
      - DB_USER=mcp_user
      - DB_PASSWORD=dein-passwort
      - DB_DATABASE=tanss
      - SERVER_HOST=0.0.0.0
      - SERVER_PORT=8000
      - LOG_LEVEL=info
    network_mode: host  # Wichtig für externe DB-Verbindungen!
    restart: unless-stopped
```

> **Hinweis:** `network_mode: host` ist notwendig, damit der Docker-Container die externe MariaDB erreichen kann.

### MariaDB für Remote-Zugriff konfigurieren

Auf dem MariaDB-Server (`192.168.222.120`):

```bash
# MariaDB Konfiguration bearbeiten
sudo nano /etc/mysql/mariadb.conf.d/50-server.cnf
```

**Ändere:**
```ini
bind-address = 0.0.0.0  # Statt 127.0.0.1
```

**Benutzer für Remote-Zugriff berechtigen:**
```sql
CREATE USER IF NOT EXISTS 'mcp_user'@'%' IDENTIFIED BY 'dein-passwort';
GRANT SELECT ON tanss.* TO 'mcp_user'@'%';
FLUSH PRIVILEGES;
```

**Neu starten:**
```bash
sudo systemctl restart mariadb
```

## 🔒 Sicherheitsfeatures

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
- `SET SESSION` - Sitzungsvariablen setzen

#### Replikation
- `CHANGE MASTER` - Master ändern
- `START SLAVE` - Slave starten
- `STOP SLAVE` - Slave stoppen

### Erlaubte Befehle

Nur folgende Befehle sind erlaubt:

#### Datenabfragen
- `SELECT` - Daten abfragen
- `WITH` / `CTE` - Common Table Expressions

#### Metadaten-Abfragen
- `SHOW` - Informationen anzeigen (TABLES, DATABASES, COLUMNS, INDEX, etc.)
- `DESCRIBE` / `DESC` - Tabellenstruktur anzeigen
- `EXPLAIN` - Ausführungsplan anzeigen
- `ANALYZE` - Ausführungsplan analysieren

#### Informationsschema
- `INFORMATION_SCHEMA` - Metadaten abfragen

#### Transaktionssteuerung (nur lesend)
- `START TRANSACTION READ ONLY` - Read-Only Transaktion starten
- `BEGIN READ ONLY` - Read-Only Transaktion beginnen
- `SET TRANSACTION READ ONLY` - Transaktion als read-only setzen

#### Sonstige
- `USE` - Datenbank auswählen
- `HELP` - Hilfe anzeigen

## 🎯 API Endpunkte

### MCP Endpunkte (für Open-WebUI)

| Methode | Endpunkt | Beschreibung |
|---------|----------|--------------|
| GET | `/mcp` | MCP Server Information (Tools, Capabilities) |
| POST | `/mcp` | MCP Anfragen verarbeiten |

### Standard API Endpunkte (für direkte Nutzung)

| Methode | Endpunkt | Beschreibung |
|---------|----------|--------------|
| GET | `/` | Server-Informationen |
| GET | `/health` | Health-Check |
| POST | `/query` | SQL-Abfrage ausführen |
| GET | `/query/validate` | SQL-Abfrage validieren |
| POST | `/query/validate` | SQL-Abfrage validieren |
| GET | `/query/stream` | SQL-Abfrage mit Streaming |
| GET | `/tables` | Alle Tabellen auflisten |
| GET | `/databases` | Alle Datenbanken auflisten |
| GET | `/schema/{table}` | Schema einer Tabelle abrufen |
| GET | `/columns/{table}` | Spalten einer Tabelle abrufen |
| GET | `/query/examples` | Beispiele für erlaubte Abfragen |

## 📊 API Beispiele

### Einfache Abfrage

```bash
curl -X POST http://localhost:8000/query \
  -H "Content-Type: application/json" \
  -d '{"query": "SELECT * FROM customers LIMIT 10"}'
```

Antwort:
```json
{
  "success": true,
  "results": [
    {"id": 1, "name": "Max Mustermann", "email": "max@example.com"},
    {"id": 2, "name": "Anna Schmidt", "email": "anna@example.com"}
  ],
  "columns": ["id", "name", "email"],
  "row_count": 2,
  "query": "SELECT * FROM customers LIMIT 10"
}
```

### MCP Endpunkt testen

```bash
# MCP Server Info abrufen
curl http://localhost:8000/mcp

# MCP Anfrage ausführen
curl -X POST http://localhost:8000/mcp \
  -H "Content-Type: application/json" \
  -d '{"method": "execute_query", "params": {"query": "SELECT * FROM customers LIMIT 5"}}'
```

### Streaming Abfrage

```bash
curl http://localhost:8000/query/stream?query=SELECT%20*%20FROM%20large_table
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
curl http://localhost:8000/tables
```

Antwort:
```json
{
  "tables": ["customers", "orders", "products"],
  "count": 3
}
```

### Schema einer Tabelle abrufen

```bash
curl http://localhost:8000/schema/customers
```

## 🧪 Testen

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
     -d '{"query": "SELECT 1"}'
   ```

4. **Blockierte Abfrage testen:**
   ```bash
   curl -X POST http://localhost:8000/query \
     -d '{"query": "INSERT INTO test VALUES (1)"}'
   ```
   → Sollte Fehler 403 zurückgeben

## 📦 Abhängigkeiten

Der Server verwendet folgende Python-Pakete:

- **fastapi** - Web-Framework für die API
- **uvicorn** - ASGI-Server
- **mysql-connector-python** - MariaDB/MySQL Connector (vollständig kompatibel mit MariaDB)
- **sse-starlette** - Server-Sent Events Unterstützung
- **pydantic** - Datenvalidierung
- **python-multipart** - Formular-Daten Unterstützung

> **Hinweis:** Wir verwenden `mysql-connector-python` statt `mariadb`, da dieser Connector keine externen Systembibliotheken benötigt und damit Docker-freundlicher ist. Er ist vollständig kompatibel mit MariaDB.

## 🚧 Fehlerbehebung

### Häufige Probleme

#### 1. Open-WebUI erkennt den MCP Server nicht
- **Ursache:** Falsche URL oder Server nicht erreichbar
- **Lösung:** URL in Open-WebUI auf `http://localhost:8000` setzen
- **Test:** `curl http://localhost:8000/health` sollte `{"status": "healthy"}` zurückgeben
- **Alternative:** Versuche `http://localhost:8000/mcp` falls die Standard-URL nicht funktioniert

#### 2. "Leere Abfrage" Fehler
- **Ursache:** Open-WebUI sendet die Abfrage in einem anderen Format als erwartet
- **Lösung:** Der Server unterstützt jetzt sowohl JSON (`{"query": "..."}`) als auch Formular-Daten
- **Test:** `curl -X POST http://localhost:8000/query -d '{"query": "SELECT * FROM belege LIMIT 10"}'`

#### 3. Verbindung zur Datenbank scheitert
- **Ursache:** Falsche Credentials oder MariaDB nicht für Remote-Zugriff konfiguriert
- **Lösung:**
  - Prüfe `DB_HOST`, `DB_USER`, `DB_PASSWORD` in `docker-compose.yml`
  - MariaDB für Remote-Zugriff konfigurieren (siehe oben)
  - `network_mode: host` in `docker-compose.yml` verwenden

#### 4. Server nicht erreichbar
- **Ursache:** Port Konflikt oder Firewall
- **Lösung:**
  - Prüfe mit `curl http://localhost:8000/health`
  - Port 8000 freigeben: `sudo ufw allow 8000`
  - Andere Dienste auf Port 8000 beenden

#### 5. Docker-Container startet nicht
- **Ursache:** Berechtigungsprobleme oder fehlende Abhängigkeiten
- **Lösung:**
  - `docker-compose down && docker-compose up -d --build`
  - Logs prüfen: `docker-compose logs mariadb-mcp-server`

#### 6. Abfragen werden blockiert
- **Ursache:** Abfrage enthält Schreiboperationen
- **Lösung:**
  - Validierung prüfen: `curl -X POST http://localhost:8000/query/validate -d '{"query": "DEINE_ABFRAGE"}'`
  - Nur lesende Abfragen verwenden

### Docker-spezifische Probleme

#### Docker kann externe MariaDB nicht erreichen
- **Ursache:** Docker-Netzwerk-Isolation
- **Lösung:** `network_mode: host` in `docker-compose.yml` verwenden

#### Berechtigungsprobleme im Container
- **Ursache:** Dateien gehören root
- **Lösung:** `chown -R mcpuser:mcpuser /app` in Dockerfile

### MariaDB-spezifische Probleme

#### Benutzer hat keine SELECT-Rechte
```sql
-- Auf der MariaDB ausführen:
GRANT SELECT ON *.* TO 'mcp_user'@'%';
FLUSH PRIVILEGES;
```

#### MariaDB läuft nur auf localhost
```bash
# In /etc/mysql/mariadb.conf.d/50-server.cnf
bind-address = 0.0.0.0
sudo systemctl restart mariadb
```

## 📚 MariaDB & MySQL Dokumentation

Für eine vollständige Liste der SQL-Befehle:
- [MariaDB SQL Statements](https://mariadb.com/docs/server/reference/sql-statements/)
- [MySQL Compatibility with MariaDB](https://mariadb.com/docs/server/references/mariadb-vs-mysql-compatibility/)
- [MySQL Connector/Python Documentation](https://dev.mysql.com/doc/connector-python/en/)

## 🔄 Versionshistorie

- **v1.0.0** (2024-07-28): Erste stabile Version
  - Read-only SQL-Validierung
  - Streaming-Unterstützung
  - Vollständige API-Dokumentation
  - Docker-Unterstützung
  - Wechsel zu mysql-connector-python für bessere Docker-Kompatibilität
  - MCP-kompatibler Endpunkt für Open-WebUI
  - Verbesserte Anfrage-Verarbeitung (JSON und Formular-Daten)

## 🤝 Mitwirken

1. Fork das Repository
2. Erstelle einen Feature-Branch (`git checkout -b feature/AmazingFeature`)
3. Commit deine Änderungen (`git commit -m 'Add some AmazingFeature'`)
4. Push zum Branch (`git push origin feature/AmazingFeature`)
5. Öffne einen Pull Request

## 📄 Lizenz

Dieses Projekt ist unter der MIT-Lizenz lizenziert - siehe [LICENSE](LICENSE) für Details.

## 📞 Kontakt

- **GitHub:** [AndiAtom/mariadb-mcp-strhttp](https://github.com/AndiAtom/mariadb-mcp-strhttp)
- **Issues:** [GitHub Issues](https://github.com/AndiAtom/mariadb-mcp-strhttp/issues)

---

**Hinweis:** Dieser Server ist **ausschließlich für lesende Abfragen** konzipiert. Alle Versuche, Schreiboperationen auszuführen, werden blockiert und führen zu einem Fehler.

**Technischer Hinweis:** Der Server verwendet `mysql-connector-python`, der vollständig mit MariaDB kompatibel ist und keine externen C-Bibliotheken benötigt, was die Docker-Installation deutlich vereinfacht. Der Server implementiert einen MCP-kompatiblen Endpunkt (`/mcp`) für nahtlose Integration mit Open-WebUI und unterstützt sowohl JSON- als auch Formular-Daten-Anfragen.

# MariaDB MCP Server mit streamable HTTP für Open-WebUI

Ein **read-only** MCP Server, der als Schnittstelle zwischen einer MariaDB Datenbank und Open-WebUI dient. Der Server erlaubt **ausschließlich lesende Abfragen** und blockiert alle Schreiboperationen wie INSERT, UPDATE, DELETE, CREATE, ALTER, DROP usw.

> **Hinweis:** Der Server verwendet `mysql-connector-python`, der vollständig mit MariaDB kompatibel ist und keine externen Systembibliotheken benötigt.

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

### Haupt-Endpunkte

| Methode | Endpunkt | Beschreibung |
|---------|----------|--------------|
| GET | `/` | Server-Informationen |
| GET | `/health` | Health-Check |
| POST | `/query` | SQL-Abfrage ausführen |
| GET | `/query/validate` | SQL-Abfrage validieren |
| POST | `/query/validate` | SQL-Abfrage validieren |
| GET | `/query/stream` | SQL-Abfrage mit Streaming |

### Datenbank-Endpunkte

| Methode | Endpunkt | Beschreibung |
|---------|----------|--------------|
| GET | `/tables` | Alle Tabellen auflisten |
| GET | `/tables?database={name}` | Tabellen einer Datenbank auflisten |
| GET | `/databases` | Alle Datenbanken auflisten |
| GET | `/schema/{table}` | Schema einer Tabelle abrufen |
| GET | `/columns/{table}` | Spalten einer Tabelle abrufen |

### Hilfs-Endpunkte

| Methode | Endpunkt | Beschreibung |
|---------|----------|--------------|
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

## 🔧 Open-WebUI Integration

### MCP Server Konfiguration

Füge in Open-WebUI einen neuen MCP Server hinzu:

```json
{
  "name": "MariaDB MCP Server",
  "url": "http://localhost:8000",
  "type": "http",
  "readOnly": true,
  "capabilities": {
    "query": true,
    "stream": true,
    "validate": true
  }
}
```

### Beispiel-Abfragen für Open-WebUI

1. **Daten abfragen:**
   ```sql
   SELECT * FROM customers WHERE status = 'active'
   ```

2. **Tabellenstruktur anzeigen:**
   ```sql
   DESCRIBE customers
   ```

3. **Ausführungsplan analysieren:**
   ```sql
   EXPLAIN SELECT * FROM orders WHERE customer_id = 1
   ```

4. **Datenbanken auflisten:**
   ```sql
   SHOW DATABASES
   ```

5. **Tabellen auflisten:**
   ```sql
   SHOW TABLES
   ```

6. **Read-Only Transaktion:**
   ```sql
   START TRANSACTION READ ONLY;
   SELECT * FROM accounts;
   -- Jede Schreiboperation würde hier fehlschlagen
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

2. **Erlaubte Abfrage testen:**
   ```bash
   curl -X POST http://localhost:8000/query \
     -d '{"query": "SELECT 1"}'
   ```

3. **Blockierte Abfrage testen:**
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

1. **Verbindungsfehler zur Datenbank:**
   - Prüfe Host, Port, Benutzername und Passwort
   - Stelle sicher, dass der MariaDB Server läuft
   - Prüfe die Firewall-Einstellungen
   - Teste die Verbindung manuell: `mysql -h hostname -u user -p`

2. **Blockierte Abfragen:**
   - Der Server blockiert alle Schreiboperationen
   - Verwende nur SELECT, SHOW, DESCRIBE, EXPLAIN usw.
   - Prüfe die Validierung mit `/query/validate`

3. **Port bereits belegt:**
   - Ändere den Port in der Konfiguration
   - Oder beende den bestehenden Prozess

4. **Docker-Probleme:**
   - Stelle sicher, Docker ist installiert und läuft
   - Prüfe die Logs mit `docker-compose logs`
   - Führe einen Clean-Build durch: `docker-compose build --no-cache`

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

**Technischer Hinweis:** Der Server verwendet `mysql-connector-python`, der vollständig mit MariaDB kompatibel ist und keine externen C-Bibliotheken benötigt, was die Docker-Installation deutlich vereinfacht.

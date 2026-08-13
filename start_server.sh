#!/bin/bash

# MariaDB MCP Server Startskript

echo "Starte MariaDB MCP Server für Open-WebUI..."
echo "============================================"

# Lade Konfiguration aus Umgebungsvariablen oder verwende Standardwerte.
# WICHTIG: In Produktion einen dedizierten Read-Only-DB-User setzen, nicht root.
export DB_HOST=${DB_HOST:-"localhost"}
export DB_PORT=${DB_PORT:-3306}
export DB_USER=${DB_USER:-"mcpuser"}
export DB_PASSWORD=${DB_PASSWORD:-""}
export DB_DATABASE=${DB_DATABASE:-""}
export SERVER_HOST=${SERVER_HOST:-"0.0.0.0"}
export SERVER_PORT=${SERVER_PORT:-8000}
export LOG_LEVEL=${LOG_LEVEL:-"info"}

echo "Datenbank-Konfiguration:"
echo "  Host: $DB_HOST"
echo "  Port: $DB_PORT"
echo "  Benutzer: $DB_USER"
echo "  Datenbank: ${DB_DATABASE:-(keine, standardmäßig aktuell ausgewählte)}"
echo ""

echo "Server-Konfiguration:"
echo "  Host: $SERVER_HOST"
echo "  Port: $SERVER_PORT"
echo "  Log-Level: $LOG_LEVEL"
echo ""

# Prüfe, ob Python installiert ist
if ! command -v python3 &> /dev/null; then
    echo "FEHLER: Python3 ist nicht installiert"
    exit 1
fi

# Starte den Server direkt (die Abhängigkeiten sind bereits in requirements.txt)
echo "Server wird gestartet... (Drücke STRG+C zum Beenden)"
echo ""

python3 -m src.server
__START_EOF__
chmod +x /workspace/AndiAtom__mariadb-mcp-strhttp/start_server.sh && echo "start_server.sh written" && bash -n /workspace/AndiAtom__mariadb-mcp-strhttp/start_server.sh && echo "bash syntax OK"
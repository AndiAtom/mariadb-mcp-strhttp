#!/bin/bash

# MariaDB MCP Server Startskript

echo "Starte MariaDB MCP Server für Open-WebUI..."
echo "============================================"

# Lade Konfiguration aus Umgebungsvariablen oder verwende Standardwerte
export DB_HOST=${DB_HOST:-"localhost"}
export DB_PORT=${DB_PORT:-3306}
export DB_USER=${DB_USER:-"root"}
export DB_PASSWORD=${DB_PASSWORD:-"",}
export DB_DATABASE=${DB_DATABASE:-"",}
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

# Prüfe, ob Python und die benötigten Pakete installiert sind
if ! command -v python3 &> /dev/null; then
    echo "FEHLER: Python3 ist nicht installiert"
    exit 1
fi

if ! python3 -c "import fastapi; import uvicorn; import mariadb" 2> /dev/null; then
    echo "Installiere benötigte Pakete..."
    pip install fastapi uvicorn mariadb sse-starlette
fi

# Starte den Server
echo "Server wird gestartet... (Drücke STRG+C zum Beenden)"
echo ""

python3 -m src.server

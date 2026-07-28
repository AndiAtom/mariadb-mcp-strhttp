# MariaDB MCP Server Dockerfile
# Verwende mysql-connector-python statt mariadb, um Systemabhängigkeiten zu vermeiden
FROM python:3.11-slim

# Setze Umgebungsvariablen
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Arbeitsverzeichnis
WORKDIR /app

# Kopiere Anforderungen und installiere Abhängigkeiten
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Kopiere den Quellcode
COPY src/ ./src/
COPY config.json .

# Erstelle einen nicht-root Benutzer
RUN useradd -m -u 1000 mcpuser
USER mcpuser

# Kopiere das Startskript
COPY start_server.sh .
RUN chmod +x start_server.sh

# Standardmäßig Port 8000 freigeben
EXPOSE 8000

# Health Check
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Startbefehl
CMD ["./start_server.sh"]

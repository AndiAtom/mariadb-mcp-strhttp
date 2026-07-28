"""
Tests für die Server-Endpunkte
"""

import pytest
import sys
import os
from fastapi.testclient import TestClient

# Füge den src-Pfad zum Python-Pfad hinzu
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from server import app, db_connection


class TestServerEndpoints:
    """Testet die Server-Endpunkte"""
    
    def setup_method(self):
        """Setup für jeden Test"""
        self.client = TestClient(app)
    
    def teardown_method(self):
        """Cleanup nach jedem Test"""
        pass
    
    def test_root_endpoint(self):
        """Root-Endpoint sollte Server-Informationen zurückgeben"""
        response = self.client.get("/")
        assert response.status_code == 200
        data = response.json()
        assert data["server"] == "MariaDB MCP Server"
        assert data["version"] == "1.0.0"
        assert data["read_only"] is True
        assert "endpoints" in data
    
    def test_health_check(self):
        """Health-Check sollte Status zurückgeben"""
        response = self.client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert "status" in data
        assert "database_connected" in data
    
    def test_query_validation_get(self):
        """GET /query/validate sollte Abfragen validieren"""
        # Gültige Abfrage
        response = self.client.get("/query/validate", params={"query": "SELECT 1"})
        assert response.status_code == 200
        data = response.json()
        assert data["valid"] is True
        
        # Ungültige Abfrage
        response = self.client.get("/query/validate", params={"query": "INSERT INTO test VALUES (1)"})
        assert response.status_code == 200
        data = response.json()
        assert data["valid"] is False
        assert "Schreiboperationen" in data["error"]
    
    def test_query_validation_post(self):
        """POST /query/validate sollte Abfragen validieren"""
        # Gültige Abfrage
        response = self.client.post("/query/validate", json={"query": "SELECT 1"})
        assert response.status_code == 200
        data = response.json()
        assert data["valid"] is True
        
        # Ungültige Abfrage
        response = self.client.post("/query/validate", json={"query": "DELETE FROM test"})
        assert response.status_code == 200
        data = response.json()
        assert data["valid"] is False
    
    def test_query_execution_blocked(self):
        """Schreiboperationen sollten blockiert werden"""
        response = self.client.post("/query", json={"query": "INSERT INTO test VALUES (1)"})
        assert response.status_code == 403
        data = response.json()
        assert "Schreiboperationen" in data["detail"]
    
    def test_query_execution_empty(self):
        """Leere Abfrage sollte Fehler zurückgeben"""
        response = self.client.post("/query", json={"query": ""})
        assert response.status_code == 400
    
    def test_query_execution_no_query_field(self):
        """Fehlendes query-Feld sollte Fehler zurückgeben"""
        response = self.client.post("/query", json={})
        assert response.status_code == 400
    
    def test_query_examples(self):
        """/query/examples sollte Beispiele zurückgeben"""
        response = self.client.get("/query/examples")
        assert response.status_code == 200
        data = response.json()
        assert "examples" in data
        assert len(data["examples"]) > 0
        assert "basic_select" in data["examples"]
        assert "show_tables" in data["examples"]


class TestQueryExamples:
    """Testet die Beispiel-Abfragen"""
    
    def setup_method(self):
        """Setup für jeden Test"""
        self.client = TestClient(app)
    
    def test_all_examples_are_valid(self):
        """Alle Beispiel-Abfragen sollten gültig sein"""
        response = self.client.get("/query/examples")
        assert response.status_code == 200
        data = response.json()
        
        for example_name, example_data in data["examples"].items():
            query = example_data["query"]
            validation_response = self.client.get("/query/validate", params={"query": query})
            assert validation_response.status_code == 200
            validation_data = validation_response.json()
            assert validation_data["valid"], f"Beispiel '{example_name}' sollte gültig sein: {query}"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

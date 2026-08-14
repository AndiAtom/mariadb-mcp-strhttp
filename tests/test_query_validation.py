"""
Tests für die SQL-Abfrage-Validierung
"""

import pytest
import re
import sys
import os

# Füge den src-Pfad zum Python-Pfad hinzu
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

# Authentifizierung in Tests deaktivieren
os.environ["DISABLE_API_AUTH"] = "true"

# Importiere nur die Validierungsfunktionen, nicht den gesamten Server
from server import (
    is_read_only_query,
    validate_query,
    validate_identifier,
    is_allowed_database,
    BLOCKED_KEYWORDS,
)


class TestQueryValidation:
    """Testet die Validierung von SQL-Abfragen"""
    
    def test_empty_query(self):
        """Leere Abfrage sollte ungültig sein"""
        result = validate_query("")
        assert not result["valid"]
        assert "Leere Abfrage" in result["error"]
    
    def test_whitespace_only_query(self):
        """Abfrage mit nur Leerzeichen sollte ungültig sein"""
        result = validate_query("   ")
        assert not result["valid"]
    
    def test_simple_select_query(self):
        """Einfache SELECT-Abfrage sollte gültig sein"""
        result = validate_query("SELECT * FROM users")
        assert result["valid"]
    
    def test_select_with_where(self):
        """SELECT mit WHERE sollte gültig sein"""
        result = validate_query("SELECT * FROM users WHERE id = 1")
        assert result["valid"]
    
    def test_select_with_join(self):
        """SELECT mit JOIN sollte gültig sein"""
        result = validate_query("""
            SELECT u.*, o.total 
            FROM users u 
            JOIN orders o ON u.id = o.user_id
        """)
        assert result["valid"]
    
    def test_show_tables(self):
        """SHOW TABLES sollte gültig sein"""
        result = validate_query("SHOW TABLES")
        assert result["valid"]
    
    def test_describe_table(self):
        """DESCRIBE sollte gültig sein"""
        result = validate_query("DESCRIBE users")
        assert result["valid"]
        
        result = validate_query("DESC users")
        assert result["valid"]
    
    def test_explain_query(self):
        """EXPLAIN sollte gültig sein"""
        result = validate_query("EXPLAIN SELECT * FROM users")
        assert result["valid"]
    
    def test_show_databases(self):
        """SHOW DATABASES sollte gültig sein"""
        result = validate_query("SHOW DATABASES")
        assert result["valid"]
    
    def test_show_columns(self):
        """SHOW COLUMNS sollte gültig sein"""
        result = validate_query("SHOW COLUMNS FROM users")
        assert result["valid"]
    
    def test_information_schema(self):
        """INFORMATION_SCHEMA-Abfragen sollten gültig sein"""
        result = validate_query("SELECT * FROM INFORMATION_SCHEMA.TABLES")
        assert result["valid"]
    
    def test_read_only_transaction(self):
        """Read-Only Transaktionen sollten gültig sein"""
        result = validate_query("START TRANSACTION READ ONLY")
        assert result["valid"]
        
        result = validate_query("BEGIN READ ONLY")
        assert result["valid"]
        
        result = validate_query("SET TRANSACTION READ ONLY")
        assert result["valid"]
    
    # Blockierte Abfragen
    
    def test_insert_query(self):
        """INSERT sollte blockiert werden"""
        result = validate_query("INSERT INTO users VALUES (1, 'test')")
        assert not result["valid"]
        assert "Schreiboperationen" in result["error"]
        assert "INSERT" in result["blocked_keywords"]
    
    def test_update_query(self):
        """UPDATE sollte blockiert werden"""
        result = validate_query("UPDATE users SET name = 'test' WHERE id = 1")
        assert not result["valid"]
        assert "UPDATE" in result["blocked_keywords"]
    
    def test_delete_query(self):
        """DELETE sollte blockiert werden"""
        result = validate_query("DELETE FROM users WHERE id = 1")
        assert not result["valid"]
        assert "DELETE" in result["blocked_keywords"]
    
    def test_create_table(self):
        """CREATE TABLE sollte blockiert werden"""
        result = validate_query("CREATE TABLE test (id INT)")
        assert not result["valid"]
        assert "CREATE" in result["blocked_keywords"]
    
    def test_alter_table(self):
        """ALTER TABLE sollte blockiert werden"""
        result = validate_query("ALTER TABLE users ADD COLUMN email VARCHAR(255)")
        assert not result["valid"]
        assert "ALTER" in result["blocked_keywords"]
    
    def test_drop_table(self):
        """DROP TABLE sollte blockiert werden"""
        result = validate_query("DROP TABLE users")
        assert not result["valid"]
        assert "DROP" in result["blocked_keywords"]
    
    def test_truncate_table(self):
        """TRUNCATE sollte blockiert werden"""
        result = validate_query("TRUNCATE TABLE users")
        assert not result["valid"]
        assert "TRUNCATE" in result["blocked_keywords"]
    
    def test_optimize_table(self):
        """OPTIMIZE TABLE sollte blockiert werden (MariaDB-spezifisch)"""
        result = validate_query("OPTIMIZE TABLE users")
        assert not result["valid"]
        assert "OPTIMIZE" in result["blocked_keywords"]
    
    def test_repair_table(self):
        """REPAIR TABLE sollte blockiert werden (MariaDB-spezifisch)"""
        result = validate_query("REPAIR TABLE users")
        assert not result["valid"]
        assert "REPAIR" in result["blocked_keywords"]
    
    def test_analyze_table(self):
        """ANALYZE TABLE sollte blockiert werden (MariaDB-spezifisch)"""
        result = validate_query("ANALYZE TABLE users")
        assert not result["valid"]
        assert "ANALYZE TABLE" in result["blocked_keywords"]
    
    def test_check_table(self):
        """CHECK TABLE sollte blockiert werden (MariaDB-spezifisch)"""
        result = validate_query("CHECK TABLE users")
        assert not result["valid"]
        assert "CHECK TABLE" in result["blocked_keywords"]
    
    def test_checksum_table(self):
        """CHECKSUM TABLE sollte blockiert werden (MariaDB-spezifisch)"""
        result = validate_query("CHECKSUM TABLE users")
        assert not result["valid"]
        assert "CHECKSUM" in result["blocked_keywords"]
    
    def test_grant_privileges(self):
        """GRANT sollte blockiert werden"""
        result = validate_query("GRANT SELECT ON users TO testuser")
        assert not result["valid"]
        assert "GRANT" in result["blocked_keywords"]
    
    def test_revoke_privileges(self):
        """REVOKE sollte blockiert werden"""
        result = validate_query("REVOKE SELECT ON users FROM testuser")
        assert not result["valid"]
        assert "REVOKE" in result["blocked_keywords"]
    
    def test_commit_transaction(self):
        """COMMIT sollte blockiert werden"""
        result = validate_query("COMMIT")
        assert not result["valid"]
        assert "COMMIT" in result["blocked_keywords"]
    
    def test_rollback_transaction(self):
        """ROLLBACK sollte blockiert werden"""
        result = validate_query("ROLLBACK")
        assert not result["valid"]
        assert "ROLLBACK" in result["blocked_keywords"]
    
    def test_shutdown_server(self):
        """SHUTDOWN sollte blockiert werden"""
        result = validate_query("SHUTDOWN")
        assert not result["valid"]
        assert "SHUTDOWN" in result["blocked_keywords"]
    
    def test_set_password(self):
        """SET PASSWORD sollte blockiert werden"""
        result = validate_query("SET PASSWORD FOR 'user'@'host' = PASSWORD('newpass')")
        assert not result["valid"]
    
    def test_set_global(self):
        """SET GLOBAL sollte blockiert werden"""
        result = validate_query("SET GLOBAL max_connections = 100")
        assert not result["valid"]
    
    def test_call_procedure(self):
        """CALL sollte blockiert werden (da wir nicht wissen, ob die Prozedur lesend ist)"""
        result = validate_query("CALL update_user(1, 'newname')")
        assert not result["valid"]
    
    def test_multi_statement_with_write(self):
        """Mehrere Anweisungen mit Schreiboperation sollten blockiert werden"""
        result = validate_query("SELECT * FROM users; INSERT INTO log VALUES (1)")
        assert not result["valid"]
        assert "INSERT" in result["blocked_keywords"]
    
    def test_commented_write_query(self):
        """Schreiboperationen in Kommentaren sollten ignoriert werden"""
        result = validate_query("SELECT * FROM users -- INSERT INTO test VALUES (1)")
        assert result["valid"]
        
        result = validate_query("SELECT * FROM users /* DROP TABLE users */")
        assert result["valid"]
    
    def test_case_insensitive(self):
        """Validierung sollte case-insensitive sein"""
        result = validate_query("select * from users")
        assert result["valid"]
        
        result = validate_query("INSERT INTO users VALUES (1)")
        assert not result["valid"]
        
        result = validate_query("insert into users values (1)")
        assert not result["valid"]
    
    def test_with_clause(self):
        """WITH/CTE sollte erlaubt sein"""
        result = validate_query("""
            WITH active_users AS (
                SELECT * FROM users WHERE status = 'active'
            )
            SELECT * FROM active_users
        """)
        assert result["valid"]
    
    def test_subqueries(self):
        """Subqueries sollten erlaubt sein"""
        result = validate_query("""
            SELECT * FROM users 
            WHERE id IN (SELECT user_id FROM orders WHERE total > 100)
        """)
        assert result["valid"]
    
    def test_use_database_blocked(self):
        """USE sollte blockiert werden (Datenbankwechsel nur über database-Parameter)"""
        result = validate_query("USE mydatabase")
        assert not result["valid"]
    
    def test_help_command(self):
        """HELP sollte erlaubt sein"""
        result = validate_query("HELP")
        assert result["valid"]


class TestBlockedKeywords:
    """Testet, dass alle blockierten Keywords tatsächlich blockiert werden
    
    Regex-Keywords (z. B. 'START\\s+SLAVE') werden hier ausgeschlossen, da sie
    als literaler String ('START\\s+SLAVE test') nie matchen würden. Sie werden
    separat in TestRegexKeywords mit korrekten SQL-Statements getestet.
    """
    
    @pytest.mark.parametrize(
        "keyword",
        [kw for kw in BLOCKED_KEYWORDS if isinstance(kw, str) and '\\' not in kw]
    )
    def test_all_blocked_keywords(self, keyword):
        """Jedes blockierte Keyword sollte die Validierung fehlschlagen lassen"""
        query = f"{keyword} test"
        result = validate_query(query)
        assert not result["valid"], f"Keyword '{keyword}' sollte blockiert werden"


class TestRegexKeywords:
    """Testet, dass Regex-basierte blockierte Keywords korrekt blockiert werden"""
    
    @pytest.mark.parametrize(
        "query",
        [
            "SET PASSWORD FOR 'user'@'host' = PASSWORD('newpass')",
            "SET GLOBAL max_connections = 100",
            "CHANGE MASTER TO MASTER_HOST='host'",
            "START SLAVE",
            "STOP SLAVE",
        ]
    )
    def test_regex_keywords_blocked(self, query):
        """Regex-Keywords sollten in realen SQL-Statements blockiert werden"""
        result = validate_query(query)
        assert not result["valid"], f"Abfrage sollte blockiert werden: {query}"


class TestIdentifierValidation:
    """Testet die Validierung von SQL-Bezeichnern (SQL-Injection-Schutz)"""
    
    def test_valid_identifier(self):
        """Gültige Bezeichner sollten akzeptiert werden"""
        assert validate_identifier("users") == "users"
        assert validate_identifier("my_table_123") == "my_table_123"
        assert validate_identifier("TestTable") == "TestTable"
    
    def test_invalid_identifier_rejected(self):
        """Bezeichner mit Sonderzeichen sollten abgelehnt werden (Injektionsschutz)"""
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc:
            validate_identifier("users'; DROP TABLE y--")
        assert exc.value.status_code == 400
    
    def test_empty_identifier_rejected(self):
        """Leere Bezeichner sollten abgelehnt werden"""
        from fastapi import HTTPException
        with pytest.raises(HTTPException):
            validate_identifier("")
    
    def test_identifier_with_space_rejected(self):
        """Bezeichner mit Leerzeichen sollten abgelehnt werden"""
        from fastapi import HTTPException
        with pytest.raises(HTTPException):
            validate_identifier("evil name")
    
    def test_identifier_with_backtick_rejected(self):
        """Bezeichner mit Backticks sollten abgelehnt werden"""
        from fastapi import HTTPException
        with pytest.raises(HTTPException):
            validate_identifier("users`")


class TestDatabaseAllowList:
    """Testet die Allow-List-Logik für Datenbanknamen"""
    
    def test_system_databases_blocked(self):
        """System-Schemata sollten immer blockiert werden"""
        assert not is_allowed_database("mysql")
        assert not is_allowed_database("information_schema")
        assert not is_allowed_database("performance_schema")
        assert not is_allowed_database("sys")
    
    def test_normal_database_allowed(self):
        """Nicht-System-Datenbanken sollten ohne Positiv-Liste erlaubt sein"""
        assert is_allowed_database("testdb")
        assert is_allowed_database("myapp")
    
    def test_invalid_database_name_blocked(self):
        """Ungültige Bezeichner sollten blockiert werden"""
        assert not is_allowed_database("db'; DROP--")
        assert not is_allowed_database("")
        assert not is_allowed_database("db with space")
    
    def test_empty_database_blocked(self):
        assert not is_allowed_database("")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

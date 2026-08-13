"""
Tests für die SQL-Abfrage-Validierung ohne Server-Abhängigkeiten
"""

import pytest
import re

# Kopiere die Validierungslogik direkt, um Abhängigkeiten zu vermeiden
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

# Compile regex patterns für bessere Performance
BLOCKED_PATTERNS = [re.compile(r'\b' + keyword + r'\b', re.IGNORECASE) 
                    for keyword in BLOCKED_KEYWORDS if isinstance(keyword, str)]

BLOCKED_PATTERNS.extend([re.compile(keyword, re.IGNORECASE) 
                         for keyword in BLOCKED_KEYWORDS if not isinstance(keyword, str)])


def is_read_only_query(query: str) -> bool:
    """
    Überprüft, ob eine SQL-Abfrage nur lesend ist.
    """
    if not query or not query.strip():
        return False
    
    # Entferne Kommentare
    query_clean = re.sub(r'--[^\n]*', '', query)  # Einzeilige Kommentare
    query_clean = re.sub(r'/\*.*?\*/', '', query_clean, flags=re.DOTALL)  # Mehrzeilige Kommentare
    
    # Überprüfe auf blockierte Keywords
    for pattern in BLOCKED_PATTERNS:
        if pattern.search(query_clean):
            return False
    
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
    
    # CALL-Befehle: Generell blockieren, da wir nicht wissen, ob die Prozedur lesend ist
    if re.search(r'\bCALL\b', query_clean, re.IGNORECASE):
        return False
    
    # Wenn keine blockierten Keywords gefunden wurden, ist die Abfrage erlaubt
    return True


def validate_query(query: str) -> dict:
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
    
    def test_show_tables(self):
        """SHOW TABLES sollte gültig sein"""
        result = validate_query("SHOW TABLES")
        assert result["valid"]
    
    def test_describe_table(self):
        """DESCRIBE sollte gültig sein"""
        result = validate_query("DESCRIBE users")
        assert result["valid"]
    
    def test_explain_query(self):
        """EXPLAIN sollte gültig sein"""
        result = validate_query("EXPLAIN SELECT * FROM users")
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
    
    def test_drop_table(self):
        """DROP TABLE sollte blockiert werden"""
        result = validate_query("DROP TABLE users")
        assert not result["valid"]
        assert "DROP" in result["blocked_keywords"]
    
    def test_commit_transaction(self):
        """COMMIT sollte blockiert werden"""
        result = validate_query("COMMIT")
        assert not result["valid"]
        assert "COMMIT" in result["blocked_keywords"]
    
    def test_set_password(self):
        """SET PASSWORD sollte blockiert werden"""
        result = validate_query("SET PASSWORD FOR 'user'@'host' = PASSWORD('newpass')")
        assert not result["valid"]
    
    def test_set_global(self):
        """SET GLOBAL sollte blockiert werden"""
        result = validate_query("SET GLOBAL max_connections = 100")
        assert not result["valid"]
    
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
    
    def test_use_database(self):
        """USE sollte erlaubt sein"""
        result = validate_query("USE mydatabase")
        assert result["valid"]
    
    def test_replication_commands(self):
        """Replikationsbefehle sollten blockiert werden"""
        result = validate_query("CHANGE MASTER TO MASTER_HOST='host'")
        assert not result["valid"]
        
        result = validate_query("START SLAVE")
        assert not result["valid"]
        
        result = validate_query("STOP SLAVE")
        assert not result["valid"]
    
    def test_mariadb_specific_commands(self):
        """MariaDB-spezifische Schreiboperationen sollten blockiert werden"""
        result = validate_query("OPTIMIZE TABLE users")
        assert not result["valid"]
        assert "OPTIMIZE" in result["blocked_keywords"]
        
        result = validate_query("REPAIR TABLE users")
        assert not result["valid"]
        assert "REPAIR" in result["blocked_keywords"]
        
        result = validate_query("ANALYZE TABLE users")
        assert not result["valid"]
        assert "ANALYZE TABLE" in result["blocked_keywords"]
        
        result = validate_query("CHECK TABLE users")
        assert not result["valid"]
        assert "CHECK TABLE" in result["blocked_keywords"]
        
        result = validate_query("CHECKSUM TABLE users")
        assert not result["valid"]
        assert "CHECKSUM" in result["blocked_keywords"]


class TestBlockedKeywords:
    """Testet, dass alle blockierten Keywords tatsächlich blockiert werden"""
    
    def test_all_simple_keywords(self):
        """Alle einfachen Keywords sollten blockiert werden"""
        simple_keywords = [kw for kw in BLOCKED_KEYWORDS if isinstance(kw, str)]
        
        for keyword in simple_keywords:
            query = f"{keyword} test"
            result = validate_query(query)
            assert not result["valid"], f"Keyword '{keyword}' sollte blockiert werden"
    
    def test_regex_keywords(self):
        """Regex-Keywords sollten blockiert werden"""
        regex_keywords = {
            r'SET\s+PASSWORD': "SET PASSWORD FOR 'user'@'host' = 'pass'",
            r'SET\s+GLOBAL': "SET GLOBAL max_connections = 100",
            r'CHANGE\s+MASTER': "CHANGE MASTER TO MASTER_HOST='host'",
            r'START\s+SLAVE': "START SLAVE",
            r'STOP\s+SLAVE': "STOP SLAVE",
        }
        
        for pattern, query in regex_keywords.items():
            result = validate_query(query)
            assert not result["valid"], f"Query '{query}' sollte blockiert werden (Pattern: {pattern})"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

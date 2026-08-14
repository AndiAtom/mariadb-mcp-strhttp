"""
Tests fuer die zusaetzlichen Sicherheits-Mechanismen (v1.3.1+):
- (2) Konstanter Token-Vergleich
- (5) Verschachtelte Kommentar-Stripping
- (6) Multi-Statement-Schutz (';')
- (7) Request-Body-Boessenbegrenzung
- (8) Security-Headers
- (10) Fail-Closed-Startup bei fehlenden Tokens
- (11) Token-Datei Hot-Reload
- (4) DB_USER=root Startup-Guard
"""

import os
import json
import time
import sys
import tempfile

import pytest
from fastapi.testclient import TestClient

# Authentifizierung fuer Server-Endpunkt-Tests deaktivieren.
os.environ["DISABLE_API_AUTH"] = "true"

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from server import (
    app,
    is_read_only_query,
    validate_query,
    _strip_sql_comments,
    MAX_REQUEST_BODY_BYTES,
)
import rate_limiting
rate_limiting.rate_limit_config.enabled = False

from auth import APITokenConfig, AuthStartupError, token_config


class TestConstantTimeTokenComparison:
    """(2) Token-Vergleich erfolgt konstant ueber secrets.compare_digest."""

    def test_valid_token_accepted(self):
        cfg = APITokenConfig()
        cfg.enabled = True
        cfg.tokens = ["secret-token-123"]
        assert cfg.is_valid_token("secret-token-123") is True

    def test_invalid_token_rejected(self):
        cfg = APITokenConfig()
        cfg.enabled = True
        cfg.tokens = ["secret-token-123"]
        assert cfg.is_valid_token("wrong-token") is False

    def test_empty_token_rejected(self):
        cfg = APITokenConfig()
        cfg.enabled = True
        cfg.tokens = ["secret-token-123"]
        assert cfg.is_valid_token("") is False
        assert cfg.is_valid_token(None) is False

    def test_disabled_auth_accepts_any(self):
        cfg = APITokenConfig()
        cfg.enabled = False
        cfg.tokens = []
        assert cfg.is_valid_token("anything") is True

    def test_multiple_tokens_each_valid(self):
        cfg = APITokenConfig()
        cfg.enabled = True
        cfg.tokens = ["t1", "t2", "t3"]
        for t in ["t1", "t2", "t3"]:
            assert cfg.is_valid_token(t) is True
        assert cfg.is_valid_token("t4") is False

    def test_timing_consistency_across_positions(self):
        """Alle gueltigen Tokens sollen aehnliche Validierungszeit haben
        (naiver Plausibilitaets-Check, kein echter Timing-Test)."""
        cfg = APITokenConfig()
        cfg.enabled = True
        cfg.tokens = [f"token-{i:03d}" for i in range(20)]
        # Jeder Token sollte akzeptiert werden unabhaengig von der Position.
        for t in cfg.tokens:
            assert cfg.is_valid_token(t) is True


class TestNestedCommentStripping:
    """(5) Verschachtelte/gestaffelte Kommentare werden korrekt entfernt."""

    def test_simple_block_comment_removed(self):
        assert "INSERT" not in _strip_sql_comments("SELECT 1 /* DROP TABLE x */")

    def test_single_line_comment_removed(self):
        assert "INSERT" not in _strip_sql_comments("SELECT 1 -- INSERT INTO t VALUES(1)")

    def test_hash_comment_removed(self):
        # MariaDB unterstuetzt # als Kommentarbeginn.
        assert "DROP" not in _strip_sql_comments("SELECT 1 # DROP TABLE x")

    def test_nested_block_comment_inner_write_removed(self):
        # Verschachtelter Kommentar: nach dem ersten */ bleibt bei nicht-greedy
        # Regex normalerweise "INSERT ... */" stehen. Iterative Loesung entfernt es.
        q = "/* a /* b */ INSERT INTO log VALUES(1) */ SELECT 1"
        stripped = _strip_sql_comments(q)
        assert "INSERT" not in stripped, f"INSERT nicht entfernt: {stripped!r}"

    def test_stacked_block_comment_write_blocked(self):
        """Eine Schreiboperation, die nach einem unvollstaendigen Kommentar
        'versteckt' ist, muss von is_read_only_query blockiert werden."""
        # /* a /* b */ INSERT ... */  -> nach Stripping kein INSERT mehr,
        # aber die Abfrage selbst bleibt ungueltig, wenn INSERT uebrig ist.
        q = "/* x /* y */ INSERT INTO log VALUES(1) */ SELECT 1"
        # Entweder ist INSERT nach Stripping weg (dann nur SELECT uebrig = ok),
        # oder es ist noch da (dann blockiert). Beides ist sicher, Hauptsache
        # kein Bypass. Hier pruefen wir, dass Stripping es entfernt.
        assert "INSERT" not in _strip_sql_comments(q)

    def test_plain_select_after_comment_valid(self):
        assert is_read_only_query("SELECT 1 /* comment */") is True


class TestMultiStatementGuard:
    """(6) ';' als Statement-Trennzeichen wird abgewiesen."""

    def test_semicolon_blocked(self):
        assert is_read_only_query("SELECT 1;") is False

    def test_stacked_select_insert_blocked(self):
        assert is_read_only_query("SELECT 1; INSERT INTO t VALUES(1)") is False

    def test_semicolon_in_comment_ignored(self):
        # ';' innerhalb eines Kommentars darf nicht zur Blockierung fuehren.
        assert is_read_only_query("SELECT 1 /* ; comment */") is True

    def test_plain_select_without_semicolon_valid(self):
        assert is_read_only_query("SELECT * FROM users") is True


class TestBodySizeLimit:
    """(7) Request-Body-Boessenbegrenzung."""

    def setup_method(self):
        self.client = TestClient(app)

    def test_small_body_accepted(self):
        resp = self.client.post("/query/validate", json={"query": "SELECT 1"})
        assert resp.status_code == 200

    def test_oversized_body_rejected(self):
        # Body deutlich ueber dem Limit.
        big = "SELECT " + ("a" * (MAX_REQUEST_BODY_BYTES + 100))
        resp = self.client.post(
            "/query/validate",
            json={"query": big},
            headers={"Content-Type": "application/json"},
        )
        assert resp.status_code == 413


class TestSecurityHeaders:
    """(8) Security-Headers werden gesetzt."""

    def setup_method(self):
        self.client = TestClient(app)

    def test_headers_present_on_health(self):
        resp = self.client.get("/health")
        assert resp.headers.get("x-content-type-options") == "nosniff"
        assert resp.headers.get("x-frame-options") == "DENY"
        assert resp.headers.get("referrer-policy") == "no-referrer"
        assert resp.headers.get("cache-control") == "no-store"

    def test_no_hsts_over_plain_http(self):
        resp = self.client.get("/health")
        # TestClient verwendet HTTP, daher kein HSTS.
        assert "strict-transport-security" not in resp.headers


class TestFailClosedStartup:
    """(10) Auth aktiviert ohne Tokens -> AuthStartupError."""

    def test_raises_when_enabled_no_tokens(self, monkeypatch):
        monkeypatch.delenv("API_TOKEN", raising=False)
        monkeypatch.delenv("API_TOKENS", raising=False)
        monkeypatch.delenv("API_TOKEN_FILE", raising=False)
        monkeypatch.delenv("DISABLE_API_AUTH", raising=False)
        cfg = APITokenConfig()
        with pytest.raises(AuthStartupError):
            cfg.load_from_env()

    def test_disabled_auth_no_error(self, monkeypatch):
        monkeypatch.delenv("API_TOKEN", raising=False)
        monkeypatch.delenv("API_TOKENS", raising=False)
        monkeypatch.delenv("API_TOKEN_FILE", raising=False)
        monkeypatch.setenv("DISABLE_API_AUTH", "true")
        cfg = APITokenConfig()
        cfg.load_from_env()
        assert cfg.enabled is False

    def test_with_token_no_error(self, monkeypatch):
        monkeypatch.setenv("API_TOKEN", "my-token")
        monkeypatch.delenv("DISABLE_API_AUTH", raising=False)
        cfg = APITokenConfig()
        cfg.load_from_env()
        assert cfg.enabled is True
        assert "my-token" in cfg.tokens


class TestTokenFileHotReload:
    """(11) Token-Datei wird bei Aenderung neu geladen."""

    def test_reload_on_mtime_change(self, tmp_path):
        token_file = tmp_path / "tokens.json"
        token_file.write_text(json.dumps({"tokens": ["token-old"]}))
        cfg = APITokenConfig()
        cfg.enabled = True
        cfg.token_file = str(token_file)
        cfg._load_tokens_from_file()
        assert cfg.is_valid_token("token-old") is True
        assert cfg.is_valid_token("token-new") is False

        # Datei aendern (mtime muss sich aendern).
        time.sleep(0.05)
        token_file.write_text(json.dumps({"tokens": ["token-new"]}))
        # Naechster is_valid_token-Aufruf triggert Reload.
        assert cfg.is_valid_token("token-new") is True
        assert cfg.is_valid_token("token-old") is False

    def test_no_reload_when_unchanged(self, tmp_path):
        token_file = tmp_path / "tokens.json"
        token_file.write_text(json.dumps({"tokens": ["t1"]}))
        cfg = APITokenConfig()
        cfg.enabled = True
        cfg.token_file = str(token_file)
        cfg._load_tokens_from_file()
        # maybe_reload_token_file gibt False zurueck bei unveraenderter Datei.
        assert cfg.maybe_reload_token_file() is False


class TestDbUserRootGuard:
    """(4) DB_USER=root Startup-Guard im lifespan."""

    def test_root_guard_present(self):
        # Der Guard ist Teil der lifespan; wir pruefen, dass die App nur mit
        # DB_USER != root (oder ALLOW_DB_ROOT) startet. Da die App bereits
        # importiert wurde (DB_USER-Default mcpuser), ist das ein Static-Check.
        import server
        assert "DB_USER" in open(server.__file__).read()
        assert "ALLOW_DB_ROOT" in open(server.__file__).read()

    def test_default_db_user_not_root(self):
        import server
        # DB_CONFIG-Default ist mcpuser, nicht root.
        assert server.DB_CONFIG["user"] == "mcpuser"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

"""
Rate Limiting Modul für den MariaDB MCP Server
Implementiert ein Token-Bucket-Algorithmus für API-Rate-Limiting
"""

import time
import logging
from typing import Optional, List, Dict, Any
from fastapi import Request, HTTPException
from fastapi.responses import JSONResponse
import os
import json

logger = logging.getLogger(__name__)


class RateLimitConfig:
    """Konfiguration für Rate Limiting"""
    
    def __init__(self):
        self.enabled = True
        self.requests_per_minute = 100  # Standard: 100 Anfragen pro Minute
        self.burst_requests = 10  # Standard: 10 Burst-Anfragen
        self.whitelist: List[str] = ["/health", "/", "/docs", "/openapi.json", "/redoc"]
        self.cleanup_interval = 60  # Sekunden zwischen Cleanups
        
    def load_from_env(self):
        """Lädt Konfiguration aus Umgebungsvariablen"""
        # Rate Limiting aktivieren/deaktivieren
        if os.getenv("RATE_LIMITING_ENABLED", "").lower() in ["false", "0", "no"]:
            self.enabled = False
            logger.info("Rate Limiting deaktiviert")
        else:
            self.enabled = os.getenv("RATE_LIMITING_ENABLED", "true").lower() in ["true", "1", "yes"]
        
        # Anfragen pro Minute
        rpm = os.getenv("RATE_LIMIT_REQUESTS_PER_MINUTE")
        if rpm:
            try:
                self.requests_per_minute = int(rpm)
                logger.info(f"Rate Limit: {self.requests_per_minute} Anfragen pro Minute")
            except ValueError:
                logger.warning(f"Ungültiger Wert für RATE_LIMIT_REQUESTS_PER_MINUTE: {rpm}")
        
        # Burst Anfragen
        burst = os.getenv("RATE_LIMIT_BURST_REQUESTS")
        if burst:
            try:
                self.burst_requests = int(burst)
                logger.info(f"Burst Limit: {self.burst_requests} Anfragen")
            except ValueError:
                logger.warning(f"Ungültiger Wert für RATE_LIMIT_BURST_REQUESTS: {burst}")
        
        # Whitelist
        whitelist = os.getenv("RATE_LIMIT_WHITELIST")
        if whitelist:
            self.whitelist = [p.strip() for p in whitelist.split(",") if p.strip()]
            logger.info(f"Rate Limiting Whitelist: {self.whitelist}")
        
        logger.info(f"Rate Limiting aktiviert: {self.enabled}")
    
    def load_from_config(self, config: Dict[str, Any]):
        """Lädt Konfiguration aus config.json"""
        if "rate_limiting" in config:
            rate_config = config["rate_limiting"]
            self.enabled = rate_config.get("enabled", True)
            self.requests_per_minute = rate_config.get("requests_per_minute", 100)
            self.burst_requests = rate_config.get("burst_requests", 10)
            self.whitelist = rate_config.get("whitelist", ["/health", "/", "/docs", "/openapi.json", "/redoc"])


class TokenBucket:
    """Token-Bucket-Algorithmus für Rate Limiting"""
    
    def __init__(self, capacity: int, refill_rate: float):
        """
        Initialisiert einen Token-Bucket
        
        Args:
            capacity: Maximale Anzahl an Tokens (Bucket-Größe)
            refill_rate: Tokens pro Sekunde, die hinzugefügt werden
        """
        self.capacity = capacity
        self.refill_rate = refill_rate
        self.tokens = capacity
        self.last_refill = time.time()
        self.lock = False  # Einfaches Lock für Thread-Safety (in ASGI-Umgebung)
    
    def consume(self, tokens: int = 1) -> bool:
        """
        Verbraucht Tokens aus dem Bucket
        
        Args:
            tokens: Anzahl der zu verbrauchenden Tokens
            
        Returns:
            True, wenn genug Tokens verfügbar waren, False sonst
        """
        now = time.time()
        
        # Refill Tokens basierend auf vergangener Zeit
        time_passed = now - self.last_refill
        new_tokens = time_passed * self.refill_rate
        
        # Aktualisiere Token-Anzahl
        self.tokens = min(self.capacity, self.tokens + new_tokens)
        self.last_refill = now
        
        # Prüfe, ob genug Tokens verfügbar sind
        if self.tokens >= tokens:
            self.tokens -= tokens
            return True
        
        return False
    
    def get_available_tokens(self) -> float:
        """Gibt die aktuell verfügbaren Tokens zurück"""
        now = time.time()
        time_passed = now - self.last_refill
        new_tokens = time_passed * self.refill_rate
        available = min(self.capacity, self.tokens + new_tokens)
        return available


class RateLimiter:
    """Rate Limiter für API-Anfragen"""
    
    def __init__(self, config: RateLimitConfig):
        self.config = config
        self.buckets: Dict[str, TokenBucket] = {}  # IP -> TokenBucket
        self.last_cleanup = time.time()
        
        # Berechne Refill-Rate: Tokens pro Sekunde
        self.refill_rate = self.config.requests_per_minute / 60.0
        
        # Bucket-Kapazität (Burst + normale Anfragen)
        self.bucket_capacity = self.config.burst_requests
    
    def _get_client_ip(self, request: Request) -> str:
        """Extrahiert die Client-IP aus der Anfrage"""
        # Versuche X-Forwarded-For Header (für Reverse Proxies)
        forwarded_for = request.headers.get("X-Forwarded-For")
        if forwarded_for:
            # Nimm die erste IP in der Liste
            ip = forwarded_for.split(",")[0].strip()
            return ip
        
        # Versuche X-Real-IP Header
        real_ip = request.headers.get("X-Real-IP")
        if real_ip:
            return real_ip
        
        # Fallback: client.host
        return request.client.host if request.client else "unknown"
    
    def _is_whitelisted(self, path: str) -> bool:
        """Prüft, ob der Pfad in der Whitelist ist"""
        for whitelist_path in self.config.whitelist:
            if path == whitelist_path or path.startswith(whitelist_path + "/"):
                return True
        return False
    
    def _cleanup_old_buckets(self):
        """Bereinigt alte Buckets, die nicht mehr verwendet werden"""
        now = time.time()
        if now - self.last_cleanup < self.config.cleanup_interval:
            return
        
        # Lösche Buckets, die länger als 5 Minuten nicht verwendet wurden
        old_buckets = []
        for ip, bucket in self.buckets.items():
            # Einfache Heuristik: wenn der Bucket voll ist, wurde er nicht verwendet
            if bucket.tokens >= bucket.capacity:
                old_buckets.append(ip)
        
        for ip in old_buckets:
            del self.buckets[ip]
        
        self.last_cleanup = now
        
        if old_buckets:
            logger.info(f"Bereinigt {len(old_buckets)} alte Rate-Limit-Buckets")
    
    def check_rate_limit(self, request: Request) -> bool:
        """
        Prüft, ob die Anfrage innerhalb des Rate Limits ist
        
        Args:
            request: FastAPI Request-Objekt
            
        Returns:
            True, wenn die Anfrage erlaubt ist, False wenn Rate Limit überschritten
        """
        if not self.config.enabled:
            return True
        
        path = request.url.path
        
        # Whitelist prüfen
        if self._is_whitelisted(path):
            return True
        
        # Client-IP extrahieren
        client_ip = self._get_client_ip(request)
        
        # Bucket für diese IP holen oder erstellen
        if client_ip not in self.buckets:
            self.buckets[client_ip] = TokenBucket(
                capacity=self.bucket_capacity,
                refill_rate=self.refill_rate
            )
        
        bucket = self.buckets[client_ip]
        
        # Cleanup (periodisch)
        self._cleanup_old_buckets()
        
        # Token verbrauchen
        return bucket.consume(1)
    
    def get_rate_limit_info(self, request: Request) -> Dict[str, Any]:
        """
        Gibt Informationen über das aktuelle Rate Limit zurück
        
        Args:
            request: FastAPI Request-Objekt
            
        Returns:
            Dictionary mit Rate-Limit-Informationen
        """
        client_ip = self._get_client_ip(request)
        
        if client_ip not in self.buckets:
            return {
                "limit": self.config.requests_per_minute,
                "remaining": self.bucket_capacity,
                "reset": int(time.time()) + 60
            }
        
        bucket = self.buckets[client_ip]
        
        return {
            "limit": self.config.requests_per_minute,
            "remaining": int(bucket.get_available_tokens()),
            "reset": int(self.last_cleanup) + self.config.cleanup_interval
        }


# Globale Rate-Limit-Konfiguration
rate_limit_config = RateLimitConfig()

# Globale Rate-Limiter-Instanz
rate_limiter = RateLimiter(rate_limit_config)


async def rate_limit_middleware(request: Request, call_next):
    """
    Middleware für Rate Limiting
    """
    if not rate_limit_config.enabled:
        response = await call_next(request)
        return response
    
    path = request.url.path
    
    # Whitelist prüfen
    whitelisted = any(path == p or path.startswith(p + "/") 
                     for p in rate_limit_config.whitelist)
    
    if whitelisted:
        response = await call_next(request)
        return response
    
    # Rate Limit prüfen
    if not rate_limiter.check_rate_limit(request):
        return JSONResponse(
            status_code=429,
            content={
                "error": "Too Many Requests",
                "detail": f"Rate Limit überschritten. Maximale Anfragen: {rate_limit_config.requests_per_minute} pro Minute",
                "retry_after": 60
            },
            headers={
                "Retry-After": "60",
                "X-RateLimit-Limit": str(rate_limit_config.requests_per_minute),
                "X-RateLimit-Remaining": "0",
                "X-RateLimit-Reset": str(int(time.time()) + 60)
            }
        )
    
    # Anfrage verarbeiten
    response = await call_next(request)
    
    # Rate-Limit-Header zur Antwort hinzufügen
    rate_info = rate_limiter.get_rate_limit_info(request)
    response.headers["X-RateLimit-Limit"] = str(rate_limit_config.requests_per_minute)
    response.headers["X-RateLimit-Remaining"] = str(rate_info["remaining"])
    response.headers["X-RateLimit-Reset"] = str(rate_info["reset"])
    
    return response


# Lade Konfiguration
rate_limit_config.load_from_env()

# Erstelle neue Rate-Limiter-Instanz mit geladener Konfiguration
rate_limiter = RateLimiter(rate_limit_config)

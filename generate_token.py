#!/usr/bin/env python3
"""
Skript zur Generierung sicherer API-Tokens für den MariaDB MCP Server
"""

import secrets
import string
import json
import argparse
import os


def generate_token(length: int = 32) -> str:
    """Generiert einen sicheren zufälligen Token"""
    alphabet = string.ascii_letters + string.digits + "-_.~"
    return ''.join(secrets.choice(alphabet) for _ in range(length))


def generate_tokens_file(filename: str, num_tokens: int = 1, token_length: int = 32):
    """Generiert eine Token-Datei mit mehreren Tokens"""
    tokens = [generate_token(token_length) for _ in range(num_tokens)]
    
    # Speichere als JSON
    data = {
        "tokens": tokens,
        "generated_at": "manual",
        "note": "Bewahre diese Datei sicher auf und füge sie NICHT zum Git-Repository hinzu!"
    }
    
    with open(filename, 'w') as f:
        json.dump(data, f, indent=2)
    
    print(f"\n")
    print(f"=" * 60)
    print(f"Token-Datei generiert: {filename}")
    print(f"=" * 60)
    print(f"\nGenerierte Tokens ({num_tokens}):")
    for i, token in enumerate(tokens, 1):
        print(f"  Token {i}: {token}")
    print(f"\nWICHTIG:")
    print(f"  - Bewahre diese Tokens sicher auf!")
    print(f"  - Füge die Datei NICHT zum Git-Repository hinzu!")
    print(f"  - Die Datei ist bereits in .gitignore eingetragen")
    print(f"\nVerwendung:")
    print(f"  - In docker-compose.yml:")
    print(f"    volumes:")
    print(f"      - ./tokens.json:/app/tokens.json:ro")
    print(f"    environment:")
    print(f"      - API_TOKEN_FILE=/app/tokens.json")
    print(f"\n  - Oder als Umgebungsvariable:")
    print(f"    API_TOKEN={tokens[0]}")
    print(f"=" * 60)


def main():
    parser = argparse.ArgumentParser(
        description="Generiere sichere API-Tokens für den MariaDB MCP Server",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Beispiele:
  python generate_token.py                    # Generiert 1 Token (32 Zeichen)
  python generate_token.py --num 5            # Generiert 5 Tokens
  python generate_token.py --length 64       # Generiert Token mit 64 Zeichen
  python generate_token.py --file tokens.json # Speichert in Datei
        """
    )
    
    parser.add_argument(
        '--num', '-n',
        type=int,
        default=1,
        help="Anzahl der zu generierenden Tokens (Standard: 1)"
    )
    
    parser.add_argument(
        '--length', '-l',
        type=int,
        default=32,
        help="Länge jedes Tokens (Standard: 32)"
    )
    
    parser.add_argument(
        '--file', '-f',
        type=str,
        default='tokens.json',
        help="Dateiname für die Token-Datei (Standard: tokens.json)"
    )
    
    parser.add_argument(
        '--no-file',
        action='store_true',
        help="Zeige Tokens nur an, speichere nicht in Datei"
    )
    
    args = parser.parse_args()
    
    # Generiere Tokens
    tokens = [generate_token(args.length) for _ in range(args.num)]
    
    if args.no_file:
        # Zeige Tokens nur an
        print(f"\nGenerierte API-Tokens ({args.num} x {args.length} Zeichen):")
        print("-" * 50)
        for i, token in enumerate(tokens, 1):
            print(f"Token {i}: {token}")
        print("-" * 50)
        print(f"\nVerwendung:")
        print(f"  - Einzelner Token: API_TOKEN={tokens[0]}")
        print(f"  - Mehrere Tokens: API_TOKENS={','.join(tokens)}")
    else:
        # Speichere in Datei
        generate_tokens_file(args.file, args.num, args.length)


if __name__ == "__main__":
    main()

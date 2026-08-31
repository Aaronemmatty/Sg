#!/usr/bin/env python3
"""
SG Trading Platform — Secret Generator
Run once during initial setup to generate all required secrets.

Usage:
    python scripts/generate_secrets.py              # generate all
    python scripts/generate_secrets.py --jwt        # JWT keypair only
    python scripts/generate_secrets.py --passwords  # random passwords only
    python scripts/generate_secrets.py --patch-env  # write directly into .env
"""

import argparse
import os
import secrets
import sys
from pathlib import Path

def generate_jwt_keypair():
    """Generate RS256 keypair for JWT signing."""
    try:
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric import rsa
        from cryptography.hazmat.backends import default_backend
    except ImportError:
        print("ERROR: cryptography package required. Run: pip install cryptography")
        sys.exit(1)

    private_key = rsa.generate_private_key(
        public_exponent=65537,
        key_size=4096,
        backend=default_backend(),
    )

    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.TraditionalOpenSSL,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()

    public_pem = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode()

    return private_pem, public_pem


def pem_to_env(pem: str) -> str:
    """Collapse PEM to single-line with \\n for .env files."""
    return pem.replace("\n", "\\n")


def generate_password(length: int = 40) -> str:
    """Generate a URL-safe random password."""
    return secrets.token_urlsafe(length)


def patch_env_file(env_path: Path, updates: dict[str, str]) -> None:
    """Write or update key=value pairs in a .env file."""
    existing = {}
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            if "=" in line and not line.startswith("#"):
                k, _, v = line.partition("=")
                existing[k.strip()] = v.strip()

    existing.update(updates)

    lines = []
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            if "=" in line and not line.startswith("#"):
                k = line.split("=")[0].strip()
                if k in updates:
                    lines.append(f"{k}={updates[k]}")
                    continue
            lines.append(line)
    # Append any new keys not already in file
    for k, v in updates.items():
        if k not in existing or not any(l.startswith(k + "=") for l in lines):
            lines.append(f"{k}={v}")

    env_path.write_text("\n".join(lines) + "\n")
    print(f"✓ Patched {env_path}")


def main():
    parser = argparse.ArgumentParser(description="SG Trading secret generator")
    parser.add_argument("--jwt", action="store_true", help="Generate JWT keypair only")
    parser.add_argument("--passwords", action="store_true", help="Generate passwords only")
    parser.add_argument("--patch-env", action="store_true", help="Write values into .env file")
    args = parser.parse_args()

    root = Path(__file__).parent.parent
    env_path = root / ".env"
    updates = {}

    do_all = not args.jwt and not args.passwords

    if do_all or args.jwt:
        print("\n── JWT RS256 Keypair ─────────────────────────────────────")
        private_pem, public_pem = generate_jwt_keypair()
        priv_env = pem_to_env(private_pem)
        pub_env  = pem_to_env(public_pem)

        if args.patch_env:
            updates["JWT_PRIVATE_KEY"] = priv_env
            updates["JWT_PUBLIC_KEY"]  = pub_env
        else:
            print(f"\nJWT_PRIVATE_KEY={priv_env}\n")
            print(f"JWT_PUBLIC_KEY={pub_env}\n")

        # Also save raw PEM files for reference
        keys_dir = root / "secrets-templates" / "jwt"
        keys_dir.mkdir(parents=True, exist_ok=True)
        (keys_dir / "private.pem").write_text(private_pem)
        (keys_dir / "public.pem").write_text(public_pem)
        (keys_dir / ".gitignore").write_text("*\n")
        print(f"✓ Raw PEM files saved to {keys_dir} (gitignored)")

        # docker/docker-compose.yml mounts the public key into
        # regime_detection_service, risk_engine_service, execution_engine_
        # service, portfolio_management_service, backtesting_engine_service,
        # ml_platform_service, ai_analyst_service and signal_aggregation_
        # service as a Docker secret (file: ./secrets/auth_public_key.pem,
        # relative to docker/docker-compose.yml). Write it there too so
        # `./sg up` works without a manual copy step.
        compose_secrets_dir = root / "docker" / "secrets"
        compose_secrets_dir.mkdir(parents=True, exist_ok=True)
        (compose_secrets_dir / "auth_public_key.pem").write_text(public_pem)
        (compose_secrets_dir / ".gitignore").write_text("*\n!.gitignore\n")
        print(f"✓ Public key also copied to {compose_secrets_dir / 'auth_public_key.pem'} (used by docker-compose.yml secrets:)")

    if do_all or args.passwords:
        print("\n── Random Passwords ──────────────────────────────────────")
        passwords = {
            "POSTGRES_PASSWORD": generate_password(),
            "REDIS_PASSWORD":    generate_password(),
            "SESSION_SECRET":    generate_password(32),
            "GRAFANA_PASSWORD":  generate_password(20),
            # auth_service's own app-level secret (separate from the JWT
            # RS256 keypair above — used for things like CSRF/state tokens,
            # not for signing tokens). auth_service/.env.example asks for
            # `openssl rand -hex 64`; secrets.token_hex(64) is equivalent.
            "SECRET_KEY":        secrets.token_hex(64),
        }
        if args.patch_env:
            updates.update(passwords)
        else:
            for k, v in passwords.items():
                print(f"{k}={v}")

    if args.patch_env:
        if not env_path.exists():
            import shutil
            example = root / ".env.example"
            if example.exists():
                shutil.copy(example, env_path)
                print(f"✓ Created {env_path} from .env.example")
        patch_env_file(env_path, updates)
    else:
        print("\n── Next steps ────────────────────────────────────────────")
        print("1. Copy above values into your .env file")
        print("2. Optionally add KITE_API_KEY, KITE_API_SECRET, ANTHROPIC_API_KEY (all optional — platform runs without them, affected endpoints return 503)")
        print("3. Or run with --patch-env to write directly:")
        print("   python scripts/generate_secrets.py --patch-env")


if __name__ == "__main__":
    main()

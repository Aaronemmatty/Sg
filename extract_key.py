from pathlib import Path

env_text = Path("auth_service/.env").read_text()
for line in env_text.splitlines():
    if line.startswith("JWT_PUBLIC_KEY="):
        value = line.split("=", 1)[1].strip().strip('"')
        pem = value.replace("\\n", "\n")
        out_dir = Path("shared_secrets")
        out_dir.mkdir(exist_ok=True)
        out_path = out_dir / "jwt_public_key.pem"
        out_path.write_text(pem)
        print(f"Written to {out_path.resolve()}")
        break
else:
    print("JWT_PUBLIC_KEY line not found in auth_service/.env")
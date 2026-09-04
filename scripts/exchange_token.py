import hashlib
import ssl
import requests
import redis
from pathlib import Path
from requests.adapters import HTTPAdapter
from urllib3.util.ssl_ import create_urllib3_context

class CustomSSLAdapter(HTTPAdapter):
    def init_poolmanager(self, *args, **kwargs):
        ctx = create_urllib3_context()
        ctx.set_ciphers("DEFAULT@SECLEVEL=1")
        ctx.check_hostname = True
        ctx.verify_mode = ssl.CERT_REQUIRED
        kwargs["ssl_context"] = ctx
        return super().init_poolmanager(*args, **kwargs)

import os
import sys
import urllib.parse
from dotenv import dotenv_values

_envs = dotenv_values(".env")
api_key = os.environ.get("KITE_API_KEY") or _envs.get("KITE_API_KEY", "")
api_secret = os.environ.get("KITE_API_SECRET") or _envs.get("KITE_API_SECRET", "")

raw_input = sys.argv[1] if len(sys.argv) > 1 else ""
if not raw_input:
    print("Usage: python scripts/exchange_token.py <request_token>")
    sys.exit(1)

if "request_token=" in raw_input:
    parsed = urllib.parse.urlparse(raw_input)
    params = urllib.parse.parse_qs(parsed.query)
    req_tok = params.get("request_token", [raw_input])[0]
else:
    req_tok = raw_input.strip()

checksum = hashlib.sha256((api_key + req_tok + api_secret).encode("utf-8")).hexdigest()

session = requests.Session()
session.mount("https://", CustomSSLAdapter())

print(f"[*] Posting to https://api.kite.trade/session/token with request_token={req_tok}", flush=True)

success = False
for attempt in range(1, 4):
    try:
        resp = session.post(
            "https://api.kite.trade/session/token",
            data={"api_key": api_key, "request_token": req_tok, "checksum": checksum},
            timeout=15.0,
            headers={"User-Agent": "kiteconnect-python/5.0.0"}
        )
        print(f"[+] HTTP Status: {resp.status_code}", flush=True)
        print(f"[+] Response: {resp.text}", flush=True)
        
        data = resp.json().get("data", {})
        access_tok = data.get("access_token")
        if access_tok:
            print(f"[+] New Access Token: {access_tok[:8]}... (len={len(access_tok)})", flush=True)
            # Store in Redis DB 0, 1, 2
            for db_num in (0, 1, 2):
                r = redis.Redis(host="127.0.0.1", port=6379, db=db_num, socket_timeout=2.0)
                r.set("sg:kite:access_token", access_tok, ex=93600)
                if db_num == 2:
                    r.publish("sg:kite:token_refreshed", "refreshed")
                    print("[+] Published sg:kite:token_refreshed to Redis DB 2", flush=True)
                    
            # Sync .env files
            REPO_ROOT = Path(r"c:\Users\emmat\Downloads\sg_repo")
            for env_file in [REPO_ROOT / ".env", REPO_ROOT / "market_data_service" / ".env", REPO_ROOT / "broker_service" / ".env"]:
                if env_file.exists():
                    lines = []
                    for line in env_file.read_text(encoding="utf-8").splitlines():
                        if line.startswith("KITE_ACCESS_TOKEN="):
                            lines.append(f"KITE_ACCESS_TOKEN={access_tok}")
                        else:
                            lines.append(line)
                    env_file.write_text("\n".join(lines) + "\n", encoding="utf-8")
                    print(f"[+] Synced KITE_ACCESS_TOKEN to {env_file.name}", flush=True)
            print("[+] SUCCESS: Token exchanged and persisted everywhere!", flush=True)
            success = True
            break
        else:
            print("[-] No access token in response data!", flush=True)
            break
    except Exception as e:
        print(f"[-] Attempt {attempt} failed: {e}", flush=True)

if not success:
    print("[-] Token exchange unsuccessful.", flush=True)

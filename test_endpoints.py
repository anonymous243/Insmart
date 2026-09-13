import urllib.request
import urllib.error
import sys

from app.api.auth import create_access_token

token = create_access_token({"sub": "admin@demo.com", "role": "ADMIN"})
headers = {"Authorization": f"Bearer {token}"}

for path in ["/api/v1/codes/mappings", "/api/v1/benchmarks", "/api/v1/hospitals"]:
    req = urllib.request.Request(f"http://127.0.0.1:8000{path}", headers=headers)
    try:
        with urllib.request.urlopen(req) as res:
            data = res.read().decode()
            print(f"{path}: {res.status} - {data[:100]}")
    except urllib.error.HTTPError as e:
        print(f"{path}: Error {e.code} - {e.read().decode()[:100]}")

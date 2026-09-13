import httpx
import json

def test():
    # 1. Login as admin
    res = httpx.post("http://localhost:8000/api/v1/auth/login", json={"email": "admin@demo.com", "password": "test"})
    token = res.json()["access_token"]
    
    # 2. Emulate getDashboardMetrics with this token
    res2 = httpx.get("http://localhost:8000/api/v1/dashboard/metrics", headers={"Authorization": f"Bearer {token}"})
    print("Metrics status:", res2.status_code)
    print("Metrics response:", res2.json())
test()

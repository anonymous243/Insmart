import httpx

def test():
    # Login as admin
    res = httpx.post("http://localhost:8000/api/v1/auth/login", json={"email": "admin@demo.com", "password": "test"})
    if res.status_code == 200:
        token = res.json()["access_token"]
        # Try auth me
        res2 = httpx.get("http://localhost:8000/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
        print("Auth me:", res2.status_code, res2.json())
test()

import asyncio
from fastapi.testclient import TestClient
from app.main import app

def test():
    client = TestClient(app)
    response = client.post("/api/v1/integrations/rest/submit", json={}, headers={"X-Facility-Api-Key": "TEST-API-KEY-A"})
    print(response.json())

test()

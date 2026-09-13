import requests

BASE_URL = 'http://127.0.0.1:8000/api/v1'

def run_tests():
    # 1. Login as Admin
    print("1. Logging in as Admin...")
    r = requests.post(f"{BASE_URL}/auth/login", json={"email": "admin@demo.com", "password": "test"})
    if r.status_code != 200:
        print("Admin login failed:", r.text)
        return
    admin_token = r.json()["access_token"]
    print("Admin Token acquired")
    
    admin_headers = {"Authorization": f"Bearer {admin_token}"}
    
    # 2. Test Admin Endpoint (metrics)
    print("2. Fetching Admin metrics...")
    r = requests.get(f"{BASE_URL}/dashboard/metrics", headers=admin_headers)
    print("Metrics response:", r.status_code, r.text[:100])
    
    # 3. Test Admin Endpoint (transactions)
    print("3. Fetching Admin transactions...")
    r = requests.get(f"{BASE_URL}/transactions", headers=admin_headers)
    print("Admin transactions response:", r.status_code, str(r.json())[:100])

    # 4. Login as Facility
    print("\n4. Logging in as Facility...")
    r = requests.post(f"{BASE_URL}/auth/login", json={"email": "amarsarjapur106@gmail.com", "password": "Amar@8722"})
    if r.status_code != 200:
        print("Facility login failed:", r.text)
        return
    facility_token = r.json()["access_token"]
    facility_headers = {"Authorization": f"Bearer {facility_token}"}
    
    # 5. Facility submit transaction
    print("5. Submitting Facility Transaction...")
    payload = {
        "hospital_id": "F033",
        "transaction_id": "TEST_AUTH_002",
        "patient_reference": "PAT-TEST",
        "items": [
            {
                "hospital_code": "DEMO-CODE-1",
                "description": "Consultation",
                "quantity": 1,
                "unit_price": 5000
            }
        ]
    }
    r = requests.post(f"{BASE_URL}/demo/submit", json=payload, headers=facility_headers)
    print("Submit response:", r.status_code, str(r.json())[:100])

    # 6. Admin verify new transaction
    print("\n6. Verifying in Admin (by fetching transaction)...")
    r = requests.get(f"{BASE_URL}/transactions", headers=admin_headers)
    txs = r.json()
    found = any(t.get("transaction_id") == "TEST_AUTH_001" for t in txs)
    print("New transaction found by admin:", found)

if __name__ == "__main__":
    run_tests()

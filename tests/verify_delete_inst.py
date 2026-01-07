import requests
import json
from datetime import datetime

BASE_URL = "http://127.0.0.1:5002"
SUPER_ADMIN_EMAIL = "verify_sa@example.com"
SUPER_ADMIN_PASS = "verify123"

def login(email, password):
    session = requests.Session()
    res = session.post(f"{BASE_URL}/login", data={"email": email, "password": password}, allow_redirects=True)
    return session, res

def test_delete_institution():
    print(">>> Starting Delete Institution Verification")

    sa_session, res = login(SUPER_ADMIN_EMAIL, SUPER_ADMIN_PASS)
    if "Login successful" not in res.text and "User Management" not in res.text:
         print("FATAL: Could not login as Super Admin.")
         return

    # 1. Create Inst
    inst_name = f"Delete Me Univ {datetime.now().timestamp()}"
    res = sa_session.post(f"{BASE_URL}/api/create-institution", json={
        "name": inst_name,
        "user_limit": 5,
        "admin_limit": 2
    })
    if res.status_code != 201:
        print(f"FATAL: Failed to create institution: {res.text}")
        return
    print(f"[OK] Created Institution: {inst_name}")

    # Get Inst ID
    res = sa_session.get(f"{BASE_URL}/api/institutions")
    insts = res.json()
    inst_id = next(i['id'] for i in insts if i['name'] == inst_name)

    # 2. Create User in Inst
    user_email = f"victim_{int(datetime.now().timestamp())}@example.com"
    res = sa_session.post(f"{BASE_URL}/api/create-user", json={
        "email": user_email,
        "username": f"victim_{int(datetime.now().timestamp())}",
        "password": "pass",
        "name": "Victim User",
        "role": "user",
        "institution_id": inst_id
    })
    if res.status_code != 201:
        print(f"FATAL: Copy creating user: {res.text}")
        return
    print(f"[OK] Created User {user_email} in Institution")

    # 3. Delete Institution
    print(">>> Deleting Institution...")
    res = sa_session.post(f"{BASE_URL}/api/delete-institution", json={"institution_id": inst_id})
    if res.status_code == 200:
        print("[OK] Institution Deleted")
    else:
        print(f"[FAIL] Delete Failed: {res.text}")
        return

    # 4. Verify User Orphaned (Inst ID -> None)
    print(">>> Verifying User Detachment...")
    res = sa_session.get(f"{BASE_URL}/api/users")
    users = res.json().get('users', [])
    target = next((u for u in users if u['email'] == user_email), None)
    
    if target:
        if target.get('institution_id') is None:
            print("[PASS] User successfully orphaned (institution_id is None).")
        else:
            print(f"[FAIL] User still has institution_id: {target.get('institution_id')}")
    else:
        print("[FAIL] User not found in list (Should exist but orphaned).")

if __name__ == "__main__":
    test_delete_institution()

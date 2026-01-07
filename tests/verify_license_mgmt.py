import requests
import json
from datetime import datetime, timedelta

BASE_URL = "http://127.0.0.1:5002"
SUPER_ADMIN_EMAIL = "verify_sa@example.com"
SUPER_ADMIN_PASS = "verify123"
# SUPER_ADMIN_EMAIL and PASS are constants
# INST_ADMIN_EMAIL will be generated dynamically
INST_ADMIN_PASS = "LicPass123"

def login(email, password):
    session = requests.Session()
    res = session.post(f"{BASE_URL}/login", data={"email": email, "password": password}, allow_redirects=True)
    return session, res

def test_license_flow():
    print(">>> Starting License Management Verification")

    # 1. Login as Super Admin Logic (Simulated via script availability or pre-reqs)
    # Ideally we use an existing super admin. Let's assume we can bootstrap one or use existing.
    # For this test, let's try to create a super admin via CLI if not exists? 
    # Or just use the one we created earlier: super_bootstrap2@example.com
    
    sa_session, res = login(SUPER_ADMIN_EMAIL, SUPER_ADMIN_PASS)
    if "Login successful" not in res.text and "User Management" not in res.text:
         print("FATAL: Could not login as Super Admin. Ensure super_bootstrap2 exists.")
         return

    print("[OK] Super Admin Logged In")

    # 2. Create Institution with EXPIRED License (Yesterday)
    yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
    inst_name = f"Expired Univ {datetime.now().timestamp()}"
    
    res = sa_session.post(f"{BASE_URL}/api/create-institution", json={
        "name": inst_name,
        "user_limit": 5,
        "admin_limit": 2,
        "license_expiry": yesterday
    })
    if res.status_code != 201:
        print(f"FATAL: Failed to create expired institution: {res.text}")
        return
    
    print(f"[OK] Created Expired Institution: {inst_name} (Expiry: {yesterday})")

    # Get Inst ID (Simulated by fetching list)
    res = sa_session.get(f"{BASE_URL}/api/institutions")
    insts = res.json()
    inst_id = next(i['id'] for i in insts if i['name'] == inst_name)
    target_inst = next(i for i in insts if i['name'] == inst_name)
    print(f"DEBUG: Created Inst Data: {target_inst}")

    # 3. Create Admin for this Institution
    inst_admin_email = f"lic_admin_{int(datetime.now().timestamp())}@example.com"
    res = sa_session.post(f"{BASE_URL}/api/create-user", json={
        "email": inst_admin_email,
        "username": f"lic_admin_{int(datetime.now().timestamp())}",
        "password": INST_ADMIN_PASS,
        "name": "Lic Admin",
        "role": "admin",
        "institution_id": inst_id
    })
    
    if res.status_code == 201:
        print("[OK] Created Institution Admin for Expired Inst")
    elif res.status_code == 409:
        print("[INFO] Admin already exists, proceeding...")
    else:
        print(f"FATAL: Failed to create admin: {res.text}")
        return

    # 4. Try Login as Expired Admin -> EXPECT FAILURE (Redirect to login)
    print(f">>> Testing Login Block on Expiry for {inst_admin_email}...")
    expired_session, res = login(inst_admin_email, INST_ADMIN_PASS)
    
    # Check if we are redirected back to login or have error message
    if "DEBUG: Expiry=" in res.text:
         print(f"DEBUG CAPTURED: {res.text.split('DEBUG:')[1].split('<')[0]}")

    if "Your institution's license has expired" in res.text:
         print("[PASS] Login BLOCKED for expired license.")
    elif "Login successful" in res.text:
         print("[FAIL] Login SUCCESSFUL despite expired license!")
         return
    else:
         print(f"[WARN] Login result unclear: {res.text[:200]}...")

    # 5. Renew License -> Tomorrow
    print(">>> Renewing License...")
    tomorrow = (datetime.now() + timedelta(days=2)).strftime("%Y-%m-%d")
    res = sa_session.post(f"{BASE_URL}/api/renew-license", json={
        "institution_id": inst_id,
        "new_expiry": tomorrow
    })
    if res.status_code == 200:
        print(f"[OK] License Renewed to {tomorrow}")
    else:
        print(f"[FAIL] Renewal Failed: {res.text}")
        return

    # 6. Try Login Again -> EXPECT SUCCESS
    print(">>> Testing Login after Renewal...")
    valid_session, res = login(inst_admin_email, INST_ADMIN_PASS)
    if "Login successful" in res.text or "dashboard" in res.text or "User Management" in res.text: # Check content indicators
         print("[PASS] Login SUCCESSFUL after renewal.")
    else:
         print(f"[FAIL] Login Failed after renewal: {res.text[:300]}")

    # Optional: Test Warning (Set expiry to +5 days)
    print(">>> Testing Expiry Warning...")
    in_5_days = (datetime.now() + timedelta(days=5)).strftime("%Y-%m-%d")
    sa_session.post(f"{BASE_URL}/api/renew-license", json={
        "institution_id": inst_id,
        "new_expiry": in_5_days
    })
    
    warn_session, res = login(inst_admin_email, INST_ADMIN_PASS)
    if "License expires in" in res.text:
         print(f"[PASS] Correctly showed warning for expiry in 5 days.")
    else:
         print("[WARN] Did not see expiry warning.")

    print(">>> Verification Complete")

if __name__ == "__main__":
    test_license_flow()

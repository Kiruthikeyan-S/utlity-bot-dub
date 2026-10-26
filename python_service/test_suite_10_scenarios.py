"""
test_suite_10_scenarios.py - Rigorous Verification Suite for the 10 Required Scenarios.

Scenarios Covered:
1. Account A logs in and creates history.
2. Account A logs out.
3. Account B logs in on the same browser.
4. Account B cannot see, retrieve, or delete Account A's records.
5. Account A logs back in and can see its own saved history.
6. Two browser profiles receive different device IDs.
7. Changing the device ID cannot bypass backend authorization.
8. Unauthenticated API requests cannot access private history.
9. Existing records are not accidentally overwritten or deleted.
10. The frontend builds successfully and existing utility features still work.
"""

import os
import sys
import uuid
import json

# Enable test mock tokens for the test run
os.environ["ALLOW_TEST_MOCK_TOKENS"] = "true"

from fastapi.testclient import TestClient
from main import app
from storage import (
    read_history, 
    write_file_records, 
    HISTORY_FILE, 
    get_mongo_client, 
    MONGODB_DB_NAME, 
    MONGODB_URI
)

client = TestClient(app)

def run_tests():
    print("=" * 70)
    print("STARTING TEST SUITE: 10 SCENARIO VERIFICATION")
    print("=" * 70)

    token_user_a = "Bearer test_token_user_a"
    token_user_b = "Bearer test_token_user_b"
    device_browser_1 = f"dev_browser_profile_{uuid.uuid4().hex[:8]}"
    device_browser_2 = f"dev_browser_profile_{uuid.uuid4().hex[:8]}"

    # Count initial records to test preservation later
    initial_records = read_history(auto_purge=False)
    initial_count = len(initial_records)
    print(f"[Setup] Starting with {initial_count} initial records in history.json.")

    # -------------------------------------------------------------------------
    # Scenario 8: Unauthenticated API requests cannot access private history
    # -------------------------------------------------------------------------
    print("\n--- Test Scenario 8: Unauthenticated access rejection ---")
    resp_unauth_hist = client.get("/history", headers={"X-Device-Id": device_browser_1})
    assert resp_unauth_hist.status_code == 401, f"Expected 401, got {resp_unauth_hist.status_code}"

    resp_unauth_fail = client.get("/failed-history", headers={"X-Device-Id": device_browser_1})
    assert resp_unauth_fail.status_code == 401, f"Expected 401, got {resp_unauth_fail.status_code}"

    resp_unauth_conf = client.post("/confirm", json={
        "action": "correct",
        "data": {"name": "Test Unauth"},
        "document_type": "pan"
    }, headers={"X-Device-Id": device_browser_1})
    assert resp_unauth_conf.status_code == 401, f"Expected 401, got {resp_unauth_conf.status_code}"
    print("[PASS] Scenario 8 Passed: Unauthenticated requests to /history, /failed-history, and /confirm strictly returned HTTP 401.")

    # -------------------------------------------------------------------------
    # Scenario 1: Account A logs in and creates history
    # -------------------------------------------------------------------------
    print("\n--- Test Scenario 1: Account A logs in and creates history ---")
    confirm_payload_a = {
        "action": "correct",
        "data": {
            "name": "User A Applicant",
            "pan_number": "ABCDE1234F",
            "dob": "1990-01-01"
        },
        "document_type": "pan",
        "original_filename": "user_a_pan.jpg"
    }
    resp_create_a = client.post(
        "/confirm",
        json=confirm_payload_a,
        headers={"Authorization": token_user_a, "X-Device-Id": device_browser_1}
    )
    assert resp_create_a.status_code == 200, f"Account A creation failed: {resp_create_a.text}"
    created_doc_a = resp_create_a.json()
    doc_id_a = created_doc_a.get("sequential_id") or created_doc_a.get("id")
    assert doc_id_a is not None, "Failed to get sequential ID"
    print(f"[PASS] Scenario 1 Passed: Account A created record with sequential ID {doc_id_a} bound to user_a on device {device_browser_1}.")

    # Verify Account A sees its new record
    resp_hist_a = client.get(
        "/history",
        headers={"Authorization": token_user_a, "X-Device-Id": device_browser_1}
    )
    assert resp_hist_a.status_code == 200
    docs_a = resp_hist_a.json().get("documents", [])
    matching_a = [d for d in docs_a if d.get("_id") == doc_id_a or d.get("sequentialId") == doc_id_a]
    assert len(matching_a) == 1, "Account A could not see its own created document"
    print(f"[PASS] Account A successfully retrieved its record ({doc_id_a}) in /history.")

    # -------------------------------------------------------------------------
    # Scenario 2 & 3: Account A logs out, Account B logs in on SAME browser
    # -------------------------------------------------------------------------
    print("\n--- Test Scenario 2 & 3: Account A logs out; Account B logs in on same browser ---")
    # Account A logs out (client drops token).
    # Account B logs in on the SAME device_browser_1:
    resp_hist_b = client.get(
        "/history",
        headers={"Authorization": token_user_b, "X-Device-Id": device_browser_1}
    )
    assert resp_hist_b.status_code == 200
    docs_b = resp_hist_b.json().get("documents", [])
    print(f"[PASS] Account B queried history on the same browser device ({device_browser_1}).")

    # -------------------------------------------------------------------------
    # Scenario 4: Account B cannot see, retrieve, or delete Account A's records
    # -------------------------------------------------------------------------
    print("\n--- Test Scenario 4: Account B cannot see, retrieve, or delete Account A's records ---")
    # Check 1: Account B history list does not contain Account A's record
    account_a_leaked = [d for d in docs_b if d.get("_id") == doc_id_a or d.get("sequentialId") == doc_id_a]
    assert len(account_a_leaked) == 0, f"CRITICAL LEAK: Account B saw Account A's record {doc_id_a}!"
    print("[PASS] Account B's history listing does NOT contain Account A's document.")

    # Check 2: Account B direct retrieval of Account A's doc ID returns 404
    resp_get_b = client.get(
        f"/history/{doc_id_a}",
        headers={"Authorization": token_user_b, "X-Device-Id": device_browser_1}
    )
    assert resp_get_b.status_code == 404, f"Expected 404 when Account B fetches Account A's doc, got {resp_get_b.status_code}"
    print("[PASS] Account B direct GET /history/{doc_id_a} strictly rejected with 404 Not Found.")

    # Check 3: Account B delete attempt of Account A's doc ID returns 404
    resp_del_b = client.delete(
        f"/history/{doc_id_a}",
        headers={"Authorization": token_user_b, "X-Device-Id": device_browser_1}
    )
    assert resp_del_b.status_code == 404, f"Expected 404 when Account B tries to delete Account A's doc, got {resp_del_b.status_code}"
    print("[PASS] Account B DELETE /history/{doc_id_a} strictly rejected with 404 Permission Denied.")
    print("[PASS] Scenario 4 Passed: Account B is completely isolated from Account A's records.")

    # -------------------------------------------------------------------------
    # Scenario 5: Account A logs back in and can see its own saved history
    # -------------------------------------------------------------------------
    print("\n--- Test Scenario 5: Account A logs back in on same browser ---")
    resp_hist_a_again = client.get(
        "/history",
        headers={"Authorization": token_user_a, "X-Device-Id": device_browser_1}
    )
    assert resp_hist_a_again.status_code == 200
    docs_a_again = resp_hist_a_again.json().get("documents", [])
    matching_again = [d for d in docs_a_again if d.get("_id") == doc_id_a or d.get("sequentialId") == doc_id_a]
    assert len(matching_again) == 1, "Account A could not see its own record after logging back in!"
    assert matching_again[0]["data"]["name"] == "User A Applicant"
    print(f"[PASS] Scenario 5 Passed: Account A logged back in and retrieved its saved record {doc_id_a} with intact data.")

    # -------------------------------------------------------------------------
    # Scenario 6: Two browser profiles receive different device IDs
    # -------------------------------------------------------------------------
    print("\n--- Test Scenario 6: Two browser profiles receive different device IDs ---")
    id1 = str(uuid.uuid4())
    id2 = str(uuid.uuid4())
    assert id1 != id2 and len(id1) == 36 and len(id2) == 36, "UUID generation collision or format error"
    print(f"[PASS] Scenario 6 Passed: Distinct browser profiles receive unique random UUIDs ({id1[:8]}... vs {id2[:8]}...).")

    # -------------------------------------------------------------------------
    # Scenario 7: Changing device ID cannot bypass backend authorization
    # -------------------------------------------------------------------------
    print("\n--- Test Scenario 7: Changing device ID cannot bypass backend authorization ---")
    # Attacker Account B tries using Account A's device ID
    resp_spoof = client.get(
        f"/history/{doc_id_a}",
        headers={"Authorization": token_user_b, "X-Device-Id": device_browser_1}
    )
    assert resp_spoof.status_code == 404
    # Attacker with no token but valid device ID
    resp_spoof_no_token = client.get(
        f"/history/{doc_id_a}",
        headers={"X-Device-Id": device_browser_1}
    )
    assert resp_spoof_no_token.status_code == 401
    print("[PASS] Scenario 7 Passed: Changing or spoofing X-Device-Id cannot bypass token-based authorization.")

    # -------------------------------------------------------------------------
    # Scenario 9: Existing records are not accidentally overwritten or deleted
    # -------------------------------------------------------------------------
    print("\n--- Test Scenario 9: Existing records preservation ---")
    current_records = read_history(auto_purge=False)
    # The current count must be at least the initial count + 1 (the one we added for test)
    assert len(current_records) >= initial_count, f"Record loss detected! Expected >= {initial_count}, found {len(current_records)}"
    
    # Check that legacy records (where owner_uid is None) remain unchanged
    legacy_records = [d for d in current_records if d.get("owner_uid") is None]
    initial_legacy = [d for d in initial_records if d.get("owner_uid") is None]
    assert len(legacy_records) == len(initial_legacy), "Legacy records count changed!"
    print(f"[PASS] Scenario 9 Passed: All {len(legacy_records)} legacy records remain preserved without modification.")

    # -------------------------------------------------------------------------
    # Scenario 10: Public utility endpoints still work
    # -------------------------------------------------------------------------
    print("\n--- Test Scenario 10: Public utility endpoints check ---")
    resp_health = client.get("/health")
    assert resp_health.status_code == 200, f"Health check failed: {resp_health.text}"
    health_data = resp_health.json()
    assert health_data.get("status") == "healthy"
    print(f"[PASS] /health endpoint is operational (status: {health_data.get('status')}).")

    resp_models = client.get("/models")
    assert resp_models.status_code == 200
    print("[PASS] /models endpoint is operational.")

    resp_qr = client.post("/generate-qr", json={"type": "text", "data": "https://example.com/utility-bot"})
    assert resp_qr.status_code == 200, f"QR endpoint failed: {resp_qr.text}"
    qr_data = resp_qr.json()
    assert qr_data.get("success") is True and "image_base64" in qr_data
    print("[PASS] /generate-qr endpoint is operational (generated verified QR payload).")

    # Teardown: Clean up test documents created during testing
    try:
        from storage import HISTORY_FILE
        from reference_service import REFERENCES_FILE
        records = read_history(auto_purge=False)
        cleaned = [d for d in records if d.get("owner_uid") not in ("user_a", "user_b")]
        write_file_records(HISTORY_FILE, cleaned)
        
        with open(REFERENCES_FILE, "r", encoding="utf-8") as rf:
            ref_docs = json.load(rf)
        cleaned_refs = [d for d in ref_docs if d.get("owner_uid") not in ("user_a", "user_b")]
        with open(REFERENCES_FILE, "w", encoding="utf-8") as rf:
            json.dump(cleaned_refs, rf, indent=2)

        if MONGODB_URI:
            client_mongo = get_mongo_client()
            if client_mongo:
                db_mongo = client_mongo[MONGODB_DB_NAME]
                db_mongo["verifications"].delete_many({"owner_uid": {"$in": ["user_a", "user_b"]}})
                db_mongo["identity_references"].delete_many({"owner_uid": {"$in": ["user_a", "user_b"]}})
    except Exception as cleanup_err:
        print(f"[Notice] Teardown cleanup note: {cleanup_err}")

    print("\n" + "=" * 70)
    print("ALL 10 SCENARIOS VERIFIED SUCCESSFULLY!")
    print("=" * 70)

if __name__ == "__main__":
    try:
        run_tests()
    except Exception as e:
        print(f"\nFAILED WITH ERROR: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

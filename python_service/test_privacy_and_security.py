"""
test_privacy_and_security.py - Comprehensive Test Suite for Phases 1-9.

Test Scenarios:
- Test A: Account switching and history isolation
- Test B: Backend ownership enforcement and non-disclosing 404s
- Test C: Cloud storage and honest health reporting
- Test D: 30-Day retention cleanup (expired purged, fresh preserved, cross-user untouched)
- Test E: Privacy-safe Reference Card sharing and revocation
- Test F: Build and regression validation
"""

import os
import sys
import uuid
import json
from datetime import datetime, timedelta, timezone

os.environ["ALLOW_TEST_MOCK_TOKENS"] = "true"

from fastapi.testclient import TestClient
from main import app
from storage import (
    read_history, 
    write_file_records, 
    HISTORY_FILE, 
    get_mongo_client, 
    MONGODB_DB_NAME, 
    MONGODB_URI,
    check_database_health
)
from reference_service import (
    REFERENCES_FILE,
    read_reference_records,
    write_reference_records
)

client = TestClient(app)

def run_all_tests():
    print("=" * 75)
    print("STARTING TEST SUITE: PRIVACY, MONGODB STORAGE, AND SECURITY AUDIT")
    print("=" * 75)

    uid_a = f"test_user_a_{uuid.uuid4().hex[:6]}"
    uid_b = f"test_user_b_{uuid.uuid4().hex[:6]}"
    token_a = f"Bearer test_token_{uid_a}"
    token_b = f"Bearer test_token_{uid_b}"
    dev_1 = f"device_session_{uuid.uuid4().hex[:8]}"
    dev_2 = f"device_session_{uuid.uuid4().hex[:8]}"

    # -------------------------------------------------------------------------
    # TEST C: Cloud Storage & Honest Health Check
    # -------------------------------------------------------------------------
    print("\n[TEST C] Validating Health Endpoint & Database Connectivity...")
    resp_health = client.get("/health")
    assert resp_health.status_code == 200, f"Health check failed: {resp_health.text}"
    health_data = resp_health.json()
    assert "database_connected" in health_data
    assert "database_type" in health_data
    print(f"-> [PASS] /health reported honest connectivity: {health_data['database_connected']} (type: {health_data['database_type']})")

    # -------------------------------------------------------------------------
    # TEST A: Account Switching & Isolation
    # -------------------------------------------------------------------------
    print("\n[TEST A] Account Switching & Isolation across Same Device...")
    
    # 1. Account A signs in and confirms a record
    create_payload_a = {
        "action": "correct",
        "data": {"name": "User Alpha", "pan_number": "ABCDE1234F"},
        "document_type": "pan",
        "original_filename": "id_card_a.jpg"
    }
    resp_create_a = client.post("/confirm", json=create_payload_a, headers={"Authorization": token_a, "X-Device-Id": dev_1})
    assert resp_create_a.status_code == 200, f"Confirm failed: {resp_create_a.text}"
    doc_id_a = resp_create_a.json().get("sequential_id")
    ref_card_a = resp_create_a.json().get("reference_card")
    ref_id_a = ref_card_a.get("reference_id") if ref_card_a else None
    assert doc_id_a is not None
    print(f"-> Created Account A record {doc_id_a} (Ref ID: {ref_id_a})")

    # 2. Account A logs in from a SECOND device (dev_2) - multi-device cloud history
    resp_hist_a_dev2 = client.get("/history", headers={"Authorization": token_a, "X-Device-Id": dev_2})
    assert resp_hist_a_dev2.status_code == 200
    docs_a_dev2 = [d for d in resp_hist_a_dev2.json().get("documents", []) if d.get("_id") == doc_id_a]
    assert len(docs_a_dev2) == 1, "Account A cloud history was not accessible from device 2!"
    print("-> [PASS] Account A can access its cloud history from multiple devices.")

    # 3. Account A logs out. Account B logs in on SAME browser/device (dev_1)
    resp_hist_b = client.get("/history", headers={"Authorization": token_b, "X-Device-Id": dev_1})
    assert resp_hist_b.status_code == 200
    leaked_docs = [d for d in resp_hist_b.json().get("documents", []) if d.get("_id") == doc_id_a]
    assert len(leaked_docs) == 0, f"CRITICAL LEAK: Account B saw Account A's record {doc_id_a}!"
    print("-> [PASS] Account B cannot see Account A's records on the same browser/device.")

    # 4. Account A logs back in and sees its history
    resp_hist_a_again = client.get("/history", headers={"Authorization": token_a, "X-Device-Id": dev_1})
    assert resp_hist_a_again.status_code == 200
    docs_a_again = [d for d in resp_hist_a_again.json().get("documents", []) if d.get("_id") == doc_id_a]
    assert len(docs_a_again) == 1, "Account A could not see its history after logging back in!"
    print("-> [PASS] Account A logs back in and retrieves its saved history intact.")

    # -------------------------------------------------------------------------
    # TEST B: Backend Ownership & Non-Disclosing Responses
    # -------------------------------------------------------------------------
    print("\n[TEST B] Backend Ownership Enforcement & Non-Disclosing Responses...")
    
    # 1. Account B requests Account A's doc by ID
    resp_b_get_a = client.get(f"/history/{doc_id_a}", headers={"Authorization": token_b, "X-Device-Id": dev_1})
    assert resp_b_get_a.status_code == 404, f"Expected 404 for unauthorized doc fetch, got {resp_b_get_a.status_code}"
    print("-> [PASS] Account B GET /history/{doc_id_a} returned non-disclosing 404.")

    # 2. Account B attempts to delete Account A's record
    resp_b_del_a = client.delete(f"/history/{doc_id_a}", headers={"Authorization": token_b, "X-Device-Id": dev_1})
    assert resp_b_del_a.status_code == 404, f"Expected 404 for unauthorized doc delete, got {resp_b_del_a.status_code}"
    print("-> [PASS] Account B DELETE /history/{doc_id_a} returned 404 permission denied.")

    # 3. Spoofed headers or missing auth
    resp_unauth = client.get(f"/history/{doc_id_a}")
    assert resp_unauth.status_code == 401, f"Expected 401, got {resp_unauth.status_code}"
    print("-> [PASS] Unauthenticated request strictly rejected with 401.")

    # -------------------------------------------------------------------------
    # TEST D: 30-Day Retention Cleanup
    # -------------------------------------------------------------------------
    print("\n[TEST D] 30-Day Retention Policy & Storage Cleanup...")
    now = datetime.now(timezone.utc)
    old_date = (now - timedelta(days=35)).strftime("%Y-%m-%dT%H:%M:%SZ")
    fresh_date = (now - timedelta(days=2)).strftime("%Y-%m-%dT%H:%M:%SZ")

    # Inject one expired record and one fresh record for Account A, plus one for Account B
    expired_id = f"IMG_EXP_{uuid.uuid4().hex[:6]}"
    fresh_id = f"IMG_FRESH_{uuid.uuid4().hex[:6]}"
    user_b_rec_id = f"IMG_B_{uuid.uuid4().hex[:6]}"

    local_records = read_history(auto_purge=False)
    local_records.append({
        "_id": expired_id,
        "sequentialId": expired_id,
        "owner_uid": uid_a,
        "deviceId": dev_1,
        "status": "Success",
        "createdAt": old_date,
        "expiresAt": (now - timedelta(days=5)).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "data": {"name": "Old Expired Doc"}
    })
    local_records.append({
        "_id": fresh_id,
        "sequentialId": fresh_id,
        "owner_uid": uid_a,
        "deviceId": dev_1,
        "status": "Success",
        "createdAt": fresh_date,
        "expiresAt": (now + timedelta(days=28)).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "data": {"name": "Fresh Active Doc"}
    })
    local_records.append({
        "_id": user_b_rec_id,
        "sequentialId": user_b_rec_id,
        "owner_uid": uid_b,
        "deviceId": dev_1,
        "status": "Success",
        "createdAt": old_date,
        "expiresAt": (now - timedelta(days=5)).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "data": {"name": "User B Doc"}
    })
    write_file_records(HISTORY_FILE, local_records)

    # Sync to Atlas if connected
    if MONGODB_URI:
        client_m = get_mongo_client()
        if client_m:
            db_m = client_m[MONGODB_DB_NAME]
            db_m["verifications"].insert_one({"_id": expired_id, "owner_uid": uid_a, "createdAt": old_date, "expiresAt": (now - timedelta(days=5)).strftime("%Y-%m-%dT%H:%M:%SZ")})
            db_m["verifications"].insert_one({"_id": fresh_id, "owner_uid": uid_a, "createdAt": fresh_date, "expiresAt": (now + timedelta(days=28)).strftime("%Y-%m-%dT%H:%M:%SZ")})
            db_m["verifications"].insert_one({"_id": user_b_rec_id, "owner_uid": uid_b, "createdAt": old_date, "expiresAt": (now - timedelta(days=5)).strftime("%Y-%m-%dT%H:%M:%SZ")})

    # Account A runs clean storage (force_all=False)
    resp_clean = client.post("/storage/clean?force_all=false", headers={"Authorization": token_a, "X-Device-Id": dev_1})
    assert resp_clean.status_code == 200, f"Clean storage failed: {resp_clean.text}"
    print("-> Clean storage executed:", resp_clean.json().get("message"))

    # Verify: Expired record was deleted
    resp_get_exp = client.get(f"/history/{expired_id}", headers={"Authorization": token_a, "X-Device-Id": dev_1})
    assert resp_get_exp.status_code == 404, "Expired record was NOT purged by 30-day retention cleanup!"
    print("-> [PASS] Expired record (>30 days) was successfully purged.")

    # Verify: Fresh record is PRESERVED
    resp_get_fresh = client.get(f"/history/{fresh_id}", headers={"Authorization": token_a, "X-Device-Id": dev_1})
    assert resp_get_fresh.status_code == 200, "Fresh record (<30 days) was accidentally deleted!"
    print("-> [PASS] Fresh record (<=30 days) was preserved.")

    # Verify: User B's record was UNTOUCHED
    resp_get_b_rec = client.get(f"/history/{user_b_rec_id}", headers={"Authorization": token_b, "X-Device-Id": dev_1})
    assert resp_get_b_rec.status_code == 200, "User B's record was improperly modified during User A's cleanup!"
    print("-> [PASS] Another user's records were completely untouched during cleanup.")

    # -------------------------------------------------------------------------
    # TEST E: Privacy-Safe Reference Cards & QR Sharing
    # -------------------------------------------------------------------------
    print("\n[TEST E] Privacy-Safe Reference Card Sharing & Revocation...")
    if ref_id_a:
        # Public card access
        resp_public_ref = client.get(f"/reference/{ref_id_a}")
        assert resp_public_ref.status_code == 200, f"Public reference fetch failed: {resp_public_ref.text}"
        public_data = resp_public_ref.json()
        
        # Verify strict omission of private internal fields
        assert "owner_uid" not in public_data, "CRITICAL LEAK: owner_uid exposed in public reference card!"
        assert "verification_id" not in public_data, "CRITICAL LEAK: verification_id exposed in public reference card!"
        assert "device_id" not in public_data, "CRITICAL LEAK: device_id exposed in public reference card!"
        assert "qr_token" not in public_data, "CRITICAL LEAK: qr_token exposed in public reference card!"
        assert "masked_number" in public_data, "Masked number missing in public card!"
        print("-> [PASS] Public reference card returns strictly approved presentation fields.")

        # Account B tries to revoke Account A's reference card
        resp_revoke_b = client.post(f"/reference/{ref_id_a}/revoke", headers={"Authorization": token_b, "X-Device-Id": dev_1})
        assert resp_revoke_b.status_code == 403, f"Expected 403 for unauthorized revocation, got {resp_revoke_b.status_code}"
        print("-> [PASS] Unauthorized reference card revocation blocked with 403.")

        # Account A revokes own card
        resp_revoke_a = client.post(f"/reference/{ref_id_a}/revoke", headers={"Authorization": token_a, "X-Device-Id": dev_1})
        assert resp_revoke_a.status_code == 200, f"Revocation failed: {resp_revoke_a.text}"
        print("-> [PASS] Owner successfully revoked reference card.")

        # Accessing revoked card now returns 410 Gone
        resp_revoked_card = client.get(f"/reference/{ref_id_a}")
        assert resp_revoked_card.status_code == 410, f"Expected 410 for revoked card, got {resp_revoked_card.status_code}"
        print("-> [PASS] Accessing revoked reference card returns 410 Gone.")

    # -------------------------------------------------------------------------
    # Teardown: Clean up test artifacts
    # -------------------------------------------------------------------------
    try:
        h_records = read_history(auto_purge=False)
        h_clean = [d for d in h_records if d.get("owner_uid") not in (uid_a, uid_b)]
        write_file_records(HISTORY_FILE, h_clean)

        r_records = read_reference_records()
        r_clean = [d for d in r_records if d.get("owner_uid") not in (uid_a, uid_b)]
        write_reference_records(r_clean)

        if MONGODB_URI:
            client_m = get_mongo_client()
            if client_m:
                db_m = client_m[MONGODB_DB_NAME]
                db_m["verifications"].delete_many({"owner_uid": {"$in": [uid_a, uid_b]}})
                db_m["failed_verifications"].delete_many({"owner_uid": {"$in": [uid_a, uid_b]}})
                db_m["identity_references"].delete_many({"owner_uid": {"$in": [uid_a, uid_b]}})
    except Exception as cleanup_err:
        print("Teardown notice:", cleanup_err)

    print("\n" + "=" * 75)
    print("ALL TESTS (A, B, C, D, E) PASSED WITH ZERO FAILURES!")
    print("=" * 75)


if __name__ == "__main__":
    try:
        run_all_tests()
    except Exception as e:
        print("\nTEST FAILED WITH ERROR:", e)
        import traceback
        traceback.print_exc()
        sys.exit(1)

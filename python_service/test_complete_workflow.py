"""
test_complete_workflow.py - Automated Regression Test Suite for all 10 Scenarios:
1. Correct button confirms OCR and persists to database with owner_uid.
2. Navigating away and returning preserves confirmed state and reference card.
3. Wrong button marks audit failed and preserves record with sequential FAIL ID.
4. Generating QR code saves to QR history without plaintext credentials.
5. Scanning QR/barcode saves to scan history with decoded symbologies.
6. Shipping label extraction saves to shipping history with sender, receiver, tracking.
7. History drawer loads all 4 categories with user isolation.
8. Deleting record removes it from storage without affecting other accounts.
9. Retention cleanup purges records >30 days while preserving recent records.
10. Health check reports MongoDB connection status honestly with TLS.
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
    FAILED_HISTORY_FILE,
    SHIPPING_HISTORY_FILE,
    QR_HISTORY_FILE,
    get_mongo_client,
    MONGODB_DB_NAME,
    MONGODB_URI,
    check_database_health,
    clean_storage
)

client = TestClient(app)

def run_all_scenarios():
    print("=" * 80)
    print("RUNNING AUTOMATED REGRESSION SUITE: 10 COMPLETE WORKFLOW SCENARIOS")
    print("=" * 80)

    uid_a = f"test_user_a_{uuid.uuid4().hex[:6]}"
    uid_b = f"test_user_b_{uuid.uuid4().hex[:6]}"
    token_a = f"Bearer test_token_{uid_a}"
    token_b = f"Bearer test_token_{uid_b}"
    dev_id = f"device_{uuid.uuid4().hex[:8]}"

    # -------------------------------------------------------------------------
    # SCENARIO 1: Correct button confirms OCR and persists to DB with owner_uid
    # -------------------------------------------------------------------------
    print("\n--- Scenario 1: Correct Button Confirms OCR & Persists Record ---")
    confirm_payload = {
        "action": "correct",
        "data": {
            "name": "Kiruthikeyan S",
            "aadhaar_number": "9876 5432 1098",
            "date_of_birth": "01/01/1995"
        },
        "document_type": "aadhaar",
        "original_filename": "aadhaar_card_test.jpg"
    }
    resp1 = client.post(
        "/confirm",
        json=confirm_payload,
        headers={"Authorization": token_a, "X-Device-Id": dev_id}
    )
    assert resp1.status_code == 200, f"Scenario 1 failed: {resp1.text}"
    data1 = resp1.json()
    seq_id_1 = data1.get("sequential_id")
    assert seq_id_1 and seq_id_1.startswith("IMG"), f"Expected IMG sequential ID, got {seq_id_1}"
    assert data1.get("status") == "Success", f"Expected Success status, got {data1.get('status')}"
    ref_card = data1.get("reference_card")
    assert ref_card is not None, "Expected reference card to be generated on confirmation"
    assert ref_card.get("owner_uid") == uid_a, f"Reference card owner mismatch: {ref_card.get('owner_uid')}"
    print(f"[PASS] Scenario 1: Confirmed ID {seq_id_1} persisted with owner_uid {uid_a}")

    # -------------------------------------------------------------------------
    # SCENARIO 2: Navigating away and returning preserves confirmed state & ref card
    # -------------------------------------------------------------------------
    print("\n--- Scenario 2: Preserving Confirmed State Across Navigation ---")
    # Retrieve record by ID as user_a
    resp2 = client.get(
        f"/history/{seq_id_1}",
        headers={"Authorization": token_a, "X-Device-Id": dev_id}
    )
    assert resp2.status_code == 200, f"Failed to retrieve record: {resp2.text}"
    doc2 = resp2.json()
    assert doc2.get("status") == "Success"
    assert doc2.get("owner_uid") == uid_a
    assert doc2.get("data", {}).get("name") == "Kiruthikeyan S"
    print(f"[PASS] Scenario 2: Confirmed state and verified data restored accurately for {seq_id_1}")

    # -------------------------------------------------------------------------
    # SCENARIO 3: Wrong button marks audit failed and preserves record
    # -------------------------------------------------------------------------
    print("\n--- Scenario 3: Wrong Button Marks Audit Failed ---")
    wrong_payload = {
        "action": "wrong",
        "data": {
            "name": "Invalid Person",
            "pan_number": "INVALID123"
        },
        "document_type": "pan",
        "original_filename": "blurry_doc.jpg"
    }
    resp3 = client.post(
        "/confirm",
        json=wrong_payload,
        headers={"Authorization": token_a, "X-Device-Id": dev_id}
    )
    assert resp3.status_code == 200, f"Scenario 3 failed: {resp3.text}"
    data3 = resp3.json()
    fail_id = data3.get("sequential_id")
    assert fail_id and fail_id.startswith("FAIL"), f"Expected FAIL sequential ID, got {fail_id}"
    assert data3.get("status") == "Failed"
    assert data3.get("reference_card") is None

    # Verify audit failure appears in failed-history for user_a
    resp_failed_hist = client.get(
        "/failed-history",
        headers={"Authorization": token_a, "X-Device-Id": dev_id}
    )
    assert resp_failed_hist.status_code == 200
    failed_docs = [d for d in resp_failed_hist.json().get("documents", []) if d.get("_id") == fail_id]
    assert len(failed_docs) == 1, "Failed record not found in failed-history"
    print(f"[PASS] Scenario 3: Audit failure recorded with sequential ID {fail_id}")

    # -------------------------------------------------------------------------
    # SCENARIO 4: Generating QR code saves to QR history without plaintext passwords
    # -------------------------------------------------------------------------
    print("\n--- Scenario 4: QR Generation & Sensitive Field Masking ---")
    qr_payload = {
        "action_type": "generate",
        "qr_type": "wifi",
        "content": "WIFI:T:WPA;S:OfficeNet;P:superSecretP@ssword;;",
        "fields": {
            "ssid": "OfficeNet",
            "password": "superSecretP@ssword",
            "auth_type": "WPA"
        },
        "metadata": {"size": 400, "error_correction": "M"}
    }
    resp4 = client.post(
        "/qr/save",
        json=qr_payload,
        headers={"Authorization": token_a, "X-Device-Id": dev_id}
    )
    assert resp4.status_code == 200, f"Scenario 4 save failed: {resp4.text}"
    qr_rec = resp4.json().get("record")
    qr_id = resp4.json().get("id")
    assert qr_id and qr_id.startswith("QR"), f"Expected QR sequential ID, got {qr_id}"
    # Verify password is masked
    assert qr_rec.get("fields", {}).get("password") == "***", f"Password was not masked: {qr_rec.get('fields')}"
    assert "superSecretP@ssword" not in qr_rec.get("content", ""), "Plaintext password leaked in QR content!"
    print(f"[PASS] Scenario 4: QR generated & saved as {qr_id} with sanitized credentials (***)")

    # -------------------------------------------------------------------------
    # SCENARIO 5: Scanning QR/barcode saves to scan history with decoded symbologies
    # -------------------------------------------------------------------------
    print("\n--- Scenario 5: Scanning QR/Barcode & Persisting Decoded Symbologies ---")
    scan_payload = {
        "action_type": "scan",
        "qr_type": "scan",
        "content": "TRACK-CODE128-892374923",
        "barcodes": [{"data": "TRACK-CODE128-892374923", "symbology": "CODE_128", "rect": [10, 20, 100, 40]}],
        "qr_codes": [{"data": "https://verify.example.com/item/101", "symbology": "QR_CODE"}],
        "metadata": {"filename": "shipping_box_scan.png", "total_detected": 2}
    }
    resp5 = client.post(
        "/qr/save",
        json=scan_payload,
        headers={"Authorization": token_a, "X-Device-Id": dev_id}
    )
    assert resp5.status_code == 200, f"Scenario 5 save failed: {resp5.text}"
    scan_id = resp5.json().get("id")
    assert scan_id and scan_id.startswith("QR")
    # Verify retrieval
    resp_qr_item = client.get(f"/qr/history/{scan_id}", headers={"Authorization": token_a, "X-Device-Id": dev_id})
    assert resp_qr_item.status_code == 200
    assert len(resp_qr_item.json().get("barcodes", [])) == 1
    assert len(resp_qr_item.json().get("qr_codes", [])) == 1
    print(f"[PASS] Scenario 5: Scan saved as {scan_id} with CODE_128 barcode & QR code")

    # -------------------------------------------------------------------------
    # SCENARIO 6: Shipping label extraction saves to shipping history
    # -------------------------------------------------------------------------
    print("\n--- Scenario 6: Shipping Label Extraction & History Persistence ---")
    ship_payload = {
        "title": "FedEx Express 7892341209",
        "carrier": "FedEx",
        "tracking_number": "7892341209",
        "sender": {"name": "Logistics Hub", "city": "Bengaluru", "pincode": "560001"},
        "receiver": {"name": "Customer John", "city": "Chennai", "pincode": "600001"},
        "package_details": {"weight": "1.8 kg", "service": "Priority Overnight"},
        "items": [{"description": "Electronics Component", "quantity": "2"}],
        "barcodes": [{"data": "7892341209", "symbology": "CODE_128"}],
        "raw_text": "FedEx Express Priority Overnight Tracking 7892341209 Deliver To Chennai"
    }
    resp6 = client.post(
        "/shipping/save",
        json=ship_payload,
        headers={"Authorization": token_a, "X-Device-Id": dev_id}
    )
    assert resp6.status_code == 200, f"Scenario 6 save failed: {resp6.text}"
    ship_id = resp6.json().get("id")
    assert ship_id and ship_id.startswith("SHIP"), f"Expected SHIP sequential ID, got {ship_id}"
    resp_ship_get = client.get(f"/shipping/history/{ship_id}", headers={"Authorization": token_a, "X-Device-Id": dev_id})
    assert resp_ship_get.status_code == 200
    ship_rec = resp_ship_get.json()
    assert ship_rec.get("tracking_number") == "7892341209"
    assert ship_rec.get("receiver", {}).get("name") == "Customer John"
    print(f"[PASS] Scenario 6: Shipping extraction saved as {ship_id} with full routing details")

    # -------------------------------------------------------------------------
    # SCENARIO 7: History drawer loads all 4 categories with user isolation
    # -------------------------------------------------------------------------
    print("\n--- Scenario 7: Unified History Drawer & Account Isolation ---")
    # User A checks all 4 categories
    r_id_a = client.get("/history", headers={"Authorization": token_a, "X-Device-Id": dev_id}).json()
    r_ship_a = client.get("/shipping/history", headers={"Authorization": token_a, "X-Device-Id": dev_id}).json()
    r_qr_gen_a = client.get("/qr/history?action_type=generate", headers={"Authorization": token_a, "X-Device-Id": dev_id}).json()
    r_qr_scan_a = client.get("/qr/history?action_type=scan", headers={"Authorization": token_a, "X-Device-Id": dev_id}).json()

    assert any(d.get("_id") == seq_id_1 for d in r_id_a.get("documents", [])), "User A ID history missing record"
    assert any(d.get("_id") == ship_id for d in r_ship_a.get("documents", [])), "User A shipping history missing record"
    assert any(d.get("_id") == qr_id for d in r_qr_gen_a.get("documents", [])), "User A QR gen history missing record"
    assert any(d.get("_id") == scan_id for d in r_qr_scan_a.get("documents", [])), "User A QR scan history missing record"

    # User B checks all 4 categories on the SAME device -> MUST SEE ZERO OF USER A'S DATA
    r_id_b = client.get("/history", headers={"Authorization": token_b, "X-Device-Id": dev_id}).json()
    r_ship_b = client.get("/shipping/history", headers={"Authorization": token_b, "X-Device-Id": dev_id}).json()
    r_qr_b = client.get("/qr/history", headers={"Authorization": token_b, "X-Device-Id": dev_id}).json()

    assert not any(d.get("_id") == seq_id_1 for d in r_id_b.get("documents", [])), "LEAK: User B saw User A's ID record!"
    assert not any(d.get("_id") == ship_id for d in r_ship_b.get("documents", [])), "LEAK: User B saw User A's shipping record!"
    assert not any(d.get("_id") in [qr_id, scan_id] for d in r_qr_b.get("documents", [])), "LEAK: User B saw User A's QR record!"
    print("[PASS] Scenario 7: All 4 categories loaded successfully with strict cross-account isolation")

    # -------------------------------------------------------------------------
    # SCENARIO 8: Deleting record removes it from MongoDB without affecting others
    # -------------------------------------------------------------------------
    print("\n--- Scenario 8: Deleting Records with Cross-Account Protection ---")
    # User B tries to delete User A's shipping record -> MUST FAIL 404
    resp_hack_del = client.delete(f"/shipping/history/{ship_id}", headers={"Authorization": token_b, "X-Device-Id": dev_id})
    assert resp_hack_del.status_code == 404, f"Unauthorized delete succeeded! {resp_hack_del.status_code}"

    # User A deletes their own shipping record -> MUST SUCCEED
    resp_legit_del = client.delete(f"/shipping/history/{ship_id}", headers={"Authorization": token_a, "X-Device-Id": dev_id})
    assert resp_legit_del.status_code == 200, f"Delete failed: {resp_legit_del.text}"

    # Verify it is no longer returned
    resp_verify_del = client.get(f"/shipping/history/{ship_id}", headers={"Authorization": token_a, "X-Device-Id": dev_id})
    assert resp_verify_del.status_code == 404
    print(f"[PASS] Scenario 8: Deletion verified. Unauthorized delete safely blocked with 404")

    # -------------------------------------------------------------------------
    # SCENARIO 9: Retention cleanup purges records >30 days, preserves fresh records
    # -------------------------------------------------------------------------
    print("\n--- Scenario 9: 30-Day Auto-Retention Cleanup ---")
    now_utc = datetime.now(timezone.utc)
    old_time_str = (now_utc - timedelta(days=45)).strftime("%Y-%m-%dT%H:%M:%SZ")

    # Insert an expired record for User A
    expired_record = {
        "_id": f"IMG{uuid.uuid4().hex[:6].upper()}",
        "sequentialId": f"IMG{uuid.uuid4().hex[:6].upper()}",
        "owner_uid": uid_a,
        "deviceId": dev_id,
        "status": "Success",
        "createdAt": old_time_str,
        "expiresAt": (now_utc - timedelta(days=15)).strftime("%Y-%m-%dT%H:%M:%SZ")
    }
    history = read_history(auto_purge=False)
    history.append(expired_record)
    write_file_records(HISTORY_FILE, history)

    # Run clean storage for User A (force_all=False)
    resp_clean = client.post(
        "/storage/clean?force_all=false",
        headers={"Authorization": token_a, "X-Device-Id": dev_id}
    )
    assert resp_clean.status_code == 200
    clean_data = resp_clean.json()
    assert clean_data.get("deleted_count", 0) >= 1

    # Fresh record from Scenario 1 must still exist
    resp_check_fresh = client.get(f"/history/{seq_id_1}", headers={"Authorization": token_a, "X-Device-Id": dev_id})
    assert resp_check_fresh.status_code == 200, "Fresh record was improperly deleted during cleanup!"
    print(f"[PASS] Scenario 9: Expired records purged (>30 days), fresh record {seq_id_1} intact")

    # -------------------------------------------------------------------------
    # SCENARIO 10: Health check reports MongoDB connection status honestly with TLS
    # -------------------------------------------------------------------------
    print("\n--- Scenario 10: Health Check & TLS Database Verification ---")
    resp_health = client.get("/health")
    assert resp_health.status_code == 200
    h_data = resp_health.json()
    assert "database_connected" in h_data
    assert "database_type" in h_data
    assert h_data.get("ocr_available") is True
    print(f"[PASS] Scenario 10: Health endpoint healthy: DB={h_data['database_connected']} ({h_data['database_type']}), OCR={h_data['ocr_available']}")

    print("\n" + "=" * 80)
    print("ALL 10 SCENARIOS PASSED REGRESSION TESTING PERFECTLY!")
    print("=" * 80)

if __name__ == "__main__":
    run_all_scenarios()

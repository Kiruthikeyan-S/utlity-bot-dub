"""
storage.py - High-Performance Verification Storage Layer.
Supports Human-in-the-Loop Confirmation Gateway, Dual Collections:
- 'verifications' (Success with sequential ID 'IMG000001', 'IMG000002'...)
- 'failed_verifications' (Audit Failed with sequential ID 'FAIL000001', 'FAIL000002'...)
With 30-Day Auto-Retention, Photo Thumbnails, and Strict User (owner_uid) + Device (deviceId) Isolation.
"""

import os
import json
import uuid
import logging
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Any, Optional
import certifi
from dotenv import load_dotenv

load_dotenv()

try:
    import pymongo
except ImportError:
    pymongo = None

logger = logging.getLogger("utility_bot.storage")

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
HISTORY_FILE = os.path.join(DATA_DIR, "history.json")
FAILED_HISTORY_FILE = os.path.join(DATA_DIR, "failed_history.json")
SHIPPING_HISTORY_FILE = os.path.join(DATA_DIR, "shipping_history.json")
QR_HISTORY_FILE = os.path.join(DATA_DIR, "qr_history.json")
COUNTERS_FILE = os.path.join(DATA_DIR, "counters.json")
RETENTION_DAYS = 30

os.makedirs(DATA_DIR, exist_ok=True)
for file_path in [HISTORY_FILE, FAILED_HISTORY_FILE, SHIPPING_HISTORY_FILE, QR_HISTORY_FILE]:
    if not os.path.exists(file_path):
        with open(file_path, "w", encoding="utf-8") as f:
            f.write("[]\n")

if not os.path.exists(COUNTERS_FILE):
    with open(COUNTERS_FILE, "w", encoding="utf-8") as f:
        json.dump({"IMG": 0, "FAIL": 0, "SHIP": 0, "QR": 0}, f, indent=2)
        f.write("\n")

# ---------------------------------------------------------------------------
# MongoDB Atlas Database Configuration
# Requires: MONGODB_URI in .env
# Dedicated History Database: utility_bot_history
# ---------------------------------------------------------------------------
MONGODB_URI = os.getenv("MONGODB_URI")
MONGODB_DATA_API_KEY = os.getenv("MONGODB_DATA_API_KEY", "")
MONGODB_APP_ID = os.getenv("MONGODB_APP_ID", "")
MONGODB_DB_NAME = os.getenv("MONGODB_DB_NAME", "utility_bot_history")
MONGODB_CLUSTER = os.getenv("MONGODB_CLUSTER", "Cluster0")

_ATLAS_DATA_URL = f"https://data.mongodb-api.com/app/{MONGODB_APP_ID}/endpoint/data/v1" if MONGODB_APP_ID else ""
IS_MONGO_ONLINE = False
_mongo_client = None


def _atlas_request(action: str, collection: str, body: dict) -> dict:
    """Send a request to MongoDB Atlas Data API (HTTPS POST). Thread-safe."""
    if not _ATLAS_DATA_URL or not MONGODB_DATA_API_KEY:
        return {}
    import urllib.request
    url = f"{_ATLAS_DATA_URL}/action/{action}"
    payload = {
        "dataSource": MONGODB_CLUSTER,
        "database": MONGODB_DB_NAME,
        "collection": collection,
        **body
    }
    data = json.dumps(payload, default=str).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={
            "Content-Type": "application/json",
            "api-key": MONGODB_DATA_API_KEY,
        },
        method="POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception as err:
        logger.warning(f"Atlas Data API error: {err}")
        return {}


def get_mongo_client():
    """
    Returns a cached, thread-safe singleton MongoClient with verified TLS certificates.
    Reusing the pooled client avoids expensive repeated DNS SRV + TLS handshakes on every request.
    """
    global _mongo_client
    if not MONGODB_URI:
        return None
    if _mongo_client is not None:
        return _mongo_client
    try:
        import pymongo
        _mongo_client = pymongo.MongoClient(
            MONGODB_URI,
            tls=True,
            tlsCAFile=certifi.where(),
            tlsAllowInvalidCertificates=False,
            serverSelectionTimeoutMS=5000,
            connectTimeoutMS=5000,
            socketTimeoutMS=10000,
            maxPoolSize=20
        )
        return _mongo_client
    except Exception as err:
        logger.warning(f"MongoDB connection notice: {err}")
        return None


def check_database_health() -> Dict[str, Any]:
    """
    Performs a real database connectivity check (e.g. MongoDB ping).
    Reports honest connection status and latency.
    """
    if not MONGODB_URI:
        return {
            "connected": True,
            "database_type": "Local Store (history.json)",
            "message": "Local JSON store operational."
        }
    try:
        import time
        client = get_mongo_client()
        if client:
            t0 = time.time()
            client.admin.command("ping")
            latency_ms = round((time.time() - t0) * 1000, 2)
            return {
                "connected": True,
                "database_type": "MongoDB Atlas",
                "latency_ms": latency_ms,
                "message": f"Connected to MongoDB Atlas ({latency_ms}ms ping)."
            }
    except Exception as e:
        logger.error(f"MongoDB ping failed: {e}")
        return {
            "connected": False,
            "database_type": "MongoDB Atlas",
            "error": f"MongoDB Atlas ping failed: {str(e)}"
        }
    return {
        "connected": False,
        "database_type": "MongoDB Atlas",
        "error": "Could not initialize MongoDB client."
    }


_indexes_initialized = False

def ensure_database_indexes():
    """Ensures owner-scoped and TTL expiry indexes exist on MongoDB Atlas collections."""
    global _indexes_initialized
    if _indexes_initialized or not MONGODB_URI:
        return
    try:
        client = get_mongo_client()
        if client:
            db = client[MONGODB_DB_NAME]
            # Owner & creation sort index on verifications
            db["verifications"].create_index([("owner_uid", 1), ("createdAt", -1)], background=True)
            db["verifications"].create_index([("expiresAt", 1)], background=True)
            # Owner index on failed verifications
            db["failed_verifications"].create_index([("owner_uid", 1), ("createdAt", -1)], background=True)
            # Owner index on shipping history
            db["shipping_history"].create_index([("owner_uid", 1), ("createdAt", -1)], background=True)
            db["shipping_history"].create_index([("expiresAt", 1)], background=True)
            # Owner index on QR history
            db["qr_history"].create_index([("owner_uid", 1), ("createdAt", -1)], background=True)
            db["qr_history"].create_index([("expiresAt", 1)], background=True)
            # Reference cards indexes
            db["identity_references"].create_index([("reference_id", 1)], unique=True, background=True)
            db["identity_references"].create_index([("owner_uid", 1)], background=True)
            _indexes_initialized = True
            logger.info("MongoDB Atlas indexes ensured successfully.")
    except Exception as e:
        logger.warning(f"Could not initialize MongoDB indexes: {e}")


def sync_record_to_mongodb(collection_name: str, record_id: str, record: dict) -> bool:
    """Syncs a record to MongoDB Atlas using native pymongo (or Data API fallback)."""
    # 1. Native PyMongo (Preferred)
    if MONGODB_URI:
        try:
            client = get_mongo_client()
            if client:
                db = client[MONGODB_DB_NAME]
                db[collection_name].replace_one({"_id": record_id}, record, upsert=True)
                return True
        except Exception as e:
            logger.error(f"Failed to sync to MongoDB Atlas via PyMongo: {e}")
            raise RuntimeError(f"Cloud persistence to MongoDB Atlas failed: {e}")

    # 2. Atlas Data API Fallback
    if IS_MONGO_ONLINE and _ATLAS_DATA_URL:
        try:
            _atlas_request("replaceOne", collection_name, {
                "filter": {"_id": record_id},
                "replacement": record,
                "upsert": True
            })
            return True
        except Exception as e:
            logger.error(f"Failed to sync to MongoDB Atlas via Data API: {e}")
            raise RuntimeError(f"Cloud persistence to MongoDB Atlas Data API failed: {e}")

    return False


def get_next_sequence_id(prefix: str = "IMG") -> str:
    """
    Generates atomic sequential IDs:
    - 'IMG000001', 'IMG000002'... for verified Success records
    - 'FAIL000001', 'FAIL000002'... for audit Failed records
    """
    counters = {"IMG": 0, "FAIL": 0}
    if os.path.exists(COUNTERS_FILE):
        try:
            with open(COUNTERS_FILE, "r", encoding="utf-8") as f:
                counters.update(json.load(f))
        except Exception:
            pass

    counters[prefix] = counters.get(prefix, 0) + 1

    # Atomic counter sync via MongoDB native if available
    if MONGODB_URI:
        try:
            client = get_mongo_client()
            if client:
                db = client[MONGODB_DB_NAME]
                doc = db["counters"].find_one_and_update(
                    {"_id": prefix},
                    {"$inc": {"seq": 1}},
                    upsert=True,
                    return_document=pymongo.ReturnDocument.AFTER
                )
                if doc and "seq" in doc:
                    counters[prefix] = max(counters[prefix], int(doc["seq"]))
        except Exception:
            pass
    elif IS_MONGO_ONLINE and _ATLAS_DATA_URL:
        try:
            _atlas_request("updateOne", "counters", {
                "filter": {"_id": prefix},
                "update": {"$inc": {"seq": 1}, "$setOnInsert": {"_id": prefix}},
                "upsert": True
            })
            res = _atlas_request("findOne", "counters", {"filter": {"_id": prefix}})
            if res and res.get("document") and "seq" in res["document"]:
                counters[prefix] = max(counters[prefix], int(res["document"]["seq"]))
        except Exception:
            pass

    try:
        with open(COUNTERS_FILE, "w", encoding="utf-8") as f:
            json.dump(counters, f, indent=2)
    except Exception:
        pass

    return f"{prefix}{counters[prefix]:06d}"


def read_file_records(file_path: str, auto_purge: bool = True) -> List[Dict[str, Any]]:
    """Reads stored records and automatically purges items older than 30 days."""
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        data = []

    if auto_purge and data:
        now = datetime.now(timezone.utc)
        valid_records = []
        has_expired = False
        for doc in data:
            created_str = doc.get("createdAt")
            if created_str:
                try:
                    clean_str = created_str.replace("Z", "+00:00")
                    created_dt = datetime.fromisoformat(clean_str)
                    if created_dt.tzinfo is None:
                        created_dt = created_dt.replace(tzinfo=timezone.utc)
                    age_days = (now - created_dt).total_seconds() / 86400.0
                    if age_days <= RETENTION_DAYS:
                        valid_records.append(doc)
                    else:
                        has_expired = True
                except Exception:
                    valid_records.append(doc)
            else:
                valid_records.append(doc)
        
        if has_expired:
            try:
                with open(file_path, "w", encoding="utf-8") as f:
                    json.dump(valid_records, f, indent=2)
            except Exception:
                pass
            return valid_records

    return data


def read_history(auto_purge: bool = True) -> List[Dict[str, Any]]:
    """Reads confirmed success verification records ('IMG...')."""
    return read_file_records(HISTORY_FILE, auto_purge=auto_purge)


def read_failed_history(auto_purge: bool = True) -> List[Dict[str, Any]]:
    """Reads failed verification records ('FAIL...')."""
    return read_file_records(FAILED_HISTORY_FILE, auto_purge=auto_purge)


def write_file_records(file_path: str, data: List[Dict[str, Any]]) -> None:
    try:
        with open(file_path, "w", encoding="utf-8") as f:
            if not data:
                f.write("[]\n")
            else:
                json.dump(data, f, indent=2)
                f.write("\n")
    except Exception as e:
        logger.error(f"Error writing {file_path}: {e}")


def save_confirmed_verification(
    result_dict: Dict[str, Any],
    action: str = "correct",
    edited_data: Optional[Dict[str, Any]] = None,
    original_filename: str = "document.jpg",
    thumbnail_image: Optional[str] = None,
    portrait_photo: Optional[str] = None,
    device_id: Optional[str] = None,
    owner_uid: Optional[str] = None
) -> Dict[str, Any]:
    """
    Saves confirmed human verification with dual-key ownership (owner_uid and deviceId):
    - 'correct': Assigns 'IMG000001', sets status='Success', saves to 'verifications'
    - 'wrong': Assigns 'FAIL000001', sets status='Failed', saves to 'failed_verifications'
    """
    prefix = "IMG" if action == "correct" else "FAIL"
    seq_id = get_next_sequence_id(prefix)
    status = "Success" if action == "correct" else "Failed"
    audit_action = "CORRECT" if action == "correct" else "WRONG"
    target_file = HISTORY_FILE if action == "correct" else FAILED_HISTORY_FILE
    target_collection_name = "verifications" if action == "correct" else "failed_verifications"

    clean_data = edited_data or result_dict.get("data", {})
    if hasattr(clean_data, "dict"):
        clean_data = clean_data.dict()
    elif hasattr(clean_data, "model_dump"):
        clean_data = clean_data.model_dump()

    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(days=RETENTION_DAYS)
    created_at_iso = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    expires_at_iso = expires_at.strftime("%Y-%m-%dT%H:%M:%SZ")

    record = {
        "_id": seq_id,
        "sequentialId": seq_id,
        "owner_uid": owner_uid,
        "deviceId": device_id or "default_client",
        "status": status,
        "auditAction": audit_action,
        "documentType": result_dict.get("document_type", "unsupported"),
        "isValid": True if action == "correct" else False,
        "shortCircuited": result_dict.get("short_circuited", False),
        "isDuplicateOrSample": result_dict.get("is_duplicate_or_sample", False),
        "authenticityStatus": result_dict.get("authenticity_status", "VERIFIED"),
        "data": clean_data,
        "warnings": result_dict.get("warnings", []),
        "ocrConfidence": result_dict.get("ocr_confidence", 0.0),
        "rawOcrText": result_dict.get("raw_ocr_text", ""),
        "qualityReport": result_dict.get("quality_report", {}),
        "originalFileName": original_filename,
        "thumbnail": thumbnail_image,
        "portraitPhoto": portrait_photo or result_dict.get("portrait_photo"),
        "createdAt": created_at_iso,
        "expiresAt": expires_at_iso,
        "retentionDays": RETENTION_DAYS,
    }

    # 1. Insert into local storage
    records = read_file_records(target_file, auto_purge=True)
    records.insert(0, record)
    if len(records) > 500:
        records = records[:500]
    write_file_records(target_file, records)

    # 2. Sync to MongoDB Atlas (PyMongo or Data API)
    if MONGODB_URI:
        sync_record_to_mongodb(target_collection_name, seq_id, record)

    return {
        "id": seq_id,
        "sequential_id": seq_id,
        "status": status,
        "audit_action": audit_action,
        "collection": target_collection_name,
        "record": record
    }


def get_history(
    limit: int = 50, 
    page: int = 1, 
    doc_type: Optional[str] = None,
    device_id: Optional[str] = None,
    owner_uid: Optional[str] = None
) -> Dict[str, Any]:
    """
    Retrieves verified SUCCESS records strictly matching authenticated owner_uid.
    Cloud history is available across all of the user's devices.
    """
    if not owner_uid:
        return {
            "documents": [],
            "total": 0,
            "page": page,
            "pages": 1,
            "deviceId": device_id,
            "owner_uid": owner_uid,
            "retentionDays": RETENTION_DAYS,
            "source": "utility_bot_store"
        }

    # Query MongoDB Atlas first if configured
    if MONGODB_URI:
        try:
            client = get_mongo_client()
            if client:
                db = client[MONGODB_DB_NAME]
                query: Dict[str, Any] = {"owner_uid": owner_uid}
                if doc_type:
                    query["documentType"] = doc_type

                total = db["verifications"].count_documents(query)
                cursor = db["verifications"].find(query).sort("createdAt", -1).skip((page - 1) * limit).limit(limit)
                docs = list(cursor)
                for d in docs:
                    if "_id" in d and not isinstance(d["_id"], str):
                        d["_id"] = str(d["_id"])
                    # Ensure reference_card is attached if stored in identity_references
                    if not d.get("reference_card"):
                        ref_doc = db["identity_references"].find_one(
                            {"verification_id": d["_id"], "owner_uid": owner_uid},
                            {"_id": 0}
                        )
                        if ref_doc:
                            d["reference_card"] = ref_doc
                pages = (total + limit - 1) // limit if total > 0 else 1
                return {
                    "documents": docs,
                    "total": total,
                    "page": page,
                    "pages": pages,
                    "deviceId": device_id,
                    "owner_uid": owner_uid,
                    "retentionDays": RETENTION_DAYS,
                    "source": "mongodb_atlas",
                    "database": MONGODB_DB_NAME
                }
        except Exception as mongo_err:
            logger.warning(f"Error querying MongoDB Atlas history: {mongo_err}")

    history = read_history(auto_purge=True)
    history = [d for d in history if d.get("owner_uid") == owner_uid]
        
    if doc_type:
        history = [d for d in history if d.get("documentType") == doc_type]
    
    total = len(history)
    start = (page - 1) * limit
    paginated = history[start:start + limit]
    pages = (total + limit - 1) // limit if total > 0 else 1
    
    return {
        "documents": paginated,
        "total": total,
        "page": page,
        "pages": pages,
        "deviceId": device_id,
        "owner_uid": owner_uid,
        "retentionDays": RETENTION_DAYS,
        "source": "utility_bot_store"
    }


def get_failed_history(
    limit: int = 50, 
    page: int = 1, 
    device_id: Optional[str] = None,
    owner_uid: Optional[str] = None
) -> Dict[str, Any]:
    """Retrieves FAILED audit records strictly matching authenticated owner_uid."""
    if not owner_uid:
        return {
            "documents": [],
            "total": 0,
            "page": page,
            "pages": 1,
            "deviceId": device_id,
            "owner_uid": owner_uid,
            "source": "failed_verifications"
        }

    # Query MongoDB Atlas first if configured
    if MONGODB_URI:
        try:
            client = get_mongo_client()
            if client:
                db = client[MONGODB_DB_NAME]
                query: Dict[str, Any] = {"owner_uid": owner_uid}

                total = db["failed_verifications"].count_documents(query)
                cursor = db["failed_verifications"].find(query).sort("createdAt", -1).skip((page - 1) * limit).limit(limit)
                docs = list(cursor)
                for d in docs:
                    if "_id" in d and not isinstance(d["_id"], str):
                        d["_id"] = str(d["_id"])
                pages = (total + limit - 1) // limit if total > 0 else 1
                return {
                    "documents": docs,
                    "total": total,
                    "page": page,
                    "pages": pages,
                    "deviceId": device_id,
                    "owner_uid": owner_uid,
                    "source": "failed_verifications_atlas"
                }
        except Exception as mongo_err:
            logger.warning(f"Error querying MongoDB Atlas failed history: {mongo_err}")

    failed = read_failed_history(auto_purge=True)
    failed = [d for d in failed if d.get("owner_uid") == owner_uid]
        
    total = len(failed)
    start = (page - 1) * limit
    paginated = failed[start:start + limit]
    pages = (total + limit - 1) // limit if total > 0 else 1
    
    return {
        "documents": paginated,
        "total": total,
        "page": page,
        "pages": pages,
        "deviceId": device_id,
        "owner_uid": owner_uid,
        "source": "failed_verifications"
    }


def get_extraction_by_id(
    doc_id: str, 
    device_id: Optional[str] = None, 
    owner_uid: Optional[str] = None
) -> Optional[Dict[str, Any]]:
    """Retrieves a single verification record verifying authenticated owner_uid."""
    if not owner_uid:
        return None

    # Check MongoDB Atlas first
    if MONGODB_URI:
        try:
            client = get_mongo_client()
            if client:
                db = client[MONGODB_DB_NAME]
                doc = db["verifications"].find_one({"_id": doc_id, "owner_uid": owner_uid})
                if doc:
                    if "_id" in doc and not isinstance(doc["_id"], str):
                        doc["_id"] = str(doc["_id"])
                    if not doc.get("reference_card"):
                        ref_doc = db["identity_references"].find_one(
                            {"verification_id": doc["_id"], "owner_uid": owner_uid},
                            {"_id": 0}
                        )
                        if ref_doc:
                            doc["reference_card"] = ref_doc
                    return doc
        except Exception:
            pass

    history = read_history(auto_purge=True)
    for doc in history:
        if doc.get("_id") == doc_id or doc.get("sequentialId") == doc_id:
            if doc.get("owner_uid") != owner_uid:
                return None
            return doc

    return None


def delete_extraction_by_id(
    doc_id: str, 
    device_id: Optional[str] = None, 
    owner_uid: Optional[str] = None
) -> bool:
    """Deletes a verification record strictly verifying authenticated owner_uid."""
    if not owner_uid:
        return False

    history = read_history(auto_purge=False)
    new_history = []
    found_local = False
    for d in history:
        if d.get("_id") == doc_id or d.get("sequentialId") == doc_id:
            if d.get("owner_uid") != owner_uid:
                new_history.append(d)
                continue
            found_local = True
        else:
            new_history.append(d)

    if found_local:
        write_file_records(HISTORY_FILE, new_history)

    found_mongo = False
    if MONGODB_URI:
        try:
            client = get_mongo_client()
            if client:
                db = client[MONGODB_DB_NAME]
                res = db["verifications"].delete_one({"_id": doc_id, "owner_uid": owner_uid})
                if res.deleted_count > 0:
                    found_mongo = True
        except Exception:
            pass

    return found_local or found_mongo


# ---------------------------------------------------------------------------
# Shipping History Operations
# ---------------------------------------------------------------------------

def save_shipping_record(
    record_data: dict,
    owner_uid: str,
    device_id: Optional[str] = None
) -> Dict[str, Any]:
    """Saves an extracted shipping-label record bound to owner_uid and deviceId."""
    if not owner_uid:
        raise ValueError("Cannot save shipping record without authenticated owner_uid.")

    seq_id = get_next_sequence_id("SHIP")
    now_utc = datetime.now(timezone.utc)
    created_at_iso = now_utc.strftime("%Y-%m-%dT%H:%M:%SZ")
    expires_at_iso = (now_utc + timedelta(days=RETENTION_DAYS)).strftime("%Y-%m-%dT%H:%M:%SZ")

    record = {
        "_id": seq_id,
        "sequentialId": seq_id,
        "owner_uid": owner_uid,
        "deviceId": device_id or "default_client",
        "category": "shipping",
        "title": record_data.get("title") or record_data.get("carrier") or f"Shipping Label {seq_id}",
        "carrier": record_data.get("carrier") or "Standard",
        "tracking_number": record_data.get("tracking_number") or "",
        "sender": record_data.get("sender") or {},
        "receiver": record_data.get("receiver") or {},
        "package_details": record_data.get("package_details") or {},
        "items": record_data.get("items") or [],
        "barcodes": record_data.get("barcodes") or [],
        "qr_codes": record_data.get("qr_codes") or [],
        "raw_text": (record_data.get("raw_text") or "")[:2000],
        "extracted_data": record_data,
        "createdAt": created_at_iso,
        "expiresAt": expires_at_iso,
        "retentionDays": RETENTION_DAYS
    }

    records = read_file_records(SHIPPING_HISTORY_FILE, auto_purge=True)
    records.insert(0, record)
    if len(records) > 500:
        records = records[:500]
    write_file_records(SHIPPING_HISTORY_FILE, records)

    if MONGODB_URI:
        sync_record_to_mongodb("shipping_history", seq_id, record)

    return record


def get_shipping_history(
    limit: int = 50,
    page: int = 1,
    device_id: Optional[str] = None,
    owner_uid: Optional[str] = None
) -> Dict[str, Any]:
    """Retrieves shipping history records strictly for the authenticated owner_uid."""
    if not owner_uid:
        return {
            "documents": [],
            "total": 0,
            "page": page,
            "pages": 1,
            "deviceId": device_id,
            "owner_uid": owner_uid,
            "retentionDays": RETENTION_DAYS,
            "source": "shipping_store"
        }

    if MONGODB_URI:
        try:
            client = get_mongo_client()
            if client:
                db = client[MONGODB_DB_NAME]
                query = {"owner_uid": owner_uid}
                total = db["shipping_history"].count_documents(query)
                cursor = db["shipping_history"].find(query).sort("createdAt", -1).skip((page - 1) * limit).limit(limit)
                docs = list(cursor)
                for d in docs:
                    if "_id" in d and not isinstance(d["_id"], str):
                        d["_id"] = str(d["_id"])
                pages = (total + limit - 1) // limit if total > 0 else 1
                return {
                    "documents": docs,
                    "total": total,
                    "page": page,
                    "pages": pages,
                    "deviceId": device_id,
                    "owner_uid": owner_uid,
                    "retentionDays": RETENTION_DAYS,
                    "source": "mongodb_atlas"
                }
        except Exception as err:
            logger.warning(f"MongoDB shipping query error: {err}")

    records = read_file_records(SHIPPING_HISTORY_FILE, auto_purge=True)
    records = [d for d in records if d.get("owner_uid") == owner_uid]
    total = len(records)
    start = (page - 1) * limit
    paginated = records[start:start + limit]
    pages = (total + limit - 1) // limit if total > 0 else 1
    return {
        "documents": paginated,
        "total": total,
        "page": page,
        "pages": pages,
        "deviceId": device_id,
        "owner_uid": owner_uid,
        "retentionDays": RETENTION_DAYS,
        "source": "local_shipping_store"
    }


def get_shipping_record_by_id(
    doc_id: str,
    device_id: Optional[str] = None,
    owner_uid: Optional[str] = None
) -> Optional[Dict[str, Any]]:
    """Retrieves a single shipping record verifying owner_uid."""
    if not owner_uid:
        return None

    if MONGODB_URI:
        try:
            client = get_mongo_client()
            if client:
                db = client[MONGODB_DB_NAME]
                doc = db["shipping_history"].find_one({"_id": doc_id, "owner_uid": owner_uid})
                if doc:
                    if "_id" in doc and not isinstance(doc["_id"], str):
                        doc["_id"] = str(doc["_id"])
                    return doc
        except Exception:
            pass

    records = read_file_records(SHIPPING_HISTORY_FILE, auto_purge=True)
    for d in records:
        if (d.get("_id") == doc_id or d.get("sequentialId") == doc_id) and d.get("owner_uid") == owner_uid:
            return d
    return None


def delete_shipping_record_by_id(
    doc_id: str,
    device_id: Optional[str] = None,
    owner_uid: Optional[str] = None
) -> bool:
    """Deletes a shipping record strictly verifying owner_uid."""
    if not owner_uid:
        return False

    records = read_file_records(SHIPPING_HISTORY_FILE, auto_purge=False)
    new_records = []
    found_local = False
    for d in records:
        if (d.get("_id") == doc_id or d.get("sequentialId") == doc_id) and d.get("owner_uid") == owner_uid:
            found_local = True
        else:
            new_records.append(d)

    if found_local:
        write_file_records(SHIPPING_HISTORY_FILE, new_records)

    found_mongo = False
    if MONGODB_URI:
        try:
            client = get_mongo_client()
            if client:
                db = client[MONGODB_DB_NAME]
                res = db["shipping_history"].delete_one({"_id": doc_id, "owner_uid": owner_uid})
                if res.deleted_count > 0:
                    found_mongo = True
        except Exception:
            pass

    return found_local or found_mongo


# ---------------------------------------------------------------------------
# QR / Barcode History Operations
# ---------------------------------------------------------------------------

def save_qr_record(
    record_data: dict,
    owner_uid: str,
    device_id: Optional[str] = None
) -> Dict[str, Any]:
    """
    Saves a QR generation or optical scan record bound to owner_uid and deviceId.
    Strictly sanitizes plain-text credentials and Wi-Fi passwords.
    """
    if not owner_uid:
        raise ValueError("Cannot save QR record without authenticated owner_uid.")

    seq_id = get_next_sequence_id("QR")
    now_utc = datetime.now(timezone.utc)
    created_at_iso = now_utc.strftime("%Y-%m-%dT%H:%M:%SZ")
    expires_at_iso = (now_utc + timedelta(days=RETENTION_DAYS)).strftime("%Y-%m-%dT%H:%M:%SZ")

    action_type = record_data.get("action_type") or record_data.get("action") or "generate"
    qr_type = record_data.get("qr_type") or record_data.get("type") or "text"

    # Sanitize Wi-Fi and passwords - NEVER store plaintext passwords in fields or content
    raw_fields = dict(record_data.get("fields") or {})
    if "password" in raw_fields:
        raw_fields["password"] = "***"

    raw_content = record_data.get("content") or record_data.get("data") or ""
    if isinstance(raw_content, str):
        import re
        if "P:" in raw_content and "WIFI:" in raw_content:
            raw_content = re.sub(r'P:[^;]*;', 'P:***;', raw_content)
        if '"password"' in raw_content:
            try:
                parsed_json = json.loads(raw_content)
                if isinstance(parsed_json, dict) and "password" in parsed_json:
                    parsed_json["password"] = "***"
                    raw_content = json.dumps(parsed_json)
            except Exception:
                raw_content = re.sub(r'"password"\s*:\s*"[^"]*"', '"password":"***"', raw_content)

    # Also sanitize inside generated_result if present
    gen_res = record_data.get("generated_result")
    if isinstance(gen_res, dict):
        gen_res = dict(gen_res)
        enc_payload = gen_res.get("encoded_payload")
        if isinstance(enc_payload, str) and "P:" in enc_payload and "WIFI:" in enc_payload:
            import re
            gen_res["encoded_payload"] = re.sub(r'P:[^;]*;', 'P:***;', enc_payload)

    record = {
        "_id": seq_id,
        "sequentialId": seq_id,
        "owner_uid": owner_uid,
        "deviceId": device_id or "default_client",
        "category": "qr",
        "action_type": action_type,  # 'generate' | 'scan'
        "qr_type": qr_type,
        "content_type": record_data.get("content_type") or qr_type,
        "content": raw_content,
        "fields": raw_fields,
        "generated_result": gen_res,
        "annotated_image": record_data.get("annotated_image"),
        "metadata": record_data.get("metadata") or {
            "format": record_data.get("format", "png"),
            "size": record_data.get("size", 400),
            "error_correction": record_data.get("error_correction", "M"),
            "symbology": record_data.get("symbology")
        },
        "barcodes": record_data.get("barcodes") or [],
        "qr_codes": record_data.get("qr_codes") or [],
        "ocr": record_data.get("ocr"),
        "createdAt": created_at_iso,
        "expiresAt": expires_at_iso,
        "retentionDays": RETENTION_DAYS
    }

    records = read_file_records(QR_HISTORY_FILE, auto_purge=True)
    records.insert(0, record)
    if len(records) > 500:
        records = records[:500]
    write_file_records(QR_HISTORY_FILE, records)

    if MONGODB_URI:
        sync_record_to_mongodb("qr_history", seq_id, record)

    return record


def get_qr_history(
    limit: int = 50,
    page: int = 1,
    action_type: Optional[str] = None,
    device_id: Optional[str] = None,
    owner_uid: Optional[str] = None
) -> Dict[str, Any]:
    """Retrieves QR history records strictly for the authenticated owner_uid."""
    if not owner_uid:
        return {
            "documents": [],
            "total": 0,
            "page": page,
            "pages": 1,
            "deviceId": device_id,
            "owner_uid": owner_uid,
            "retentionDays": RETENTION_DAYS,
            "source": "qr_store"
        }

    if MONGODB_URI:
        try:
            client = get_mongo_client()
            if client:
                db = client[MONGODB_DB_NAME]
                query: Dict[str, Any] = {"owner_uid": owner_uid}
                if action_type:
                    query["action_type"] = action_type
                total = db["qr_history"].count_documents(query)
                cursor = db["qr_history"].find(query).sort("createdAt", -1).skip((page - 1) * limit).limit(limit)
                docs = list(cursor)
                for d in docs:
                    if "_id" in d and not isinstance(d["_id"], str):
                        d["_id"] = str(d["_id"])
                pages = (total + limit - 1) // limit if total > 0 else 1
                return {
                    "documents": docs,
                    "total": total,
                    "page": page,
                    "pages": pages,
                    "deviceId": device_id,
                    "owner_uid": owner_uid,
                    "retentionDays": RETENTION_DAYS,
                    "source": "mongodb_atlas"
                }
        except Exception as err:
            logger.warning(f"MongoDB qr query error: {err}")

    records = read_file_records(QR_HISTORY_FILE, auto_purge=True)
    records = [d for d in records if d.get("owner_uid") == owner_uid]
    if action_type:
        records = [d for d in records if d.get("action_type") == action_type]
    total = len(records)
    start = (page - 1) * limit
    paginated = records[start:start + limit]
    pages = (total + limit - 1) // limit if total > 0 else 1
    return {
        "documents": paginated,
        "total": total,
        "page": page,
        "pages": pages,
        "deviceId": device_id,
        "owner_uid": owner_uid,
        "retentionDays": RETENTION_DAYS,
        "source": "local_qr_store"
    }


def get_qr_record_by_id(
    doc_id: str,
    device_id: Optional[str] = None,
    owner_uid: Optional[str] = None
) -> Optional[Dict[str, Any]]:
    """Retrieves a single QR history record verifying owner_uid."""
    if not owner_uid:
        return None

    if MONGODB_URI:
        try:
            client = get_mongo_client()
            if client:
                db = client[MONGODB_DB_NAME]
                doc = db["qr_history"].find_one({"_id": doc_id, "owner_uid": owner_uid})
                if doc:
                    if "_id" in doc and not isinstance(doc["_id"], str):
                        doc["_id"] = str(doc["_id"])
                    return doc
        except Exception:
            pass

    records = read_file_records(QR_HISTORY_FILE, auto_purge=True)
    for d in records:
        if (d.get("_id") == doc_id or d.get("sequentialId") == doc_id) and d.get("owner_uid") == owner_uid:
            return d
    return None


def delete_qr_record_by_id(
    doc_id: str,
    device_id: Optional[str] = None,
    owner_uid: Optional[str] = None
) -> bool:
    """Deletes a QR record strictly verifying owner_uid."""
    if not owner_uid:
        return False

    records = read_file_records(QR_HISTORY_FILE, auto_purge=False)
    new_records = []
    found_local = False
    for d in records:
        if (d.get("_id") == doc_id or d.get("sequentialId") == doc_id) and d.get("owner_uid") == owner_uid:
            found_local = True
        else:
            new_records.append(d)

    if found_local:
        write_file_records(QR_HISTORY_FILE, new_records)

    found_mongo = False
    if MONGODB_URI:
        try:
            client = get_mongo_client()
            if client:
                db = client[MONGODB_DB_NAME]
                res = db["qr_history"].delete_one({"_id": doc_id, "owner_uid": owner_uid})
                if res.deleted_count > 0:
                    found_mongo = True
        except Exception:
            pass

    return found_local or found_mongo


def get_storage_stats(
    device_id: Optional[str] = None, 
    owner_uid: Optional[str] = None
) -> Dict[str, Any]:
    """Returns storage space usage and record count for the requesting authenticated user from MongoDB Atlas (or local fallback)."""
    if owner_uid and MONGODB_URI:
        try:
            client = get_mongo_client()
            if client:
                db = client[MONGODB_DB_NAME]
                q = {"owner_uid": owner_uid}
                n_hist = db["verifications"].count_documents(q)
                n_fail = db["failed_verifications"].count_documents(q)
                n_ship = db["shipping_history"].count_documents(q)
                n_qr = db["qr_history"].count_documents(q)
                total_records = n_hist + n_fail + n_ship + n_qr
                est_bytes = total_records * 18432  # ~18 KB avg per record
                kb_size = round(est_bytes / 1024.0, 1)
                mb_size = round(est_bytes / (1024.0 * 1024.0), 2)
                return {
                    "deviceRecords": n_hist,
                    "totalSuccessRecords": n_hist,
                    "totalFailedRecords": n_fail,
                    "totalShippingRecords": n_ship,
                    "totalQrRecords": n_qr,
                    "totalRecords": total_records,
                    "maxRecords": 500,
                    "retentionDays": RETENTION_DAYS,
                    "storageSizeBytes": est_bytes,
                    "storageSizeKB": kb_size,
                    "storageSizeMB": mb_size,
                    "percentUsed": min(100, round((total_records / 500.0) * 100, 1)),
                    "deviceId": device_id,
                    "owner_uid": owner_uid,
                    "databaseEngine": f"MongoDB Atlas ({MONGODB_DB_NAME})"
                }
        except Exception as err:
            logger.warning(f"MongoDB stats notice: {err}")

    history = read_history(auto_purge=True)
    failed = read_failed_history(auto_purge=True)
    shipping = read_file_records(SHIPPING_HISTORY_FILE, auto_purge=True)
    qr_records = read_file_records(QR_HISTORY_FILE, auto_purge=True)
    
    if owner_uid:
        user_history = [d for d in history if d.get("owner_uid") == owner_uid]
        user_failed = [d for d in failed if d.get("owner_uid") == owner_uid]
        user_shipping = [d for d in shipping if d.get("owner_uid") == owner_uid]
        user_qr = [d for d in qr_records if d.get("owner_uid") == owner_uid]
    else:
        user_history = []
        user_failed = []
        user_shipping = []
        user_qr = []

    file_size_bytes = 0
    for fp in [HISTORY_FILE, FAILED_HISTORY_FILE, SHIPPING_HISTORY_FILE, QR_HISTORY_FILE]:
        if os.path.exists(fp):
            file_size_bytes += os.path.getsize(fp)
    
    kb_size = round(file_size_bytes / 1024.0, 1)
    mb_size = round(file_size_bytes / (1024.0 * 1024.0), 2)

    total_records = len(user_history) + len(user_failed) + len(user_shipping) + len(user_qr)

    return {
        "deviceRecords": len(user_history),
        "totalSuccessRecords": len(user_history),
        "totalFailedRecords": len(user_failed),
        "totalShippingRecords": len(user_shipping),
        "totalQrRecords": len(user_qr),
        "totalRecords": total_records,
        "maxRecords": 500,
        "retentionDays": RETENTION_DAYS,
        "storageSizeBytes": file_size_bytes,
        "storageSizeKB": kb_size,
        "storageSizeMB": mb_size,
        "percentUsed": min(100, round((total_records / 500.0) * 100, 1)),
        "deviceId": device_id,
        "owner_uid": owner_uid,
        "databaseEngine": "MongoDB Atlas" if MONGODB_URI else "Local JSON Store"
    }


def clean_storage(
    device_id: Optional[str] = None, 
    owner_uid: Optional[str] = None, 
    force_all: bool = False
) -> Dict[str, Any]:
    """
    Purges expired records (>30 days) strictly for the requesting authenticated user.
    If force_all=False, preserves fresh records (<=30 days).
    Never touches another user's records or reference cards.
    """
    if not owner_uid:
        return {"message": "Authentication required to clean storage.", "deleted_count": 0}

    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=RETENTION_DAYS)
    cutoff_str = cutoff.strftime("%Y-%m-%dT%H:%M:%SZ")
    now_str = now.strftime("%Y-%m-%dT%H:%M:%SZ")

    def is_eligible_for_deletion(doc: dict) -> bool:
        if doc.get("owner_uid") != owner_uid:
            return False
        if force_all:
            return True
        # Check explicit expiresAt
        exp_str = doc.get("expiresAt")
        if exp_str:
            try:
                exp_dt = datetime.fromisoformat(exp_str.replace("Z", "+00:00"))
                if exp_dt <= now:
                    return True
            except Exception:
                pass
        # Check createdAt
        c_str = doc.get("createdAt")
        if c_str:
            try:
                c_dt = datetime.fromisoformat(c_str.replace("Z", "+00:00"))
                if c_dt <= cutoff:
                    return True
            except Exception:
                pass
        return False

    # 1. Clean local JSON files
    del_count = 0
    for target_file in [HISTORY_FILE, FAILED_HISTORY_FILE, SHIPPING_HISTORY_FILE, QR_HISTORY_FILE]:
        docs = read_file_records(target_file, auto_purge=False)
        remaining = []
        for d in docs:
            if is_eligible_for_deletion(d):
                del_count += 1
            else:
                remaining.append(d)
        write_file_records(target_file, remaining)

    # 2. Clean MongoDB Atlas
    if MONGODB_URI:
        try:
            client = get_mongo_client()
            if client:
                db = client[MONGODB_DB_NAME]
                if force_all:
                    query: Dict[str, Any] = {"owner_uid": owner_uid}
                else:
                    query = {
                        "owner_uid": owner_uid,
                        "$or": [
                            {"expiresAt": {"$lte": now_str}},
                            {"createdAt": {"$lte": cutoff_str}}
                        ]
                    }
                r1 = db["verifications"].delete_many(query)
                r2 = db["failed_verifications"].delete_many(query)
                r3 = db["shipping_history"].delete_many(query)
                r4 = db["qr_history"].delete_many(query)
                del_count = max(del_count, r1.deleted_count + r2.deleted_count + r3.deleted_count + r4.deleted_count)
        except Exception as e:
            logger.error(f"MongoDB storage cleanup error: {e}")
            raise RuntimeError(f"Database cleanup error: {e}")

    action_label = "Cleaned all records" if force_all else f"Cleaned expired records (>30 days)"
    return {
        "message": f"{action_label} successfully for account.",
        "deleted_count": del_count,
        "retention_policy": f"{RETENTION_DAYS} days"
    }

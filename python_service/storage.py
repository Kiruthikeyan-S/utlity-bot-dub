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

try:
    import pymongo
except ImportError:
    pymongo = None

logger = logging.getLogger("utility_bot.storage")

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
HISTORY_FILE = os.path.join(DATA_DIR, "history.json")
FAILED_HISTORY_FILE = os.path.join(DATA_DIR, "failed_history.json")
COUNTERS_FILE = os.path.join(DATA_DIR, "counters.json")
RETENTION_DAYS = 30

os.makedirs(DATA_DIR, exist_ok=True)
for file_path in [HISTORY_FILE, FAILED_HISTORY_FILE]:
    if not os.path.exists(file_path):
        with open(file_path, "w", encoding="utf-8") as f:
            f.write("[]\n")

if not os.path.exists(COUNTERS_FILE):
    with open(COUNTERS_FILE, "w", encoding="utf-8") as f:
        json.dump({"IMG": 0, "FAIL": 0}, f, indent=2)
        f.write("\n")

# ---------------------------------------------------------------------------
# MongoDB Atlas Database Configuration
# Requires: MONGODB_URI in .env
# ---------------------------------------------------------------------------
MONGODB_URI = os.getenv("MONGODB_URI")
MONGODB_DATA_API_KEY = os.getenv("MONGODB_DATA_API_KEY", "")
MONGODB_APP_ID = os.getenv("MONGODB_APP_ID", "")
MONGODB_DB_NAME = os.getenv("MONGODB_DB_NAME", "utility_bot")
MONGODB_CLUSTER = os.getenv("MONGODB_CLUSTER", "Cluster0")

_ATLAS_DATA_URL = f"https://data.mongodb-api.com/app/{MONGODB_APP_ID}/endpoint/data/v1" if MONGODB_APP_ID else ""
IS_MONGO_ONLINE = False


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
    Returns a native MongoClient with strictly verified TLS certificates.
    Removes insecure tlsAllowInvalidCertificates=True and uses trusted certifi bundle.
    """
    if not MONGODB_URI:
        return None
    try:
        import pymongo
        return pymongo.MongoClient(
            MONGODB_URI,
            tls=True,
            tlsCAFile=certifi.where(),
            tlsAllowInvalidCertificates=False,
            serverSelectionTimeoutMS=4000
        )
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

    history = read_history(auto_purge=True)
    for doc in history:
        if doc.get("_id") == doc_id or doc.get("sequentialId") == doc_id:
            if doc.get("owner_uid") != owner_uid:
                return None
            return doc

    # Also check MongoDB if not in local cache
    if MONGODB_URI:
        try:
            client = get_mongo_client()
            if client:
                db = client[MONGODB_DB_NAME]
                doc = db["verifications"].find_one({"_id": doc_id, "owner_uid": owner_uid})
                if doc:
                    return doc
        except Exception:
            pass

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
    found = False
    for d in history:
        if d.get("_id") == doc_id or d.get("sequentialId") == doc_id:
            # Only delete if owner matches
            if d.get("owner_uid") != owner_uid:
                new_history.append(d)
                continue
            found = True
        else:
            new_history.append(d)
            
    if found:
        write_file_records(HISTORY_FILE, new_history)
        if MONGODB_URI:
            try:
                client = get_mongo_client()
                if client:
                    db = client[MONGODB_DB_NAME]
                    db["verifications"].delete_one({"_id": doc_id, "owner_uid": owner_uid})
            except Exception:
                pass
        return True
    return False


def get_storage_stats(
    device_id: Optional[str] = None, 
    owner_uid: Optional[str] = None
) -> Dict[str, Any]:
    """Returns storage space usage and record count for the requesting authenticated user."""
    history = read_history(auto_purge=True)
    failed = read_failed_history(auto_purge=True)
    
    if owner_uid:
        user_history = [d for d in history if d.get("owner_uid") == owner_uid]
        user_failed = [d for d in failed if d.get("owner_uid") == owner_uid]
    else:
        user_history = []
        user_failed = []

    file_size_bytes = 0
    for fp in [HISTORY_FILE, FAILED_HISTORY_FILE]:
        if os.path.exists(fp):
            file_size_bytes += os.path.getsize(fp)
    
    kb_size = round(file_size_bytes / 1024.0, 1)
    mb_size = round(file_size_bytes / (1024.0 * 1024.0), 2)

    return {
        "deviceRecords": len(user_history),
        "totalSuccessRecords": len(user_history),
        "totalFailedRecords": len(user_failed),
        "totalRecords": len(user_history) + len(user_failed),
        "maxRecords": 500,
        "retentionDays": RETENTION_DAYS,
        "storageSizeBytes": file_size_bytes,
        "storageSizeKB": kb_size,
        "storageSizeMB": mb_size,
        "percentUsed": min(100, round(((len(user_history) + len(user_failed)) / 500.0) * 100, 1)),
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
    history = read_history(auto_purge=False)
    del_count = 0
    new_history = []
    for d in history:
        if is_eligible_for_deletion(d):
            del_count += 1
        else:
            new_history.append(d)
    write_file_records(HISTORY_FILE, new_history)

    failed = read_failed_history(auto_purge=False)
    new_failed = []
    for d in failed:
        if is_eligible_for_deletion(d):
            del_count += 1
        else:
            new_failed.append(d)
    write_file_records(FAILED_HISTORY_FILE, new_failed)

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
                del_count = max(del_count, r1.deleted_count + r2.deleted_count)
        except Exception as e:
            logger.error(f"MongoDB storage cleanup error: {e}")
            raise RuntimeError(f"Database cleanup error: {e}")

    action_label = "Cleaned all records" if force_all else f"Cleaned expired records (>30 days)"
    return {
        "message": f"{action_label} successfully for account.",
        "deleted_count": del_count,
        "retention_policy": f"{RETENTION_DAYS} days"
    }

/**
 * localStore.js - IndexedDB Storage Layer for Utility Bot.
 * Safely persists local image blobs and verification records partitioned strictly
 * by authenticated user (ownerUid) AND browser device (deviceId).
 *
 * Guarantees:
 * 1. Account A's local records remain preserved when Account A logs out.
 * 2. Account B on the same device sees only Account B's partition.
 * 3. Never stores large image blobs in localStorage.
 * 4. Account A logging back in immediately re-accesses its preserved records.
 */

const DB_NAME = 'UtilityBotLocalDB';
const DB_VERSION = 1;
const STORE_NAME = 'verification_records';

function openDatabase() {
  return new Promise((resolve, reject) => {
    if (typeof window === 'undefined' || !window.indexedDB) {
      return reject(new Error('IndexedDB not supported in this environment.'));
    }

    const request = window.indexedDB.open(DB_NAME, DB_VERSION);

    request.onupgradeneeded = (event) => {
      const db = event.target.result;
      if (!db.objectStoreNames.contains(STORE_NAME)) {
        const store = db.createObjectStore(STORE_NAME, { keyPath: 'storageKey' });
        store.createIndex('partitionKey', 'partitionKey', { unique: false });
        store.createIndex('ownerUid', 'ownerUid', { unique: false });
        store.createIndex('deviceId', 'deviceId', { unique: false });
        store.createIndex('createdAt', 'createdAt', { unique: false });
      }
    };

    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
  });
}

/**
 * Builds a deterministic partition key for (ownerUid, deviceId).
 */
export function buildPartitionKey(ownerUid, deviceId) {
  const uid = ownerUid || 'anonymous';
  const dev = deviceId || 'default_device';
  return `${uid}###${dev}`;
}

/**
 * Saves or updates a verification record in IndexedDB under (ownerUid, deviceId).
 */
export async function saveLocalRecord(record, ownerUid, deviceId) {
  if (!ownerUid || !deviceId) return null;
  const db = await openDatabase();
  const partitionKey = buildPartitionKey(ownerUid, deviceId);
  const recordId = record._id || record.id || record.sequentialId || ('local_' + Date.now());
  const storageKey = `${partitionKey}###${recordId}`;

  const entry = {
    ...record,
    _id: recordId,
    id: recordId,
    storageKey,
    partitionKey,
    ownerUid,
    deviceId,
    updatedAt: new Date().toISOString(),
    createdAt: record.createdAt || new Date().toISOString(),
  };

  return new Promise((resolve, reject) => {
    const tx = db.transaction(STORE_NAME, 'readwrite');
    const store = tx.objectStore(STORE_NAME);
    const req = store.put(entry);

    req.onsuccess = () => resolve(entry);
    req.onerror = () => reject(req.error);
  });
}

/**
 * Retrieves all records belonging strictly to ownerUid.
 * Never returns records belonging to any other user.
 */
export async function getLocalRecords(ownerUid) {
  if (!ownerUid) return [];
  const db = await openDatabase();

  return new Promise((resolve, reject) => {
    const tx = db.transaction(STORE_NAME, 'readonly');
    const store = tx.objectStore(STORE_NAME);
    const index = store.index('ownerUid');
    const req = index.getAll(IDBKeyRange.only(ownerUid));

    req.onsuccess = () => {
      const records = req.result || [];
      // Sort newest first
      records.sort((a, b) => new Date(b.createdAt || 0) - new Date(a.createdAt || 0));
      resolve(records);
    };
    req.onerror = () => reject(req.error);
  });
}

/**
 * Retrieves a single record by ID if and only if it belongs to ownerUid.
 */
export async function getLocalRecordById(recordId, ownerUid) {
  if (!recordId || !ownerUid) return null;
  const db = await openDatabase();

  return new Promise((resolve, reject) => {
    const tx = db.transaction(STORE_NAME, 'readonly');
    const store = tx.objectStore(STORE_NAME);
    const index = store.index('ownerUid');
    const req = index.openCursor(IDBKeyRange.only(ownerUid));

    req.onsuccess = (event) => {
      const cursor = event.target.result;
      if (cursor) {
        const val = cursor.value;
        if (val._id === recordId || val.id === recordId) {
          resolve(val);
          return;
        }
        cursor.continue();
      } else {
        resolve(null);
      }
    };
    req.onerror = () => reject(req.error);
  });
}

/**
 * Deletes a record by ID strictly verifying ownerUid.
 */
export async function deleteLocalRecord(recordId, ownerUid) {
  if (!recordId || !ownerUid) return false;
  const db = await openDatabase();

  return new Promise((resolve, reject) => {
    const tx = db.transaction(STORE_NAME, 'readwrite');
    const store = tx.objectStore(STORE_NAME);
    const index = store.index('ownerUid');
    const req = index.openCursor(IDBKeyRange.only(ownerUid));

    req.onsuccess = (event) => {
      const cursor = event.target.result;
      if (cursor) {
        const val = cursor.value;
        if (val._id === recordId || val.id === recordId) {
          cursor.delete();
          resolve(true);
          return;
        }
        cursor.continue();
      } else {
        resolve(false);
      }
    };
    req.onerror = () => reject(req.error);
  });
}

/**
 * Purges only expired records (>30 days) for ownerUid.
 * Preserves fresh records (<=30 days) and other accounts' data.
 */
export async function cleanExpiredLocalRecords(ownerUid, retentionDays = 30) {
  if (!ownerUid) return 0;
  const db = await openDatabase();
  const now = new Date();
  const cutoff = new Date(now.getTime() - retentionDays * 24 * 60 * 60 * 1000);

  return new Promise((resolve, reject) => {
    const tx = db.transaction(STORE_NAME, 'readwrite');
    const store = tx.objectStore(STORE_NAME);
    const index = store.index('ownerUid');
    const req = index.openCursor(IDBKeyRange.only(ownerUid));
    let deletedCount = 0;

    req.onsuccess = (event) => {
      const cursor = event.target.result;
      if (cursor) {
        const record = cursor.value;
        let isExpired = false;
        if (record.expiresAt) {
          isExpired = new Date(record.expiresAt) <= now;
        } else if (record.createdAt) {
          isExpired = new Date(record.createdAt) <= cutoff;
        }
        if (isExpired) {
          cursor.delete();
          deletedCount++;
        }
        cursor.continue();
      } else {
        resolve(deletedCount);
      }
    };
    req.onerror = () => reject(req.error);
  });
}

/**
 * Clears only the active account's records if user specifically requests a full purge.
 * Leaves all other accounts' data intact in IndexedDB.
 */
export async function clearLocalRecordsForUser(ownerUid) {
  if (!ownerUid) return 0;
  const db = await openDatabase();

  return new Promise((resolve, reject) => {
    const tx = db.transaction(STORE_NAME, 'readwrite');
    const store = tx.objectStore(STORE_NAME);
    const index = store.index('ownerUid');
    const req = index.openCursor(IDBKeyRange.only(ownerUid));
    let count = 0;

    req.onsuccess = (event) => {
      const cursor = event.target.result;
      if (cursor) {
        cursor.delete();
        count++;
        cursor.continue();
      } else {
        resolve(count);
      }
    };
    req.onerror = () => reject(req.error);
  });
}

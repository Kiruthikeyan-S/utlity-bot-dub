import axios from 'axios';
import { auth, logoutUser } from '../firebase';

// Connect directly to Python FastAPI backend (auto-adapts to unified domain in production)
const API_BASE = import.meta.env.VITE_API_URL || (import.meta.env.DEV ? 'http://localhost:8000' : (typeof window !== 'undefined' ? window.location.origin : ''));

/**
 * Returns a unique random UUID for this browser profile.
 * Persistently stored in localStorage so it remains constant across all sessions in this browser.
 * Replaces hardcoded default device IDs and hardware fingerprinting.
 */
export const getDeviceId = () => {
  if (typeof window === 'undefined') return 'server_session';
  let deviceId = localStorage.getItem('utility_bot_device_id');
  if (!deviceId || deviceId === 'dev_mtcqjgy8_gr4nils' || deviceId.startsWith('device_')) {
    deviceId = (typeof crypto !== 'undefined' && crypto.randomUUID)
      ? crypto.randomUUID()
      : 'dev_' + Math.random().toString(36).substring(2, 15) + '_' + Date.now().toString(36);
    localStorage.setItem('utility_bot_device_id', deviceId);
  }
  return deviceId;
};

/**
 * Allows manually fixing / setting a custom Device Name.
 */
export const setCustomDeviceId = (customId) => {
  if (customId && customId.trim()) {
    const formatted = customId.trim().toLowerCase().replace(/[^a-z0-9_-]/g, '_');
    localStorage.setItem('utility_bot_device_id', formatted);
    return formatted;
  }
  return getDeviceId();
};

export const api = axios.create({
  baseURL: API_BASE,
  timeout: 120000,
});

// Request Interceptor: Attach Device ID AND fresh Firebase ID token to EVERY outgoing request
api.interceptors.request.use(async (config) => {
  config.headers = config.headers || {};
  const deviceId = getDeviceId();
  config.headers['X-Device-Id'] = deviceId;

  // Retrieve current Firebase user and attach fresh ID token (never user-supplied UID)
  try {
    const currentUser = auth.currentUser;
    if (currentUser) {
      const token = await currentUser.getIdToken();
      if (token) {
        config.headers.Authorization = `Bearer ${token}`;
      }
    }
  } catch (authErr) {
    console.warn('[API Interceptor] Could not fetch ID token:', authErr);
  }

  return config;
}, (error) => {
  return Promise.reject(error);
});

// Response Interceptor: Handle HTTP 401 Unauthorized responses and expired sessions
api.interceptors.response.use(
  (response) => response,
  async (error) => {
    if (error.response && error.response.status === 401) {
      console.warn('[API Interceptor] 401 Unauthorized - session expired or invalid credentials.');
      try {
        await logoutUser();
      } catch (logoutErr) {
        // ignore
      }
      if (typeof window !== 'undefined') {
        window.dispatchEvent(new CustomEvent('utilitybot:unauthorized'));
      }
    }
    return Promise.reject(error);
  }
);

/**
 * Uploads ID document image directly to Python FastAPI backend.
 */
export const extractDocumentApi = async (file, settings = {}, isDeepScan = false) => {
  const formData = new FormData();
  formData.append('file', file);
  formData.append('deviceId', getDeviceId());
  if (isDeepScan) {
    formData.append('deep_scan', 'true');
  }

  Object.entries(settings).forEach(([key, value]) => {
    if (value !== undefined && value !== null) {
      formData.append(key, value);
    }
  });

  const response = await api.post('/extract', formData, {
    headers: {
      'Content-Type': 'multipart/form-data',
    },
  });

  return response.data;
};

/**
 * Submits Human-in-the-Loop confirmation decision ('correct' or 'wrong').
 * - 'correct': Assigns sequential ID 'IMG000001', sets status='Success', saves to 'verifications' (Public History)
 * - 'wrong': Assigns sequential ID 'FAIL000001', sets status='Failed', saves to 'failed_verifications' (Hidden)
 */
export const confirmVerificationApi = async (payload) => {
  const data = {
    ...payload,
    deviceId: getDeviceId(),
  };
  const response = await api.post('/confirm', data);
  return response.data;
};

/**
 * Retrieves extraction history list for the active device.
 */
export const getHistoryApi = async (params = {}) => {
  const queryParams = typeof params === 'object' ? params : { page: 1, limit: 50 };
  queryParams.deviceId = getDeviceId();
  const response = await api.get('/history', { params: queryParams });
  return response.data;
};

/**
 * Retrieves single extraction record by ID.
 */
export const getDocumentByIdApi = async (id) => {
  const response = await api.get(`/history/${id}`);
  return response.data;
};

/**
 * Deletes extraction record by ID.
 */
export const deleteDocumentApi = async (id) => {
  const response = await api.delete(`/history/${id}`);
  return response.data;
};

export const deleteHistoryApi = deleteDocumentApi;

/**
 * Fetches available Groq models from Python FastAPI backend.
 */
export const getModelsApi = async () => {
  const response = await api.get('/models');
  return response.data;
};

/**
 * Checks system health status.
 */
export const getHealthApi = async () => {
  const response = await api.get('/health');
  return response.data;
};

/**
 * Retrieves storage usage statistics (30-day retention) for active device.
 */
export const getStorageStatsApi = async () => {
  const response = await api.get('/storage/stats');
  return response.data;
};

/**
 * Triggers storage cleanup / purge for active device.
 */
export const cleanStorageApi = async (forceAll = false) => {
  const response = await api.post(`/storage/clean?force_all=${forceAll}`);
  return response.data;
};

/**
 * Retrieves public privacy-safe Identity Reference Record.
 */
export const getReferenceApi = async (refId) => {
  const response = await api.get(`/reference/${refId}`);
  return response.data;
};

/**
 * Revokes an existing Reference Card.
 */
export const revokeReferenceApi = async (refId) => {
  const response = await api.post(`/reference/${refId}/revoke`);
  return response.data;
};

/**
 * Fetches an active randomized liveness challenge.
 */
export const getLivenessChallengeApi = async () => {
  const response = await api.get('/verify/liveness-challenge');
  return response.data;
};

/**
 * Submits live webcam selfie + ID portrait photo for liveness and face similarity verification.
 */
export const verifyLiveFaceApi = async (payload) => {
  const data = {
    ...payload,
    deviceId: getDeviceId(),
  };
  const response = await api.post('/verify/live-face', data);
  return response.data;
};

/**
 * Submits primary ID details + secondary ID details for multi-document cross-verification.
 */
export const verifySecondIdApi = async (payload) => {
  const data = {
    ...payload,
    deviceId: getDeviceId(),
  };
  const response = await api.post('/verify/second-id', data);
  return response.data;
};

/**
 * Uploads 1 to 3 shipping label images for parallel separate processing.
 */
export const extractShippingApi = async (files, options = {}) => {
  const formData = new FormData();
  if (Array.isArray(files)) {
    files.forEach((file) => {
      formData.append('files', file);
    });
  } else if (files) {
    formData.append('files', files);
  }

  if (options.min_confidence !== undefined) {
    formData.append('min_confidence', options.min_confidence);
  }
  if (options.enable_clahe !== undefined) {
    formData.append('enable_clahe', options.enable_clahe);
  }
  if (options.enable_denoise !== undefined) {
    formData.append('enable_denoise', options.enable_denoise);
  }
  if (options.model_name !== undefined && options.model_name) {
    formData.append('model_name', options.model_name);
  }
  const apiKey = (options.groq_api_key || localStorage.getItem('groq_api_key') || '').trim();
  if (apiKey) {
    formData.append('groq_api_key', apiKey);
  }

  const response = await api.post('/extract-shipping', formData, {
    headers: {
      'Content-Type': 'multipart/form-data',
    },
  });


  return response.data;
};

/**
 * Generates a verified QR Code across 12 standardized payload types.
 */
export const generateQrApi = async (payload) => {
  const response = await api.post('/generate-qr', payload);
  return response.data;
};

/**
 * Standalone optical scanner: Uploads 1 image to detect all Barcodes and QR codes.
 */
export const scanCodeApi = async (file) => {
  const formData = new FormData();
  formData.append('file', file);
  const response = await api.post('/scan-code', formData, {
    headers: { 'Content-Type': 'multipart/form-data' },
  });
  return response.data;
};

/**
 * Combined scanner: Uploads 1 image to extract RapidOCR text AND all Barcode/QR codes.
 */
export const scanDocumentCodesApi = async (file, minConfidence = 20.0) => {
  const formData = new FormData();
  formData.append('file', file);
  formData.append('min_confidence', minConfidence);
  const response = await api.post('/scan-document-codes', formData, {
    headers: { 'Content-Type': 'multipart/form-data' },
  });
  return response.data;
};




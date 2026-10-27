"""
auth.py - Firebase Authentication & Token Verification Guard.
Verifies Firebase ID tokens using the Firebase Admin SDK or Google OAuth2 public certificates,
extracts the authenticated user's UID, and secures protected endpoints against unauthorized access.
Never trusts unverified claims or decodes tokens without cryptographic signature verification.
"""

import os
import json
import logging
from typing import Optional, Dict, Any
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
import firebase_admin
from firebase_admin import auth as admin_auth, credentials
from google.oauth2 import id_token as google_id_token
from google.auth.transport import requests as google_requests
from google.auth.exceptions import GoogleAuthError
import requests
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger("utility_bot.auth")

# Firebase Project configuration
FIREBASE_PROJECT_ID = os.getenv("FIREBASE_PROJECT_ID", "utility-bot-web")
FIREBASE_SERVICE_ACCOUNT = os.getenv("FIREBASE_SERVICE_ACCOUNT_KEY")

_firebase_initialized = False
_has_service_account_creds = False

try:
    import cachecontrol
    _http_session = cachecontrol.CacheControl(requests.Session())
except ImportError:
    _http_session = requests.Session()

_google_request = google_requests.Request(session=_http_session)

def initialize_firebase():
    """Initializes Firebase Admin SDK when service account credentials are provided."""
    global _firebase_initialized, _has_service_account_creds
    if _firebase_initialized:
        return

    try:
        if FIREBASE_SERVICE_ACCOUNT and FIREBASE_SERVICE_ACCOUNT.strip():
            if os.path.exists(FIREBASE_SERVICE_ACCOUNT):
                cred = credentials.Certificate(FIREBASE_SERVICE_ACCOUNT)
                if not firebase_admin._apps:
                    firebase_admin.initialize_app(cred)
                _has_service_account_creds = True
                logger.info("Firebase Admin initialized using service account file.")
            else:
                try:
                    sa_dict = json.loads(FIREBASE_SERVICE_ACCOUNT)
                    cred = credentials.Certificate(sa_dict)
                    if not firebase_admin._apps:
                        firebase_admin.initialize_app(cred)
                    _has_service_account_creds = True
                    logger.info("Firebase Admin initialized using service account JSON string.")
                except Exception as parse_err:
                    logger.warning(f"Failed to parse FIREBASE_SERVICE_ACCOUNT_KEY: {parse_err}")
                    _has_service_account_creds = False
        else:
            logger.info(
                f"No FIREBASE_SERVICE_ACCOUNT_KEY set; using Google OAuth2 cached public x509 certificates for project '{FIREBASE_PROJECT_ID}'."
            )
            _has_service_account_creds = False
        _firebase_initialized = True
    except Exception as e:
        logger.error(f"Failed to initialize Firebase Admin: {e}")
        _firebase_initialized = True

# Initialize on module load
initialize_firebase()

# FastAPI HTTPBearer scheme
security = HTTPBearer(auto_error=False)


def verify_token(token: str) -> Dict[str, Any]:
    """
    Verifies a Firebase ID token cryptographically and returns the verified token claims.

    Security guarantees:
    1. Rejects missing, empty, or whitespace tokens.
    2. Mock test tokens are strictly guarded: NEVER permitted in production, only when
       ALLOW_TEST_MOCK_TOKENS="true" AND ENVIRONMENT/NODE_ENV is NOT production.
    3. Cryptographic Verifier 1: Firebase Admin SDK verify_id_token (when credentials exist).
    4. Cryptographic Verifier 2: Google OAuth2 verify_firebase_token (verifies RSA signature
       against Google's official x509 public certificates for FIREBASE_PROJECT_ID).
    5. If both verifiers fail, unconditionally rejects the request with HTTP 401 Unauthorized.
       Never decodes or trusts claims (aud, iss, sub, user_id, exp) from an unverified token.
    """
    if not token or not token.strip():
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing authentication token.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    clean_token = token.strip()

    # 1. Guarded test mock tokens (for automated test suites ONLY)
    # Strictly prohibited if running in production or if not explicitly enabled
    env_name = (os.getenv("ENVIRONMENT") or os.getenv("NODE_ENV") or "development").strip().lower()
    is_production = env_name in ("production", "prod")
    allow_mock = os.getenv("ALLOW_TEST_MOCK_TOKENS", "false").strip().lower() == "true"

    if allow_mock and not is_production:
        if clean_token.startswith("test_token_"):
            mock_uid = clean_token[len("test_token_"):].strip()
            if mock_uid:
                return {
                    "uid": mock_uid,
                    "sub": mock_uid,
                    "user_id": mock_uid,
                    "email": f"{mock_uid}@test.local",
                    "auth_time": 0
                }

    last_error_detail = "Could not validate credentials."

    # 2. Cryptographic Verifier 1: Firebase Admin SDK (only when service account credentials exist,
    # avoiding 12s GCE metadata server timeout on non-GCP hosts)
    if _firebase_initialized and _has_service_account_creds:
        try:
            decoded_token = admin_auth.verify_id_token(clean_token)
            uid = decoded_token.get("uid") or decoded_token.get("sub") or decoded_token.get("user_id")
            if uid:
                decoded_token["uid"] = uid
                return decoded_token
        except admin_auth.ExpiredIdTokenError:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Authentication token has expired. Please sign in again.",
                headers={"WWW-Authenticate": "Bearer"},
            )
        except admin_auth.RevokedIdTokenError:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Authentication token has been revoked.",
                headers={"WWW-Authenticate": "Bearer"},
            )
        except admin_auth.InvalidIdTokenError as e:
            logger.debug(f"Firebase Admin InvalidIdTokenError: {e}")
            last_error_detail = "Invalid authentication token."
        except Exception as admin_err:
            logger.debug(f"Firebase Admin verify notice (falling back to Google public certs): {admin_err}")

    # 3. Cryptographic Verifier 2: Google OAuth2 Firebase Token Verifier
    # Cryptographically validates RSA signature against Google x509 certs, expiry, issuer, and audience
    try:
        decoded_token = google_id_token.verify_firebase_token(
            clean_token,
            _google_request,
            audience=FIREBASE_PROJECT_ID
        )
        if decoded_token:
            uid = decoded_token.get("user_id") or decoded_token.get("sub") or decoded_token.get("uid")
            if uid:
                decoded_token["uid"] = uid
                return decoded_token
    except ValueError as val_err:
        err_msg = str(val_err)
        logger.debug(f"Google public key verify error: {err_msg}")
        if "expired" in err_msg.lower():
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Authentication token has expired. Please sign in again.",
                headers={"WWW-Authenticate": "Bearer"},
            )
        last_error_detail = "Invalid authentication token."
    except GoogleAuthError as auth_err:
        err_msg = str(auth_err)
        logger.debug(f"Google auth error: {err_msg}")
        if "expired" in err_msg.lower():
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Authentication token has expired. Please sign in again.",
                headers={"WWW-Authenticate": "Bearer"},
            )
        last_error_detail = "Invalid authentication token."
    except Exception as g_err:
        err_msg = str(g_err)
        logger.debug(f"Token verification error: {err_msg}")
        if "expired" in err_msg.lower():
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Authentication token has expired. Please sign in again.",
                headers={"WWW-Authenticate": "Bearer"},
            )
        last_error_detail = "Invalid authentication token."

    # 4. If both verifiers fail, REJECT with HTTP 401. Never trust unverified claims.
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=last_error_detail,
        headers={"WWW-Authenticate": "Bearer"},
    )


def get_current_user(
    auth_credentials: Optional[HTTPAuthorizationCredentials] = Depends(security)
) -> Dict[str, Any]:
    """
    FastAPI dependency that enforces authentication and returns verified user payload.
    Rejects missing or invalid tokens with HTTP 401.
    """
    if not auth_credentials or not auth_credentials.credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required. Please sign in to access this resource.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return verify_token(auth_credentials.credentials)


def get_optional_user(
    auth_credentials: Optional[HTTPAuthorizationCredentials] = Depends(security)
) -> Optional[Dict[str, Any]]:
    """
    FastAPI dependency for endpoints that can be accessed with or without authentication.
    """
    if not auth_credentials or not auth_credentials.credentials:
        return None
    try:
        return verify_token(auth_credentials.credentials)
    except Exception:
        return None

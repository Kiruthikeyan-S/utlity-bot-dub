"""
test_auth_security.py - Comprehensive Security & Cryptographic Token Verification Test Suite.

Automated verification tests proving that:
1. Forged JWTs with unverified signatures are strictly rejected (HTTP 401).
2. Expired tokens are rejected (HTTP 401).
3. Missing expiry claims (no 'exp') are rejected (HTTP 401).
4. Incorrect audience ('aud') tokens are rejected (HTTP 401).
5. Incorrect issuer ('iss') tokens are rejected (HTTP 401).
6. Missing, empty, or whitespace tokens are rejected (HTTP 401).
7. Malformed tokens are rejected (HTTP 401).
8. Mock test tokens are strictly prohibited in production mode even if ALLOW_TEST_MOCK_TOKENS=true.
9. Mock test tokens are rejected when ALLOW_TEST_MOCK_TOKENS is false or unset.
10. Mock test tokens are accepted ONLY when ALLOW_TEST_MOCK_TOKENS=true AND ENVIRONMENT!=production.
11. End-to-end protected endpoints (/history, /confirm, /storage/stats, /history/clear) reject forged tokens.
"""

import os
import sys
import json
import time
import base64
import unittest
from fastapi import HTTPException
from fastapi.testclient import TestClient

# Ensure current directory is in sys.path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import auth
from main import app

def make_jwt(header_dict: dict, payload_dict: dict, signature_bytes: bytes = b"fake_sig") -> str:
    """Constructs a JWT string from header, payload, and signature."""
    h_b64 = base64.urlsafe_b64encode(json.dumps(header_dict).encode("utf-8")).decode("utf-8").rstrip("=")
    p_b64 = base64.urlsafe_b64encode(json.dumps(payload_dict).encode("utf-8")).decode("utf-8").rstrip("=")
    s_b64 = base64.urlsafe_b64encode(signature_bytes).decode("utf-8").rstrip("=")
    return f"{h_b64}.{p_b64}.{s_b64}"


class TestAuthSecurity(unittest.TestCase):

    def setUp(self):
        # Save original environment state
        self.orig_env = os.environ.get("ENVIRONMENT")
        self.orig_node_env = os.environ.get("NODE_ENV")
        self.orig_allow_mock = os.environ.get("ALLOW_TEST_MOCK_TOKENS")
        self.client = TestClient(app)

    def tearDown(self):
        # Restore environment variables
        if self.orig_env is not None:
            os.environ["ENVIRONMENT"] = self.orig_env
        else:
            os.environ.pop("ENVIRONMENT", None)

        if self.orig_node_env is not None:
            os.environ["NODE_ENV"] = self.orig_node_env
        else:
            os.environ.pop("NODE_ENV", None)

        if self.orig_allow_mock is not None:
            os.environ["ALLOW_TEST_MOCK_TOKENS"] = self.orig_allow_mock
        else:
            os.environ.pop("ALLOW_TEST_MOCK_TOKENS", None)

    # -------------------------------------------------------------------------
    # TEST 1: Missing, empty, or whitespace tokens
    # -------------------------------------------------------------------------
    def test_missing_or_empty_token_rejected(self):
        """Verifies that empty or whitespace tokens raise 401."""
        for empty_val in ["", "   ", "\t", "\n"]:
            with self.assertRaises(HTTPException) as ctx:
                auth.verify_token(empty_val)
            self.assertEqual(ctx.exception.status_code, 401)
            self.assertIn("Missing", ctx.exception.detail)

    # -------------------------------------------------------------------------
    # TEST 2: Malformed tokens
    # -------------------------------------------------------------------------
    def test_malformed_token_rejected(self):
        """Verifies that malformed string tokens raise 401."""
        for malformed in ["not.a.valid.jwt", "random_string", "abc.def", "123.456.789"]:
            with self.assertRaises(HTTPException) as ctx:
                auth.verify_token(malformed)
            self.assertEqual(ctx.exception.status_code, 401)

    # -------------------------------------------------------------------------
    # TEST 3: Forged JWT with forged signature (CRITICAL VULNERABILITY TEST)
    # -------------------------------------------------------------------------
    def test_forged_jwt_unverified_signature_rejected(self):
        """
        CRITICAL TEST: An attacker crafts a JWT with valid claims targeting a victim UID.
        The token has an arbitrary signature.
        Without cryptographic verification against Google public certs, a naive claims
        fallback would trust it.
        We assert that auth.verify_token() MUST reject this token with 401!
        """
        os.environ["ALLOW_TEST_MOCK_TOKENS"] = "false"
        now = int(time.time())
        forged_claims = {
            "aud": auth.FIREBASE_PROJECT_ID,
            "iss": f"https://securetoken.google.com/{auth.FIREBASE_PROJECT_ID}",
            "sub": "victim_account_uid_9999",
            "user_id": "victim_account_uid_9999",
            "email": "victim@example.com",
            "exp": now + 3600,
            "iat": now,
        }
        forged_header = {"alg": "RS256", "typ": "JWT", "kid": "attacker_fake_key_id"}
        forged_jwt = make_jwt(forged_header, forged_claims, b"attacker_forged_signature_bytes")

        with self.assertRaises(HTTPException) as ctx:
            auth.verify_token(forged_jwt)
        self.assertEqual(ctx.exception.status_code, 401)
        print("  -> [PASS] Forged JWT with unverified signature was successfully rejected with 401.")

    # -------------------------------------------------------------------------
    # TEST 4: Expired token rejected
    # -------------------------------------------------------------------------
    def test_expired_token_rejected(self):
        """Verifies that an expired token is rejected with 401."""
        os.environ["ALLOW_TEST_MOCK_TOKENS"] = "false"
        now = int(time.time())
        expired_claims = {
            "aud": auth.FIREBASE_PROJECT_ID,
            "iss": f"https://securetoken.google.com/{auth.FIREBASE_PROJECT_ID}",
            "sub": "some_user_uid",
            "user_id": "some_user_uid",
            "exp": now - 3600,  # Expired 1 hour ago
            "iat": now - 7200,
        }
        expired_jwt = make_jwt({"alg": "RS256", "typ": "JWT", "kid": "expired_kid"}, expired_claims)

        with self.assertRaises(HTTPException) as ctx:
            auth.verify_token(expired_jwt)
        self.assertEqual(ctx.exception.status_code, 401)
        print("  -> [PASS] Expired token was successfully rejected with 401.")

    # -------------------------------------------------------------------------
    # TEST 5: Missing 'exp' claim rejected
    # -------------------------------------------------------------------------
    def test_missing_exp_claim_rejected(self):
        """Verifies that a token missing the 'exp' claim is rejected with 401."""
        os.environ["ALLOW_TEST_MOCK_TOKENS"] = "false"
        now = int(time.time())
        no_exp_claims = {
            "aud": auth.FIREBASE_PROJECT_ID,
            "iss": f"https://securetoken.google.com/{auth.FIREBASE_PROJECT_ID}",
            "sub": "some_user_uid",
            "user_id": "some_user_uid",
            "iat": now,
        }
        no_exp_jwt = make_jwt({"alg": "RS256", "typ": "JWT", "kid": "no_exp_kid"}, no_exp_claims)

        with self.assertRaises(HTTPException) as ctx:
            auth.verify_token(no_exp_jwt)
        self.assertEqual(ctx.exception.status_code, 401)
        print("  -> [PASS] Token missing 'exp' claim was successfully rejected with 401.")

    # -------------------------------------------------------------------------
    # TEST 6: Incorrect audience ('aud') rejected
    # -------------------------------------------------------------------------
    def test_incorrect_audience_rejected(self):
        """Verifies that a token with an audience from another Firebase project is rejected."""
        os.environ["ALLOW_TEST_MOCK_TOKENS"] = "false"
        now = int(time.time())
        bad_aud_claims = {
            "aud": "attacker-other-project-id",
            "iss": "https://securetoken.google.com/attacker-other-project-id",
            "sub": "attacker_user_uid",
            "user_id": "attacker_user_uid",
            "exp": now + 3600,
            "iat": now,
        }
        bad_aud_jwt = make_jwt({"alg": "RS256", "typ": "JWT", "kid": "bad_aud_kid"}, bad_aud_claims)

        with self.assertRaises(HTTPException) as ctx:
            auth.verify_token(bad_aud_jwt)
        self.assertEqual(ctx.exception.status_code, 401)
        print("  -> [PASS] Token with incorrect audience was successfully rejected with 401.")

    # -------------------------------------------------------------------------
    # TEST 7: Incorrect issuer ('iss') rejected
    # -------------------------------------------------------------------------
    def test_incorrect_issuer_rejected(self):
        """Verifies that a token with a forged/evil issuer is rejected."""
        os.environ["ALLOW_TEST_MOCK_TOKENS"] = "false"
        now = int(time.time())
        bad_iss_claims = {
            "aud": auth.FIREBASE_PROJECT_ID,
            "iss": "https://evil-identity-provider.com/token",
            "sub": "attacker_user_uid",
            "user_id": "attacker_user_uid",
            "exp": now + 3600,
            "iat": now,
        }
        bad_iss_jwt = make_jwt({"alg": "RS256", "typ": "JWT", "kid": "bad_iss_kid"}, bad_iss_claims)

        with self.assertRaises(HTTPException) as ctx:
            auth.verify_token(bad_iss_jwt)
        self.assertEqual(ctx.exception.status_code, 401)
        print("  -> [PASS] Token with incorrect issuer was successfully rejected with 401.")

    # -------------------------------------------------------------------------
    # TEST 8: Mock token rejection in production mode
    # -------------------------------------------------------------------------
    def test_mock_token_disabled_in_production(self):
        """
        Verifies that mock test tokens (test_token_...) CANNOT be used in production
        even if ALLOW_TEST_MOCK_TOKENS=true is set in the environment.
        """
        for prod_env in ["production", "prod", "PRODUCTION"]:
            os.environ["ENVIRONMENT"] = prod_env
            os.environ["ALLOW_TEST_MOCK_TOKENS"] = "true"

            with self.assertRaises(HTTPException) as ctx:
                auth.verify_token("test_token_some_user_uid")
            self.assertEqual(ctx.exception.status_code, 401)

        print("  -> [PASS] Mock tokens are strictly rejected in production environments.")

    # -------------------------------------------------------------------------
    # TEST 9: Mock token rejection when ALLOW_TEST_MOCK_TOKENS is false
    # -------------------------------------------------------------------------
    def test_mock_token_rejected_when_not_allowed(self):
        """Verifies that mock test tokens are rejected when ALLOW_TEST_MOCK_TOKENS is false/unset."""
        os.environ["ENVIRONMENT"] = "development"
        for disallow_val in ["false", "0", "", "no"]:
            os.environ["ALLOW_TEST_MOCK_TOKENS"] = disallow_val
            with self.assertRaises(HTTPException) as ctx:
                auth.verify_token("test_token_some_user_uid")
            self.assertEqual(ctx.exception.status_code, 401)

        print("  -> [PASS] Mock tokens are rejected when ALLOW_TEST_MOCK_TOKENS is false/unset.")

    # -------------------------------------------------------------------------
    # TEST 10: Mock token acceptance ONLY when explicitly allowed in development
    # -------------------------------------------------------------------------
    def test_mock_token_accepted_in_dev_testing(self):
        """Verifies that mock test tokens work as expected for automated testing in dev mode."""
        os.environ["ENVIRONMENT"] = "development"
        os.environ["ALLOW_TEST_MOCK_TOKENS"] = "true"

        res = auth.verify_token("test_token_dev_tester_42")
        self.assertIsInstance(res, dict)
        self.assertEqual(res.get("uid"), "dev_tester_42")
        self.assertEqual(res.get("sub"), "dev_tester_42")
        print("  -> [PASS] Mock tokens work in development testing mode when explicitly enabled.")

    # -------------------------------------------------------------------------
    # TEST 11: End-to-end FastAPI endpoint rejection with forged tokens
    # -------------------------------------------------------------------------
    def test_endpoints_reject_forged_tokens(self):
        """
        Verifies that calling protected FastAPI routes with forged tokens returns HTTP 401.
        Protected routes tested:
        - GET /history
        - POST /confirm
        - GET /storage/stats
        - DELETE /history/clear
        """
        os.environ["ENVIRONMENT"] = "development"
        os.environ["ALLOW_TEST_MOCK_TOKENS"] = "false"

        now = int(time.time())
        forged_jwt = make_jwt(
            {"alg": "RS256", "typ": "JWT", "kid": "fake_kid"},
            {
                "aud": auth.FIREBASE_PROJECT_ID,
                "iss": f"https://securetoken.google.com/{auth.FIREBASE_PROJECT_ID}",
                "sub": "victim_uid",
                "user_id": "victim_uid",
                "exp": now + 3600
            }
        )
        headers = {"Authorization": f"Bearer {forged_jwt}"}

        # 1. GET /history
        r_hist = self.client.get("/history", headers=headers)
        self.assertEqual(r_hist.status_code, 401, f"GET /history did not reject forged token: {r_hist.status_code}")

        # 2. POST /confirm
        r_conf = self.client.post("/confirm", json={"action": "correct", "data": {}}, headers=headers)
        self.assertEqual(r_conf.status_code, 401, f"POST /confirm did not reject forged token: {r_conf.status_code}")

        # 3. GET /storage/stats
        r_stats = self.client.get("/storage/stats", headers=headers)
        self.assertEqual(r_stats.status_code, 401, f"GET /storage/stats did not reject forged token: {r_stats.status_code}")

        # 4. DELETE /history/clear
        r_clear = self.client.delete("/history/clear", headers=headers)
        self.assertEqual(r_clear.status_code, 401, f"DELETE /history/clear did not reject forged token: {r_clear.status_code}")

        print("  -> [PASS] All protected endpoints rejected forged Bearer tokens with 401.")


if __name__ == "__main__":
    print("=" * 75)
    print("RUNNING AUTHENTICATION SECURITY & TOKEN VERIFICATION TEST SUITE")
    print("=" * 75)
    unittest.main(verbosity=2)

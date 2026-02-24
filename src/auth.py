import os
import json
import urllib.request
from jose import jwk, jwt

COGNITO_REGION   = os.environ.get("COGNITO_REGION", "us-east-1")
USER_POOL_ID     = os.environ.get("COGNITO_USER_POOL_ID", "")
CLIENT_ID        = os.environ.get("COGNITO_CLIENT_ID", "")

JWKS_URL = (
    f"https://cognito-idp.{COGNITO_REGION}.amazonaws.com"
    f"/{USER_POOL_ID}/.well-known/jwks.json"
)

# Cached per Lambda container lifetime to avoid fetching on every request
_jwks_cache = None


def _get_jwks():
    global _jwks_cache
    if _jwks_cache is None:
        with urllib.request.urlopen(JWKS_URL) as response:
            _jwks_cache = json.loads(response.read())
    return _jwks_cache


def _unauthorized(message: str) -> dict:
    return {
        "statusCode": 401,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Headers": "Content-Type,Authorization",
            "Access-Control-Allow-Methods": "POST, OPTIONS",
        },
        "body": json.dumps({"error": message}),
    }


def verify_token(event: dict):
    """
    Verify the Cognito ID token from the Authorization header.

    Returns (claims, None) on success.
    Returns (None, error_response) on failure — caller should return the error_response immediately.
    """
    headers = event.get("headers") or {}
    # Lambda Function URLs lowercase all header names
    auth_header = headers.get("authorization") or headers.get("Authorization", "")

    if not auth_header.startswith("Bearer "):
        return None, _unauthorized("Missing or malformed Authorization header")

    token = auth_header[len("Bearer "):]

    try:
        unverified_header = jwt.get_unverified_header(token)
        kid = unverified_header.get("kid")

        jwks = _get_jwks()
        matching_keys = [k for k in jwks["keys"] if k["kid"] == kid]
        if not matching_keys:
            return None, _unauthorized("Public key not found")

        public_key = jwk.construct(matching_keys[0])
        issuer = f"https://cognito-idp.{COGNITO_REGION}.amazonaws.com/{USER_POOL_ID}"

        claims = jwt.decode(
            token,
            public_key,
            algorithms=["RS256"],
            audience=CLIENT_ID,
            issuer=issuer,
        )

        if claims.get("token_use") != "id":
            return None, _unauthorized("Token is not an ID token")

        return claims, None

    except Exception as exc:
        print(f"Token verification failed: {exc}")
        return None, _unauthorized("Invalid or expired token")

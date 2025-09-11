import os
import json
import base64
from typing import Optional, Tuple
from firebase_admin import credentials, firestore, initialize_app, storage, _apps

# Helper: Build a Firebase credential from multiple env-driven sources
# Priority:
# 1) FIREBASE_CREDENTIALS_JSON (raw JSON)
# 2) FIREBASE_CREDENTIALS_JSON_BASE64 (base64-encoded JSON)
# 3) FIREBASE_CREDENTIALS (file path)
# 4) GOOGLE_APPLICATION_CREDENTIALS (file path)
# 5) Local files next to this module (serviceAccount*.json)

def _build_credential() -> Optional[credentials.Certificate]:
    # 1) Raw JSON string
    raw_json = os.environ.get('FIREBASE_CREDENTIALS_JSON')
    if raw_json:
        try:
            data = json.loads(raw_json)
            return credentials.Certificate(data)
        except Exception:
            pass

    # 2) Base64-encoded JSON
    b64_json = os.environ.get('FIREBASE_CREDENTIALS_JSON_BASE64') or os.environ.get('FIREBASE_CREDENTIALS_B64')
    if b64_json:
        try:
            decoded = base64.b64decode(b64_json).decode('utf-8')
            data = json.loads(decoded)
            return credentials.Certificate(data)
        except Exception:
            pass

    # 3) Explicit path env var
    path_envs = [
        os.environ.get('FIREBASE_CREDENTIALS'),
        os.environ.get('GOOGLE_APPLICATION_CREDENTIALS'),
    ]
    for p in path_envs:
        if p and os.path.exists(p):
            try:
                return credentials.Certificate(p)
            except Exception:
                pass

    # 5) Local common filenames
    here = os.path.dirname(os.path.abspath(__file__))
    for fname in [
        'serviceAccount.json',
        'serviceAccountKey.json',
        'firebase_credentials.json',
        'firebase-key.json',
    ]:
        candidate = os.path.join(here, fname)
        if os.path.exists(candidate):
            try:
                return credentials.Certificate(candidate)
            except Exception:
                pass
        # Also check a ./credentials directory to keep secrets out of the repo root
        candidate_nested = os.path.join(here, 'credentials', fname)
        if os.path.exists(candidate_nested):
            try:
                return credentials.Certificate(candidate_nested)
            except Exception:
                pass

    return None

# Initialize Firebase Admin SDK in a safe, env-driven way
# Returns (db, bucket) or (None, None) if credentials are not available.
# We intentionally avoid falling back to ADC when not explicitly configured, to
# prevent slow metadata server checks (common on local Windows dev).

def initialize_firebase() -> Tuple[Optional[object], Optional[object]]:
    try:
        bucket_name = (
            os.environ.get('FIREBASE_STORAGE_BUCKET')
            or os.environ.get('GOOGLE_CLOUD_STORAGE_BUCKET')
            or os.environ.get('GCS_BUCKET')
        )

        app_options = {'storageBucket': bucket_name} if bucket_name else None

        if not _apps:
            cred = _build_credential()
            if cred is None:
                # No credentials configured; skip initialization, let the app run without DB
                print('Firebase credentials not found. Skipping Admin SDK initialization. Set GOOGLE_APPLICATION_CREDENTIALS or FIREBASE_CREDENTIALS* env vars.')
                return None, None
            initialize_app(cred, app_options)

        # Acquire clients
        db = firestore.client()
        bucket = storage.bucket(bucket_name) if bucket_name else storage.bucket()
        return db, bucket
    except Exception as e:
        print(f"Error initializing Firebase: {str(e)}")
        return None, None

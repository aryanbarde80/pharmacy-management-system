import os
from firebase_admin import credentials, firestore, initialize_app, storage, _apps

# Initialize Firebase Admin SDK in a safe, env-driven way
def initialize_firebase():
    try:
        # Credentials: prefer GOOGLE_APPLICATION_CREDENTIALS path if set
        cred_path = os.environ.get('GOOGLE_APPLICATION_CREDENTIALS')
        app_kwargs = {}
        bucket_name = os.environ.get('FIREBASE_STORAGE_BUCKET')
        if bucket_name:
            app_kwargs['storageBucket'] = bucket_name

        if not _apps:
            if cred_path and os.path.exists(cred_path):
                cred = credentials.Certificate(cred_path)
                initialize_app(cred, app_kwargs or None)
            else:
                # Attempt to initialize with application default credentials
                # This will work in many cloud/local environments where ADC is configured
                initialize_app(options=app_kwargs or None)

        # Acquire clients
        db = firestore.client()
        # If a bucket name is provided, return that; otherwise default bucket (may be None)
        bucket = storage.bucket(bucket_name) if bucket_name else storage.bucket()
        return db, bucket
    except Exception as e:
        print(f"Error initializing Firebase: {str(e)}")
        return None, None

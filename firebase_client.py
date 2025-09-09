"""
Simple Firebase client wrapper for Firestore with a mocked fallback when credentials are not provided.
Set the environment variable GOOGLE_APPLICATION_CREDENTIALS to the path of your service account JSON file.
"""
import os
import json

USE_FIREBASE = False
try:
    import firebase_admin
    from firebase_admin import credentials, firestore

    # initialize app if credentials provided
    cred_path = os.environ.get('GOOGLE_APPLICATION_CREDENTIALS')
    if cred_path and os.path.exists(cred_path):
        cred = credentials.Certificate(cred_path)
        firebase_admin.initialize_app(cred)
        db = firestore.client()
        USE_FIREBASE = True
    else:
        # try application default
        try:
            firebase_admin.initialize_app()
            db = firestore.client()
            USE_FIREBASE = True
        except Exception:
            USE_FIREBASE = False
except Exception:
    USE_FIREBASE = False


# Mock data used when Firebase isn't configured
MOCK = {
    'inventory': [
        {'name': 'Pain Relief Tablets', 'batch': 'BTCH2023001', 'qty': 500, 'expiry': '2024-12-31', 'status': 'Adequate'},
        {'name': 'Antibiotic Capsules', 'batch': 'BTCH2023002', 'qty': 75, 'expiry': '2024-06-30', 'status': 'Low Stock'},
    ],
    'medicines': [
        {'name': 'Medication A', 'category': 'Pain Relief', 'stock': 150, 'expiry': '2024-12-31'},
        {'name': 'Medication B', 'category': 'Antibiotics', 'stock': 25, 'expiry': '2024-08-15'},
    ],
    'orders': [
        {'id': '#ORD12345', 'supplier': 'MediCorp Inc.', 'date': '2023-08-15', 'status': 'Completed'},
        {'id': '#ORD12346', 'supplier': 'HealthPlus Supplies', 'date': '2023-08-16', 'status': 'In Transit'},
    ],
    'stats': {
        'total_medicines': 1250,
        'expiring_soon': 35,
        'active_prescriptions': 120,
        'low_inventory': 15,
    }
}


def get_collection(name: str):
    """Return a list/dict from Firestore collection or mock data."""
    if USE_FIREBASE:
        try:
            col = db.collection(name)
            docs = col.stream()
            data = [d.to_dict() for d in docs]
            return data
        except Exception:
            return MOCK.get(name, [])
    else:
        return MOCK.get(name, [])


def add_document(collection: str, data: dict):
    """Add a document to Firestore collection or update mock data.

    Returns the document id (or True for mock append).
    """
    if USE_FIREBASE:
        try:
            doc_ref = db.collection(collection).add(data)
            # doc_ref is a tuple (reference, write_time) for admin SDK; return id if possible
            try:
                return doc_ref[0].id
            except Exception:
                return True
        except Exception:
            return False
    else:
        # append to mock list to simulate a write
        if collection in MOCK and isinstance(MOCK[collection], list):
            MOCK[collection].append(data)
            return True
        else:
            return False

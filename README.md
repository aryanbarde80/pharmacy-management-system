# KicksUp (PharmaSys) — Flask + Firebase

This repository contains a small Flask app serving the static pages as templates and wired to Firebase (Firestore) with a mocked fallback when Firebase is not configured.

Getting started

1. Create a Python virtual environment and install dependencies:

```powershell
python -m venv .venv; .\.venv\Scripts\Activate; pip install -r requirements.txt
```

2. Provide Firebase credentials (optional)
- Create a Firebase project and a service account with Firestore access.
- Download the service account JSON and set an environment variable on Windows PowerShell:

```powershell
$env:GOOGLE_APPLICATION_CREDENTIALS = 'C:\path\to\serviceAccount.json'
```

If no credentials are provided the app will use mocked sample data.

3. Run the app

```powershell
python app.py
```

Open http://127.0.0.1:5000

Notes
- Templates live in `templates/` and are basic Jinja templates that render data from Firestore or mock data.
- To actually use Firebase, ensure `GOOGLE_APPLICATION_CREDENTIALS` points to your service account JSON.

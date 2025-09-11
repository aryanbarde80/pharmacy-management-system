import os
import json
import base64
from datetime import datetime, timezone, timedelta
from functools import wraps
from flask import Flask, render_template, redirect, url_for, session, flash, request, jsonify, make_response, g
from flask_cors import CORS
from translations import get_translation
from firebase_admin import auth, credentials, firestore
from firebase_config import initialize_firebase
from dotenv import load_dotenv
from google.oauth2 import id_token as google_id_token
from google.auth.transport import requests as google_requests

# Load environment variables from .env if present (dev convenience)
load_dotenv()

# Initialize Firebase using environment configuration (safe for open source)
try:
    db, bucket = initialize_firebase()
except Exception as e:
    print(f"Firebase initialization warning: {str(e)}")
    db, bucket = (None, None)

app = Flask(__name__, static_folder='static', template_folder='templates')
# Read from environment; provide a dev default that should be changed in production
app.secret_key = os.environ.get('FLASK_SECRET_KEY', 'dev-secret-change-me')  # Set FLASK_SECRET_KEY in your environment

@app.before_request
def before_request():
    # Set language from session, cookie, or default to English
    g.lang = session.get('language', request.cookies.get('language', 'en'))
    # Ensure we have a valid language
    if g.lang not in ['en', 'ar']:
        g.lang = 'en'
    # Update session with current language
    session['language'] = g.lang
    # Set translation function
    g._ = lambda key: get_translation(key, g.lang)
    g.now = datetime.now()
    # Set response headers for language
    response = make_response()
    response.set_cookie('language', g.lang, max_age=60*60*24*30)  # 30 days

@app.context_processor
def inject_translations():
    # Use session directly to avoid relying on setup order
    lang = session.get('language', 'en')
    return dict(
        _=lambda key: get_translation(key, lang),
        gettext=lambda key: get_translation(key, lang),
        now=datetime.now()
    )

# Use dev-friendly cookies locally; secure settings in production
# Flask 3 removed app.config['ENV'], so detect development using env vars or FLASK_DEBUG
_env = os.environ.get('FLASK_ENV') or os.environ.get('ENV')
_is_dev = (_env == 'development') or (os.environ.get('FLASK_DEBUG') == '1')

if _is_dev:
    app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
    app.config['SESSION_COOKIE_SECURE'] = False
else:
    app.config['SESSION_COOKIE_SAMESITE'] = 'None'
    app.config['SESSION_COOKIE_SECURE'] = True

# Enable CORS
CORS(app, resources={
    r"/*": {
        "origins": ["http://localhost:5000", "http://127.0.0.1:5000"],
        "supports_credentials": True
    }
})

# Firebase Authentication and Database Functions
def get_user_by_email(email):
    try:
        users_ref = db.collection('users')
        query = users_ref.where('email', '==', email).limit(1)
        results = query.stream()
        
        for user in results:
            return user.to_dict()
        return None
    except Exception as e:
        print(f"Error getting user: {str(e)}")
        return None

def verify_password(user_data, password):
    # In a real app, you should use proper password hashing
    # This is a simplified example - use Firebase Auth in production
    return user_data.get('password') == password

def get_collection(collection_name):
    try:
        if db is None:
            raise RuntimeError('Firestore client is not initialized')
        col_ref = db.collection(collection_name).stream()
        return [{'id': doc.id, **doc.to_dict()} for doc in col_ref]
    except Exception as e:
        print(f"Error fetching collection {collection_name}: {str(e)}")
        return []

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user' not in session:
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return jsonify({'error': 'Authentication required'}), 401
            return redirect(url_for('login', next=request.url))
        return f(*args, **kwargs)
    return decorated_function


@app.route('/login')
def login():
    if 'user' in session:
        return redirect(url_for('dashboard'))
    return render_template('login.html')

@app.route('/signup')
def signup():
    if 'user' in session:
        return redirect(url_for('dashboard'))
    return render_template('signup.html')

@app.route('/verify-token', methods=['POST', 'OPTIONS'])
def verify_token():
    if request.method == 'OPTIONS':
        response = make_response()
        response.headers.add('Access-Control-Allow-Origin', request.headers.get('Origin', '*'))
        response.headers.add('Access-Control-Allow-Headers', 'Content-Type')
        response.headers.add('Access-Control-Allow-Methods', 'POST, OPTIONS')
        response.headers.add('Access-Control-Allow-Credentials', 'true')
        return response

    try:
        # Get the ID token from the request
        id_token = request.json.get('token')
        if not id_token:
            return jsonify({'error': 'No token provided'}), 400

        # Decode token (without verification) for debug info
        try:
            header_b64, payload_b64, _sig = id_token.split('.')
            def b64url_decode(b):
                b += '=' * (-len(b) % 4)
                return base64.urlsafe_b64decode(b.encode('utf-8')).decode('utf-8')
            header = json.loads(b64url_decode(header_b64))
            payload = json.loads(b64url_decode(payload_b64))
            print(f"[verify-token] Token claims preview: aud={payload.get('aud')}, iss={payload.get('iss')}, sub={payload.get('sub')}")
        except Exception as decode_err:
            print(f"[verify-token] Failed to decode token (non-fatal): {decode_err}")

        # Verify the ID token
        decoded_token = None
        uid = None
        try:
            # Prefer Admin SDK when initialized
            clock_skew = int(os.environ.get('AUTH_CLOCK_SKEW_SECONDS', '300'))
            decoded_token = auth.verify_id_token(id_token, clock_skew_seconds=clock_skew)
            uid = decoded_token.get('uid') or decoded_token.get('sub')
        except Exception as admin_verify_err:
            # Fallback: verify using google-auth without requiring Admin app
            try:
                aud = os.environ.get('FIREBASE_PROJECT_ID') or os.environ.get('GCLOUD_PROJECT')
                if not aud:
                    try:
                        header_b64, payload_b64, _sig = id_token.split('.')
                        def b64url_decode(b):
                            b += '=' * (-len(b) % 4)
                            return base64.urlsafe_b64decode(b.encode('utf-8')).decode('utf-8')
                        payload = json.loads(b64url_decode(payload_b64))
                        aud = payload.get('aud')
                    except Exception:
                        aud = None
                req = google_requests.Request()
                clock_skew = int(os.environ.get('AUTH_CLOCK_SKEW_SECONDS', '300'))
                try:
                    decoded_token = google_id_token.verify_firebase_token(id_token, req, audience=aud, clock_skew_in_seconds=clock_skew)
                except TypeError:
                    # Older google-auth versions may not support clock_skew_in_seconds
                    decoded_token = google_id_token.verify_firebase_token(id_token, req, audience=aud)
                uid = decoded_token.get('uid') or decoded_token.get('sub')
            except Exception as e2:
                print(f"[verify-token] Token verification failed: {e2}")
                raise
        if not uid:
            return jsonify({'error': 'Authentication failed'}), 401
        print(f"[verify-token] Token verified for uid={uid}")
        
        # Get or create the user's data in Firestore (if available); otherwise minimal session only
        user_data = None
        if db is not None:
            user_ref = db.collection('users').document(uid)
            user_doc = user_ref.get()

            if not user_doc.exists:
                # Auto-provision a minimal user profile if none exists
                default_name = (decoded_token.get('name')
                                or (decoded_token.get('email') or '').split('@')[0]
                                or 'User')
                user_data = {
                    'email': decoded_token.get('email'),
                    'name': default_name,
                    'role': 'user',
                    'created_at': firestore.SERVER_TIMESTAMP,
                    'last_login_at': firestore.SERVER_TIMESTAMP,
                }
                user_ref.set(user_data, merge=True)
            else:
                user_data = user_doc.to_dict()
                # Update last login time
                user_ref.update({'last_login_at': firestore.SERVER_TIMESTAMP})
        else:
            # DB not configured; create minimal user data from token claims
            default_name = (decoded_token.get('name')
                            or (decoded_token.get('email') or '').split('@')[0]
                            or 'User')
            user_data = {
                'email': decoded_token.get('email'),
                'name': default_name,
                'role': 'user',
            }

        # Set up the session
        session.permanent = True
        session['user'] = {
            'uid': uid,
            'email': user_data.get('email'),
            'name': user_data.get('name', 'User'),
            'role': user_data.get('role', 'user')
        }

        response = jsonify({'success': True, 'user': session['user']})
        response.headers.add('Access-Control-Allow-Origin', request.headers.get('Origin', '*'))
        response.headers.add('Access-Control-Allow-Credentials', 'true')
        return response
        
    except auth.ExpiredIdTokenError as e:
        print(f"[verify-token] Token expired: {e}")
        return jsonify({'error': 'Token expired'}), 401
    except auth.InvalidIdTokenError as e:
        print(f"[verify-token] Invalid token: {e}")
        return jsonify({'error': 'Invalid token'}), 401
    except Exception as e:
        print(f"[verify-token] Token verification error (unexpected): {str(e)}")
        return jsonify({'error': 'Authentication failed'}), 500

@app.route('/logout')
def logout():
    session.pop('user', None)
    return redirect(url_for('login'))

@app.route('/set_language/<lang>')
def set_language(lang):
    print(f"Setting language to: {lang}")  # Debug log
    print(f"Session before: {dict(session)}")  # Debug log
    
    if lang in ['en', 'ar']:
        session['language'] = lang
        session.modified = True  # Ensure session is saved
        print(f"Session after: {dict(session)}")  # Debug log
        response = jsonify({'status': 'success', 'language': lang})
        response.set_cookie('language', lang, max_age=60*60*24*30)  # 30 days
        return response
    return jsonify({'status': 'error', 'message': 'Invalid language'}), 400

@app.route('/')
def index():
    return redirect(url_for('login'))

@app.route('/dashboard')
@login_required
def dashboard():
    # Compute real-time dashboard stats and chart data from Firestore
    stats = {
        'total_medicines': 0,
        'expiring_soon': 0,
        'active_prescriptions': 0,
        'low_inventory': 0,
    }
    chart_data = { 'months': [], 'sales': [] }
    try:
        if db is None:
            raise RuntimeError('Firestore client is not initialized')

        # 1) Total medicines
        meds_iter = db.collection('medicines').stream()
        total_meds = 0
        expiring = 0
        from datetime import date
        today = datetime.now(timezone.utc).date()
        horizon = today + timedelta(days=30)
        for d in meds_iter:
            total_meds += 1
            data = d.to_dict() or {}
            expiry = data.get('expiry') or data.get('expiration')
            exp_date = None
            if expiry is not None:
                if isinstance(expiry, datetime):
                    exp_date = expiry.date()
                elif isinstance(expiry, str):
                    try:
                        exp_date = datetime.strptime(expiry[:10], '%Y-%m-%d').date()
                    except Exception:
                        exp_date = None
            if exp_date and today <= exp_date <= horizon:
                expiring += 1
        stats['total_medicines'] = total_meds
        stats['expiring_soon'] = expiring

        # 2) Active prescriptions (if collection exists), otherwise 0
        try:
            active_statuses = ['active', 'processing', 'قيد التنفيذ']
            pres_q = db.collection('prescriptions').where('status', 'in', active_statuses).stream()
            stats['active_prescriptions'] = sum(1 for _ in pres_q)
        except Exception:
            # Fallback scan
            try:
                pres_all = db.collection('prescriptions').stream()
                c = 0
                for p in pres_all:
                    s = (p.to_dict() or {}).get('status', '')
                    if isinstance(s, str) and (('active' in s.lower()) or (s in ['قيد التنفيذ'])):
                        c += 1
                stats['active_prescriptions'] = c
            except Exception:
                stats['active_prescriptions'] = 0

        # 3) Low inventory (stock < min)
        try:
            inv_iter = db.collection('inventory').stream()
            low = 0
            for it in inv_iter:
                data = it.to_dict() or {}
                try:
                    stock = int(data.get('stock') or 0)
                except Exception:
                    stock = 0
                minv = data.get('min')
                try:
                    min_i = int(minv) if minv is not None and str(minv) != '' else None
                except Exception:
                    min_i = None
                if (min_i is not None) and (stock < min_i):
                    low += 1
            stats['low_inventory'] = low
        except Exception:
            stats['low_inventory'] = 0

        # 4) Chart data: last 6 months revenue from orders.total
        # Build month labels
        def month_key(dt: datetime):
            return (dt.year, dt.month)
        # Start from 5 months ago
        base = datetime.now(timezone.utc).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        months = []
        year = base.year
        month = base.month
        for i in range(5, -1, -1):
            m = month - i
            y = year
            while m <= 0:
                m += 12
                y -= 1
            months.append((y, m))
        # labels
        import calendar
        labels = [calendar.month_abbr[m] for (_, m) in months]
        totals_by_month = { (y, m): 0.0 for (y, m) in months }
        start_ym = months[0]
        start_dt = datetime(start_ym[0], start_ym[1], 1, tzinfo=timezone.utc)
        # end = first day of next month after last
        last_ym = months[-1]
        if last_ym[1] == 12:
            end_dt = datetime(last_ym[0] + 1, 1, 1, tzinfo=timezone.utc)
        else:
            end_dt = datetime(last_ym[0], last_ym[1] + 1, 1, tzinfo=timezone.utc)
        try:
            q = db.collection('orders').where(filter=firestore.And(firestore.FieldFilter('date', '>=', start_dt), firestore.FieldFilter('date', '<', end_dt))).stream()
        except Exception:
            q = db.collection('orders').stream()
        for doc in q:
            data = doc.to_dict() or {}
            dt = data.get('date')
            if not isinstance(dt, datetime):
                continue
            # normalize tz
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            key = month_key(dt)
            if key not in totals_by_month:
                continue
            val = data.get('total')
            amt = None
            if isinstance(val, (int, float)):
                amt = float(val)
            elif isinstance(val, str):
                cleaned = ''.join(ch for ch in val if ch.isdigit() or ch in ['.', ','])
                cleaned = cleaned.replace(',', '')
                try:
                    amt = float(cleaned) if cleaned else None
                except Exception:
                    amt = None
            if amt is not None:
                totals_by_month[key] += amt
        chart_data['months'] = labels
        chart_data['sales'] = [ round(totals_by_month[(y, m)], 2) for (y, m) in months ]

    except Exception as e:
        print(f"Error fetching dashboard data: {str(e)}")
        # keep defaults (zeros, empty chart)
    return render_template('index.html', active='dashboard', stats=stats, chart_data=chart_data)


@app.route('/inventory')
@login_required
def inventory():
    inv_stats = {
        'total_items': 0,
        'active_items': 0,
        'low_stock': 0,
        'critical': 0,
        'out_of_stock': 0,
        'on_order': 0,
        'inventory_value': 0.0,
        'active_pct': 0,
        'low_pct': 0,
        'on_order_pct': 0,
    }
    try:
        if db is None:
            raise RuntimeError('Firestore client is not initialized')
        # Load inventory items
        items_ref = db.collection('inventory').stream()
        items = [{'id': item.id, **item.to_dict()} for item in items_ref]
        inv_stats['total_items'] = len(items)

        # Compute per-item stats
        total_value = 0.0
        low_count = 0
        critical_count = 0
        active_count = 0
        out_count = 0
        for it in items:
            stock = 0
            try:
                stock = int(it.get('stock') or 0)
            except Exception:
                stock = 0
            price_val = it.get('price')
            price = None
            if isinstance(price_val, (int, float)):
                price = float(price_val)
            elif isinstance(price_val, str):
                cleaned = ''.join(ch for ch in price_val if ch.isdigit() or ch in ['.', ','])
                cleaned = cleaned.replace(',', '')
                try:
                    price = float(cleaned) if cleaned else None
                except Exception:
                    price = None
            if price is not None:
                total_value += price * stock

            # thresholds
            min_val = it.get('min')
            try:
                min_i = int(min_val) if min_val is not None and str(min_val) != '' else None
            except Exception:
                min_i = None

            if stock > 0 and (it.get('active', True) is not False):
                active_count += 1
            if stock <= 0:
                out_count += 1
            if (min_i is not None) and (stock < min_i):
                low_count += 1
                # critical: below half of min (at least threshold 1)
                threshold = max(min_i // 2, 1)
                if stock < threshold:
                    critical_count += 1

        inv_stats['inventory_value'] = round(total_value, 2)
        inv_stats['low_stock'] = low_count
        inv_stats['critical'] = critical_count
        inv_stats['active_items'] = active_count
        inv_stats['out_of_stock'] = out_count

        # On-order items: count distinct item_ids in pending/processing orders
        pending_statuses = ['pending', 'processing', 'in_transit', 'قيد الانتظار', 'قيد المعالجة']
        on_order_ids = set()
        try:
            ord_q = db.collection('orders').where('status', 'in', pending_statuses).stream()
        except Exception:
            ord_q = db.collection('orders').stream()
        for o in ord_q:
            data = o.to_dict() or {}
            its = data.get('items') or []
            if isinstance(its, list):
                for row in its:
                    iid = (row or {}).get('item_id') or (row or {}).get('id') or (row or {}).get('code')
                    if iid:
                        on_order_ids.add(str(iid))
        inv_stats['on_order'] = len(on_order_ids)

        # Percentages for progress bars
        total = inv_stats['total_items']
        if total > 0:
            inv_stats['active_pct'] = round((inv_stats['active_items'] / total) * 100)
            inv_stats['low_pct'] = round((inv_stats['low_stock'] / total) * 100)
            inv_stats['on_order_pct'] = round((inv_stats['on_order'] / total) * 100)

    except Exception as e:
        print(f"Error fetching inventory: {str(e)}")
        items = []
        flash('An error occurred while fetching inventory', 'error')
    return render_template('inventory.html', active='inventory', items=items, inv_stats=inv_stats)


@app.route('/medicines')
@login_required
def medicines():
    try:
        if db is None:
            raise RuntimeError('Firestore client is not initialized')
        meds_ref = db.collection('medicines').stream()
        meds = [{'id': med.id, **med.to_dict()} for med in meds_ref]
    except Exception as e:
        print(f"Error fetching medicines: {str(e)}")
        meds = []
        flash('An error occurred while loading medicines', 'error')
    return render_template('medicines.html', active='medicines', meds=meds)

@app.route('/medicines/add', methods=['GET'])
def add_medicine_form():
    return render_template('add_medicine.html', active='medicines')

@app.route('/medicines/add', methods=['POST'])
def add_medicine_submit():
    data = {
        'name': request.form.get('name'),
        'category': request.form.get('category'),
        'stock': int(request.form.get('stock') or 0),
        'expiry': request.form.get('expiry'),
        'price': request.form.get('price')
    }
    try:
        if db is None:
            raise RuntimeError('Firestore client is not initialized')
        db.collection('medicines').add(data)
        flash('تمت إضافة الدواء بنجاح', 'success')
    except Exception as e:
        print(f"Error adding medicine: {str(e)}")
        flash('An error occurred while adding medicine', 'error')
    return redirect(url_for('medicines'))


@app.route('/orders')
@login_required
def orders():
    stats = {
        'total_orders': 0,
        'pending': 0,
        'month_total': 0.0,
        'avg_order_value': None,
    }
    try:
        if db is None:
            raise RuntimeError('Firestore client is not initialized')
        # Recent orders for table
        orders_ref = db.collection('orders').order_by('date', direction='DESCENDING').limit(50).stream()
        orders = [{'id': order.id, **order.to_dict()} for order in orders_ref]

        # Full scan for stats (small to medium datasets). For very large datasets, consider aggregation queries.
        # Total count, pending count, average order value, and this month's total amount.
        now = datetime.now(timezone.utc)
        start_month = datetime(now.year, now.month, 1, tzinfo=timezone.utc)
        next_month = (start_month.replace(day=28) + timedelta(days=4)).replace(day=1)
        total_sum_all = 0.0
        total_count_all = 0

        all_orders_iter = db.collection('orders').stream()
        for d in all_orders_iter:
            data = d.to_dict() or {}
            stats['total_orders'] += 1
            # Pending count (Arabic + English)
            st = data.get('status', '')
            if isinstance(st, str):
                st_l = st.lower()
                if ('pend' in st_l) or (st in ['قيد الانتظار']):
                    stats['pending'] += 1
            # Totals
            val = data.get('total')
            amt = None
            if isinstance(val, (int, float)):
                amt = float(val)
            elif isinstance(val, str):
                cleaned = ''.join(ch for ch in val if ch.isdigit() or ch in ['.', ','])
                cleaned = cleaned.replace(',', '')
                try:
                    amt = float(cleaned) if cleaned else None
                except Exception:
                    amt = None
            if amt is not None:
                total_sum_all += amt
                total_count_all += 1
            # Month total
            created = data.get('date')
            try:
                if isinstance(created, datetime):
                    # Ensure tz-aware comparison by converting naive to UTC if needed
                    if created.tzinfo is None:
                        created = created.replace(tzinfo=timezone.utc)
                    if start_month <= created < next_month and amt is not None:
                        stats['month_total'] += amt
            except Exception:
                pass

        if total_count_all > 0:
            stats['avg_order_value'] = round(total_sum_all / total_count_all, 2)

    except Exception as e:
        print(f"Error fetching orders: {str(e)}")
        orders = []
        flash('An error occurred while loading orders', 'error')
    return render_template('orders.html', active='orders', orders=orders, stats=stats)


@app.route('/orders/create', methods=['GET'])
@login_required
def create_order():
    try:
        if db is None:
            raise RuntimeError('Firestore client is not initialized')
        items_ref = db.collection('inventory').stream()
        items = [{'id': item.id, **item.to_dict()} for item in items_ref]
        suppliers_ref = db.collection('suppliers').stream()
        suppliers = [{'id': s.id, **s.to_dict()} for s in suppliers_ref]
    except Exception as e:
        print(f"Error preparing create order: {str(e)}")
        items = []
        suppliers = []
        flash('An error occurred while preparing the create order page', 'error')
    return render_template('create_order.html', active='inventory', items=items, suppliers=suppliers)


@app.route('/orders/create', methods=['POST'])
@login_required
def create_order_submit():
    supplier = request.form.get('supplier') or request.form.get('supplier_text')
    item_ids = request.form.getlist('item_id[]')
    qtys = request.form.getlist('quantity[]')
    items = []
    for iid, q in zip(item_ids, qtys):
        try:
            qn = int(q)
        except:
            qn = 0
        if iid:
            items.append({'item_id': iid, 'quantity': qn})
    order = {
        'supplier': supplier,
        'items': items,
        'status': 'pending',
        'created_by': session.get('user', {}).get('email'),
        'date': firestore.SERVER_TIMESTAMP
    }
    try:
        if db is None:
            raise RuntimeError('Firestore client is not initialized')
        db.collection('orders').add(order)
        flash('تم إنشاء الطلب بنجاح', 'success')
    except Exception as e:
        print(f"Error creating order: {str(e)}")
        flash('An error occurred while creating the order', 'error')
    return redirect(url_for('orders'))


@app.route('/suppliers/add', methods=['GET'])
@login_required
def add_supplier():
    """Display the form to add a new supplier"""
    return render_template('add_supplier.html', active='suppliers')

@app.route('/suppliers/add', methods=['POST'])
@login_required
def add_supplier_submit():
    """Process the new supplier form submission"""
    try:
        supplier_data = {
            'name': request.form.get('name'),
            'contact_person': request.form.get('contact_person'),
            'email': request.form.get('email'),
            'phone': request.form.get('phone'),
            'address': request.form.get('address'),
            'tax_id': request.form.get('tax_id'),
            'payment_terms': request.form.get('payment_terms'),
            'notes': request.form.get('notes'),
            'created_at': firestore.SERVER_TIMESTAMP,
            'updated_at': firestore.SERVER_TIMESTAMP
        }
        
        # Add the new supplier to Firestore
        doc_ref = db.collection('suppliers').document()
        doc_ref.set(supplier_data)
        
        flash('Supplier added successfully!', 'success')
        return redirect(url_for('suppliers'))
        
    except Exception as e:
        print(f"Error adding supplier: {str(e)}")
        flash('An error occurred while adding the supplier', 'error')
        return redirect(url_for('add_supplier'))

@app.route('/suppliers')
@login_required
def suppliers():
    suppliers = []
    stats = {
        'total_suppliers': 0,
        'active_orders': 0,
        'expenses_month': 0.0,
        'avg_delivery_days': None,
    }
    try:
        if db is None:
            raise RuntimeError('Firestore client is not initialized')
        # Suppliers list
        suppliers_ref = db.collection('suppliers').stream()
        suppliers = [{'id': sup.id, **sup.to_dict()} for sup in suppliers_ref]
        stats['total_suppliers'] = len(suppliers)

        # Active orders count (pending/processing/in transit/shipped)
        active_statuses = ['pending', 'processing', 'in_transit', 'shipped', 'قيد الانتظار', 'قيد المعالجة', 'تم الشحن']
        try:
            active_q = db.collection('orders').where('status', 'in', active_statuses).stream()
            stats['active_orders'] = sum(1 for _ in active_q)
        except Exception:
            # Fallback: count by scanning
            all_orders = db.collection('orders').stream()
            cnt = 0
            for o in all_orders:
                st = (o.to_dict() or {}).get('status', '')
                if isinstance(st, str) and any(k in st.lower() for k in ['pend', 'process', 'ship']) or st in ['قيد الانتظار', 'قيد المعالجة', 'تم الشحن']:
                    cnt += 1
            stats['active_orders'] = cnt

        # Expenses this month (sum of totals in current month)
        now = datetime.now(timezone.utc)
        start_month = datetime(now.year, now.month, 1, tzinfo=timezone.utc)
        next_month = (start_month.replace(day=28) + timedelta(days=4)).replace(day=1)
        try:
            month_q = db.collection('orders').where(filter=firestore.And(firestore.FieldFilter('date', '>=', start_month), firestore.FieldFilter('date', '<', next_month))).stream()
            total_sum = 0.0
            for d in month_q:
                val = (d.to_dict() or {}).get('total')
                if isinstance(val, (int, float)):
                    total_sum += float(val)
                elif isinstance(val, str):
                    # Strip non-numeric except dot and comma
                    cleaned = ''.join(ch for ch in val if ch.isdigit() or ch in ['.', ','])
                    cleaned = cleaned.replace(',', '')
                    try:
                        total_sum += float(cleaned) if cleaned else 0.0
                    except Exception:
                        pass
            stats['expenses_month'] = round(total_sum, 2)
        except Exception:
            stats['expenses_month'] = 0.0

        # Average delivery time (days) for delivered orders with delivered_at
        delivered_statuses = ['delivered', 'تم التسليم']
        try:
            del_q = db.collection('orders').where('status', 'in', delivered_statuses).stream()
            times = []
            for d in del_q:
                data = d.to_dict() or {}
                created = data.get('date')
                delivered_at = data.get('delivered_at')
                if created and delivered_at and hasattr(delivered_at, 'timestamp') and hasattr(created, 'timestamp'):
                    delta = delivered_at - created
                    times.append(delta.total_seconds() / 86400.0)
            if times:
                stats['avg_delivery_days'] = round(sum(times) / len(times), 1)
        except Exception:
            pass

    except Exception as e:
        print(f"Error fetching suppliers: {str(e)}")
        suppliers = []
        flash('An error occurred while loading suppliers', 'error')
    return render_template('suppliers.html', active='suppliers', suppliers=suppliers, stats=stats)


@app.route('/reports')
@login_required
def reports():
    try:
        if db is None:
            raise RuntimeError('Firestore client is not initialized')
        # Prefer created_at if present; fall back to date
        try:
            reports_ref = db.collection('reports').order_by('created_at', direction='DESCENDING').limit(10).stream()
        except Exception:
            reports_ref = db.collection('reports').order_by('date', direction='DESCENDING').limit(10).stream()
        reports = [{'id': report.id, **report.to_dict()} for report in reports_ref]
    except Exception as e:
        print(f"Error fetching reports: {str(e)}")
        reports = []
        flash('حدث خطأ أثناء تحميل التقارير', 'error')
    return render_template('reports.html', active='reports', reports=reports)

@app.route('/reports/create', methods=['GET', 'POST'])
@login_required
def reports_create():
    try:
        if db is None:
            raise RuntimeError('Firestore client is not initialized')
            
        if request.method == 'POST':
            # Handle form submission
            title = request.form.get('title', 'Untitled Report')
            report_type = request.form.get('report_type', 'custom')
            selected_medicines = request.form.getlist('selected_medicines')
            report_content = request.form.get('report_content', '')
            include_stock = 'include_stock' in request.form
            include_pricing = 'include_pricing' in request.form
            export_format = request.form.get('export_format', 'pdf')
            
            # Get medicine details for the report
            medicines_data = []
            for med_id in selected_medicines:
                med_doc = db.collection('medicines').document(med_id).get()
                if med_doc.exists:
                    med_data = med_doc.to_dict()
                    medicines_data.append({
                        'id': med_id,
                        'name': med_data.get('name', 'Unnamed Medicine'),
                        'stock': med_data.get('stock', 0),
                        'price': med_data.get('price', 0),
                        'category': med_data.get('category', 'Uncategorized')
                    })
            
            # Create report document
            report_data = {
                'title': title,
                'type': report_type,
                'content': report_content,
                'medicines': medicines_data,
                'include_stock': include_stock,
                'include_pricing': include_pricing,
                'export_format': export_format,
                'status': 'draft',
                'created_at': firestore.SERVER_TIMESTAMP,
                'created_by': session.get('user_id'),
                'updated_at': firestore.SERVER_TIMESTAMP
            }
            
            # Add report to Firestore
            db.collection('reports').add(report_data)
            flash(_('report_created_success'), 'success')
            return redirect(url_for('reports'))
            
        else:
            # GET request - show the form
            # Fetch all medicines for the selection modal
            medicines_ref = db.collection('medicines')\
                            .where('stock', '>', 0)\
                            .order_by('name')\
                            .stream()
            
            medicines = []
            for med in medicines_ref:
                med_data = med.to_dict()
                med_data['id'] = med.id
                medicines.append(med_data)
                
            return render_template('create_report.html', 
                                 medicines=medicines,
                                 active='reports')
            
    except Exception as e:
        print(f"Error in create_report: {str(e)}")
        flash(_('error_creating_report'), 'error')
        return redirect(url_for('reports'))


@app.route('/contact')
@login_required
def contact():
    """Render the contact page with contact information and form."""
    return render_template('contact.html', active='contact')


if __name__ == '__main__':
    app.run(debug=True)

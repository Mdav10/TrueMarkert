from flask import Flask, render_template, request, redirect, url_for, flash, session, jsonify
from datetime import datetime, timedelta
import os
from functools import wraps
import hashlib
import psycopg2
from psycopg2.extras import RealDictCursor
from werkzeug.utils import secure_filename
import uuid
import sys

print(f"Python version: {sys.version}")

app = Flask(__name__)
app.secret_key = 'your-super-secret-key-2024'
app.config['UPLOAD_FOLDER_PRODUCTS'] = 'static/uploads/products'
app.config['UPLOAD_FOLDER_PROFILES'] = 'static/uploads/profiles'
app.config['UPLOAD_FOLDER_PROOFS'] = 'static/uploads/proofs'
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024

ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp'}

for folder in [app.config['UPLOAD_FOLDER_PRODUCTS'], app.config['UPLOAD_FOLDER_PROFILES'], app.config['UPLOAD_FOLDER_PROOFS']]:
    os.makedirs(folder, exist_ok=True)

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

DATABASE_URL = os.environ.get('DATABASE_URL', 'postgresql://mymarket_8q19_user:Hs2KnIFTlDPiz1vWfrPnLQ2dZUwhfN7B@dpg-d8i4gfmq1p3s73ebd8a0-a/mymarket_8q19')

def get_db():
    try:
        return psycopg2.connect(DATABASE_URL)
    except Exception as e:
        print(f"Database connection error: {e}")
        return None

def init_db():
    conn = get_db()
    if not conn:
        print("Failed to connect to database")
        return
    
    c = conn.cursor()
    
    # Sellers table
    c.execute('''
        CREATE TABLE IF NOT EXISTS sellers (
            id SERIAL PRIMARY KEY,
            business_name VARCHAR(255) NOT NULL,
            owner_name VARCHAR(255) NOT NULL,
            email VARCHAR(255) UNIQUE NOT NULL,
            phone VARCHAR(50) NOT NULL,
            whatsapp VARCHAR(50) NOT NULL,
            password VARCHAR(255) NOT NULL,
            profile_pic VARCHAR(500),
            trial_start DATE NOT NULL,
            trial_end DATE NOT NULL,
            subscription_end DATE,
            is_paid BOOLEAN DEFAULT FALSE,
            is_active BOOLEAN DEFAULT TRUE,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # Products table
    c.execute('''
        CREATE TABLE IF NOT EXISTS products (
            id SERIAL PRIMARY KEY,
            seller_id INTEGER REFERENCES sellers(id) ON DELETE CASCADE,
            product_name VARCHAR(255) NOT NULL,
            price DECIMAL(10,2) NOT NULL,
            description TEXT,
            location VARCHAR(255) NOT NULL,
            whatsapp VARCHAR(50) NOT NULL,
            image_url VARCHAR(500),
            category VARCHAR(100),
            views INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # Buyers table
    c.execute('''
        CREATE TABLE IF NOT EXISTS buyers (
            id SERIAL PRIMARY KEY,
            full_name VARCHAR(255) NOT NULL,
            email VARCHAR(255) UNIQUE NOT NULL,
            phone VARCHAR(50),
            password VARCHAR(255) NOT NULL,
            profile_pic VARCHAR(500),
            is_active BOOLEAN DEFAULT TRUE,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # Subscriptions table
    c.execute('''
        CREATE TABLE IF NOT EXISTS subscriptions (
            id SERIAL PRIMARY KEY,
            seller_id INTEGER REFERENCES sellers(id) ON DELETE CASCADE,
            plan_name VARCHAR(50) NOT NULL,
            amount DECIMAL(10,2) NOT NULL,
            months INTEGER NOT NULL,
            proof_image VARCHAR(500) NOT NULL,
            status VARCHAR(50) DEFAULT 'pending',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # Bank settings table
    c.execute('''
        CREATE TABLE IF NOT EXISTS bank_settings (
            id SERIAL PRIMARY KEY,
            bank_name VARCHAR(255) NOT NULL,
            account_name VARCHAR(255) NOT NULL,
            account_number VARCHAR(100) NOT NULL,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # Wishlist table
    c.execute('''
        CREATE TABLE IF NOT EXISTS wishlist (
            id SERIAL PRIMARY KEY,
            buyer_id INTEGER REFERENCES buyers(id) ON DELETE CASCADE,
            product_id INTEGER REFERENCES products(id) ON DELETE CASCADE,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(buyer_id, product_id)
        )
    ''')
    
    conn.commit()
    
    # Insert default bank settings
    c.execute("SELECT * FROM bank_settings")
    if not c.fetchone():
        c.execute("INSERT INTO bank_settings (bank_name, account_name, account_number) VALUES (%s, %s, %s)",
                  ('KCB Bank', 'TrueMarket Enterprise', '1234567890'))
        conn.commit()
    
    # Insert admin account
    c.execute("SELECT * FROM sellers WHERE email = 'admin@truemarket.com'")
    if not c.fetchone():
        admin_password = hashlib.sha256('Admin@2024'.encode()).hexdigest()
        c.execute('''
            INSERT INTO sellers (business_name, owner_name, email, phone, whatsapp, password, trial_start, trial_end, is_paid)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        ''', ('TrueMarket Admin', 'System Admin', 'admin@truemarket.com', '0000000000', '0000000000', 
              admin_password, datetime.now().date(), datetime.now().date() + timedelta(days=3650), True))
        conn.commit()
    
    conn.close()
    print("Database initialized successfully!")

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session:
            flash('Please login to continue', 'danger')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated

def seller_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if session.get('user_type') != 'seller':
            flash('Seller access required', 'danger')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated

def buyer_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if session.get('user_type') != 'buyer':
            flash('Buyer access required', 'danger')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated

def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if session.get('user_type') != 'admin':
            flash('Admin access required', 'danger')
            return redirect(url_for('admin_login'))
        return f(*args, **kwargs)
    return decorated

@app.route('/')
def index():
    conn = get_db()
    if not conn:
        return render_template('index.html', featured=[], categories=[])
    
    c = conn.cursor()
    today = datetime.now().date()
    
    c.execute('''
        SELECT p.*, s.business_name
        FROM products p
        JOIN sellers s ON p.seller_id = s.id
        WHERE s.is_active = TRUE AND (s.is_paid = TRUE OR s.trial_end >= %s)
        ORDER BY p.created_at DESC LIMIT 8
    ''', (today,))
    featured = c.fetchall()
    
    c.execute('''
        SELECT category, COUNT(*) as count
        FROM products p
        JOIN sellers s ON p.seller_id = s.id
        WHERE s.is_active = TRUE AND (s.is_paid = TRUE OR s.trial_end >= %s)
        GROUP BY category LIMIT 10
    ''', (today,))
    categories = c.fetchall()
    
    conn.close()
    return render_template('index.html', featured=featured, categories=categories)

@app.route('/products')
def products():
    search = request.args.get('search', '')
    category = request.args.get('category', '')
    min_price = request.args.get('min_price', '')
    max_price = request.args.get('max_price', '')
    location = request.args.get('location', '')
    
    conn = get_db()
    if not conn:
        return render_template('products.html', products=[], categories=[], search='', category='', min_price='', max_price='', location='')
    
    c = conn.cursor()
    today = datetime.now().date()
    
    query = '''
        SELECT p.*, s.business_name
        FROM products p
        JOIN sellers s ON p.seller_id = s.id
        WHERE s.is_active = TRUE AND (s.is_paid = TRUE OR s.trial_end >= %s)
    '''
    params = [today]
    
    if search:
        query += " AND (p.product_name ILIKE %s OR p.description ILIKE %s)"
        params.extend([f'%{search}%', f'%{search}%'])
    if category:
        query += " AND p.category = %s"
        params.append(category)
    if min_price:
        query += " AND p.price >= %s"
        params.append(float(min_price))
    if max_price:
        query += " AND p.price <= %s"
        params.append(float(max_price))
    if location:
        query += " AND p.location ILIKE %s"
        params.append(f'%{location}%')
    
    query += " ORDER BY p.created_at DESC"
    c.execute(query, params)
    products = c.fetchall()
    
    c.execute("SELECT DISTINCT category FROM products WHERE category IS NOT NULL")
    categories = [row[0] for row in c.fetchall()]
    
    conn.close()
    return render_template('products.html', products=products, categories=categories, 
                         search=search, category=category, min_price=min_price, 
                         max_price=max_price, location=location)

@app.route('/product/<int:product_id>')
def product_detail(product_id):
    conn = get_db()
    if not conn:
        flash('Database connection error', 'danger')
        return redirect(url_for('index'))
    
    c = conn.cursor()
    
    c.execute("UPDATE products SET views = views + 1 WHERE id = %s", (product_id,))
    conn.commit()
    
    c.execute('''
        SELECT p.*, s.business_name, s.profile_pic, s.whatsapp as seller_whatsapp
        FROM products p
        JOIN sellers s ON p.seller_id = s.id
        WHERE p.id = %s AND s.is_active = TRUE
    ''', (product_id,))
    product = c.fetchone()
    
    if not product:
        flash('Product not found', 'danger')
        return redirect(url_for('products'))
    
    conn.close()
    return render_template('product_detail.html', product=product)

@app.route('/register/seller', methods=['GET', 'POST'])
def register_seller():
    if request.method == 'POST':
        business_name = request.form['business_name']
        owner_name = request.form['owner_name']
        email = request.form['email']
        phone = request.form['phone']
        whatsapp = request.form['whatsapp']
        password = hashlib.sha256(request.form['password'].encode()).hexdigest()
        
        trial_start = datetime.now().date()
        trial_end = trial_start + timedelta(days=10)
        
        profile_pic = None
        if 'profile_pic' in request.files:
            file = request.files['profile_pic']
            if file and file.filename and allowed_file(file.filename):
                ext = file.filename.rsplit('.', 1)[1].lower()
                filename = f"seller_{uuid.uuid4().hex}.{ext}"
                file.save(os.path.join(app.config['UPLOAD_FOLDER_PROFILES'], filename))
                profile_pic = f"/static/uploads/profiles/{filename}"
        
        conn = get_db()
        if not conn:
            flash('Database connection error', 'danger')
            return redirect(url_for('register_seller'))
        
        c = conn.cursor()
        
        try:
            c.execute('''
                INSERT INTO sellers (business_name, owner_name, email, phone, whatsapp, password, profile_pic, trial_start, trial_end)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            ''', (business_name, owner_name, email, phone, whatsapp, password, profile_pic, trial_start, trial_end))
            conn.commit()
            flash('Registration successful! You have 10 days free trial.', 'success')
            return redirect(url_for('login'))
        except psycopg2.IntegrityError:
            flash('Email already registered', 'danger')
            conn.rollback()
        finally:
            conn.close()
    
    return render_template('register_seller.html')

@app.route('/register/buyer', methods=['GET', 'POST'])
def register_buyer():
    if request.method == 'POST':
        full_name = request.form['full_name']
        email = request.form['email']
        phone = request.form.get('phone', '')
        password = hashlib.sha256(request.form['password'].encode()).hexdigest()
        
        profile_pic = None
        if 'profile_pic' in request.files:
            file = request.files['profile_pic']
            if file and file.filename and allowed_file(file.filename):
                ext = file.filename.rsplit('.', 1)[1].lower()
                filename = f"buyer_{uuid.uuid4().hex}.{ext}"
                file.save(os.path.join(app.config['UPLOAD_FOLDER_PROFILES'], filename))
                profile_pic = f"/static/uploads/profiles/{filename}"
        
        conn = get_db()
        if not conn:
            flash('Database connection error', 'danger')
            return redirect(url_for('register_buyer'))
        
        c = conn.cursor()
        
        try:
            c.execute('''
                INSERT INTO buyers (full_name, email, phone, password, profile_pic)
                VALUES (%s, %s, %s, %s, %s)
            ''', (full_name, email, phone, password, profile_pic))
            conn.commit()
            flash('Registration successful! Please login.', 'success')
            return redirect(url_for('login'))
        except psycopg2.IntegrityError:
            flash('Email already registered', 'danger')
            conn.rollback()
        finally:
            conn.close()
    
    return render_template('register_buyer.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form['email']
        password = hashlib.sha256(request.form['password'].encode()).hexdigest()
        user_type = request.form['user_type']
        
        conn = get_db()
        if not conn:
            flash('Database connection error', 'danger')
            return redirect(url_for('login'))
        
        c = conn.cursor()
        
        if user_type == 'seller':
            c.execute("SELECT id, business_name, email, is_active FROM sellers WHERE email = %s AND password = %s", (email, password))
            user = c.fetchone()
            if user and user[3]:
                session['user_id'] = user[0]
                session['user_type'] = 'seller'
                session['user_name'] = user[1]
                flash(f'Welcome {user[1]}!', 'success')
                conn.close()
                return redirect(url_for('seller_dashboard'))
            else:
                flash('Invalid email or password', 'danger')
        
        elif user_type == 'buyer':
            c.execute("SELECT id, full_name, email, is_active FROM buyers WHERE email = %s AND password = %s", (email, password))
            user = c.fetchone()
            if user and user[3]:
                session['user_id'] = user[0]
                session['user_type'] = 'buyer'
                session['user_name'] = user[1]
                flash(f'Welcome {user[1]}!', 'success')
                conn.close()
                return redirect(url_for('buyer_dashboard'))
            else:
                flash('Invalid email or password', 'danger')
        
        conn.close()
    
    return render_template('login.html')

@app.route('/admin/login', methods=['GET', 'POST'])
def admin_login():
    if request.method == 'POST':
        email = request.form['email']
        password = hashlib.sha256(request.form['password'].encode()).hexdigest()
        
        conn = get_db()
        if not conn:
            flash('Database connection error', 'danger')
            return redirect(url_for('admin_login'))
        
        c = conn.cursor()
        c.execute("SELECT id FROM sellers WHERE email = %s AND password = %s AND email = 'admin@truemarket.com'", (email, password))
        user = c.fetchone()
        conn.close()
        
        if user:
            session['user_id'] = user[0]
            session['user_type'] = 'admin'
            session['user_name'] = 'Admin'
            flash('Welcome Admin!', 'success')
            return redirect(url_for('admin_dashboard'))
        else:
            flash('Invalid admin credentials', 'danger')
    
    return render_template('admin_login.html')

@app.route('/logout')
def logout():
    session.clear()
    flash('Logged out successfully', 'success')
    return redirect(url_for('index'))

@app.route('/seller/dashboard')
@seller_required
def seller_dashboard():
    conn = get_db()
    if not conn:
        flash('Database connection error', 'danger')
        return redirect(url_for('index'))
    
    c = conn.cursor()
    
    c.execute("SELECT * FROM sellers WHERE id = %s", (session['user_id'],))
    seller = c.fetchone()
    
    c.execute("SELECT COUNT(*) FROM products WHERE seller_id = %s", (session['user_id'],))
    products_count = c.fetchone()[0]
    
    c.execute("SELECT COALESCE(SUM(views), 0) FROM products WHERE seller_id = %s", (session['user_id'],))
    total_views = c.fetchone()[0]
    
    c.execute("SELECT * FROM products WHERE seller_id = %s ORDER BY created_at DESC LIMIT 5", (session['user_id'],))
    recent_products = c.fetchall()
    
    today = datetime.now().date()
    trial_end = seller[9]
    trial_days_left = (trial_end - today).days if trial_end >= today else 0
    is_on_trial = trial_days_left > 0 and not seller[11]
    is_subscribed = seller[11]
    
    c.execute("SELECT * FROM subscriptions WHERE seller_id = %s AND status = 'pending'", (session['user_id'],))
    pending_sub = c.fetchone()
    
    conn.close()
    
    return render_template('seller_dashboard.html', 
                         seller=seller, products_count=products_count, total_views=total_views,
                         recent_products=recent_products, trial_days_left=trial_days_left,
                         is_on_trial=is_on_trial, is_subscribed=is_subscribed, pending_sub=pending_sub)

@app.route('/seller/products')
@seller_required
def seller_products():
    conn = get_db()
    if not conn:
        flash('Database connection error', 'danger')
        return redirect(url_for('seller_dashboard'))
    
    c = conn.cursor()
    c.execute("SELECT * FROM products WHERE seller_id = %s ORDER BY created_at DESC", (session['user_id'],))
    products = c.fetchall()
    conn.close()
    return render_template('seller_products.html', products=products)

@app.route('/seller/product/add', methods=['GET', 'POST'])
@seller_required
def seller_add_product():
    if request.method == 'POST':
        product_name = request.form['product_name']
        price = float(request.form['price'])
        description = request.form['description']
        location = request.form['location']
        whatsapp = request.form['whatsapp']
        category = request.form.get('category', 'Other')
        
        image_url = None
        if 'product_image' in request.files:
            file = request.files['product_image']
            if file and file.filename and allowed_file(file.filename):
                ext = file.filename.rsplit('.', 1)[1].lower()
                filename = f"product_{uuid.uuid4().hex}.{ext}"
                file.save(os.path.join(app.config['UPLOAD_FOLDER_PRODUCTS'], filename))
                image_url = f"/static/uploads/products/{filename}"
        
        conn = get_db()
        if not conn:
            flash('Database connection error', 'danger')
            return redirect(url_for('seller_add_product'))
        
        c = conn.cursor()
        c.execute('''
            INSERT INTO products (seller_id, product_name, price, description, location, whatsapp, category, image_url)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        ''', (session['user_id'], product_name, price, description, location, whatsapp, category, image_url))
        conn.commit()
        conn.close()
        
        flash('Product added successfully!', 'success')
        return redirect(url_for('seller_products'))
    
    return render_template('seller_add_product.html')

@app.route('/seller/product/edit/<int:product_id>', methods=['GET', 'POST'])
@seller_required
def seller_edit_product(product_id):
    conn = get_db()
    if not conn:
        flash('Database connection error', 'danger')
        return redirect(url_for('seller_products'))
    
    c = conn.cursor()
    
    c.execute("SELECT * FROM products WHERE id = %s AND seller_id = %s", (product_id, session['user_id']))
    product = c.fetchone()
    
    if not product:
        flash('Product not found', 'danger')
        return redirect(url_for('seller_products'))
    
    if request.method == 'POST':
        product_name = request.form['product_name']
        price = float(request.form['price'])
        description = request.form['description']
        location = request.form['location']
        whatsapp = request.form['whatsapp']
        category = request.form.get('category', 'Other')
        
        image_url = product[7]
        if 'product_image' in request.files:
            file = request.files['product_image']
            if file and file.filename and allowed_file(file.filename):
                ext = file.filename.rsplit('.', 1)[1].lower()
                filename = f"product_{uuid.uuid4().hex}.{ext}"
                file.save(os.path.join(app.config['UPLOAD_FOLDER_PRODUCTS'], filename))
                image_url = f"/static/uploads/products/{filename}"
        
        c.execute('''
            UPDATE products SET product_name=%s, price=%s, description=%s, location=%s, whatsapp=%s, category=%s, image_url=%s
            WHERE id=%s
        ''', (product_name, price, description, location, whatsapp, category, image_url, product_id))
        conn.commit()
        flash('Product updated successfully!', 'success')
        return redirect(url_for('seller_products'))
    
    conn.close()
    return render_template('seller_edit_product.html', product=product)

@app.route('/seller/product/delete/<int:product_id>')
@seller_required
def seller_delete_product(product_id):
    conn = get_db()
    if not conn:
        flash('Database connection error', 'danger')
        return redirect(url_for('seller_products'))
    
    c = conn.cursor()
    c.execute("DELETE FROM products WHERE id = %s AND seller_id = %s", (product_id, session['user_id']))
    conn.commit()
    conn.close()
    flash('Product deleted', 'success')
    return redirect(url_for('seller_products'))

@app.route('/seller/profile/edit', methods=['GET', 'POST'])
@seller_required
def seller_edit_profile():
    conn = get_db()
    if not conn:
        flash('Database connection error', 'danger')
        return redirect(url_for('seller_dashboard'))
    
    c = conn.cursor()
    
    if request.method == 'POST':
        business_name = request.form['business_name']
        owner_name = request.form['owner_name']
        phone = request.form['phone']
        whatsapp = request.form['whatsapp']
        
        c.execute("UPDATE sellers SET business_name=%s, owner_name=%s, phone=%s, whatsapp=%s WHERE id=%s",
                 (business_name, owner_name, phone, whatsapp, session['user_id']))
        
        if 'profile_pic' in request.files:
            file = request.files['profile_pic']
            if file and file.filename and allowed_file(file.filename):
                ext = file.filename.rsplit('.', 1)[1].lower()
                filename = f"seller_{uuid.uuid4().hex}.{ext}"
                file.save(os.path.join(app.config['UPLOAD_FOLDER_PROFILES'], filename))
                c.execute("UPDATE sellers SET profile_pic=%s WHERE id=%s", (f"/static/uploads/profiles/{filename}", session['user_id']))
        
        conn.commit()
        flash('Profile updated successfully!', 'success')
        return redirect(url_for('seller_dashboard'))
    
    c.execute("SELECT * FROM sellers WHERE id = %s", (session['user_id'],))
    seller = c.fetchone()
    conn.close()
    return render_template('seller_edit_profile.html', seller=seller)

@app.route('/seller/subscribe', methods=['GET', 'POST'])
@seller_required
def seller_subscribe():
    conn = get_db()
    if not conn:
        flash('Database connection error', 'danger')
        return redirect(url_for('seller_dashboard'))
    
    c = conn.cursor()
    
    if request.method == 'POST':
        plan_name = request.form['plan_name']
        amount = float(request.form['amount'])
        months = int(request.form['months'])
        
        if 'proof_image' not in request.files:
            flash('Please upload payment proof', 'danger')
            return redirect(url_for('seller_subscribe'))
        
        file = request.files['proof_image']
        if not file or not file.filename:
            flash('Please select a file', 'danger')
            return redirect(url_for('seller_subscribe'))
        
        ext = file.filename.rsplit('.', 1)[1].lower()
        filename = f"proof_{uuid.uuid4().hex}.{ext}"
        file.save(os.path.join(app.config['UPLOAD_FOLDER_PROOFS'], filename))
        
        c.execute('''
            INSERT INTO subscriptions (seller_id, plan_name, amount, months, proof_image, status)
            VALUES (%s, %s, %s, %s, %s, 'pending')
        ''', (session['user_id'], plan_name, amount, months, filename))
        conn.commit()
        
        flash('Subscription request sent! Admin will review.', 'success')
        return redirect(url_for('seller_dashboard'))
    
    c.execute("SELECT * FROM bank_settings LIMIT 1")
    bank = c.fetchone()
    conn.close()
    
    plans = [
        {'name': 'Basic', 'months': 1, 'price': 10},
        {'name': 'Standard', 'months': 3, 'price': 25},
        {'name': 'Premium', 'months': 6, 'price': 45},
        {'name': 'Enterprise', 'months': 12, 'price': 80}
    ]
    
    return render_template('seller_subscribe.html', bank=bank, plans=plans)

@app.route('/buyer/dashboard')
@buyer_required
def buyer_dashboard():
    conn = get_db()
    if not conn:
        flash('Database connection error', 'danger')
        return redirect(url_for('index'))
    
    c = conn.cursor()
    today = datetime.now().date()
    
    c.execute("SELECT * FROM buyers WHERE id = %s", (session['user_id'],))
    buyer = c.fetchone()
    
    c.execute("SELECT COUNT(*) FROM wishlist WHERE buyer_id = %s", (session['user_id'],))
    wishlist_count = c.fetchone()[0]
    
    c.execute('''
        SELECT p.*, s.business_name
        FROM products p
        JOIN sellers s ON p.seller_id = s.id
        WHERE s.is_active = TRUE AND (s.is_paid = TRUE OR s.trial_end >= %s)
        ORDER BY p.created_at DESC LIMIT 6
    ''', (today,))
    recent_products = c.fetchall()
    
    conn.close()
    return render_template('buyer_dashboard.html', buyer=buyer, wishlist_count=wishlist_count, recent_products=recent_products)

@app.route('/buyer/wishlist')
@buyer_required
def buyer_wishlist():
    conn = get_db()
    if not conn:
        flash('Database connection error', 'danger')
        return redirect(url_for('buyer_dashboard'))
    
    c = conn.cursor()
    today = datetime.now().date()
    
    c.execute('''
        SELECT p.*, s.business_name
        FROM wishlist w
        JOIN products p ON w.product_id = p.id
        JOIN sellers s ON p.seller_id = s.id
        WHERE w.buyer_id = %s AND s.is_active = TRUE AND (s.is_paid = TRUE OR s.trial_end >= %s)
        ORDER BY w.created_at DESC
    ''', (session['user_id'], today))
    products = c.fetchall()
    
    conn.close()
    return render_template('buyer_wishlist.html', products=products)

@app.route('/buyer/wishlist/add/<int:product_id>')
@buyer_required
def add_to_wishlist(product_id):
    conn = get_db()
    if not conn:
        flash('Database connection error', 'danger')
        return redirect(request.referrer or url_for('products'))
    
    c = conn.cursor()
    try:
        c.execute("INSERT INTO wishlist (buyer_id, product_id) VALUES (%s, %s)", (session['user_id'], product_id))
        conn.commit()
        flash('Added to wishlist!', 'success')
    except:
        flash('Already in wishlist', 'warning')
    finally:
        conn.close()
    return redirect(request.referrer or url_for('products'))

@app.route('/buyer/wishlist/remove/<int:product_id>')
@buyer_required
def remove_from_wishlist(product_id):
    conn = get_db()
    if not conn:
        flash('Database connection error', 'danger')
        return redirect(url_for('buyer_wishlist'))
    
    c = conn.cursor()
    c.execute("DELETE FROM wishlist WHERE buyer_id = %s AND product_id = %s", (session['user_id'], product_id))
    conn.commit()
    conn.close()
    flash('Removed from wishlist', 'success')
    return redirect(url_for('buyer_wishlist'))

@app.route('/buyer/profile/edit', methods=['GET', 'POST'])
@buyer_required
def buyer_edit_profile():
    conn = get_db()
    if not conn:
        flash('Database connection error', 'danger')
        return redirect(url_for('buyer_dashboard'))
    
    c = conn.cursor()
    
    if request.method == 'POST':
        full_name = request.form['full_name']
        phone = request.form['phone']
        
        c.execute("UPDATE buyers SET full_name=%s, phone=%s WHERE id=%s", (full_name, phone, session['user_id']))
        
        if 'profile_pic' in request.files:
            file = request.files['profile_pic']
            if file and file.filename and allowed_file(file.filename):
                ext = file.filename.rsplit('.', 1)[1].lower()
                filename = f"buyer_{uuid.uuid4().hex}.{ext}"
                file.save(os.path.join(app.config['UPLOAD_FOLDER_PROFILES'], filename))
                c.execute("UPDATE buyers SET profile_pic=%s WHERE id=%s", (f"/static/uploads/profiles/{filename}", session['user_id']))
        
        conn.commit()
        flash('Profile updated successfully!', 'success')
        return redirect(url_for('buyer_dashboard'))
    
    c.execute("SELECT * FROM buyers WHERE id = %s", (session['user_id'],))
    buyer = c.fetchone()
    conn.close()
    return render_template('buyer_edit_profile.html', buyer=buyer)

@app.route('/admin/dashboard')
@admin_required
def admin_dashboard():
    conn = get_db()
    if not conn:
        flash('Database connection error', 'danger')
        return redirect(url_for('admin_login'))
    
    c = conn.cursor()
    
    c.execute("SELECT COUNT(*) FROM sellers WHERE email != 'admin@truemarket.com'")
    total_sellers = c.fetchone()[0]
    
    c.execute("SELECT COUNT(*) FROM buyers")
    total_buyers = c.fetchone()[0]
    
    c.execute("SELECT COUNT(*) FROM products")
    total_products = c.fetchone()[0]
    
    c.execute("SELECT COUNT(*) FROM subscriptions WHERE status = 'pending'")
    pending_subs = c.fetchone()[0]
    
    c.execute("SELECT * FROM sellers WHERE email != 'admin@truemarket.com' ORDER BY created_at DESC LIMIT 10")
    recent_sellers = c.fetchall()
    
    c.execute('''
        SELECT s.*, se.business_name 
        FROM subscriptions s
        JOIN sellers se ON s.seller_id = se.id
        WHERE s.status = 'pending'
        ORDER BY s.created_at DESC
    ''')
    pending_subscriptions = c.fetchall()
    
    stats = {'total_sellers': total_sellers, 'total_buyers': total_buyers, 
             'total_products': total_products, 'pending_subs': pending_subs}
    
    conn.close()
    return render_template('admin_dashboard.html', stats=stats, recent_sellers=recent_sellers, 
                         pending_subscriptions=pending_subscriptions)

@app.route('/admin/sellers')
@admin_required
def admin_sellers():
    conn = get_db()
    if not conn:
        flash('Database connection error', 'danger')
        return redirect(url_for('admin_dashboard'))
    
    c = conn.cursor()
    c.execute("SELECT * FROM sellers WHERE email != 'admin@truemarket.com' ORDER BY created_at DESC")
    sellers = c.fetchall()
    conn.close()
    return render_template('admin_sellers.html', sellers=sellers)

@app.route('/admin/buyers')
@admin_required
def admin_buyers():
    conn = get_db()
    if not conn:
        flash('Database connection error', 'danger')
        return redirect(url_for('admin_dashboard'))
    
    c = conn.cursor()
    c.execute("SELECT * FROM buyers ORDER BY created_at DESC")
    buyers = c.fetchall()
    conn.close()
    return render_template('admin_buyers.html', buyers=buyers)

@app.route('/admin/products')
@admin_required
def admin_products():
    conn = get_db()
    if not conn:
        flash('Database connection error', 'danger')
        return redirect(url_for('admin_dashboard'))
    
    c = conn.cursor()
    c.execute('''
        SELECT p.*, s.business_name 
        FROM products p
        JOIN sellers s ON p.seller_id = s.id
        ORDER BY p.created_at DESC
    ''')
    products = c.fetchall()
    conn.close()
    return render_template('admin_products.html', products=products)

@app.route('/admin/seller/toggle/<int:seller_id>')
@admin_required
def admin_toggle_seller(seller_id):
    conn = get_db()
    if not conn:
        flash('Database connection error', 'danger')
        return redirect(url_for('admin_sellers'))
    
    c = conn.cursor()
    c.execute("UPDATE sellers SET is_active = NOT is_active WHERE id = %s", (seller_id,))
    conn.commit()
    conn.close()
    flash('Seller status updated', 'success')
    return redirect(request.referrer or url_for('admin_sellers'))

@app.route('/admin/seller/delete/<int:seller_id>')
@admin_required
def admin_delete_seller(seller_id):
    conn = get_db()
    if not conn:
        flash('Database connection error', 'danger')
        return redirect(url_for('admin_sellers'))
    
    c = conn.cursor()
    c.execute("DELETE FROM sellers WHERE id = %s", (seller_id,))
    conn.commit()
    conn.close()
    flash('Seller deleted', 'success')
    return redirect(url_for('admin_sellers'))

@app.route('/admin/buyer/toggle/<int:buyer_id>')
@admin_required
def admin_toggle_buyer(buyer_id):
    conn = get_db()
    if not conn:
        flash('Database connection error', 'danger')
        return redirect(url_for('admin_buyers'))
    
    c = conn.cursor()
    c.execute("UPDATE buyers SET is_active = NOT is_active WHERE id = %s", (buyer_id,))
    conn.commit()
    conn.close()
    flash('Buyer status updated', 'success')
    return redirect(request.referrer or url_for('admin_buyers'))

@app.route('/admin/buyer/delete/<int:buyer_id>')
@admin_required
def admin_delete_buyer(buyer_id):
    conn = get_db()
    if not conn:
        flash('Database connection error', 'danger')
        return redirect(url_for('admin_buyers'))
    
    c = conn.cursor()
    c.execute("DELETE FROM buyers WHERE id = %s", (buyer_id,))
    conn.commit()
    conn.close()
    flash('Buyer deleted', 'success')
    return redirect(url_for('admin_buyers'))

@app.route('/admin/product/delete/<int:product_id>')
@admin_required
def admin_delete_product(product_id):
    conn = get_db()
    if not conn:
        flash('Database connection error', 'danger')
        return redirect(url_for('admin_products'))
    
    c = conn.cursor()
    c.execute("DELETE FROM products WHERE id = %s", (product_id,))
    conn.commit()
    conn.close()
    flash('Product deleted', 'success')
    return redirect(url_for('admin_products'))

@app.route('/admin/subscription/approve/<int:sub_id>')
@admin_required
def admin_approve_subscription(sub_id):
    conn = get_db()
    if not conn:
        flash('Database connection error', 'danger')
        return redirect(url_for('admin_dashboard'))
    
    c = conn.cursor()
    c.execute("SELECT seller_id, months FROM subscriptions WHERE id = %s", (sub_id,))
    sub = c.fetchone()
    if sub:
        seller_id, months = sub
        subscription_end = datetime.now().date() + timedelta(days=30 * months)
        c.execute("UPDATE sellers SET is_paid = TRUE, subscription_end = %s WHERE id = %s", (subscription_end, seller_id))
        c.execute("UPDATE subscriptions SET status = 'approved' WHERE id = %s", (sub_id,))
        conn.commit()
        flash('Subscription approved!', 'success')
    conn.close()
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/subscription/reject/<int:sub_id>')
@admin_required
def admin_reject_subscription(sub_id):
    conn = get_db()
    if not conn:
        flash('Database connection error', 'danger')
        return redirect(url_for('admin_dashboard'))
    
    c = conn.cursor()
    c.execute("UPDATE subscriptions SET status = 'rejected' WHERE id = %s", (sub_id,))
    conn.commit()
    conn.close()
    flash('Subscription rejected', 'warning')
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/bank/settings', methods=['GET', 'POST'])
@admin_required
def admin_bank_settings():
    conn = get_db()
    if not conn:
        flash('Database connection error', 'danger')
        return redirect(url_for('admin_dashboard'))
    
    c = conn.cursor()
    
    if request.method == 'POST':
        bank_name = request.form['bank_name']
        account_name = request.form['account_name']
        account_number = request.form['account_number']
        c.execute("UPDATE bank_settings SET bank_name=%s, account_name=%s, account_number=%s, updated_at=CURRENT_TIMESTAMP", 
                  (bank_name, account_name, account_number))
        conn.commit()
        flash('Bank settings updated!', 'success')
        return redirect(url_for('admin_bank_settings'))
    
    c.execute("SELECT * FROM bank_settings LIMIT 1")
    bank = c.fetchone()
    conn.close()
    return render_template('admin_bank_settings.html', bank=bank)

if __name__ == '__main__':
    init_db()
    app.run(debug=True, host='0.0.0.0', port=10000)

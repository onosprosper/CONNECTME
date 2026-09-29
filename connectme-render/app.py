import os
import re
import secrets
import json
import hmac
import hashlib
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError
from io import BytesIO
from datetime import datetime, timezone, timedelta
from functools import wraps
from urllib.parse import urlsplit, quote
from flask import Flask, abort, flash, redirect, render_template, request, session, url_for, send_file
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import UniqueConstraint, or_
from werkzeug.security import check_password_hash, generate_password_hash
from PIL import Image, UnidentifiedImageError

NIGERIA_LOCATIONS = {
    'Abia': ('Umuahia', 'Aba', 'Ohafia'),
    'Adamawa': ('Yola', 'Mubi', 'Numan'),
    'Akwa Ibom': ('Uyo', 'Eket', 'Ikot Ekpene'),
    'Anambra': ('Awka', 'Onitsha', 'Nnewi'),
    'Bauchi': ('Bauchi', 'Azare'),
    'Bayelsa': ('Yenagoa', 'Sagbama'),
    'Benue': ('Makurdi', 'Gboko', 'Otukpo'),
    'Borno': ('Maiduguri', 'Biu'),
    'Cross River': ('Calabar', 'Ikom', 'Ogoja'),
    'Delta': ('Asaba', 'Warri', 'Sapele', 'Ughelli'),
    'Ebonyi': ('Abakaliki', 'Afikpo'),
    'Edo': ('Benin City', 'Auchi', 'Ekpoma'),
    'Ekiti': ('Ado Ekiti', 'Ikere Ekiti'),
    'Enugu': ('Enugu', 'Nsukka', 'Agbani'),
    'FCT': ('Abuja', 'Gwagwalada', 'Kuje', 'Kubwa'),
    'Gombe': ('Gombe', 'Kaltungo'),
    'Imo': ('Owerri', 'Orlu', 'Okigwe'),
    'Jigawa': ('Dutse', 'Hadejia'),
    'Kaduna': ('Kaduna', 'Zaria', 'Kafanchan'),
    'Kano': ('Kano', 'Wudil'),
    'Katsina': ('Katsina', 'Funtua', 'Daura'),
    'Kebbi': ('Birnin Kebbi', 'Argungu', 'Yauri'),
    'Kogi': ('Lokoja', 'Okene', 'Idah'),
    'Kwara': ('Ilorin', 'Offa'),
    'Lagos': ('Lagos', 'Ikeja', 'Lekki', 'Ikorodu', 'Epe', 'Badagry'),
    'Nasarawa': ('Lafia', 'Keffi', 'Karu'),
    'Niger': ('Minna', 'Suleja', 'Bida', 'Kontagora'),
    'Ogun': ('Abeokuta', 'Ijebu Ode', 'Sagamu', 'Ota'),
    'Ondo': ('Akure', 'Ondo', 'Owo'),
    'Osun': ('Osogbo', 'Ile-Ife', 'Ilesa'),
    'Oyo': ('Ibadan', 'Ogbomoso', 'Oyo'),
    'Plateau': ('Jos', 'Bukuru', 'Pankshin'),
    'Rivers': ('Port Harcourt', 'Bonny', 'Ahoada', 'Omoku'),
    'Sokoto': ('Sokoto', 'Tambuwal'),
    'Taraba': ('Jalingo', 'Wukari'),
    'Yobe': ('Damaturu', 'Potiskum', 'Nguru'),
    'Zamfara': ('Gusau', 'Kaura Namoda'),
}

CATEGORIES = ('Food & cooking', 'Wellness', 'Home services', 'Skilled workers', 'Beauty', 'Care services', 'Tutors & skills', 'Transport & help', 'Experiences', 'Connect & community')
SERVICE_CHOICES = {
    'Food & cooking': [('🍲', 'Nigerian meals'), ('🎂', 'Baking & cakes'), ('🍽️', 'Event catering'), ('👩🏽‍🍳', 'Private chef'), ('🥘', 'Cooking lessons')],
    'Wellness': [('💆', 'Massage'), ('🧘', 'Fitness & yoga'), ('🌿', 'Spa & wellness')],
    'Home services': [('🧹', 'Cleaning'), ('🧺', 'Laundry'), ('🌱', 'Gardening'), ('🛠️', 'Home repairs')],
    'Skilled workers': [('⚡', 'Electrician'), ('🚰', 'Plumber'), ('🚗', 'Mechanic'), ('🎨', 'Painter'), ('🔌', 'Generator repair')],
    'Beauty': [('💄', 'Makeup'), ('💇', 'Hair styling'), ('🧶', 'Braids'), ('🪡', 'Wig installation'), ('💅', 'Nails'), ('✂️', 'Barber')],
    'Care services': [('👶', 'Babysitting'), ('🧓', 'Elderly care'), ('🏠', 'Domestic help')],
    'Tutors & skills': [('➗', 'Mathematics'), ('🔬', 'Science'), ('📖', 'English'), ('💻', 'Computer lessons'), ('🎹', 'Music'), ('🗣️', 'Languages')],
    'Transport & help': [('🚘', 'Driver'), ('📦', 'Moving help'), ('🛍️', 'Errands')],
    'Experiences': [('🗺️', 'City companion'), ('🥾', 'Hiking'), ('🎭', 'Events'), ('🍳', 'Cooking experience')],
    'Connect & community': [('🤝', 'Networking'), ('📷', 'Photography'), ('🎲', 'Games'), ('🏙️', 'City companion')],
}
app = Flask(__name__)
secret = os.getenv('SECRET_KEY')
if not secret and os.getenv('RENDER'):
    raise RuntimeError('Set SECRET_KEY in the Render environment before deploying.')
app.config['SECRET_KEY'] = secret or 'local-development-only-change-me'
url = os.getenv('DATABASE_URL', 'sqlite:///connectme.db')
if url.startswith('postgres://'):
    url = 'postgresql+psycopg://' + url[len('postgres://'):]
elif url.startswith('postgresql://'):
    url = 'postgresql+psycopg://' + url[len('postgresql://'):]
app.config['SQLALCHEMY_DATABASE_URI'] = url
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
app.config['SESSION_COOKIE_SECURE'] = bool(os.getenv('RENDER'))
app.config['MAX_CONTENT_LENGTH'] = 3 * 1024 * 1024
db = SQLAlchemy(app)


def now():
    return datetime.now(timezone.utc)

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(80), nullable=False)
    email = db.Column(db.String(255), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), default=now, nullable=False)
    photo = db.relationship('ProfilePhoto', uselist=False)
    profile = db.relationship('UserProfile', uselist=False)

class UserProfile(db.Model):
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), primary_key=True)
    date_of_birth = db.Column(db.Date)
    home_address = db.Column(db.String(255), nullable=False, default='')
    state = db.Column(db.String(80), nullable=False, default='')
    city = db.Column(db.String(80), nullable=False, default='')
    updated_at = db.Column(db.DateTime(timezone=True), default=now, nullable=False)

class AdminAccount(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(255), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    failed_logins = db.Column(db.Integer, nullable=False, default=0)
    locked_until = db.Column(db.DateTime(timezone=True))
    created_at = db.Column(db.DateTime(timezone=True), default=now, nullable=False)

class AdminAudit(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    admin_id = db.Column(db.Integer, db.ForeignKey('admin_account.id'), nullable=False)
    action = db.Column(db.String(80), nullable=False)
    target_id = db.Column(db.Integer, nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), default=now, nullable=False)

class Provider(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), unique=True, nullable=False)
    category = db.Column(db.String(80), nullable=False)
    service = db.Column(db.String(120), nullable=False)
    city = db.Column(db.String(80), nullable=False)
    area = db.Column(db.String(120), nullable=False)
    bio = db.Column(db.String(800), nullable=False, default='')
    price = db.Column(db.Integer, nullable=False)
    # A profile photo is not identity verification.
    phone_verified = db.Column(db.Boolean, nullable=False, default=False)
    identity_verified = db.Column(db.Boolean, nullable=False, default=False)
    user = db.relationship('User')

class JobRequest(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    customer_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    category = db.Column(db.String(80), nullable=False)
    title = db.Column(db.String(140), nullable=False)
    city = db.Column(db.String(80), nullable=False)
    area = db.Column(db.String(120), nullable=False)
    date_needed = db.Column(db.Date, nullable=False)
    budget = db.Column(db.Integer, nullable=False)
    details = db.Column(db.String(1200), nullable=False, default='')
    status = db.Column(db.String(20), nullable=False, default='open')
    created_at = db.Column(db.DateTime(timezone=True), default=now, nullable=False)
    customer = db.relationship('User')
    photo_display = db.relationship('RequestPhotoDisplay', uselist=False)
    offers = db.relationship('Offer', back_populates='job', order_by='Offer.created_at.desc()')

class RequestPhotoDisplay(db.Model):
    job_id = db.Column(db.Integer, db.ForeignKey('job_request.id'), primary_key=True)
    show_photo = db.Column(db.Boolean, nullable=False, default=False)

class Offer(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    job_id = db.Column(db.Integer, db.ForeignKey('job_request.id'), nullable=False)
    provider_id = db.Column(db.Integer, db.ForeignKey('provider.id'), nullable=False)
    amount = db.Column(db.Integer, nullable=False)
    message = db.Column(db.String(600), nullable=False)
    status = db.Column(db.String(20), nullable=False, default='pending')
    created_at = db.Column(db.DateTime(timezone=True), default=now, nullable=False)
    job = db.relationship('JobRequest', back_populates='offers')
    provider = db.relationship('Provider')
    __table_args__ = (UniqueConstraint('job_id', 'provider_id', name='uq_job_provider'),)

class ProfilePhoto(db.Model):
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), primary_key=True)
    image = db.Column(db.LargeBinary, nullable=False)
    updated_at = db.Column(db.DateTime(timezone=True), default=now, nullable=False)

class VerificationRecord(db.Model):
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), primary_key=True)
    phone = db.Column(db.String(25), nullable=False, default='')
    phone_verified = db.Column(db.Boolean, nullable=False, default=False)
    identity_verified = db.Column(db.Boolean, nullable=False, default=False)
    updated_at = db.Column(db.DateTime(timezone=True), default=now, nullable=False)

class PhoneChallenge(db.Model):
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), primary_key=True)
    phone = db.Column(db.String(25), nullable=False)
    pin_id = db.Column(db.String(120), nullable=False)
    expires_at = db.Column(db.DateTime(timezone=True), nullable=False)
    last_sent_at = db.Column(db.DateTime(timezone=True), nullable=False)
    attempts = db.Column(db.Integer, nullable=False, default=0)

class PhoneCallChallenge(db.Model):
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), primary_key=True)
    phone = db.Column(db.String(25), nullable=False)
    code_hash = db.Column(db.String(255), nullable=False)
    status = db.Column(db.String(20), nullable=False, default='pending')
    attempts = db.Column(db.Integer, nullable=False, default=0)
    created_at = db.Column(db.DateTime(timezone=True), default=now, nullable=False)
    expires_at = db.Column(db.DateTime(timezone=True), nullable=False)
    reviewed_at = db.Column(db.DateTime(timezone=True))
    user = db.relationship('User')

class ProviderReview(db.Model):
    provider_id = db.Column(db.Integer, db.ForeignKey('provider.id'), primary_key=True)
    status = db.Column(db.String(20), nullable=False, default='pending')
    reviewed_at = db.Column(db.DateTime(timezone=True))
    reviewer_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    provider = db.relationship('Provider', backref=db.backref('review', uselist=False))

class SafetyReport(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    reporter_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    provider_id = db.Column(db.Integer, db.ForeignKey('provider.id'), nullable=False)
    job_id = db.Column(db.Integer, db.ForeignKey('job_request.id'))
    reason = db.Column(db.String(40), nullable=False)
    details = db.Column(db.String(1200), nullable=False)
    status = db.Column(db.String(20), nullable=False, default='open')
    created_at = db.Column(db.DateTime(timezone=True), default=now, nullable=False)
    reviewed_at = db.Column(db.DateTime(timezone=True))
    reviewer_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    provider = db.relationship('Provider')
    reporter = db.relationship('User', foreign_keys=[reporter_id])

class SubscriptionInterest(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    role = db.Column(db.String(12), nullable=False)
    monthly_ngn = db.Column(db.Integer, nullable=False)
    status = db.Column(db.String(24), nullable=False, default='pending_payment')
    created_at = db.Column(db.DateTime(timezone=True), default=now, nullable=False)
    __table_args__ = (UniqueConstraint('user_id', 'role', name='uq_subscription_interest'),)

class PlanPayment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    reference = db.Column(db.String(90), unique=True, nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    role = db.Column(db.String(12), nullable=False)
    amount_ngn = db.Column(db.Integer, nullable=False)
    email = db.Column(db.String(255), nullable=False)
    status = db.Column(db.String(16), nullable=False, default='pending')
    created_at = db.Column(db.DateTime(timezone=True), default=now, nullable=False)
    paid_at = db.Column(db.DateTime(timezone=True))
    expires_at = db.Column(db.DateTime(timezone=True))

class BankTransferPayment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    reference = db.Column(db.String(90), unique=True, nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    role = db.Column(db.String(12), nullable=False)
    amount_ngn = db.Column(db.Integer, nullable=False)
    status = db.Column(db.String(24), nullable=False, default='awaiting_transfer')
    payer_name = db.Column(db.String(120), nullable=False, default='')
    bank_reference = db.Column(db.String(120), nullable=False, default='')
    created_at = db.Column(db.DateTime(timezone=True), default=now, nullable=False)
    submitted_at = db.Column(db.DateTime(timezone=True))
    reviewed_at = db.Column(db.DateTime(timezone=True))
    reviewer_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    expires_at = db.Column(db.DateTime(timezone=True))
    user = db.relationship('User', foreign_keys=[user_id])

PLAN_PRICES = {'customer': 'CUSTOMER_MONTHLY_NGN', 'provider': 'PROVIDER_MONTHLY_NGN'}

def plan_prices():
    return {role: max(100, int(os.getenv(env, default))) for role, env, default in
            [('customer', PLAN_PRICES['customer'], '1000'), ('provider', PLAN_PRICES['provider'], '3000')]}

def paystack_api(path, method='GET', payload=None):
    key = os.getenv('PAYSTACK_SECRET_KEY', '')
    if not key.startswith(('sk_test_', 'sk_live_')): raise ValueError('Paystack is not configured.')
    data = json.dumps(payload).encode() if payload is not None else None
    req = Request('https://api.paystack.co/' + path, data=data, method=method,
                  headers={'Authorization': 'Bearer ' + key, 'Content-Type': 'application/json'})
    with urlopen(req, timeout=10) as response:
        result = json.load(response)
    if not result.get('status'): raise ValueError('Payment service rejected the request.')
    return result['data']

def latest_paid_plan(user_id, role, active_only=False):
    entries = []
    for model, paid_status in ((PlanPayment, 'paid'), (BankTransferPayment, 'approved')):
        query = model.query.filter(model.user_id == user_id, model.role == role, model.status == paid_status)
        if active_only: query = query.filter(model.expires_at > now())
        entry = query.order_by(model.expires_at.desc()).first()
        if entry: entries.append(entry)
    return max(entries, key=lambda entry: utc(entry.expires_at)) if entries else None

def active_plan(user_id, role):
    return latest_paid_plan(user_id, role, active_only=True)

def require_plan(role):
    if os.getenv('REQUIRE_SUBSCRIPTION') == '1' and not active_plan(session['user_id'], role):
        flash('Choose a ' + role + ' plan to continue.', 'info')
        return redirect(url_for('subscriptions'))

def confirm_payment(payment):
    if payment.status == 'paid': return True
    data = paystack_api('transaction/verify/' + quote(payment.reference, safe=''))
    customer = data.get('customer') or {}
    if (data.get('status') != 'success' or data.get('reference') != payment.reference or
        data.get('currency') != 'NGN' or data.get('amount') != payment.amount_ngn * 100 or
        (customer.get('email') or '').casefold() != payment.email.casefold()):
        return False
    latest = latest_paid_plan(payment.user_id, payment.role)
    base = max(now(), utc(latest.expires_at) if latest else now())
    payment.status, payment.paid_at, payment.expires_at = 'paid', now(), base + timedelta(days=30)
    db.session.commit()
    return True

@app.context_processor
def shared():
    return {'categories': CATEGORIES, 'service_choices': SERVICE_CHOICES, 'current_user': db.session.get(User, session['user_id']) if 'user_id' in session else None, 'current_admin': db.session.get(AdminAccount, session['admin_id']) if 'admin_id' in session else None, 'csrf_token': csrf_token}

def csrf_token():
    if 'csrf' not in session:
        session['csrf'] = secrets.token_urlsafe(32)
    return session['csrf']

@app.before_request
def protect_post():
    if request.path == '/payments/paystack/webhook': return
    if request.method in ('POST', 'PUT', 'PATCH', 'DELETE') and not secrets.compare_digest(request.form.get('csrf_token', ''), session.get('csrf', '')):
        abort(400, 'Invalid form token. Refresh the page and try again.')

def login_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if 'user_id' not in session:
            flash('Sign in to continue.', 'info')
            return redirect(url_for('login', next=request.path))
        return fn(*args, **kwargs)
    return wrapper

def field(key, max_len, required=True):
    value = request.form.get(key, '').strip()
    if (required and not value) or len(value) > max_len:
        raise ValueError(f'Check {key.replace("_", " ")}.')
    return value

def amount(key):
    try:
        value = int(request.form.get(key, ''))
        if 0 <= value <= 100_000_000:
            return value
    except ValueError:
        pass
    raise ValueError(f'Enter a valid {key}.')

def safe_next(value):
    parts = urlsplit(value or '')
    return value if value and value.startswith('/') and not value.startswith('//') and not parts.netloc else url_for('home')

@app.get('/')
def home():
    q = request.args.get('q', '').strip()[:100]
    city = request.args.get('city', '').strip()[:80]
    category = request.args.get('category', '').strip()[:80]
    service = request.args.get('service', '').strip()[:120]
    if category not in CATEGORIES:
        category = ''
    if service and (not category or service not in [name for _, name in SERVICE_CHOICES[category]]):
        service = ''
    query = Provider.query.outerjoin(ProviderReview, ProviderReview.provider_id == Provider.id).filter(or_(ProviderReview.status.is_(None), ProviderReview.status != 'suspended'))
    if q:
        query = query.filter(or_(Provider.service.ilike(f'%{q}%'), Provider.bio.ilike(f'%{q}%'), Provider.area.ilike(f'%{q}%')))
    if city:
        query = query.filter(Provider.city.ilike(f'%{city}%'))
    if category:
        query = query.filter(Provider.category == category)
    if service:
        query = query.filter(or_(Provider.service.ilike(f'%{service}%'), Provider.bio.ilike(f'%{service}%')))
    providers = query.order_by(Provider.id.desc()).limit(60).all()
    return render_template('home.html', providers=providers, q=q, city=city, category=category, service=service)

@app.route('/signup', methods=['GET', 'POST'])
def signup():
    if request.method == 'POST':
        try:
            name, email, password = field('name', 80), field('email', 255).lower(), request.form.get('password', '')
            if '@' not in email or len(password) < 10:
                raise ValueError('Use a valid email and a password with at least 10 characters.')
            if User.query.filter_by(email=email).first():
                raise ValueError('This email is already registered.')
            user = User(name=name, email=email, password_hash=generate_password_hash(password))
            db.session.add(user); db.session.commit()
            session.clear(); session['user_id'] = user.id
            flash('Welcome to ConnectMe.', 'success')
            return redirect(url_for('home'))
        except ValueError as exc:
            flash(str(exc), 'error')
    return render_template('auth.html', mode='signup')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        user = User.query.filter_by(email=request.form.get('email', '').strip().lower()).first()
        if not user or not check_password_hash(user.password_hash, request.form.get('password', '')):
            flash('Email or password is incorrect.', 'error')
        else:
            target = safe_next(request.form.get('next', ''))
            session.clear(); session['user_id'] = user.id
            return redirect(target)
    return render_template('auth.html', mode='login')

@app.post('/logout')
@login_required
def logout():
    session.clear()
    return redirect(url_for('home'))

@app.route('/request', methods=['GET', 'POST'])
@login_required
def create_request():
    if request.method == 'POST':
        blocked = require_plan('customer')
        if blocked: return blocked
        try:
            category = field('category', 80)
            if category not in CATEGORIES: raise ValueError('Choose a category.')
            date_needed = datetime.strptime(field('date_needed', 10), '%Y-%m-%d').date()
            if date_needed < now().date(): raise ValueError('Choose a current or future date.')
            job = JobRequest(customer_id=session['user_id'], category=category, title=field('title', 140), city=field('city', 80), area=field('area', 120), date_needed=date_needed, budget=amount('budget'), details=field('details', 1200, False))
            db.session.add(job); db.session.flush()
            db.session.add(RequestPhotoDisplay(job_id=job.id, show_photo=request.form.get('show_photo') == 'yes'))
            db.session.commit()
            flash('Your request is live.', 'success')
            return redirect(url_for('job_detail', job_id=job.id))
        except ValueError as exc: flash(str(exc), 'error')
    return render_template('request_form.html')

@app.route('/provide', methods=['GET', 'POST'])
@login_required
def provide():
    provider = Provider.query.filter_by(user_id=session['user_id']).first()
    if request.method == 'POST':
        try:
            category = field('category', 80)
            if category not in CATEGORIES: raise ValueError('Choose a category.')
            if not provider: provider = Provider(user_id=session['user_id'])
            provider.category, provider.service = category, field('service', 120)
            provider.city, provider.area = field('city', 80), field('area', 120)
            provider.bio, provider.price = field('bio', 800, False), amount('price')
            phone_record = db.session.get(VerificationRecord, session['user_id'])
            provider.phone_verified = bool(phone_record and phone_record.phone_verified)
            db.session.add(provider); db.session.flush()
            review = db.session.get(ProviderReview, provider.id)
            if not review: db.session.add(ProviderReview(provider_id=provider.id))
            elif review.status in ('approved', 'rejected'):
                review.status = 'pending'; review.reviewed_at = None; review.reviewer_id = None
            db.session.commit()
            flash('Your profile is saved. It is awaiting review.', 'success')
            return redirect(url_for('provider_detail', provider_id=provider.id))
        except ValueError as exc: flash(str(exc), 'error')
    return render_template('provider_form.html', provider=provider)

@app.get('/providers/<int:provider_id>')
def provider_detail(provider_id):
    provider = db.get_or_404(Provider, provider_id)
    if provider.review and provider.review.status == 'suspended' and session.get('user_id') != provider.user_id and not session.get('admin_id'): abort(404)
    return render_template('provider_detail.html', provider=provider)

@app.get('/requests')
def requests_list():
    jobs = JobRequest.query.filter_by(status='open').order_by(JobRequest.created_at.desc()).limit(100).all()
    return render_template('requests.html', jobs=jobs)

@app.get('/requests/<int:job_id>')
def job_detail(job_id):
    job = db.get_or_404(JobRequest, job_id)
    owner = session.get('user_id') == job.customer_id
    if job.status != 'open' and not owner and not any(o.provider.user_id == session.get('user_id') and o.status == 'accepted' for o in job.offers):
        abort(404)
    provider = Provider.query.filter_by(user_id=session.get('user_id')).first() if session.get('user_id') else None
    my_offer = next((o for o in job.offers if provider and o.provider_id == provider.id), None)
    return render_template('job_detail.html', job=job, owner=owner, provider=provider, my_offer=my_offer)

@app.post('/requests/<int:job_id>/offer')
@login_required
def submit_offer(job_id):
    blocked = require_plan('provider')
    if blocked: return blocked
    job = db.get_or_404(JobRequest, job_id)
    provider = Provider.query.filter_by(user_id=session['user_id']).first()
    if not provider or job.customer_id == session['user_id'] or job.status != 'open' or (provider.review and provider.review.status == 'suspended'): abort(403)
    if job.category in ('Care services', 'Transport & help', 'Experiences', 'Connect & community') and (not provider.review or provider.review.status != 'approved'):
        flash('This category requires a reviewed provider profile before sending offers.', 'error')
        return redirect(url_for('job_detail', job_id=job_id))
    if Offer.query.filter_by(job_id=job.id, provider_id=provider.id).first(): abort(409)
    try:
        offer = Offer(job_id=job.id, provider_id=provider.id, amount=amount('amount'), message=field('message', 600))
        db.session.add(offer); db.session.commit()
        flash('Offer sent.', 'success')
    except ValueError as exc: flash(str(exc), 'error')
    return redirect(url_for('job_detail', job_id=job_id))

@app.post('/offers/<int:offer_id>/accept')
@login_required
def accept_offer(offer_id):
    offer = db.get_or_404(Offer, offer_id)
    job = JobRequest.query.filter_by(id=offer.job_id, customer_id=session['user_id'], status='open').first_or_404()
    if offer.status != 'pending': abort(409)
    if offer.provider.review and offer.provider.review.status == 'suspended': abort(403)
    job.status = 'booked'
    for other in job.offers: other.status = 'accepted' if other.id == offer.id else 'declined'
    db.session.commit()
    flash('Booking confirmed. The agreed price is saved.', 'success')
    return redirect(url_for('dashboard'))

@app.route('/profile', methods=['GET', 'POST'])
@login_required
def my_profile():
    user = db.session.get(User, session['user_id'])
    profile = db.session.get(UserProfile, user.id)
    if request.method == 'POST':
        try:
            name = field('name', 80)
            address = field('home_address', 255, False)
            state = field('state', 80, False)
            selected_city = field('city', 80, False)
            city = field('other_city', 80) if selected_city == '__other__' else selected_city
            if state:
                if state not in NIGERIA_LOCATIONS or not city:
                    raise ValueError('Select a state and city or town.')
                if selected_city != '__other__' and city not in NIGERIA_LOCATIONS[state]:
                    raise ValueError('Choose a city for the selected state.')
            elif city:
                raise ValueError('Select a state for your city.')
            if any(ord(ch) < 32 for ch in name + address + state + city):
                raise ValueError('Remove control characters from your profile.')
            raw_dob = request.form.get('date_of_birth', '').strip()
            dob = datetime.strptime(raw_dob, '%Y-%m-%d').date() if raw_dob else None
            if dob and not (datetime(1900, 1, 1).date() <= dob <= now().date()):
                raise ValueError('Enter a valid date of birth.')
            if not profile: profile = UserProfile(user_id=user.id)
            user.name = name
            profile.date_of_birth, profile.home_address = dob, address
            profile.state, profile.city, profile.updated_at = state, city, now()
            db.session.add(profile); db.session.commit()
            flash('Your profile was updated.', 'success')
            return redirect(url_for('my_profile'))
        except ValueError as exc:
            flash('Check your profile details. ' + str(exc), 'error')
    return render_template('my_profile.html', user=user, profile=profile, today=now().date().isoformat(), locations=NIGERIA_LOCATIONS)

@app.get('/dashboard')
@login_required
def dashboard():
    jobs = JobRequest.query.filter_by(customer_id=session['user_id']).order_by(JobRequest.created_at.desc()).all()
    provider = Provider.query.filter_by(user_id=session['user_id']).first()
    sent = Offer.query.filter_by(provider_id=provider.id).order_by(Offer.created_at.desc()).all() if provider else []
    return render_template('dashboard.html', jobs=jobs, provider=provider, sent=sent)

def utc(value):
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value

def normalize_phone(value):
    digits = re.sub(r'[^0-9]', '', value)
    if len(digits) == 11 and digits.startswith('0'): digits = '234' + digits[1:]
    if len(digits) == 13 and digits.startswith('234') and digits[3] in '789': return digits
    return None

def otp_configured():
    return bool(os.getenv('TERMII_API_KEY') and os.getenv('TERMII_SENDER_ID') and termii_base_url())

def termii_base_url():
    value = os.getenv('TERMII_BASE_URL', '').rstrip('/')
    parts = urlsplit(value)
    host = (parts.hostname or '').lower()
    return value if (parts.scheme == 'https' and (host == 'termii.com' or host.endswith('.termii.com')) and not parts.username and not parts.password and not parts.port and not parts.path and not parts.query and not parts.fragment) else None

def termii_request(action, data):
    # Only Termii HTTPS hosts are allowed; keys stay on the server.
    base = termii_base_url()
    if not base: raise ValueError('Termii base URL is not configured')
    payload = json.dumps({'api_key': os.environ['TERMII_API_KEY'], **data}).encode()
    req = Request(f'{base}/api/sms/otp/{action}', data=payload, headers={'Content-Type': 'application/json'}, method='POST')
    try:
        with urlopen(req, timeout=8) as response:
            return json.load(response)
    except HTTPError as exc:
        raise ValueError('OTP provider rejected the request') from exc

def review_admin_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        account = db.session.get(AdminAccount, session['admin_id']) if session.get('admin_id') else None
        if not account or not account.is_active:
            session.pop('admin_id', None)
            return redirect(url_for('admin_login'))
        return fn(*args, **kwargs)
    return wrapper

@app.route('/admin/login', methods=['GET', 'POST'])
def admin_login():
    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()[:255]
        password = request.form.get('password', '')
        account = AdminAccount.query.filter_by(email=email, is_active=True).first()
        locked = account and account.locked_until and utc(account.locked_until) > now()
        if account and not locked and check_password_hash(account.password_hash, password):
            account.failed_logins = 0; account.locked_until = None
            db.session.commit()
            session.clear(); session['admin_id'] = account.id
            return redirect(url_for('review_queue'))
        if account and not locked:
            account.failed_logins += 1
            if account.failed_logins >= 5:
                account.locked_until = now() + timedelta(minutes=15)
                account.failed_logins = 0
            db.session.commit()
        flash('Invalid credentials or account temporarily locked. Try again later.', 'error')
    return render_template('admin_login.html')

@app.post('/admin/logout')
@review_admin_required
def admin_logout():
    session.clear()
    return redirect(url_for('admin_login'))

@app.route('/admin/password', methods=['GET', 'POST'])
@review_admin_required
def admin_password():
    if request.method == 'POST':
        account = db.session.get(AdminAccount, session['admin_id'])
        old = request.form.get('old_password', '')
        new = request.form.get('new_password', '')
        if not check_password_hash(account.password_hash, old) or len(new) < 16 or len(new) > 256:
            flash('Check your current password and use at least 16 characters for the new one.', 'error')
        else:
            account.password_hash = generate_password_hash(new)
            db.session.commit(); session.clear()
            flash('Password changed. Sign in again.', 'success')
            return redirect(url_for('admin_login'))
    return render_template('admin_password.html')

@app.route('/admin/reviews/login', methods=['GET', 'POST'])
def review_admin_login():
    return redirect(url_for('admin_login'))

@app.get('/admin/reviews')
@review_admin_required
def review_queue():
    reviews = ProviderReview.query.filter_by(status='pending').order_by(ProviderReview.provider_id.desc()).all()
    suspended = ProviderReview.query.filter_by(status='suspended').order_by(ProviderReview.provider_id.desc()).all()
    return render_template('review_queue.html', reviews=reviews, suspended=suspended)

@app.post('/admin/reviews/<int:provider_id>')
@review_admin_required
def review_decision(provider_id):
    review = db.get_or_404(ProviderReview, provider_id)
    decision = request.form.get('decision')
    if decision not in ('approved', 'rejected') or (review.status == 'suspended' and decision != 'approved'): abort(400)
    review.status = decision; review.reviewed_at = now(); review.reviewer_id = None
    db.session.add(AdminAudit(admin_id=session['admin_id'], action='provider_' + decision, target_id=provider_id))
    db.session.commit()
    flash('Provider review recorded.', 'success')
    return redirect(url_for('review_queue'))

REPORT_REASONS = ('Misleading listing', 'Harassment or abuse', 'Unsafe behaviour', 'Fraud or payment concern', 'Other')

@app.route('/providers/<int:provider_id>/report', methods=['GET', 'POST'])
@login_required
def report_provider(provider_id):
    provider = db.get_or_404(Provider, provider_id)
    if provider.user_id == session['user_id']: abort(403)
    if request.method == 'POST':
        try:
            reason = field('reason', 40)
            if reason not in REPORT_REASONS: raise ValueError('Choose a reason.')
            details = field('details', 1200)
            if len(details) < 15: raise ValueError('Please describe the concern in at least 15 characters.')
            existing = SafetyReport.query.filter_by(reporter_id=session['user_id'], provider_id=provider_id, status='open').first()
            if existing: raise ValueError('You already have an open report about this provider.')
            db.session.add(SafetyReport(reporter_id=session['user_id'], provider_id=provider_id, reason=reason, details=details))
            db.session.commit()
            flash('Your report was sent to the ConnectMe team.', 'success')
            return redirect(url_for('provider_detail', provider_id=provider_id))
        except ValueError as exc: flash(str(exc), 'error')
    return render_template('report_form.html', provider=provider, reasons=REPORT_REASONS)

@app.get('/admin/reports')
@review_admin_required
def report_queue():
    reports = SafetyReport.query.filter_by(status='open').order_by(SafetyReport.created_at.asc()).all()
    return render_template('report_queue.html', reports=reports)

@app.post('/admin/reports/<int:report_id>')
@review_admin_required
def report_decision(report_id):
    report = db.get_or_404(SafetyReport, report_id)
    decision = request.form.get('decision')
    if report.status != 'open' or decision not in ('dismissed', 'resolved', 'suspended'): abort(400)
    if decision == 'suspended':
        review = db.session.get(ProviderReview, report.provider_id)
        if not review: review = ProviderReview(provider_id=report.provider_id)
        review.status = 'suspended'; review.reviewed_at = now(); review.reviewer_id = None
        db.session.add(review)
    report.status = decision; report.reviewed_at = now(); report.reviewer_id = None
    db.session.add(AdminAudit(admin_id=session['admin_id'], action='report_' + decision, target_id=report_id))
    db.session.commit()
    flash('Report decision recorded.', 'success')
    return redirect(url_for('report_queue'))

@app.get('/admin/phone-calls')
@review_admin_required
def phone_call_queue():
    challenges = PhoneCallChallenge.query.filter_by(status='pending').order_by(PhoneCallChallenge.created_at.asc()).all()
    return render_template('phone_call_queue.html', challenges=challenges)

@app.post('/admin/phone-calls/<int:user_id>')
@review_admin_required
def phone_call_decision(user_id):
    challenge = db.get_or_404(PhoneCallChallenge, user_id)
    if challenge.status != 'pending': abort(409)
    if utc(challenge.expires_at) < now():
        challenge.status = 'expired'; db.session.commit()
        flash('This code expired. Ask the user to request a new call.', 'error')
        return redirect(url_for('phone_call_queue'))
    admin = db.session.get(AdminAccount, session['admin_id'])
    if admin.email.casefold() == challenge.user.email.casefold(): abort(403)
    decision = request.form.get('decision')
    if decision == 'reject':
        challenge.status = 'rejected'
    elif decision == 'confirm':
        code = request.form.get('code', '').strip()
        challenge.attempts += 1
        if not re.fullmatch(r'[0-9]{6}', code) or not check_password_hash(challenge.code_hash, code):
            if challenge.attempts >= 5: challenge.status = 'rejected'
            db.session.commit()
            flash('The code did not match. Do not approve this number.', 'error')
            return redirect(url_for('phone_call_queue'))
        if VerificationRecord.query.filter(VerificationRecord.phone == challenge.phone,
            VerificationRecord.phone_verified.is_(True), VerificationRecord.user_id != user_id).first():
            flash('That number is verified on another account.', 'error')
            return redirect(url_for('phone_call_queue'))
        record = db.session.get(VerificationRecord, user_id)
        if not record: record = VerificationRecord(user_id=user_id)
        record.phone = challenge.phone; record.phone_verified = True; record.updated_at = now()
        provider = Provider.query.filter_by(user_id=user_id).first()
        if provider: provider.phone_verified = True
        db.session.add(record)
        challenge.status = 'confirmed'
    else: abort(400)
    challenge.reviewed_at = now()
    db.session.add(AdminAudit(admin_id=admin.id, action='phone_call_' + challenge.status, target_id=user_id))
    db.session.commit()
    flash('Phone call decision saved.', 'success')
    return redirect(url_for('phone_call_queue'))

@app.route('/verification', methods=['GET', 'POST'])
@login_required
def verification():
    record = db.session.get(VerificationRecord, session['user_id'])
    if request.method == 'POST':
        action = request.form.get('action')
        if action == 'photo':
            upload = request.files.get('photo')
            if not upload or not upload.filename:
                flash('Choose a photo first.', 'error')
            else:
                try:
                    source = upload.read(2 * 1024 * 1024 + 1)
                    if len(source) > 2 * 1024 * 1024:
                        raise ValueError('Choose an image smaller than 2 MB.')
                    im = Image.open(BytesIO(source))
                    im.verify()
                    im = Image.open(BytesIO(source))
                    if im.format not in ('JPEG', 'PNG', 'WEBP') or im.width * im.height > 20_000_000:
                        raise ValueError('Use a JPG, PNG or WebP photo under 20 megapixels.')
                    im = im.convert('RGB')
                    im.thumbnail((700, 700))
                    output = BytesIO()
                    im.save(output, format='JPEG', quality=82, optimize=True)
                    photo = db.session.get(ProfilePhoto, session['user_id'])
                    if not photo: photo = ProfilePhoto(user_id=session['user_id'])
                    photo.image = output.getvalue()
                    photo.updated_at = now()
                    db.session.add(photo); db.session.commit()
                    flash('Your profile photo is saved. A photo alone does not verify identity.', 'success')
                except (UnidentifiedImageError, OSError, ValueError) as exc:
                    flash(str(exc) if isinstance(exc, ValueError) else 'This image could not be opened.', 'error')
        elif action == 'request_phone_call':
            phone = normalize_phone(request.form.get('phone', ''))
            if not phone:
                flash('Enter a valid Nigerian mobile number.', 'error')
            elif VerificationRecord.query.filter(VerificationRecord.phone == phone,
                 VerificationRecord.phone_verified.is_(True), VerificationRecord.user_id != session['user_id']).first():
                flash('This phone number is already verified on another account.', 'error')
            else:
                challenge = db.session.get(PhoneCallChallenge, session['user_id'])
                if challenge and (now() - utc(challenge.created_at)).total_seconds() < 600:
                    flash('Please wait ten minutes before requesting another call.', 'error')
                else:
                    code = f'{secrets.randbelow(1_000_000):06d}'
                    if not challenge: challenge = PhoneCallChallenge(user_id=session['user_id'])
                    challenge.phone, challenge.code_hash = phone, generate_password_hash(code)
                    challenge.status, challenge.attempts = 'pending', 0
                    challenge.created_at, challenge.expires_at = now(), now() + timedelta(hours=24)
                    challenge.reviewed_at = None
                    record = db.session.get(VerificationRecord, session['user_id'])
                    if not record: record = VerificationRecord(user_id=session['user_id'])
                    record.phone, record.phone_verified, record.updated_at = phone, False, now()
                    provider = Provider.query.filter_by(user_id=session['user_id']).first()
                    if provider: provider.phone_verified = False
                    db.session.add_all([challenge, record]); db.session.commit()
                    session['phone_call_code'] = code
                    flash('Call requested. Keep the code below ready when ConnectMe staff call you.', 'info')
        elif action == 'phone':
            phone = normalize_phone(request.form.get('phone', ''))
            if not phone:
                flash('Enter a valid Nigerian mobile number.', 'error')
            elif not otp_configured():
                flash('SMS verification is not configured yet. No code was sent.', 'error')
            elif VerificationRecord.query.filter(VerificationRecord.phone == phone, VerificationRecord.phone_verified.is_(True), VerificationRecord.user_id != session['user_id']).first():
                flash('This phone number is already verified on another account.', 'error')
            else:
                challenge = db.session.get(PhoneChallenge, session['user_id'])
                if challenge and (now() - utc(challenge.last_sent_at)).total_seconds() < 90:
                    flash('Please wait before requesting another code.', 'error')
                else:
                    try:
                        result = termii_request('send', {'to': phone, 'from': os.environ['TERMII_SENDER_ID'], 'channel': 'generic', 'pin_type': 'NUMERIC', 'pin_attempts': 3, 'pin_time_to_live': 5, 'pin_length': 6, 'pin_placeholder': '< 123456 >', 'message_text': 'Your ConnectMe verification code is < 123456 >. It expires in 5 minutes.'})
                        pin_id = result.get('pin_id') or result.get('pinId')
                        if not pin_id: raise ValueError('SMS service did not accept the request.')
                        if not record: record = VerificationRecord(user_id=session['user_id'])
                        record.phone = phone; record.phone_verified = False; record.updated_at = now()
                        provider = Provider.query.filter_by(user_id=session['user_id']).first()
                        if provider: provider.phone_verified = False
                        if not challenge: challenge = PhoneChallenge(user_id=session['user_id'])
                        challenge.phone = phone; challenge.pin_id = str(pin_id)
                        challenge.last_sent_at = now(); challenge.expires_at = now() + timedelta(minutes=5); challenge.attempts = 0
                        db.session.add_all([record, challenge]); db.session.commit()
                        flash('A verification code was sent to your phone.', 'success')
                    except (ValueError, URLError, TimeoutError):
                        flash('The SMS service could not send a code. Please try again later.', 'error')
        elif action == 'verify_phone':
            challenge = db.session.get(PhoneChallenge, session['user_id'])
            code = request.form.get('code', '').strip()
            if not otp_configured() or not challenge or utc(challenge.expires_at) < now() or challenge.attempts >= 3:
                flash('The code has expired. Request a new one.', 'error')
            elif not re.fullmatch(r'[0-9]{6}', code):
                flash('Enter the six-digit code.', 'error')
            else:
                challenge.attempts += 1
                db.session.commit()
                try:
                    result = termii_request('verify', {'pin_id': challenge.pin_id, 'pin': code})
                    verified = result.get('verified') is True or str(result.get('verified', '')).lower() == 'true'
                    if verified and record and record.phone == challenge.phone:
                        record.phone_verified = True; record.updated_at = now()
                        provider = Provider.query.filter_by(user_id=session['user_id']).first()
                        if provider: provider.phone_verified = True
                        db.session.delete(challenge); db.session.commit()
                        flash('Your phone number is verified.', 'success')
                    else:
                        flash('That code was not accepted.', 'error')
                except (ValueError, URLError, TimeoutError):
                    flash('The SMS service is unavailable. Please try again.', 'error')
        else:
            abort(400)
        return redirect(url_for('verification'))
    photo = db.session.get(ProfilePhoto, session['user_id'])
    call_challenge = db.session.get(PhoneCallChallenge, session['user_id'])
    if not call_challenge or call_challenge.status != 'pending' or utc(call_challenge.expires_at) < now():
        session.pop('phone_call_code', None)
    return render_template('verification.html', record=record, has_photo=bool(photo), challenge=db.session.get(PhoneChallenge, session['user_id']), otp_ready=otp_configured(), call_challenge=call_challenge, call_code=session.get('phone_call_code'))

@app.get('/photo/<int:user_id>')
def profile_photo(user_id):
    photo = db.session.get(ProfilePhoto, user_id)
    if not photo: abort(404)
    response = send_file(BytesIO(photo.image), mimetype='image/jpeg', max_age=3600)
    response.headers['X-Content-Type-Options'] = 'nosniff'
    return response

@app.get('/subscriptions')
def subscriptions():
    plans = {role: active_plan(session['user_id'], role) for role in PLAN_PRICES} if session.get('user_id') else {}
    bank_transfers = BankTransferPayment.query.filter_by(user_id=session['user_id']).order_by(BankTransferPayment.created_at.desc()).limit(20).all() if session.get('user_id') else []
    bank_details = {k: os.getenv(k, '').strip() for k in ('BANK_NAME', 'BANK_ACCOUNT_NAME', 'BANK_ACCOUNT_NUMBER')}
    bank_ready = all(bank_details.values()) and bool(re.fullmatch(r'[0-9]{10}', bank_details['BANK_ACCOUNT_NUMBER']))
    return render_template('subscriptions.html', prices=plan_prices(), plans=plans,
        payment_ready=bool(os.getenv('PAYSTACK_SECRET_KEY', '').startswith(('sk_test_', 'sk_live_'))),
        test_mode=os.getenv('PAYSTACK_SECRET_KEY', '').startswith('sk_test_'),
        bank_ready=bank_ready, bank_details=bank_details, bank_transfers=bank_transfers)

@app.post('/subscriptions/bank/<role>')
@login_required
def start_bank_transfer(role):
    if role not in PLAN_PRICES: abort(404)
    bank_number = os.getenv('BANK_ACCOUNT_NUMBER', '').strip()
    if not (os.getenv('BANK_NAME', '').strip() and os.getenv('BANK_ACCOUNT_NAME', '').strip()
            and re.fullmatch(r'[0-9]{10}', bank_number)):
        flash('Bank transfer is being set up.', 'error'); return redirect(url_for('subscriptions'))
    existing = BankTransferPayment.query.filter(BankTransferPayment.user_id == session['user_id'],
        BankTransferPayment.role == role, BankTransferPayment.status.in_(('awaiting_transfer', 'submitted'))).first()
    if not existing:
        existing = BankTransferPayment(reference='cm_bank_' + secrets.token_hex(16),
            user_id=session['user_id'], role=role, amount_ngn=plan_prices()[role])
        db.session.add(existing); db.session.commit()
    return redirect(url_for('subscriptions'))

@app.post('/subscriptions/bank/notify/<int:payment_id>')
@login_required
def submit_bank_transfer(payment_id):
    payment = db.get_or_404(BankTransferPayment, payment_id)
    if payment.user_id != session['user_id']: abort(403)
    if payment.status != 'awaiting_transfer': abort(409)
    payer = request.form.get('payer_name', '').strip()
    bank_ref = request.form.get('bank_reference', '').strip()
    if not (2 <= len(payer) <= 120 and 4 <= len(bank_ref) <= 120):
        flash('Enter the payer name and bank transaction reference.', 'error')
        return redirect(url_for('subscriptions'))
    payment.payer_name, payment.bank_reference = payer, bank_ref
    payment.status, payment.submitted_at = 'submitted', now()
    db.session.commit()
    flash('Transfer details submitted. Access starts after staff confirm the credit in our bank account.', 'info')
    return redirect(url_for('subscriptions'))

@app.get('/admin/payments')
@review_admin_required
def bank_payment_queue():
    payments = BankTransferPayment.query.filter_by(status='submitted').order_by(BankTransferPayment.submitted_at.asc()).all()
    return render_template('bank_payment_queue.html', payments=payments)

@app.post('/admin/payments/<int:payment_id>')
@review_admin_required
def bank_payment_decision(payment_id):
    payment = db.get_or_404(BankTransferPayment, payment_id)
    decision = request.form.get('decision')
    if payment.status != 'submitted' or decision not in ('approved', 'rejected'): abort(409)
    if payment.user.email.casefold() == db.session.get(AdminAccount, session['admin_id']).email.casefold(): abort(403)
    if decision == 'approved':
        latest = latest_paid_plan(payment.user_id, payment.role)
        base = max(now(), utc(latest.expires_at) if latest else now())
        payment.expires_at = base + timedelta(days=30)
    payment.status, payment.reviewed_at, payment.reviewer_id = decision, now(), None
    db.session.add(AdminAudit(admin_id=session['admin_id'], action='bank_' + decision, target_id=payment_id))
    db.session.commit()
    flash('Bank transfer decision saved.', 'success')
    return redirect(url_for('bank_payment_queue'))

@app.post('/subscriptions/pay/<role>')
@login_required
def start_plan_payment(role):
    if role not in PLAN_PRICES: abort(404)
    if not os.getenv('PAYSTACK_SECRET_KEY', '').startswith(('sk_test_', 'sk_live_')):
        flash('Payment is not available yet.', 'error'); return redirect(url_for('subscriptions'))
    user = db.session.get(User, session['user_id'])
    payment = PlanPayment(reference='cm_' + secrets.token_hex(20), user_id=user.id,
                          role=role, amount_ngn=plan_prices()[role], email=user.email)
    db.session.add(payment); db.session.commit()
    public_base = os.getenv('PUBLIC_BASE_URL', request.url_root.rstrip('/')).rstrip('/')
    if os.getenv('RENDER') and not public_base.startswith('https://'):
        flash('Configure PUBLIC_BASE_URL with your HTTPS site address.', 'error')
        return redirect(url_for('subscriptions'))
    try:
        data = paystack_api('transaction/initialize', 'POST', {'email': payment.email,
            'amount': payment.amount_ngn * 100, 'currency': 'NGN', 'reference': payment.reference,
            'callback_url': public_base + url_for('payment_callback')})
        checkout = data.get('authorization_url', '')
        host = urlsplit(checkout)
        if host.scheme != 'https' or not (host.hostname == 'paystack.com' or (host.hostname or '').endswith('.paystack.com')):
            raise ValueError('Invalid checkout address.')
        return redirect(checkout)
    except (ValueError, URLError, HTTPError, KeyError, TimeoutError):
        app.logger.exception('Paystack initialization failed')
        flash('Payment could not start. Please try again.', 'error')
        return redirect(url_for('subscriptions'))

@app.get('/payments/callback')
def payment_callback():
    reference = request.args.get('reference', '')
    payment = PlanPayment.query.filter_by(reference=reference).first() if reference else None
    if not payment or session.get('user_id') != payment.user_id:
        flash('Sign in to the account that started this payment to check its status.', 'info')
        return redirect(url_for('login', next=url_for('subscriptions')))
    try:
        if confirm_payment(payment): flash('Payment confirmed. Your 30-day plan is active.', 'success')
        else: flash('Payment is not confirmed yet. Please check again shortly.', 'info')
    except (ValueError, URLError, HTTPError, KeyError, TimeoutError):
        app.logger.exception('Paystack verification failed')
        flash('Payment status could not be checked. Please try again shortly.', 'error')
    return redirect(url_for('subscriptions'))

@app.post('/payments/paystack/webhook')
def payment_webhook():
    key = os.getenv('PAYSTACK_SECRET_KEY', '')
    raw = request.get_data()
    signature = request.headers.get('x-paystack-signature', '')
    if not key or len(raw) > 65536 or not hmac.compare_digest(
        hmac.new(key.encode(), raw, hashlib.sha512).hexdigest(), signature): abort(403)
    event = request.get_json(silent=True) or {}
    if event.get('event') == 'charge.success':
        reference = (event.get('data') or {}).get('reference', '')
        payment = PlanPayment.query.filter_by(reference=reference).first() if isinstance(reference, str) else None
        if payment:
            try: confirm_payment(payment)
            except (ValueError, URLError, HTTPError, KeyError, TimeoutError):
                app.logger.exception('Paystack webhook verification failed')
                return {'status': 'retry'}, 503
    return {'status': 'ok'}

@app.get('/health')
def health():
    return {'status': 'ok'}

with app.app_context():
    db.create_all()
    if not AdminAccount.query.first():
        setup_email = os.getenv('ADMIN_SETUP_EMAIL', '').strip().lower()
        setup_password = os.getenv('ADMIN_SETUP_PASSWORD', '')
        if setup_email and setup_password:
            if not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+', setup_email) or len(setup_password) < 16:
                raise RuntimeError('ADMIN_SETUP_EMAIL must be valid and ADMIN_SETUP_PASSWORD must have at least 16 characters.')
            db.session.add(AdminAccount(email=setup_email, password_hash=generate_password_hash(setup_password)))
            db.session.commit()
            app.logger.warning('Initial admin account created. Remove ADMIN_SETUP_PASSWORD and ADMIN_SETUP_EMAIL from Render.')

if __name__ == '__main__':
    app.run(debug=True)

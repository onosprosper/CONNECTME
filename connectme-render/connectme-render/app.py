import os
import re
import secrets
from io import BytesIO
from datetime import datetime, timezone
from functools import wraps
from urllib.parse import urlsplit
from flask import Flask, abort, flash, redirect, render_template, request, session, url_for, send_file
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import UniqueConstraint, or_
from werkzeug.security import check_password_hash, generate_password_hash
from PIL import Image, UnidentifiedImageError

CATEGORIES = ('Food & cooking', 'Wellness', 'Home services', 'Skilled workers', 'Beauty', 'Care services', 'Tutors & skills', 'Transport & help', 'Experiences', 'Connect & community')
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

class Provider(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), unique=True, nullable=False)
    category = db.Column(db.String(80), nullable=False)
    service = db.Column(db.String(120), nullable=False)
    city = db.Column(db.String(80), nullable=False)
    area = db.Column(db.String(120), nullable=False)
    bio = db.Column(db.String(800), nullable=False, default='')
    price = db.Column(db.Integer, nullable=False)
    # No verified badge until a real OTP/NIN integration has completed.
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
    offers = db.relationship('Offer', back_populates='job', order_by='Offer.created_at.desc()')

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

class SubscriptionInterest(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    role = db.Column(db.String(12), nullable=False)
    monthly_ngn = db.Column(db.Integer, nullable=False)
    status = db.Column(db.String(24), nullable=False, default='pending_payment')
    created_at = db.Column(db.DateTime(timezone=True), default=now, nullable=False)
    __table_args__ = (UniqueConstraint('user_id', 'role', name='uq_subscription_interest'),)

@app.context_processor
def shared():
    return {'categories': CATEGORIES, 'current_user': db.session.get(User, session['user_id']) if 'user_id' in session else None, 'csrf_token': csrf_token}

def csrf_token():
    if 'csrf' not in session:
        session['csrf'] = secrets.token_urlsafe(32)
    return session['csrf']

@app.before_request
def protect_post():
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
    query = Provider.query
    if q:
        query = query.filter(or_(Provider.service.ilike(f'%{q}%'), Provider.bio.ilike(f'%{q}%'), Provider.area.ilike(f'%{q}%')))
    if city:
        query = query.filter(Provider.city.ilike(f'%{city}%'))
    if category:
        query = query.filter_by(category=category)
    providers = query.order_by(Provider.id.desc()).limit(60).all()
    return render_template('home.html', providers=providers, q=q, city=city, category=category)

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
        try:
            category = field('category', 80)
            if category not in CATEGORIES: raise ValueError('Choose a category.')
            date_needed = datetime.strptime(field('date_needed', 10), '%Y-%m-%d').date()
            if date_needed < now().date(): raise ValueError('Choose a current or future date.')
            job = JobRequest(customer_id=session['user_id'], category=category, title=field('title', 140), city=field('city', 80), area=field('area', 120), date_needed=date_needed, budget=amount('budget'), details=field('details', 1200, False))
            db.session.add(job); db.session.commit()
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
            db.session.add(provider); db.session.commit()
            flash('Your profile is saved. Verification is not yet active.', 'success')
            return redirect(url_for('provider_detail', provider_id=provider.id))
        except ValueError as exc: flash(str(exc), 'error')
    return render_template('provider_form.html', provider=provider)

@app.get('/providers/<int:provider_id>')
def provider_detail(provider_id):
    provider = db.get_or_404(Provider, provider_id)
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
    job = db.get_or_404(JobRequest, job_id)
    provider = Provider.query.filter_by(user_id=session['user_id']).first()
    if not provider or job.customer_id == session['user_id'] or job.status != 'open': abort(403)
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
    job.status = 'booked'
    for other in job.offers: other.status = 'accepted' if other.id == offer.id else 'declined'
    db.session.commit()
    flash('Booking confirmed. The agreed price is saved.', 'success')
    return redirect(url_for('dashboard'))

@app.get('/dashboard')
@login_required
def dashboard():
    jobs = JobRequest.query.filter_by(customer_id=session['user_id']).order_by(JobRequest.created_at.desc()).all()
    provider = Provider.query.filter_by(user_id=session['user_id']).first()
    sent = Offer.query.filter_by(provider_id=provider.id).order_by(Offer.created_at.desc()).all() if provider else []
    return render_template('dashboard.html', jobs=jobs, provider=provider, sent=sent)

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
        elif action == 'phone':
            phone = request.form.get('phone', '').strip()
            if not re.fullmatch(r'\+?[0-9]{10,15}', phone):
                flash('Enter a phone number with 10 to 15 digits.', 'error')
            else:
                if not record: record = VerificationRecord(user_id=session['user_id'])
                record.phone = phone
                record.phone_verified = False
                record.updated_at = now()
                db.session.add(record); db.session.commit()
                flash('Phone number saved. OTP verification is not active yet.', 'success')
        else:
            abort(400)
        return redirect(url_for('verification'))
    photo = db.session.get(ProfilePhoto, session['user_id'])
    return render_template('verification.html', record=record, has_photo=bool(photo))

@app.get('/photo/<int:user_id>')
def profile_photo(user_id):
    photo = db.session.get(ProfilePhoto, user_id)
    if not photo: abort(404)
    response = send_file(BytesIO(photo.image), mimetype='image/jpeg', max_age=3600)
    response.headers['X-Content-Type-Options'] = 'nosniff'
    return response

@app.route('/subscriptions', methods=['GET', 'POST'])
def subscriptions():
    prices = {'customer': max(0, int(os.getenv('CUSTOMER_MONTHLY_NGN', '1000'))),
              'provider': max(0, int(os.getenv('PROVIDER_MONTHLY_NGN', '3000')))}
    if request.method == 'POST':
        if 'user_id' not in session:
            flash('Sign in to register your interest.', 'info')
            return redirect(url_for('login', next=url_for('subscriptions')))
        role = request.form.get('role')
        if role not in prices: abort(400)
        interest = SubscriptionInterest.query.filter_by(user_id=session['user_id'], role=role).first()
        if not interest: interest = SubscriptionInterest(user_id=session['user_id'], role=role)
        interest.monthly_ngn = prices[role]
        interest.status = 'pending_payment'
        db.session.add(interest); db.session.commit()
        flash('Interest saved. No payment was taken and access is not active.', 'success')
        return redirect(url_for('subscriptions'))
    mine = SubscriptionInterest.query.filter_by(user_id=session['user_id']).all() if session.get('user_id') else []
    return render_template('subscriptions.html', prices=prices, interests={row.role: row for row in mine})

@app.get('/health')
def health():
    return {'status': 'ok'}

with app.app_context():
    db.create_all()

if __name__ == '__main__':
    app.run(debug=True)

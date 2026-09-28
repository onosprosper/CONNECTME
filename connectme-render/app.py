import os
import re
import secrets
import json
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError
from io import BytesIO
from datetime import datetime, timezone, timedelta
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

class PhoneChallenge(db.Model):
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), primary_key=True)
    phone = db.Column(db.String(25), nullable=False)
    pin_id = db.Column(db.String(120), nullable=False)
    expires_at = db.Column(db.DateTime(timezone=True), nullable=False)
    last_sent_at = db.Column(db.DateTime(timezone=True), nullable=False)
    attempts = db.Column(db.Integer, nullable=False, default=0)

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
    query = Provider.query.outerjoin(ProviderReview, ProviderReview.provider_id == Provider.id).filter(or_(ProviderReview.status.is_(None), ProviderReview.status != 'suspended'))
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
            db.session.add(provider); db.session.flush()
            review = db.session.get(ProviderReview, provider.id)
            if not review: db.session.add(ProviderReview(provider_id=provider.id))
            elif review.status == 'approved':
                review.status = 'pending'; review.reviewed_at = None; review.reviewer_id = None
            db.session.commit()
            flash('Your profile is saved. It is awaiting review.', 'success')
            return redirect(url_for('provider_detail', provider_id=provider.id))
        except ValueError as exc: flash(str(exc), 'error')
    return render_template('provider_form.html', provider=provider)

@app.get('/providers/<int:provider_id>')
def provider_detail(provider_id):
    provider = db.get_or_404(Provider, provider_id)
    if provider.review and provider.review.status == 'suspended' and session.get('user_id') != provider.user_id and not session.get('review_admin'): abort(404)
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
        key = os.getenv('ADMIN_REVIEW_KEY', '')
        if not key or len(key) < 32 or not session.get('review_admin'):
            abort(403)
        return fn(*args, **kwargs)
    return wrapper

@app.route('/admin/reviews/login', methods=['GET', 'POST'])
@login_required
def review_admin_login():
    if request.method == 'POST':
        key = os.getenv('ADMIN_REVIEW_KEY', '')
        if len(key) >= 32 and secrets.compare_digest(request.form.get('review_key', ''), key):
            session['review_admin'] = True
            return redirect(url_for('review_queue'))
        flash('Invalid review access key.', 'error')
    return render_template('review_login.html')

@app.get('/admin/reviews')
@login_required
@review_admin_required
def review_queue():
    reviews = ProviderReview.query.filter_by(status='pending').order_by(ProviderReview.provider_id.desc()).all()
    suspended = ProviderReview.query.filter_by(status='suspended').order_by(ProviderReview.provider_id.desc()).all()
    return render_template('review_queue.html', reviews=reviews, suspended=suspended)

@app.post('/admin/reviews/<int:provider_id>')
@login_required
@review_admin_required
def review_decision(provider_id):
    review = db.get_or_404(ProviderReview, provider_id)
    decision = request.form.get('decision')
    if decision not in ('approved', 'rejected') or (review.status == 'suspended' and decision != 'approved'): abort(400)
    review.status = decision; review.reviewed_at = now(); review.reviewer_id = session['user_id']
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
@login_required
@review_admin_required
def report_queue():
    reports = SafetyReport.query.filter_by(status='open').order_by(SafetyReport.created_at.asc()).all()
    return render_template('report_queue.html', reports=reports)

@app.post('/admin/reports/<int:report_id>')
@login_required
@review_admin_required
def report_decision(report_id):
    report = db.get_or_404(SafetyReport, report_id)
    decision = request.form.get('decision')
    if report.status != 'open' or decision not in ('dismissed', 'resolved', 'suspended'): abort(400)
    if decision == 'suspended':
        review = db.session.get(ProviderReview, report.provider_id)
        if not review: review = ProviderReview(provider_id=report.provider_id)
        review.status = 'suspended'; review.reviewed_at = now(); review.reviewer_id = session['user_id']
        db.session.add(review)
    report.status = decision; report.reviewed_at = now(); report.reviewer_id = session['user_id']
    db.session.commit()
    flash('Report decision recorded.', 'success')
    return redirect(url_for('report_queue'))

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
            phone = normalize_phone(request.form.get('phone', ''))
            if not phone:
                flash('Enter a valid Nigerian mobile number.', 'error')
            elif not otp_configured():
                flash('SMS verification is not configured yet. No code was sent.', 'error')
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
            if not challenge or utc(challenge.expires_at) < now() or challenge.attempts >= 3:
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
    return render_template('verification.html', record=record, has_photo=bool(photo), challenge=db.session.get(PhoneChallenge, session['user_id']), otp_ready=otp_configured())

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

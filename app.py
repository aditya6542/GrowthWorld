import os
import jwt
import datetime
import uuid
import hashlib
from functools import wraps
from flask import Flask, request, jsonify, render_template, send_from_directory, redirect, url_for
from flask_sqlalchemy import SQLAlchemy
from werkzeug.utils import secure_filename

app = Flask(__name__)
app.config['SECRET_KEY'] = 'growthworld-super-secret-key-1234567890'
import sys
if 'pytest' in sys.modules or os.environ.get('PYTEST_CURRENT_TEST'):
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///:memory:'
else:
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///growthworld.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

UPLOAD_FOLDER = os.path.join(app.root_path, 'static', 'uploads')
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

db = SQLAlchemy(app)

# ==========================================
# DATABASE MODELS
# ==========================================

class User(db.Model):
    __tablename__ = 'users'
    id = db.Column(db.Integer, primary_key=True)
    phone = db.Column(db.String(20), unique=True, nullable=False, index=True)
    email = db.Column(db.String(120), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(256), nullable=False)
    referral_code = db.Column(db.String(50), unique=True, nullable=False, index=True)
    referred_by_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    wallet_balance = db.Column(db.Float, default=0.0)
    
    # Withdrawal details
    upi_id = db.Column(db.String(100), nullable=True)
    bank_name = db.Column(db.String(100), nullable=True)
    account_number = db.Column(db.String(100), nullable=True)
    ifsc_code = db.Column(db.String(100), nullable=True)
    
    is_admin = db.Column(db.Boolean, default=False)
    last_task_claim_at = db.Column(db.DateTime, nullable=True)
    last_salary_claim_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.datetime.utcnow)

    # Relationships
    referred_by = db.relationship('User', remote_side=[id], backref=db.backref('referrals', lazy='dynamic'))
    investments = db.relationship('UserInvestment', backref='user', lazy='dynamic')
    transactions = db.relationship('Transaction', backref='user', lazy='dynamic')

    @property
    def is_active(self):
        # A user is active if they have at least one active investment
        now = datetime.datetime.utcnow()
        return self.investments.filter(
            UserInvestment.status == 'active',
            UserInvestment.expires_at > now
        ).count() > 0

class InvestmentPlan(db.Model):
    __tablename__ = 'investment_plans'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    price = db.Column(db.Float, nullable=False) # Minimum ₹1200
    daily_earning_min = db.Column(db.Float, nullable=False)
    daily_earning_max = db.Column(db.Float, nullable=False)
    duration_days = db.Column(db.Integer, nullable=False)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.datetime.utcnow)

class UserInvestment(db.Model):
    __tablename__ = 'user_investments'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    plan_id = db.Column(db.Integer, db.ForeignKey('investment_plans.id'), nullable=False)
    price = db.Column(db.Float, nullable=False)
    daily_earning = db.Column(db.Float, nullable=False) # Picked randomly in range at purchase
    activated_at = db.Column(db.DateTime, default=datetime.datetime.utcnow)
    expires_at = db.Column(db.DateTime, nullable=False)
    last_payout_at = db.Column(db.DateTime, nullable=False)
    status = db.Column(db.String(20), default='active') # active, expired

    plan = db.relationship('InvestmentPlan')

class UserTaskProgress(db.Model):
    __tablename__ = 'user_task_progress'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    date = db.Column(db.String(10), nullable=False) # YYYY-MM-DD
    tasks_completed = db.Column(db.Integer, default=0) # 0 to 5
    reward_claimed = db.Column(db.Boolean, default=False)
    last_task_completed_at = db.Column(db.DateTime, nullable=True)

    __table_args__ = (db.UniqueConstraint('user_id', 'date', name='_user_date_uc'),)

class Transaction(db.Model):
    __tablename__ = 'transactions'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    amount = db.Column(db.Float, nullable=False)
    type = db.Column(db.String(30), nullable=False) # deposit, withdrawal, referral_bonus, task_reward, plan_payout, salary
    status = db.Column(db.String(20), default='pending') # pending, approved, rejected
    payment_method = db.Column(db.String(30), nullable=True) # bank_upi, crypto_trc20, crypto_bep20
    utr_number = db.Column(db.String(100), nullable=True)
    proof_screenshot = db.Column(db.String(256), nullable=True)
    fee = db.Column(db.Float, default=0.0)
    description = db.Column(db.String(256), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)

class PlatformSetting(db.Model):
    __tablename__ = 'platform_settings'
    key = db.Column(db.String(100), primary_key=True)
    value = db.Column(db.Text, nullable=False)

# ==========================================
# HELPERS
# ==========================================

def hash_password(password: str) -> str:
    salt = os.urandom(16)
    key = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), salt, 100000)
    return salt.hex() + '$' + key.hex()

def check_password(password: str, hashed: str) -> bool:
    try:
        salt_hex, key_hex = hashed.split('$')
        salt = bytes.fromhex(salt_hex)
        key = bytes.fromhex(key_hex)
        new_key = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), salt, 100000)
        return new_key == key
    except Exception:
        return False

def get_setting(key, default=None):
    setting = PlatformSetting.query.get(key)
    return setting.value if setting else default

def set_setting(key, value):
    setting = PlatformSetting.query.get(key)
    if not setting:
        setting = PlatformSetting(key=key, value=str(value))
        db.session.add(setting)
    else:
        setting.value = str(value)
    db.session.commit()

# ==========================================
# AUTH DECORATORS
# ==========================================

def token_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        token = None
        if 'Authorization' in request.headers:
            auth_header = request.headers['Authorization']
            if auth_header.startswith('Bearer '):
                token = auth_header.split(' ')[1]
        if not token:
            token = request.cookies.get('token')
        if not token:
            return jsonify({'message': 'Authentication token is missing!'}), 401
        try:
            data = jwt.decode(token, app.config['SECRET_KEY'], algorithms=['HS256'])
            current_user = User.query.get(data['user_id'])
            if not current_user:
                return jsonify({'message': 'Invalid user token!'}), 401
        except jwt.ExpiredSignatureError:
            return jsonify({'message': 'Token has expired! Please log in again.'}), 401
        except Exception:
            return jsonify({'message': 'Invalid token!'}), 401
        
        # Lazy load/distribute daily earnings payouts on any authenticated action
        process_lazy_payouts(current_user)
        
        return f(current_user, *args, **kwargs)
    return decorated

def admin_required(f):
    @wraps(f)
    @token_required
    def decorated(current_user, *args, **kwargs):
        if not current_user.is_admin:
            return jsonify({'message': 'Admin privilege required!'}), 403
        return f(current_user, *args, **kwargs)
    return decorated

# ==========================================
# LAZY DAILY PAYOUT LOGIC
# ==========================================

def process_lazy_payouts(user):
    """
    Checks user's active investments. For any investment that has passed its
    expiration date, updates its status to 'expired'. Payouts are claimed via tasks.
    """
    now = datetime.datetime.utcnow()
    active_investments = UserInvestment.query.filter_by(user_id=user.id, status='active').all()
    
    updated = False
    for inv in active_investments:
        if inv.expires_at <= now:
            inv.status = 'expired'
            db.session.add(inv)
            updated = True
                
    if updated:
        db.session.commit()

# ==========================================
# CORE VIEW ROUTES
# ==========================================

@app.route('/')
def home():
    return render_template('index.html')

# Support SPA routes falling back to index.html
@app.route('/dashboard')
@app.route('/plans')
@app.route('/tasks')
@app.route('/referrals')
@app.route('/salary')
@app.route('/wallet')
@app.route('/admin')
def spa_fallback():
    return render_template('index.html')

# ==========================================
# AUTHENTICATION API
# ==========================================

@app.route('/api/auth/signup', methods=['POST'])
def signup():
    data = request.get_json() or {}
    phone = data.get('phone')
    email = data.get('email')
    password = data.get('password')
    ref_code = data.get('referral_code') # optional referral code
    
    # Banking Info (optional on signup, editable in settings)
    upi_id = data.get('upi_id', '')
    bank_name = data.get('bank_name', '')
    account_number = data.get('account_number', '')
    ifsc_code = data.get('ifsc_code', '')

    if not phone or not email or not password:
        return jsonify({'message': 'Phone, email, and password are required.'}), 400

    if User.query.filter_by(phone=phone).first():
        return jsonify({'message': 'Phone number already registered.'}), 400
        
    if User.query.filter_by(email=email).first():
        return jsonify({'message': 'Email address already registered.'}), 400

    # Handle Referral Code checking
    referred_by_id = None
    if ref_code:
        parent = User.query.filter_by(referral_code=ref_code).first()
        if parent:
            referred_by_id = parent.id
        else:
            return jsonify({'message': 'Invalid referral code.'}), 400

    # Generate unique referral code for new user
    new_ref_code = f"GW-{uuid.uuid4().hex[:6].upper()}"
    while User.query.filter_by(referral_code=new_ref_code).first():
        new_ref_code = f"GW-{uuid.uuid4().hex[:6].upper()}"

    new_user = User(
        phone=phone,
        email=email,
        password_hash=hash_password(password),
        referral_code=new_ref_code,
        referred_by_id=referred_by_id,
        upi_id=upi_id,
        bank_name=bank_name,
        account_number=account_number,
        ifsc_code=ifsc_code
    )

    db.session.add(new_user)
    db.session.commit()

    # Create JWT token for auto-login
    token = jwt.encode({
        'user_id': new_user.id,
        'exp': datetime.datetime.utcnow() + datetime.timedelta(days=7)
    }, app.config['SECRET_KEY'], algorithm='HS256')

    return jsonify({
        'message': 'Signup successful!',
        'token': token,
        'user': {
            'id': new_user.id,
            'phone': new_user.phone,
            'email': new_user.email,
            'referral_code': new_user.referral_code,
            'is_admin': new_user.is_admin
        }
    }), 201

@app.route('/api/auth/login', methods=['POST'])
def login():
    data = request.get_json() or {}
    login_id = data.get('login_id') # Can be email or phone
    password = data.get('password')

    if not login_id or not password:
        return jsonify({'message': 'Email/Phone and password are required.'}), 400

    user = User.query.filter((User.email == login_id) | (User.phone == login_id)).first()

    if not user or not check_password(password, user.password_hash):
        return jsonify({'message': 'Invalid credentials.'}), 401

    token = jwt.encode({
        'user_id': user.id,
        'exp': datetime.datetime.utcnow() + datetime.timedelta(days=7)
    }, app.config['SECRET_KEY'], algorithm='HS256')

    return jsonify({
        'message': 'Login successful!',
        'token': token,
        'user': {
            'id': user.id,
            'phone': user.phone,
            'email': user.email,
            'referral_code': user.referral_code,
            'is_admin': user.is_admin
        }
    })

@app.route('/api/auth/me', methods=['GET'])
@token_required
def get_me(current_user):
    now = datetime.datetime.utcnow()
    active_invs = current_user.investments.filter(
        UserInvestment.status == 'active',
        UserInvestment.expires_at > now
    ).all()
    active_count = len(active_invs)
    daily_yield = sum(inv.daily_earning for inv in active_invs)

    return jsonify({
        'id': current_user.id,
        'phone': current_user.phone,
        'email': current_user.email,
        'referral_code': current_user.referral_code,
        'wallet_balance': current_user.wallet_balance,
        'upi_id': current_user.upi_id,
        'bank_name': current_user.bank_name,
        'account_number': current_user.account_number,
        'ifsc_code': current_user.ifsc_code,
        'is_admin': current_user.is_admin,
        'is_active': current_user.is_active,
        'active_investments_count': active_count,
        'daily_yield_sum': round(daily_yield, 2),
        'platform_notice': get_setting('platform_notice', 'Join GrowthWorld Today and Unlock Daily Rewards, Team Bonuses, VIP Benefits & Free Wednesday Withdrawals!'),
        'referred_by': current_user.referred_by.email if current_user.referred_by else None
    })

@app.route('/api/user/bank-details', methods=['PUT'])
@token_required
def update_bank_details(current_user):
    data = request.get_json() or {}
    current_user.upi_id = data.get('upi_id', current_user.upi_id)
    current_user.bank_name = data.get('bank_name', current_user.bank_name)
    current_user.account_number = data.get('account_number', current_user.account_number)
    current_user.ifsc_code = data.get('ifsc_code', current_user.ifsc_code)
    
    db.session.commit()
    return jsonify({'message': 'Bank & UPI withdrawal details updated successfully.'})

# ==========================================
# INVESTMENT PLANS API
# ==========================================

@app.route('/api/plans', methods=['GET'])
def list_plans():
    plans = InvestmentPlan.query.all()
    plans_data = []
    for plan in plans:
        plans_data.append({
            'id': plan.id,
            'name': plan.name,
            'price': plan.price,
            'daily_earning_min': plan.daily_earning_min,
            'daily_earning_max': plan.daily_earning_max,
            'duration_days': plan.duration_days,
            'is_active': plan.is_active
        })
    return jsonify(plans_data)

@app.route('/api/plans/purchase', methods=['POST'])
@token_required
def purchase_plan(current_user):
    data = request.get_json() or {}
    plan_id = data.get('plan_id')
    
    if not plan_id:
        return jsonify({'message': 'Plan ID is required.'}), 400
        
    plan = InvestmentPlan.query.get(plan_id)
    if not plan or not plan.is_active:
        return jsonify({'message': 'Investment plan not found or inactive.'}), 404
        
    if current_user.wallet_balance < plan.price:
        return jsonify({'message': f'Insufficient wallet balance. You need ₹{plan.price - current_user.wallet_balance:.2f} more.'}), 400

    # Deduct wallet balance
    current_user.wallet_balance -= plan.price

    # Generate exact daily return (random within min/max bounds)
    import random
    daily_earning = round(random.uniform(plan.daily_earning_min, plan.daily_earning_max), 2)

    # Calculate timestamps
    now = datetime.datetime.utcnow()
    expires_at = now + datetime.timedelta(days=plan.duration_days)

    user_inv = UserInvestment(
        user_id=current_user.id,
        plan_id=plan.id,
        price=plan.price,
        daily_earning=daily_earning,
        activated_at=now,
        expires_at=expires_at,
        last_payout_at=now,
        status='active'
    )

    # Log transaction
    tx = Transaction(
        user_id=current_user.id,
        amount=plan.price,
        type='purchase',
        status='approved',
        description=f"Purchased plan: {plan.name} (Earning ₹{daily_earning}/day)"
    )

    db.session.add(user_inv)
    db.session.add(tx)
    db.session.add(current_user)
    
    # Process 3-Level Referral Commission immediately
    process_referral_commissions(current_user, plan.price)

    db.session.commit()
    return jsonify({
        'message': f'Plan "{plan.name}" activated successfully!',
        'daily_earning': daily_earning
    })

def process_referral_commissions(buyer, amount):
    """
    Distributes commission to referred managers up to 3 levels.
    Level A: 10%
    Level B: 2%
    Level C: 0.5%
    """
    levels = [
        (1, 0.10, 'Level A Referral Bonus'),
        (2, 0.02, 'Level B Referral Bonus'),
        (3, 0.005, 'Level C Referral Bonus')
    ]

    current_parent = buyer.referred_by
    for level_num, rate, label in levels:
        if not current_parent:
            break
            
        commission = round(amount * rate, 2)
        current_parent.wallet_balance += commission
        
        tx = Transaction(
            user_id=current_parent.id,
            amount=commission,
            type='referral_bonus',
            status='approved',
            description=f"{label} from {buyer.email} buying plan (₹{amount})"
        )
        
        db.session.add(current_parent)
        db.session.add(tx)
        
        current_parent = current_parent.referred_by

# ==========================================
# DAILY TASK SYSTEM API
# ==========================================

@app.route('/api/tasks', methods=['GET'])
@token_required
def get_daily_tasks(current_user):
    active_investments = UserInvestment.query.filter_by(user_id=current_user.id, status='active').all()
    has_active_plan = len(active_investments) > 0
    
    today = datetime.datetime.utcnow().strftime('%Y-%m-%d')
    progress = UserTaskProgress.query.filter_by(user_id=current_user.id, date=today).first()
    
    completed = progress.tasks_completed if progress else 0
    claimed = progress.reward_claimed if progress else False
    
    # Check 24 hour cooldown on reward claim
    cooldown = False
    cooldown_seconds = 0
    if current_user.last_task_claim_at:
        diff = datetime.datetime.utcnow() - current_user.last_task_claim_at
        if diff.total_seconds() < 86400:
            cooldown = True
            cooldown_seconds = int(86400 - diff.total_seconds())

    # Task list (custom clickable earn items)
    tasks = []
    if has_active_plan:
        tasks = [
            {'id': 1, 'name': 'Ad Link 1: Grow Money Tips', 'reward': 10.0, 'completed': completed >= 1},
            {'id': 2, 'name': 'Ad Link 2: Crypto Investing Guide', 'reward': 10.0, 'completed': completed >= 2},
            {'id': 3, 'name': 'Ad Link 3: High Yield Platforms', 'reward': 10.0, 'completed': completed >= 3},
            {'id': 4, 'name': 'Ad Link 4: Fintech News Wrap-up', 'reward': 10.0, 'completed': completed >= 4},
            {'id': 5, 'name': 'Ad Link 5: GrowthWorld Tutorials', 'reward': 10.0, 'completed': completed >= 5},
        ]

    daily_reward_amt = round(sum(inv.daily_earning for inv in active_investments), 2) if has_active_plan else 0.0

    return jsonify({
        'has_active_plan': has_active_plan,
        'tasks': tasks,
        'completed_count': completed,
        'reward_claimed': claimed,
        'cooldown_active': cooldown,
        'cooldown_remaining_seconds': cooldown_seconds,
        'daily_reward_amt': daily_reward_amt
    })

@app.route('/api/tasks/complete', methods=['POST'])
@token_required
def complete_task(current_user):
    active_investments = UserInvestment.query.filter_by(user_id=current_user.id, status='active').all()
    if not active_investments:
        return jsonify({'message': 'You must have an active investment plan to perform daily tasks.'}), 400

    today = datetime.datetime.utcnow().strftime('%Y-%m-%d')
    progress = UserTaskProgress.query.filter_by(user_id=current_user.id, date=today).first()
    
    if not progress:
        progress = UserTaskProgress(user_id=current_user.id, date=today, tasks_completed=0)
        db.session.add(progress)
        
    if progress.tasks_completed >= 5:
        return jsonify({'message': 'All 5 tasks for today are already completed.'}), 400

    progress.tasks_completed += 1
    progress.last_task_completed_at = datetime.datetime.utcnow()
    db.session.commit()

    return jsonify({
        'message': f'Task completed successfully! ({progress.tasks_completed}/5)',
        'completed_count': progress.tasks_completed
    })

@app.route('/api/tasks/claim', methods=['POST'])
@token_required
def claim_task_reward(current_user):
    active_investments = UserInvestment.query.filter_by(user_id=current_user.id, status='active').all()
    if not active_investments:
        return jsonify({'message': 'You must have an active investment plan to claim rewards.'}), 400

    today = datetime.datetime.utcnow().strftime('%Y-%m-%d')
    progress = UserTaskProgress.query.filter_by(user_id=current_user.id, date=today).first()
    
    if not progress or progress.tasks_completed < 5:
        return jsonify({'message': 'Please complete all 5 tasks before claiming rewards.'}), 400

    if progress.reward_claimed:
        return jsonify({'message': 'Reward for today already claimed.'}), 400

    # Cooldown checks
    now = datetime.datetime.utcnow()
    if current_user.last_task_claim_at:
        diff = now - current_user.last_task_claim_at
        if diff.total_seconds() < 86400:
            remaining_h = int((86400 - diff.total_seconds()) // 3600)
            remaining_m = int(((86400 - diff.total_seconds()) % 3600) // 60)
            return jsonify({'message': f'Cooldown active. Please wait {remaining_h}h {remaining_m}m to claim again.'}), 400

    # The reward amount is the sum of daily earnings from active investments
    reward_amt = round(sum(inv.daily_earning for inv in active_investments), 2)
    
    # Credit balance
    current_user.wallet_balance += reward_amt
    current_user.last_task_claim_at = now
    progress.reward_claimed = True

    # Update inv.last_payout_at for each active investment to track when it was paid
    for inv in active_investments:
        inv.last_payout_at = now
        db.session.add(inv)

    # Log Transaction
    tx = Transaction(
        user_id=current_user.id,
        amount=reward_amt,
        type='task_reward',
        status='approved',
        description=f"Daily Click & Earn Task Reward"
    )
    
    db.session.add(current_user)
    db.session.add(progress)
    db.session.add(tx)
    db.session.commit()

    return jsonify({
        'message': f'Reward of ₹{reward_amt} successfully claimed!',
        'wallet_balance': current_user.wallet_balance
    })

# ==========================================
# REFERRAL & TEAM API
# ==========================================

@app.route('/api/referrals', methods=['GET'])
@token_required
def get_referral_data(current_user):
    # Retrieve Levels
    level1_users = User.query.filter_by(referred_by_id=current_user.id).all()
    
    level2_users = []
    for u1 in level1_users:
        level2_users.extend(User.query.filter_by(referred_by_id=u1.id).all())
        
    level3_users = []
    for u2 in level2_users:
        level3_users.extend(User.query.filter_by(referred_by_id=u2.id).all())

    # Map team summaries
    def user_summary(u):
        return {
            'email': u.email,
            'phone': u.phone[:4] + '****' + u.phone[-2:],
            'is_active': u.is_active,
            'joined_at': u.created_at.strftime('%Y-%m-%d')
        }

    # Sum up earnings from referral bonus transactions
    ref_earnings = db.session.query(db.func.sum(Transaction.amount)).filter(
        Transaction.user_id == current_user.id,
        Transaction.type == 'referral_bonus',
        Transaction.status == 'approved'
    ).scalar() or 0.0

    return jsonify({
        'referral_code': current_user.referral_code,
        'referral_link': f"{request.url_root}?ref={current_user.referral_code}",
        'referral_earnings': float(ref_earnings),
        'team_size': len(level1_users) + len(level2_users) + len(level3_users),
        'level1': [user_summary(u) for u in level1_users],
        'level2': [user_summary(u) for u in level2_users],
        'level3': [user_summary(u) for u in level3_users]
    })

# ==========================================
# SALARY SYSTEM API
# ==========================================

@app.route('/api/salary', methods=['GET'])
@token_required
def get_salary_status(current_user):
    # Only active direct referrals (Level 1) are counted
    level1 = User.query.filter_by(referred_by_id=current_user.id).all()
    active_ref_count = sum(1 for u in level1 if u.is_active)

    # Determine eligibility levels
    level_a_req = int(get_setting('salary_level_a_referrals', '12'))
    level_b_req = int(get_setting('salary_level_b_referrals', '30'))
    level_c_req = int(get_setting('salary_level_c_referrals', '100'))

    salary_a_amt = float(get_setting('salary_level_a_amount', '5000'))
    salary_b_amt = float(get_setting('salary_level_b_amount', '15000'))
    salary_c_amt = float(get_setting('salary_level_c_amount', '60000'))

    current_tier = "None"
    current_amount = 0.0
    next_tier = "Level A"
    next_req = level_a_req

    if active_ref_count >= level_c_req:
        current_tier = "Level C"
        current_amount = salary_c_amt
        next_tier = "Highest Tier Reached"
        next_req = level_c_req
    elif active_ref_count >= level_b_req:
        current_tier = "Level B"
        current_amount = salary_b_amt
        next_tier = "Level C"
        next_req = level_c_req
    elif active_ref_count >= level_a_req:
        current_tier = "Level A"
        current_amount = salary_a_amt
        next_tier = "Level B"
        next_req = level_b_req

    # Check 30-day claiming cooldown
    cooldown = False
    cooldown_days = 0
    if current_user.last_salary_claim_at:
        diff = datetime.datetime.utcnow() - current_user.last_salary_claim_at
        if diff.days < 30:
            cooldown = True
            cooldown_days = 30 - diff.days

    return jsonify({
        'active_referrals': active_ref_count,
        'level_a_requirement': level_a_req,
        'level_b_requirement': level_b_req,
        'level_c_requirement': level_c_req,
        'current_tier': current_tier,
        'eligible_amount': current_amount,
        'next_tier': next_tier,
        'next_requirement': next_req,
        'cooldown_active': cooldown,
        'cooldown_days_remaining': cooldown_days
    })

@app.route('/api/salary/claim', methods=['POST'])
@token_required
def claim_salary(current_user):
    level1 = User.query.filter_by(referred_by_id=current_user.id).all()
    active_ref_count = sum(1 for u in level1 if u.is_active)

    level_a_req = int(get_setting('salary_level_a_referrals', '12'))
    level_b_req = int(get_setting('salary_level_b_referrals', '30'))
    level_c_req = int(get_setting('salary_level_c_referrals', '100'))

    salary_a_amt = float(get_setting('salary_level_a_amount', '5000'))
    salary_b_amt = float(get_setting('salary_level_b_amount', '15000'))
    salary_c_amt = float(get_setting('salary_level_c_amount', '60000'))

    # Calculate claimable amount
    claimable_amount = 0.0
    tier_label = ""
    if active_ref_count >= level_c_req:
        claimable_amount = salary_c_amt
        tier_label = "Level C"
    elif active_ref_count >= level_b_req:
        claimable_amount = salary_b_amt
        tier_label = "Level B"
    elif active_ref_count >= level_a_req:
        claimable_amount = salary_a_amt
        tier_label = "Level A"

    if claimable_amount <= 0.0:
        return jsonify({'message': f'You are not eligible for salary yet. You need at least {level_a_req} active referrals.'}), 400

    # Cooldown checks (30 days)
    now = datetime.datetime.utcnow()
    if current_user.last_salary_claim_at:
        diff = now - current_user.last_salary_claim_at
        if diff.days < 30:
            return jsonify({'message': f'You can only claim salary once every 30 days. {30 - diff.days} days remaining.'}), 400

    current_user.wallet_balance += claimable_amount
    current_user.last_salary_claim_at = now

    tx = Transaction(
        user_id=current_user.id,
        amount=claimable_amount,
        type='salary',
        status='approved',
        description=f"Monthly referral salary - Tier: {tier_label}"
    )

    db.session.add(current_user)
    db.session.add(tx)
    db.session.commit()

    return jsonify({
        'message': f'Monthly salary of ₹{claimable_amount} claimed successfully!',
        'wallet_balance': current_user.wallet_balance
    })

# ==========================================
# DEPOSITS SYSTEM API
# ==========================================

@app.route('/api/deposits/methods', methods=['GET'])
def get_deposit_methods():
    return jsonify({
        'upi_id': get_setting('upi_id', 'growthworld@upi'),
        'crypto_trc20_address': get_setting('crypto_trc20_address', 'TYxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx'),
        'crypto_bep20_address': get_setting('crypto_bep20_address', '0x71xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx'),
        'qr_code_url': '/static/uploads/' + get_setting('qr_code_filename', 'default_qr.png')
    })

@app.route('/api/deposits', methods=['POST'])
@token_required
def request_deposit(current_user):
    # Form data since file upload is needed
    amount_str = request.form.get('amount')
    method = request.form.get('payment_method')
    utr_number = request.form.get('utr_number')

    if not amount_str or not method or not utr_number:
        return jsonify({'message': 'Amount, payment method, and UTR number are required.'}), 400

    try:
        amount = float(amount_str)
        if amount <= 0:
            raise ValueError()
    except ValueError:
        return jsonify({'message': 'Invalid deposit amount.'}), 400

    # Handle Screenshot Upload
    screenshot_filename = None
    if 'screenshot' in request.files:
        file = request.files['screenshot']
        if file.filename != '':
            ext = os.path.splitext(file.filename)[1].lower()
            if ext not in ['.jpg', '.jpeg', '.png', '.webp']:
                return jsonify({'message': 'Invalid screenshot format. Only PNG, JPG, JPEG, WEBP allowed.'}), 400
            
            # Save file
            filename = f"deposit_{uuid.uuid4().hex}{ext}"
            file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
            screenshot_filename = filename

    if not screenshot_filename:
        return jsonify({'message': 'Payment screenshot is required for deposit verification.'}), 400

    # Create pending transaction
    tx = Transaction(
        user_id=current_user.id,
        amount=amount,
        type='deposit',
        status='pending',
        payment_method=method,
        utr_number=utr_number,
        proof_screenshot=screenshot_filename,
        description=f"Manual deposit via {method}"
    )

    db.session.add(tx)
    db.session.commit()

    return jsonify({'message': 'Deposit request submitted successfully! Pending admin approval.'}), 201

# ==========================================
# WITHDRAWALS SYSTEM API
# ==========================================

@app.route('/api/withdrawals/breakdown', methods=['POST'])
@token_required
def get_withdrawal_breakdown(current_user):
    data = request.get_json() or {}
    amount_str = data.get('amount')
    
    if not amount_str:
        return jsonify({'message': 'Amount is required.'}), 400
        
    try:
        amount = float(amount_str)
        if amount <= 0:
            raise ValueError()
    except ValueError:
        return jsonify({'message': 'Invalid amount.'}), 400

    utc_now = datetime.datetime.utcnow()
    ist_now = utc_now + datetime.timedelta(hours=5, minutes=30)
    is_wednesday = (ist_now.weekday() == 2) # Monday is 0, Wednesday is 2

    if is_wednesday:
        fee_pct = 0.0
        fee = 0.0
    else:
        fee_pct = float(get_setting('withdrawal_fee_pct', '10'))
        fee = round(amount * (fee_pct / 100.0), 2)
        
    payout = round(amount - fee, 2)
    min_withdrawal = float(get_setting('min_withdrawal', '300'))

    # Checks
    insufficient = current_user.wallet_balance < amount
    below_min = amount < min_withdrawal

    # Verify time window (10 AM - 6 PM IST)
    current_hour = ist_now.hour
    allowed_time = 10 <= current_hour < 18

    # Verify withdrawal details
    no_details = not current_user.upi_id and not (current_user.bank_name and current_user.account_number)

    return jsonify({
        'amount': amount,
        'fee': fee,
        'fee_percent': fee_pct,
        'is_wednesday': is_wednesday,
        'payout_amount': payout,
        'min_withdrawal': min_withdrawal,
        'current_balance': current_user.wallet_balance,
        'insufficient_balance': insufficient,
        'below_minimum': below_min,
        'time_allowed': allowed_time,
        'current_ist_time': ist_now.strftime('%H:%M:%S'),
        'details_missing': no_details,
        'bank_info': {
            'upi_id': current_user.upi_id,
            'bank_name': current_user.bank_name,
            'account_number': current_user.account_number,
            'ifsc_code': current_user.ifsc_code
        }
    })

@app.route('/api/withdrawals', methods=['POST'])
@token_required
def request_withdrawal(current_user):
    data = request.get_json() or {}
    amount_str = data.get('amount')
    method = data.get('payment_method', 'bank_upi') # default

    if not amount_str:
        return jsonify({'message': 'Amount is required.'}), 400

    try:
        amount = float(amount_str)
        if amount <= 0:
            raise ValueError()
    except ValueError:
        return jsonify({'message': 'Invalid amount.'}), 400

    min_withdrawal = float(get_setting('min_withdrawal', '300'))
    if amount < min_withdrawal:
        return jsonify({'message': f'Minimum withdrawal amount is ₹{min_withdrawal}.'}), 400

    if current_user.wallet_balance < amount:
        return jsonify({'message': 'Insufficient wallet balance.'}), 400

    # Time window check (10 AM - 6 PM IST)
    utc_now = datetime.datetime.utcnow()
    ist_now = utc_now + datetime.timedelta(hours=5, minutes=30)
    current_hour = ist_now.hour
    if not (10 <= current_hour < 18):
        return jsonify({'message': 'Withdrawals are only permitted between 10:00 AM and 6:00 PM IST.'}), 400

    # Bank credentials check
    if not current_user.upi_id and not (current_user.bank_name and current_user.account_number):
        return jsonify({'message': 'Please update your UPI ID or Bank account details in Profile Settings first.'}), 400

    # Platform fee calculations (Wednesday is fee-free)
    is_wednesday = (ist_now.weekday() == 2)
    if is_wednesday:
        fee_pct = 0.0
        fee = 0.0
    else:
        fee_pct = float(get_setting('withdrawal_fee_pct', '10'))
        fee = round(amount * (fee_pct / 100.0), 2)

    # Immediately lock/deduct the full withdrawal amount to prevent double spending
    current_user.wallet_balance -= amount

    tx = Transaction(
        user_id=current_user.id,
        amount=amount,
        type='withdrawal',
        status='pending',
        payment_method=method,
        fee=fee,
        description=f"Withdrawal request. Fee: ₹{fee}, Payout: ₹{amount - fee} to {current_user.upi_id or current_user.account_number}"
    )

    db.session.add(tx)
    db.session.add(current_user)
    db.session.commit()

    return jsonify({'message': 'Withdrawal request submitted successfully! Deducted from balance and pending admin review.'})

# ==========================================
# HISTORY / TRANSACTIONS API
# ==========================================

@app.route('/api/transactions', methods=['GET'])
@token_required
def list_transactions(current_user):
    txs = Transaction.query.filter_by(user_id=current_user.id).order_by(Transaction.created_at.desc()).all()
    
    txs_data = []
    for t in txs:
        txs_data.append({
            'id': t.id,
            'amount': t.amount,
            'type': t.type,
            'status': t.status,
            'payment_method': t.payment_method,
            'utr_number': t.utr_number,
            'proof_screenshot': '/static/uploads/' + t.proof_screenshot if t.proof_screenshot else None,
            'fee': t.fee,
            'description': t.description,
            'created_at': t.created_at.strftime('%Y-%m-%d %H:%M:%S')
        })
    return jsonify(txs_data)

# ==========================================
# ADMIN DASHBOARD API
# ==========================================

@app.route('/api/admin/stats', methods=['GET'])
@admin_required
def admin_stats(current_user):
    total_users = User.query.count()
    active_users = sum(1 for u in User.query.all() if u.is_active)
    
    # Deposits
    total_deposit_val = db.session.query(db.func.sum(Transaction.amount)).filter(
        Transaction.type == 'deposit',
        Transaction.status == 'approved'
    ).scalar() or 0.0
    pending_deposits_count = Transaction.query.filter_by(type='deposit', status='pending').count()
    
    # Withdrawals
    total_withdrawal_val = db.session.query(db.func.sum(Transaction.amount)).filter(
        Transaction.type == 'withdrawal',
        Transaction.status == 'approved'
    ).scalar() or 0.0
    pending_withdrawals_count = Transaction.query.filter_by(type='withdrawal', status='pending').count()
    
    # Active plan values
    total_invested = db.session.query(db.func.sum(UserInvestment.price)).filter_by(status='active').scalar() or 0.0

    return jsonify({
        'total_users': total_users,
        'active_users': active_users,
        'total_deposited': float(total_deposit_val),
        'pending_deposits': pending_deposits_count,
        'total_withdrawn': float(total_withdrawal_val),
        'pending_withdrawals': pending_withdrawals_count,
        'total_invested': float(total_invested),
        'platform_fee_pct': float(get_setting('withdrawal_fee_pct', '10'))
    })

@app.route('/api/admin/users', methods=['GET', 'PUT'])
@admin_required
def admin_users(current_user):
    if request.method == 'GET':
        users = User.query.all()
        users_list = []
        for u in users:
            users_list.append({
                'id': u.id,
                'email': u.email,
                'phone': u.phone,
                'wallet_balance': u.wallet_balance,
                'upi_id': u.upi_id,
                'bank_name': u.bank_name,
                'account_number': u.account_number,
                'ifsc_code': u.ifsc_code,
                'is_active': u.is_active,
                'is_admin': u.is_admin,
                'created_at': u.created_at.strftime('%Y-%m-%d %H:%M:%S')
            })
        return jsonify(users_list)
        
    elif request.method == 'PUT':
        data = request.get_json() or {}
        user_id = data.get('user_id')
        new_balance = data.get('wallet_balance')
        is_admin_flag = data.get('is_admin')
        
        target_user = User.query.get(user_id)
        if not target_user:
            return jsonify({'message': 'User not found.'}), 404
            
        if new_balance is not None:
            target_user.wallet_balance = float(new_balance)
            
        if is_admin_flag is not None:
            target_user.is_admin = bool(is_admin_flag)
            
        db.session.commit()
        return jsonify({'message': f'User {target_user.email} updated successfully.'})

@app.route('/api/admin/deposits', methods=['GET', 'POST'])
@admin_required
def admin_deposits(current_user):
    if request.method == 'GET':
        deposits = Transaction.query.filter_by(type='deposit').order_by(Transaction.created_at.desc()).all()
        deposits_list = []
        for d in deposits:
            deposits_list.append({
                'id': d.id,
                'user_email': d.user.email,
                'user_phone': d.user.phone,
                'amount': d.amount,
                'status': d.status,
                'payment_method': d.payment_method,
                'utr_number': d.utr_number,
                'proof_screenshot': '/static/uploads/' + d.proof_screenshot if d.proof_screenshot else None,
                'created_at': d.created_at.strftime('%Y-%m-%d %H:%M:%S')
            })
        return jsonify(deposits_list)
        
    elif request.method == 'POST':
        data = request.get_json() or {}
        tx_id = data.get('transaction_id')
        action = data.get('action') # approve or reject
        
        tx = Transaction.query.filter_by(id=tx_id, type='deposit', status='pending').first()
        if not tx:
            return jsonify({'message': 'Pending deposit transaction not found.'}), 404
            
        if action == 'approve':
            tx.status = 'approved'
            # Credit user's wallet
            deposit_owner = tx.user
            deposit_owner.wallet_balance += tx.amount
            db.session.add(deposit_owner)
            db.session.add(tx)
            db.session.commit()
            return jsonify({'message': f'Deposit of ₹{tx.amount} approved. Wallet credited.'})
            
        elif action == 'reject':
            tx.status = 'rejected'
            db.session.add(tx)
            db.session.commit()
            return jsonify({'message': 'Deposit request rejected.'})
            
        return jsonify({'message': 'Invalid action. Specify "approve" or "reject".'}), 400

@app.route('/api/admin/withdrawals', methods=['GET', 'POST'])
@admin_required
def admin_withdrawals(current_user):
    if request.method == 'GET':
        withdrawals = Transaction.query.filter_by(type='withdrawal').order_by(Transaction.created_at.desc()).all()
        withdrawals_list = []
        for w in withdrawals:
            withdrawals_list.append({
                'id': w.id,
                'user_email': w.user.email,
                'user_phone': w.user.phone,
                'amount': w.amount,
                'fee': w.fee,
                'payout_amount': w.amount - w.fee,
                'status': w.status,
                'upi_id': w.user.upi_id,
                'bank_name': w.user.bank_name,
                'account_number': w.user.account_number,
                'ifsc_code': w.user.ifsc_code,
                'created_at': w.created_at.strftime('%Y-%m-%d %H:%M:%S')
            })
        return jsonify(withdrawals_list)
        
    elif request.method == 'POST':
        data = request.get_json() or {}
        tx_id = data.get('transaction_id')
        action = data.get('action') # approve or reject
        
        tx = Transaction.query.filter_by(id=tx_id, type='withdrawal', status='pending').first()
        if not tx:
            return jsonify({'message': 'Pending withdrawal transaction not found.'}), 404
            
        if action == 'approve':
            tx.status = 'approved'
            db.session.add(tx)
            db.session.commit()
            return jsonify({'message': f'Withdrawal of ₹{tx.amount} marked as approved.'})
            
        elif action == 'reject':
            tx.status = 'rejected'
            # Refund the balance to user
            withdrawal_owner = tx.user
            withdrawal_owner.wallet_balance += tx.amount
            db.session.add(withdrawal_owner)
            db.session.add(tx)
            db.session.commit()
            return jsonify({'message': f'Withdrawal request rejected. Refunded ₹{tx.amount} to user balance.'})
            
        return jsonify({'message': 'Invalid action. Specify "approve" or "reject".'}), 400

@app.route('/api/admin/plans', methods=['POST', 'PUT', 'DELETE'])
@admin_required
def admin_manage_plans(current_user):
    if request.method == 'POST':
        # Create plan
        data = request.get_json() or {}
        name = data.get('name')
        price = data.get('price')
        min_earn = data.get('daily_earning_min')
        max_earn = data.get('daily_earning_max')
        duration = data.get('duration_days')

        if not name or price is None or min_earn is None or max_earn is None or not duration:
            return jsonify({'message': 'All plan fields are required.'}), 400

        if float(price) < 1200:
            return jsonify({'message': 'Plan price must be at least ₹1200.'}), 400

        new_plan = InvestmentPlan(
            name=name,
            price=float(price),
            daily_earning_min=float(min_earn),
            daily_earning_max=float(max_earn),
            duration_days=int(duration)
        )
        db.session.add(new_plan)
        db.session.commit()
        return jsonify({'message': f'Plan "{name}" created successfully!'}), 201
        
    elif request.method == 'PUT':
        # Edit plan
        data = request.get_json() or {}
        plan_id = data.get('id')
        plan = InvestmentPlan.query.get(plan_id)
        if not plan:
            return jsonify({'message': 'Plan not found.'}), 404

        plan.name = data.get('name', plan.name)
        if 'price' in data:
            if float(data['price']) < 1200:
                return jsonify({'message': 'Plan price must be at least ₹1200.'}), 400
            plan.price = float(data['price'])
        plan.daily_earning_min = float(data.get('daily_earning_min', plan.daily_earning_min))
        plan.daily_earning_max = float(data.get('daily_earning_max', plan.daily_earning_max))
        plan.duration_days = int(data.get('duration_days', plan.duration_days))
        
        if 'is_active' in data:
            plan.is_active = bool(data['is_active'])

        db.session.commit()
        return jsonify({'message': f'Plan "{plan.name}" updated successfully.'})
        
    elif request.method == 'DELETE':
        # Deactivate plan (we soft delete by setting is_active=False to preserve references in user_investments)
        data = request.get_json() or {}
        plan_id = data.get('id')
        plan = InvestmentPlan.query.get(plan_id)
        if not plan:
            return jsonify({'message': 'Plan not found.'}), 404

        plan.is_active = False
        db.session.commit()
        return jsonify({'message': f'Plan "{plan.name}" deactivated successfully.'})

@app.route('/api/admin/settings', methods=['GET', 'POST'])
@admin_required
def admin_settings(current_user):
    if request.method == 'GET':
        return jsonify({
            'upi_id': get_setting('upi_id', 'growthworld@upi'),
            'crypto_trc20_address': get_setting('crypto_trc20_address', 'TYxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx'),
            'crypto_bep20_address': get_setting('crypto_bep20_address', '0x71xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx'),
            'qr_code_filename': get_setting('qr_code_filename', 'default_qr.png'),
            'withdrawal_fee_pct': float(get_setting('withdrawal_fee_pct', '10')),
            'daily_task_reward': float(get_setting('daily_task_reward', '50')),
            'min_withdrawal': float(get_setting('min_withdrawal', '300')),
            'platform_notice': get_setting('platform_notice', 'Join GrowthWorld Today and Unlock Daily Rewards, Team Bonuses, VIP Benefits & Free Wednesday Withdrawals!'),
            'salary_level_a_referrals': int(get_setting('salary_level_a_referrals', '12')),
            'salary_level_b_referrals': int(get_setting('salary_level_b_referrals', '30')),
            'salary_level_c_referrals': int(get_setting('salary_level_c_referrals', '100')),
            'salary_level_a_amount': float(get_setting('salary_level_a_amount', '5000')),
            'salary_level_b_amount': float(get_setting('salary_level_b_amount', '15000')),
            'salary_level_c_amount': float(get_setting('salary_level_c_amount', '60000')),
        })
        
    elif request.method == 'POST':
        # Handle settings update (JSON or Form Multi-part for QR code upload)
        if request.content_type.startswith('multipart/form-data'):
            # Upload QR code
            if 'qr_code' in request.files:
                file = request.files['qr_code']
                if file.filename != '':
                    ext = os.path.splitext(file.filename)[1].lower()
                    if ext not in ['.jpg', '.jpeg', '.png', '.webp']:
                        return jsonify({'message': 'Invalid file format. Only PNG, JPG, JPEG, WEBP allowed.'}), 400
                    filename = f"qrcode_{uuid.uuid4().hex}{ext}"
                    file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
                    set_setting('qr_code_filename', filename)
            
            # Form fields
            for key in request.form:
                set_setting(key, request.form[key])
        else:
            data = request.get_json() or {}
            for key, val in data.items():
                set_setting(key, val)

        return jsonify({'message': 'Platform settings updated successfully.'})

# ==========================================
# SEED & RUN SETUP
# ==========================================

def seed_database():
    db.create_all()

    # Seed Admin User if none exists
    admin_user = User.query.filter_by(is_admin=True).first()
    if not admin_user:
        hashed = hash_password('AdminPassword123')
        default_admin = User(
            phone='9999999999',
            email='admin@growthworld.com',
            password_hash=hashed,
            referral_code='GW-ADMIN',
            is_admin=True,
            upi_id='admin@upi',
            bank_name='Admin Bank',
            account_number='0000000000',
            ifsc_code='ADMIN0000'
        )
        db.session.add(default_admin)

    # Seed Platform Settings if none exist
    if not PlatformSetting.query.get('upi_id'):
        set_setting('upi_id', 'growthworld@upi')
        set_setting('crypto_trc20_address', 'TYX1234567890CryptoTrc20AddressXYZ')
        set_setting('crypto_bep20_address', '0x1234567890CryptoBep20AddressAbcDef')
        set_setting('qr_code_filename', 'default_qr.png')
        set_setting('withdrawal_fee_pct', '10')
        set_setting('daily_task_reward', '50')
        set_setting('min_withdrawal', '300')
        set_setting('platform_notice', 'Join GrowthWorld Today and Unlock Daily Rewards, Team Bonuses, VIP Benefits & Free Wednesday Withdrawals!')
        set_setting('salary_level_a_referrals', '12')
        set_setting('salary_level_b_referrals', '30')
        set_setting('salary_level_c_referrals', '100')
        set_setting('salary_level_a_amount', '5000')
        set_setting('salary_level_b_amount', '15000')
        set_setting('salary_level_c_amount', '60000')

    # Migration: Delete old plans if migrating to the new system
    if InvestmentPlan.query.filter_by(price=1200).first() is not None:
        UserInvestment.query.delete()
        InvestmentPlan.query.delete()
        db.session.commit()

    # Seed Default Plans if none exist
    if InvestmentPlan.query.count() == 0:
        default_plans = [
            # Active Plans
            InvestmentPlan(name='Starter Active Plan', price=1500, daily_earning_min=90, daily_earning_max=105, duration_days=50, is_active=True),
            InvestmentPlan(name='Bronze Active Plan', price=2200, daily_earning_min=132, daily_earning_max=154, duration_days=50, is_active=True),
            InvestmentPlan(name='Silver Active Plan', price=4500, daily_earning_min=270, daily_earning_max=315, duration_days=50, is_active=True),
            InvestmentPlan(name='Gold Active Plan', price=8000, daily_earning_min=480, daily_earning_max=560, duration_days=50, is_active=True),
            
            # Upcoming Plans (is_active = False)
            InvestmentPlan(name='Platinum Upcoming', price=15000, daily_earning_min=900, daily_earning_max=1050, duration_days=50, is_active=False),
            InvestmentPlan(name='Diamond Upcoming', price=30000, daily_earning_min=1800, daily_earning_max=2100, duration_days=50, is_active=False),
            InvestmentPlan(name='Crown Upcoming', price=65000, daily_earning_min=3900, daily_earning_max=4550, duration_days=50, is_active=False),
            InvestmentPlan(name='GrowthWorld Elite', price=90000, daily_earning_min=5400, daily_earning_max=6300, duration_days=50, is_active=False),
        ]
        db.session.add_all(default_plans)
        
    db.session.commit()

    # Create dummy default_qr.png in static/uploads if it doesn't exist
    qr_path = os.path.join(app.config['UPLOAD_FOLDER'], 'default_qr.png')
    if not os.path.exists(qr_path):
        # Write a tiny dummy 1x1 png or simple visual text image for QR code placeholder
        import base64
        # A tiny transparent 1x1 pixel PNG
        tiny_png = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII=")
        with open(qr_path, 'wb') as f:
            f.write(tiny_png)

import sys
if 'pytest' not in sys.modules and not os.environ.get('PYTEST_CURRENT_TEST'):
    with app.app_context():
        seed_database()

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)

import pytest
import datetime
import jwt
import app as app_module
from app import app, db, User, InvestmentPlan, UserInvestment, UserTaskProgress, Transaction, PlatformSetting, hash_password

@pytest.fixture
def client():
    app.config['TESTING'] = True
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///:memory:'
    
    # Reset Flask-SQLAlchemy state to pick up the new database URI
    if 'sqlalchemy' in app.extensions:
        del app.extensions['sqlalchemy']
        
    with app.app_context():
        db.drop_all()
        db.create_all()
        # Seed settings
        from app import set_setting
        set_setting('upi_id', 'test@upi')
        set_setting('crypto_trc20_address', 'test_trc20')
        set_setting('crypto_bep20_address', 'test_bep20')
        set_setting('withdrawal_fee_pct', '10')
        set_setting('daily_task_reward', '50')
        set_setting('min_withdrawal', '300')
        set_setting('salary_level_a_referrals', '12')
        set_setting('salary_level_a_amount', '5000')
        set_setting('salary_level_b_referrals', '30')
        set_setting('salary_level_b_amount', '15000')
        set_setting('salary_level_c_referrals', '100')
        set_setting('salary_level_c_amount', '60000')

        # Seed test plans
        plan1 = InvestmentPlan(name='Starter Test Plan', price=1500, daily_earning_min=90, daily_earning_max=105, duration_days=50, is_active=True)
        plan2 = InvestmentPlan(name='Bronze Test Plan', price=2200, daily_earning_min=132, daily_earning_max=154, duration_days=50, is_active=True)
        db.session.add(plan1)
        db.session.add(plan2)
        
        # Seed admin
        admin = User(
            phone='9999999999',
            email='admin@growthworld.com',
            password_hash=hash_password('AdminPassword123'),
            referral_code='GW-ADMIN',
            is_admin=True
        )
        db.session.add(admin)
        db.session.commit()

        yield app.test_client()
        db.session.remove()
        db.drop_all()

def get_auth_headers(client, email_or_phone, password):
    res = client.post('/api/auth/login', json={
        'login_id': email_or_phone,
        'password': password
    })
    token = res.get_json()['token']
    return {'Authorization': f'Bearer {token}'}

# ==========================================
# TEST CASES
# ==========================================

def test_signup_login(client):
    # Test Signup
    res = client.post('/api/auth/signup', json={
        'email': 'user1@test.com',
        'phone': '1111111111',
        'password': 'password123',
        'upi_id': 'user1@upi'
    })
    assert res.status_code == 201
    assert 'token' in res.get_json()

    # Test Duplicate Phone
    res = client.post('/api/auth/signup', json={
        'email': 'user2@test.com',
        'phone': '1111111111',
        'password': 'password123'
    })
    assert res.status_code == 400

    # Test Login
    res = client.post('/api/auth/login', json={
        'login_id': 'user1@test.com',
        'password': 'password123'
    })
    assert res.status_code == 200
    assert 'token' in res.get_json()

def test_purchase_plan_and_referrals(client):
    # Create 3-level referral network
    # Admin (Level 3) -> UserA (Level 2) -> UserB (Level 1) -> UserC (buyer)
    # UserA
    res_a = client.post('/api/auth/signup', json={'email': 'usera@test.com', 'phone': '2222222222', 'password': 'password123'})
    code_a = res_a.get_json()['user']['referral_code']
    
    # UserB referred by UserA
    res_b = client.post('/api/auth/signup', json={'email': 'userb@test.com', 'phone': '3333333333', 'password': 'password123', 'referral_code': code_a})
    code_b = res_b.get_json()['user']['referral_code']

    # UserC referred by UserB
    res_c = client.post('/api/auth/signup', json={'email': 'userc@test.com', 'phone': '4444444444', 'password': 'password123', 'referral_code': code_b})
    headers_c = {'Authorization': f"Bearer {res_c.get_json()['token']}"}

    # Verify relationships in DB
    with app.app_context():
        user_c = User.query.filter_by(email='userc@test.com').first()
        user_b = User.query.filter_by(email='userb@test.com').first()
        user_a = User.query.filter_by(email='usera@test.com').first()
        assert user_c.referred_by_id == user_b.id
        assert user_b.referred_by_id == user_a.id

        # Credit UserC wallet to afford plan
        user_c.wallet_balance = 2000.0
        db.session.commit()

    # Get Plan ID
    plans = client.get('/api/plans').get_json()
    # Find active plan Starter Active Plan (price = 1500)
    plan_id = [p['id'] for p in plans if p['price'] == 1500][0]

    # UserC purchases plan
    res_buy = client.post('/api/plans/purchase', headers=headers_c, json={'plan_id': plan_id})
    assert res_buy.status_code == 200

    # Verify wallets and transaction logs for commissions
    with app.app_context():
        user_c = User.query.filter_by(email='userc@test.com').first()
        user_b = User.query.filter_by(email='userb@test.com').first() # Level A parent gets 10%
        user_a = User.query.filter_by(email='usera@test.com').first() # Level B parent gets 2%
        
        # UserC balance: 2000 - 1500 = 500
        assert user_c.wallet_balance == 500.0
        # UserB balance: 1500 * 0.10 = 150
        assert user_b.wallet_balance == 150.0
        # UserA balance: 1500 * 0.02 = 30
        assert user_a.wallet_balance == 30.0

        # Check transactions logged
        tx_b = Transaction.query.filter_by(user_id=user_b.id, type='referral_bonus').first()
        assert tx_b is not None
        assert tx_b.amount == 150.0

def test_daily_tasks(client):
    # Register user
    res = client.post('/api/auth/signup', json={'email': 'taskuser@test.com', 'phone': '5555555555', 'password': 'password123'})
    headers = {'Authorization': f"Bearer {res.get_json()['token']}"}

    # Fetch initial tasks before purchasing a plan -> has_active_plan should be False
    res_tasks_pre = client.get('/api/tasks', headers=headers).get_json()
    assert res_tasks_pre['has_active_plan'] is False
    assert len(res_tasks_pre['tasks']) == 0

    # Try completing task without active plan -> should fail
    res_comp_fail = client.post('/api/tasks/complete', headers=headers)
    assert res_comp_fail.status_code == 400

    # Credit user to purchase a plan
    with app.app_context():
        user = User.query.filter_by(email='taskuser@test.com').first()
        user.wallet_balance = 2000.0
        db.session.commit()

    plans = client.get('/api/plans').get_json()
    plan_id = [p['id'] for p in plans if p['price'] == 1500][0]
    res_buy = client.post('/api/plans/purchase', headers=headers, json={'plan_id': plan_id})
    assert res_buy.status_code == 200

    # Fetch tasks after purchasing a plan -> has_active_plan should be True
    res_tasks = client.get('/api/tasks', headers=headers).get_json()
    assert res_tasks['has_active_plan'] is True
    assert len(res_tasks['tasks']) == 5
    assert res_tasks['completed_count'] == 0
    assert res_tasks['reward_claimed'] is False
    daily_reward_amt = res_tasks['daily_reward_amt']
    assert 90.0 <= daily_reward_amt <= 105.0

    # Complete 5 tasks sequentially
    for i in range(5):
        res_comp = client.post('/api/tasks/complete', headers=headers)
        assert res_comp.status_code == 200
        assert res_comp.get_json()['completed_count'] == i + 1

    # Claim reward
    res_claim = client.post('/api/tasks/claim', headers=headers)
    assert res_claim.status_code == 200
    assert 'successfully claimed' in res_claim.get_json()['message']

    # Verify wallet has task reward (2000 - 1500 + daily_reward_amt)
    with app.app_context():
        user = User.query.filter_by(email='taskuser@test.com').first()
        assert abs(user.wallet_balance - (500.0 + daily_reward_amt)) < 0.01

    # Test Cooldown (claim again should fail)
    res_claim_again = client.post('/api/tasks/claim', headers=headers)
    assert res_claim_again.status_code == 400

def test_withdrawals_constraints(client):
    # Register and credit user
    res = client.post('/api/auth/signup', json={
        'email': 'withdrawuser@test.com', 
        'phone': '6666666666', 
        'password': 'password123',
        'upi_id': 'withdraw@upi'
    })
    headers = {'Authorization': f"Bearer {res.get_json()['token']}"}

    with app.app_context():
        user = User.query.filter_by(email='withdrawuser@test.com').first()
        user.wallet_balance = 1000.0
        db.session.commit()

    from app import datetime as app_datetime
    original_datetime = app_datetime.datetime

    class MockDatetimeThu(original_datetime):
        @classmethod
        def utcnow(cls):
            # Thursday (e.g. 2026-06-25 is Thursday), 12:00:00 (allowed IST hour: 17:30 IST)
            return cls(2026, 6, 25, 12, 0, 0)

    try:
        app_module.datetime.datetime = MockDatetimeThu

        # Get breakdown (fee should be 10%)
        res_bd = client.post('/api/withdrawals/breakdown', headers=headers, json={'amount': 500})
        assert res_bd.status_code == 200
        bd = res_bd.get_json()
        assert bd['amount'] == 500.0
        assert bd['fee'] == 50.0 # 10%
        assert bd['payout_amount'] == 450.0

        # Submit withdrawal request
        res_with = client.post('/api/withdrawals', headers=headers, json={'amount': 500})
        assert res_with.status_code == 200
        
        # Verify wallet deducted
        with app.app_context():
            user = User.query.filter_by(email='withdrawuser@test.com').first()
            assert user.wallet_balance == 500.0 # 1000 - 500
    finally:
        app_module.datetime.datetime = original_datetime

def test_salary_system(client):
    # Create Manager User
    res_mgr = client.post('/api/auth/signup', json={'email': 'manager@test.com', 'phone': '7777777777', 'password': 'password123'})
    mgr_code = res_mgr.get_json()['user']['referral_code']
    mgr_headers = {'Authorization': f"Bearer {res_mgr.get_json()['token']}"}

    # Register 12 referrals under manager
    ref_tokens = []
    for i in range(12):
        res_ref = client.post('/api/auth/signup', json={
            'email': f'ref{i}@test.com', 
            'phone': f'70000000{i:02d}', 
            'password': 'password123',
            'referral_code': mgr_code
        })
        ref_tokens.append(res_ref.get_json()['token'])

    # Verify active referrals count is 0 because they don't have active plans
    res_status = client.get('/api/salary', headers=mgr_headers).get_json()
    assert res_status['active_referrals'] == 0
    assert res_status['level_a_amount'] == 5000.0
    assert res_status['level_b_amount'] == 15000.0
    assert res_status['level_c_amount'] == 60000.0

    # Buy plans for all 12 users to make them active
    # Credit their wallets first
    with app.app_context():
        for i in range(12):
            user = User.query.filter_by(email=f'ref{i}@test.com').first()
            user.wallet_balance = 2000.0
        db.session.commit()

    plans = client.get('/api/plans').get_json()
    plan_id = [p['id'] for p in plans if p['price'] == 1500][0]

    for tok in ref_tokens:
        client.post('/api/plans/purchase', headers={'Authorization': f'Bearer {tok}'}, json={'plan_id': plan_id})

    # Now verify active referrals count is 12 (Level A salary qualified)
    res_status = client.get('/api/salary', headers=mgr_headers).get_json()
    assert res_status['active_referrals'] == 12
    assert res_status['current_tier'] == 'Level A'
    assert res_status['eligible_amount'] == 5000.0

    # Claim salary
    res_claim = client.post('/api/salary/claim', headers=mgr_headers)
    assert res_claim.status_code == 200
    
    with app.app_context():
        mgr = User.query.filter_by(email='manager@test.com').first()
        # Earned 5000 from salary + referral commission!
        # Commissions: 12 referrals * (1500 price * 10% rate) = 1800 commission.
        # Total: 5000 + 1800 = 6800.
        assert mgr.wallet_balance == 6800.0

def test_admin_approvals(client):
    admin_headers = get_auth_headers(client, 'admin@growthworld.com', 'AdminPassword123')
    
    # Create user deposit request
    res_user = client.post('/api/auth/signup', json={'email': 'depuser@test.com', 'phone': '8888888888', 'password': 'password123'})
    user_headers = {'Authorization': f"Bearer {res_user.get_json()['token']}"}

    # Propose pending deposit (UTR: 123456789012)
    # We will upload screenshot in form-data
    import io
    screenshot_file = (io.BytesIO(b"dummy screenshot data"), 'screenshot.png')
    
    res_dep = client.post('/api/deposits', headers=user_headers, data={
        'amount': '1500',
        'payment_method': 'bank_upi',
        'utr_number': '123456789012',
        'screenshot': screenshot_file
    }, content_type='multipart/form-data')
    assert res_dep.status_code == 201

    # Admin lists pending deposits
    res_list = client.get('/api/admin/deposits', headers=admin_headers)
    assert res_list.status_code == 200
    pending_deps = res_list.get_json()
    tx_id = pending_deps[0]['id']

    # Admin approves deposit
    res_app = client.post('/api/admin/deposits', headers=admin_headers, json={
        'transaction_id': tx_id,
        'action': 'approve'
    })
    assert res_app.status_code == 200

    # Verify user's wallet is credited
    with app.app_context():
        user = User.query.filter_by(email='depuser@test.com').first()
        assert user.wallet_balance == 1500.0

def test_wednesday_withdrawal_free(client):
    # Register and credit user
    res = client.post('/api/auth/signup', json={
        'email': 'weduser@test.com', 
        'phone': '9000000099', 
        'password': 'password123',
        'upi_id': 'wed@upi'
    })
    headers = {'Authorization': f"Bearer {res.get_json()['token']}"}

    with app.app_context():
        user = User.query.filter_by(email='weduser@test.com').first()
        user.wallet_balance = 1000.0
        db.session.commit()

    from app import datetime as app_datetime
    original_datetime = app_datetime.datetime
    
    class MockDatetimeWed(original_datetime):
        @classmethod
        def utcnow(cls):
            # Wednesday (e.g. 2026-06-24 is Wednesday)
            return cls(2026, 6, 24, 12, 0, 0)
            
    class MockDatetimeThu(original_datetime):
        @classmethod
        def utcnow(cls):
            # Thursday (e.g. 2026-06-25 is Thursday)
            return cls(2026, 6, 25, 12, 0, 0)
    
    try:
        app_module.datetime.datetime = MockDatetimeWed
        
        res_bd = client.post('/api/withdrawals/breakdown', headers=headers, json={'amount': 500})
        assert res_bd.status_code == 200
        bd = res_bd.get_json()
        assert bd['is_wednesday'] is True
        assert bd['fee'] == 0.0
        assert bd['payout_amount'] == 500.0
        
        # Test Thursday (10% Fee)
        app_module.datetime.datetime = MockDatetimeThu
        
        res_bd_thu = client.post('/api/withdrawals/breakdown', headers=headers, json={'amount': 500})
        assert res_bd_thu.status_code == 200
        bd_thu = res_bd_thu.get_json()
        assert bd_thu['is_wednesday'] is False
        assert bd_thu['fee'] == 50.0
        assert bd_thu['payout_amount'] == 450.0
        
    finally:
        app_module.datetime.datetime = original_datetime

def test_delete_plan_and_purchased_plans(client):
    # 1. Register user
    res_user = client.post('/api/auth/signup', json={
        'email': 'purchasetest@test.com', 
        'phone': '9111111111', 
        'password': 'password123'
    })
    assert res_user.status_code == 201
    user_token = res_user.get_json()['token']
    user_headers = {'Authorization': f'Bearer {user_token}'}

    # 2. Get plans list to find the active plan ID
    plans = client.get('/api/plans').get_json()
    plan = [p for p in plans if p['price'] == 1500][0]
    plan_id = plan['id']

    # 3. Credit wallet and purchase the plan
    with app.app_context():
        user = User.query.filter_by(email='purchasetest@test.com').first()
        user.wallet_balance = 2000.0
        db.session.commit()

    res_buy = client.post('/api/plans/purchase', headers=user_headers, json={'plan_id': plan_id})
    assert res_buy.status_code == 200

    # 4. Verify the plan is in the user's purchased plans list
    res_invs = client.get('/api/user/investments', headers=user_headers)
    assert res_invs.status_code == 200
    invs = res_invs.get_json()
    assert len(invs) == 1
    assert invs[0]['plan_name'] == 'Starter Test Plan'
    assert invs[0]['price'] == 1500.0
    assert invs[0]['status'] == 'active'

    # 5. Verify non-admin cannot delete the plan
    res_del_fail = client.delete('/api/admin/plans', headers=user_headers, json={'id': plan_id})
    assert res_del_fail.status_code in [401, 403] # Unauthorized/Forbidden

    # 6. Admin deletes the plan
    admin_headers = get_auth_headers(client, 'admin@growthworld.com', 'AdminPassword123')
    res_del_success = client.delete('/api/admin/plans', headers=admin_headers, json={'id': plan_id})
    assert res_del_success.status_code == 200
    assert 'completely deleted' in res_del_success.get_json()['message']

    # 7. Verify the plan is removed from db
    with app.app_context():
        assert InvestmentPlan.query.get(plan_id) is None
        assert UserInvestment.query.filter_by(plan_id=plan_id).first() is None

    # 8. Verify the user's investments list is now empty (hard deleted)
    res_invs_post = client.get('/api/user/investments', headers=user_headers)
    assert res_invs_post.status_code == 200
    assert len(res_invs_post.get_json()) == 0

def test_change_password(client):
    # 1. Register a test user
    res_user = client.post('/api/auth/signup', json={
        'email': 'passtest@test.com', 
        'phone': '9222222222', 
        'password': 'password123'
    })
    assert res_user.status_code == 201
    user_id = res_user.get_json()['user']['id']
    user_token = res_user.get_json()['token']
    user_headers = {'Authorization': f'Bearer {user_token}'}

    # 2. Try to change password with incorrect old password -> should fail
    res_change_fail1 = client.post('/api/user/change-password', headers=user_headers, json={
        'old_password': 'wrongpassword',
        'new_password': 'newpassword123'
    })
    assert res_change_fail1.status_code == 400
    assert 'Incorrect old password' in res_change_fail1.get_json()['message']

    # 3. Try to change password with short new password -> should fail
    res_change_fail2 = client.post('/api/user/change-password', headers=user_headers, json={
        'old_password': 'password123',
        'new_password': '123'
    })
    assert res_change_fail2.status_code == 400
    assert 'at least 6 characters' in res_change_fail2.get_json()['message']

    # 4. Change password successfully
    res_change_success = client.post('/api/user/change-password', headers=user_headers, json={
        'old_password': 'password123',
        'new_password': 'newpassword123'
    })
    assert res_change_success.status_code == 200
    assert 'Password changed successfully' in res_change_success.get_json()['message']

    # Verify old password is saved in DB and accessible by admin
    admin_headers = get_auth_headers(client, 'admin@growthworld.com', 'AdminPassword123')
    res_users = client.get('/api/admin/users', headers=admin_headers).get_json()
    u = [usr for usr in res_users if usr['id'] == user_id][0]
    assert u['password_plain'] == 'newpassword123'
    assert u['password_old'] == 'password123'

    # 5. Verify user can log in with new password
    res_login_new = client.post('/api/auth/login', json={
        'login_id': 'passtest@test.com',
        'password': 'newpassword123'
    })
    assert res_login_new.status_code == 200
    assert 'token' in res_login_new.get_json()

    # 6. Verify non-admin cannot change user's password via admin API
    res_admin_fail = client.put('/api/admin/users', headers=user_headers, json={
        'user_id': user_id,
        'new_password': 'adminchanged123'
    })
    assert res_admin_fail.status_code in [401, 403]

    # 7. Admin changes user's password successfully
    res_admin_success = client.put('/api/admin/users', headers=admin_headers, json={
        'user_id': user_id,
        'new_password': 'adminchanged123'
    })
    assert res_admin_success.status_code == 200

    # Verify admin password change updates old password history too
    res_users_post = client.get('/api/admin/users', headers=admin_headers).get_json()
    u_post = [usr for usr in res_users_post if usr['id'] == user_id][0]
    assert u_post['password_plain'] == 'adminchanged123'
    assert u_post['password_old'] == 'newpassword123'

    # 8. Verify user can log in with the admin-changed password
    res_login_admin = client.post('/api/auth/login', json={
        'login_id': 'passtest@test.com',
        'password': 'adminchanged123'
    })
    assert res_login_admin.status_code == 200
    assert 'token' in res_login_admin.get_json()

def test_admin_delete_user(client):
    # 1. Register a test user (User A)
    res_a = client.post('/api/auth/signup', json={
        'email': 'usera@test.com',
        'phone': '9999999001',
        'password': 'password123'
    })
    assert res_a.status_code == 201
    user_a_id = res_a.get_json()['user']['id']
    ref_code_a = res_a.get_json()['user']['referral_code']

    # 2. Register User B, referred by User A
    res_b = client.post('/api/auth/signup', json={
        'email': 'userb@test.com',
        'phone': '9999999002',
        'password': 'password123',
        'referral_code': ref_code_a
    })
    assert res_b.status_code == 201
    user_b_id = res_b.get_json()['user']['id']

    # Verify B is referred by A
    with app.app_context():
        user_b = User.query.get(user_b_id)
        assert user_b.referred_by_id == user_a_id

    # 3. Create some investments and transactions for User A
    with app.app_context():
        # Add UserInvestment
        inv = UserInvestment(
            user_id=user_a_id,
            plan_id=1,
            price=1500.0,
            daily_earning=90.0,
            status='active',
            activated_at=datetime.datetime.utcnow(),
            last_payout_at=datetime.datetime.utcnow(),
            expires_at=datetime.datetime.utcnow() + datetime.timedelta(days=50)
        )
        db.session.add(inv)
        # Add Transaction
        tx = Transaction(
            user_id=user_a_id,
            amount=1500.0,
            type='deposit',
            status='approved'
        )
        db.session.add(tx)
        db.session.commit()

        # Confirm they exist
        assert UserInvestment.query.filter_by(user_id=user_a_id).count() > 0
        assert Transaction.query.filter_by(user_id=user_a_id).count() > 0

    # 4. Admin deletes User A
    admin_headers = get_auth_headers(client, 'admin@growthworld.com', 'AdminPassword123')
    res_del = client.delete('/api/admin/users', headers=admin_headers, json={'user_id': user_a_id})
    assert res_del.status_code == 200
    assert 'completely deleted' in res_del.get_json()['message']

    # 5. Verify User A is gone, and investments and transactions are deleted
    with app.app_context():
        assert User.query.get(user_a_id) is None
        assert UserInvestment.query.filter_by(user_id=user_a_id).count() == 0
        assert Transaction.query.filter_by(user_id=user_a_id).count() == 0

        # Verify User B referred_by_id is now None
        user_b_post = User.query.get(user_b_id)
        assert user_b_post.referred_by_id is None

def test_referral_commission_settings(client):
    admin_headers = get_auth_headers(client, 'admin@growthworld.com', 'AdminPassword123')

    # 1. Verify default referral commissions in settings GET
    res_settings = client.get('/api/admin/settings', headers=admin_headers)
    assert res_settings.status_code == 200
    settings = res_settings.get_json()
    assert settings['ref_commission_a'] == 10.0
    assert settings['ref_commission_b'] == 2.0
    assert settings['ref_commission_c'] == 0.5

    # 2. Update referral commissions using admin settings POST
    res_update = client.post('/api/admin/settings', headers=admin_headers, json={
        'ref_commission_a': 15.0,
        'ref_commission_b': 5.0,
        'ref_commission_c': 1.5
    })
    assert res_update.status_code == 200
    assert 'updated successfully' in res_update.get_json()['message']

    # 3. Verify settings are saved and returned correctly
    res_settings_post = client.get('/api/admin/settings', headers=admin_headers)
    settings_post = res_settings_post.get_json()
    assert settings_post['ref_commission_a'] == 15.0
    assert settings_post['ref_commission_b'] == 5.0
    assert settings_post['ref_commission_c'] == 1.5

    # 4. Verify commissions calculation changes.
    # We will register a chain of referrals: User C (referred by User B, who was referred by User A)
    # Register User A
    res_a = client.post('/api/auth/signup', json={
        'email': 'refa@test.com',
        'phone': '9999999101',
        'password': 'password123'
    })
    assert res_a.status_code == 201
    user_a_id = res_a.get_json()['user']['id']
    ref_code_a = res_a.get_json()['user']['referral_code']

    # Register User B, referred by A
    res_b = client.post('/api/auth/signup', json={
        'email': 'refb@test.com',
        'phone': '9999999102',
        'password': 'password123',
        'referral_code': ref_code_a
    })
    assert res_b.status_code == 201
    user_b_id = res_b.get_json()['user']['id']
    ref_code_b = res_b.get_json()['user']['referral_code']

    # Register User C, referred by B
    res_c = client.post('/api/auth/signup', json={
        'email': 'refc@test.com',
        'phone': '9999999103',
        'password': 'password123',
        'referral_code': ref_code_b
    })
    assert res_c.status_code == 201
    user_c_token = res_c.get_json()['token']
    user_c_headers = {'Authorization': f'Bearer {user_c_token}'}

    # Verify chain: C -> B -> A
    with app.app_context():
        # Fund User C
        user_c = User.query.filter_by(email='refc@test.com').first()
        user_c.wallet_balance = 2000.0
        db.session.commit()

    # Find an active plan ID
    plans = client.get('/api/plans').get_json()
    plan_id = [p for p in plans if p['price'] == 1500][0]['id']

    # Verify referrals endpoint returns the updated rates
    res_refs = client.get('/api/referrals', headers=user_c_headers)
    assert res_refs.status_code == 200
    refs_data = res_refs.get_json()
    assert refs_data['ref_commission_a'] == 15.0
    assert refs_data['ref_commission_b'] == 5.0
    assert refs_data['ref_commission_c'] == 1.5

    # User C purchases a plan for 1500.
    # Level A manager (B) should get 15% of 1500 = 225
    # Level B manager (A) should get 5% of 1500 = 75
    res_buy = client.post('/api/plans/purchase', headers=user_c_headers, json={'plan_id': plan_id})
    assert res_buy.status_code == 200

    # Verify wallet balances of A and B
    with app.app_context():
        user_a_post = User.query.get(user_a_id)
        user_b_post = User.query.get(user_b_id)
        assert user_b_post.wallet_balance == 225.0
        assert user_a_post.wallet_balance == 75.0

        # Check transactions are created
        tx_b = Transaction.query.filter_by(user_id=user_b_id, type='referral_bonus').first()
        assert tx_b is not None
        assert tx_b.amount == 225.0

        tx_a = Transaction.query.filter_by(user_id=user_a_id, type='referral_bonus').first()
        assert tx_a is not None
        assert tx_a.amount == 75.0



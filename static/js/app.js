// ==========================================================================
// GrowthWorld - SPA State & Logic Controller
// ==========================================================================

let state = {
    token: localStorage.getItem('token') || null,
    user: null,
    currentView: 'dashboard',
    plans: [],
    tasks: [],
    referralData: null,
    selectedRefLevel: 1,
    salaryData: null,
    depositMethods: null,
    transactions: [],
    selectedDepositFile: null,
    
    // Admin state
    adminStats: null,
    adminUsers: [],
    adminDeposits: [],
    adminWithdrawals: [],
    adminSettings: null,
    selectedAdminTab: 'deposits'
};

// Initializer
document.addEventListener('DOMContentLoaded', () => {
    initApp();
});

function initApp() {
    // Check url referral parameter
    const urlParams = new URLSearchParams(window.location.search);
    const ref = urlParams.get('ref');

    if (state.token) {
        fetchProfile().then(success => {
            if (success) {
                showMainLayout();
                // Route to hash if present
                const hash = window.location.hash.replace('#', '') || 'dashboard';
                navigateTo(hash);
            } else {
                logoutSession();
                showAuthSection();
            }
        });
    } else {
        showAuthSection();
        if (ref) {
            switchAuthTab('signup');
            const refField = document.getElementById('signup-ref');
            if (refField) refField.value = ref;
            showToast('Referral code loaded!', 'success');
        }
    }
}

// ==========================================
// CORE API UTILITY
// ==========================================
async function apiCall(endpoint, method = 'GET', body = null, isMultipart = false) {
    showLoader();
    const headers = {};
    
    if (state.token) {
        headers['Authorization'] = `Bearer ${state.token}`;
    }
    
    if (!isMultipart && !(body instanceof FormData)) {
        headers['Content-Type'] = 'application/json';
    }

    const config = {
        method: method,
        headers: headers
    };

    if (body) {
        config.body = isMultipart || body instanceof FormData ? body : JSON.stringify(body);
    }

    try {
        const response = await fetch(endpoint, config);
        const data = await response.json();
        
        if (!response.ok) {
            throw new Error(data.message || 'Something went wrong.');
        }
        
        hideLoader();
        return { success: true, data: data };
    } catch (error) {
        hideLoader();
        showToast(error.message, 'danger');
        return { success: false, error: error.message };
    }
}

// ==========================================
// NAVIGATION & SPA ROUTING
// ==========================================
function navigateTo(viewId, params = {}) {
    if (!state.token) {
        showAuthSection();
        return;
    }

    state.currentView = viewId;
    window.location.hash = viewId;

    // Update active nav links
    document.querySelectorAll('.menu-item, .mobile-nav-item').forEach(el => {
        el.classList.remove('active');
        const href = el.getAttribute('href');
        if (href === `#${viewId}`) {
            el.classList.add('active');
        }
    });

    // Hide all sections
    document.querySelectorAll('.content-section').forEach(sec => {
        sec.classList.add('hidden');
    });

    // Show selected section
    const targetSection = document.getElementById(`section-${viewId}`);
    if (targetSection) {
        targetSection.classList.remove('hidden');
    }

    // Scroll to top
    window.scrollTo({ top: 0, behavior: 'smooth' });

    // Load dynamic data for views
    switch (viewId) {
        case 'dashboard':
            loadDashboardData();
            break;
        case 'plans':
            loadPlansData();
            break;
        case 'tasks':
            loadTasksData();
            break;
        case 'referrals':
            loadReferralData();
            break;
        case 'salary':
            loadSalaryData();
            break;
        case 'wallet':
            loadWalletData(params.tab || 'deposit');
            break;
        case 'admin':
            if (state.user && state.user.is_admin) {
                loadAdminData();
            } else {
                navigateTo('dashboard');
                showToast('Access Denied: Admin role required.', 'danger');
            }
            break;
    }
}

// ==========================================
// AUTHENTICATION CLIENT LOGIC
// ==========================================
function switchAuthTab(tab) {
    const loginForm = document.getElementById('login-form');
    const signupForm = document.getElementById('signup-form');
    const loginTabBtn = document.getElementById('tab-login-btn');
    const signupTabBtn = document.getElementById('tab-signup-btn');

    if (tab === 'login') {
        loginForm.classList.remove('hidden');
        signupForm.classList.add('hidden');
        loginTabBtn.classList.add('active');
        signupTabBtn.classList.remove('active');
    } else {
        loginForm.classList.add('hidden');
        signupForm.classList.remove('hidden');
        loginTabBtn.classList.remove('active');
        signupTabBtn.classList.add('active');
    }
}

function toggleSignupBankDetails() {
    const fields = document.getElementById('signup-bank-fields');
    const toggle = document.querySelector('.bank-details-toggle');
    fields.classList.toggle('hidden');
    toggle.classList.toggle('active');
}

async function handleLogin(e) {
    e.preventDefault();
    const loginId = document.getElementById('login-id').value;
    const password = document.getElementById('login-password').value;

    const res = await apiCall('/api/auth/login', 'POST', { login_id: loginId, password: password });
    if (res.success) {
        state.token = res.data.token;
        state.user = res.data.user;
        localStorage.setItem('token', res.data.token);
        
        showToast('Successfully logged in!', 'success');
        showMainLayout();
        navigateTo('dashboard');
        
        // Fetch full profile info to update settings
        fetchProfile();
    }
}

async function handleSignup(e) {
    e.preventDefault();
    const email = document.getElementById('signup-email').value;
    const phone = document.getElementById('signup-phone').value;
    const password = document.getElementById('signup-password').value;
    const refCode = document.getElementById('signup-ref').value;
    
    // Optional Bank Fields
    const upiId = document.getElementById('signup-upi').value;
    const bankName = document.getElementById('signup-bank-name').value;
    const accNum = document.getElementById('signup-bank-acc').value;
    const ifsc = document.getElementById('signup-bank-ifsc').value;

    if (password.length < 6) {
        showToast('Password must be at least 6 characters.', 'warning');
        return;
    }

    const payload = {
        email: email,
        phone: phone,
        password: password,
        referral_code: refCode,
        upi_id: upiId,
        bank_name: bankName,
        account_number: accNum,
        ifsc_code: ifsc
    };

    const res = await apiCall('/api/auth/signup', 'POST', payload);
    if (res.success) {
        state.token = res.data.token;
        state.user = res.data.user;
        localStorage.setItem('token', res.data.token);
        
        showToast('Registration successful! Welcome.', 'success');
        showMainLayout();
        navigateTo('dashboard');
        
        // Fetch full profile info to update settings
        fetchProfile();
    }
}

async function fetchProfile() {
    const res = await apiCall('/api/auth/me');
    if (res.success) {
        state.user = res.data;
        updateUserProfileDOM();
        return true;
    }
    return false;
}

function updateUserProfileDOM() {
    if (!state.user) return;
    
    // Header/Sidebar Profile details
    document.getElementById('user-display-email').textContent = state.user.email;
    document.getElementById('user-avatar-initial').textContent = state.user.email.charAt(0).toUpperCase();
    
    const statusText = state.user.is_active ? 'Active' : 'Inactive';
    const statusEl = document.getElementById('user-display-status');
    const statusMobileEl = document.getElementById('user-display-status-mobile');
    
    statusEl.textContent = statusText;
    statusMobileEl.textContent = statusText;
    
    if (state.user.is_active) {
        statusEl.classList.remove('inactive');
        statusMobileEl.classList.add('active');
        statusMobileEl.classList.remove('inactive');
    } else {
        statusEl.classList.add('inactive');
        statusMobileEl.classList.remove('active');
        statusMobileEl.classList.add('inactive');
    }

    // Toggle Admin Button
    const adminLink = document.getElementById('nav-admin-link');
    if (state.user.is_admin) {
        adminLink.classList.remove('hidden');
    } else {
        adminLink.classList.add('hidden');
    }

    // Fill profile fields in Payout Settings
    document.getElementById('wallet-upi').value = state.user.upi_id || '';
    document.getElementById('wallet-bank-name').value = state.user.bank_name || '';
    document.getElementById('wallet-bank-acc').value = state.user.account_number || '';
    document.getElementById('wallet-bank-ifsc').value = state.user.ifsc_code || '';

    // Render notice board text
    const noticeBoard = document.getElementById('notice-board-text');
    if (noticeBoard && state.user.platform_notice) {
        noticeBoard.textContent = state.user.platform_notice;
    }
}

function handleLogout() {
    logoutSession();
    showAuthSection();
    showToast('Logged out successfully.', 'info');
}

function logoutSession() {
    state.token = null;
    state.user = null;
    localStorage.removeItem('token');
}

function showAuthSection() {
    document.getElementById('auth-section').classList.remove('hidden');
    document.getElementById('main-layout').classList.add('hidden');
}

function showMainLayout() {
    document.getElementById('auth-section').classList.add('hidden');
    document.getElementById('main-layout').classList.remove('hidden');
}

// ==========================================
// DASHBOARD DATA LOADER
// ==========================================
async function loadDashboardData() {
    // Reload profile balance
    await fetchProfile();
    
    document.getElementById('dashboard-wallet-val').textContent = `₹${state.user.wallet_balance.toFixed(2)}`;
    
    // Fetch stats
    const plansRes = await apiCall('/api/plans'); // will return plan details
    const txRes = await apiCall('/api/transactions');
    const tasksRes = await apiCall('/api/tasks');
    const refRes = await apiCall('/api/referrals');
    const salaryRes = await apiCall('/api/salary');

    if (plansRes.success && txRes.success && tasksRes.success && refRes.success && salaryRes.success) {
        // Active investments count
        // We calculate this from transaction types or just check active plans
        // Fetch transactions & count how many active investments the user has
        // Let's filter transaction for plan payouts or just use the details from referrals/salary
        let activeCount = 0;
        let dailyYieldVal = 0;
        
        // Load user investments
        // Since we don't have a separate user-investments api, we can load it from the database on profile or calculate from user active plans.
        // Actually, we added `is_active` to user profile, but wait! Let's get active plan list.
        // To make it easy, we can calculate active plans using a special flag. Let's create an endpoint or compute from active investments count.
        // Let's add active plan count in dashboard details by requesting profile or active plans from backend.
        // Wait, did we provide user investment details in api/auth/me?
        // In backend, User model has relationship investments. Let's query them.
        // Wait, we can fetch the user active investments count from the server.
        // Let's see: we did not write an endpoint for user investments, but we can compute from transaction list, or write a quick endpoint.
        // Actually, let's look at transactions to count. Better, we can add this info to the profile or fetch it.
        // Wait, we can fetch this simply. Let's query transactions of type 'plan_payout' to count active investments, or let's inspect the active plans.
        // Let's modify api/auth/me in app.py to also return `active_investments_count` and `daily_yield_sum`.
        // Let's check: we can compute active investments and daily yield rate on backend and return it in `api/auth/me`.
        // Let's look at app.py: we returned `is_admin`, `is_active` in `/api/auth/me`. We can add:
        // 'active_investments_count': current_user.investments.filter_by(status='active').count(),
        // 'daily_yield_sum': sum(inv.daily_earning for inv in current_user.investments.filter_by(status='active').all())
        // That is perfect! I will run a code replacement on app.py in a moment to include these. For now, let's write the javascript to expect them.
        
        const activeInvestmentsCount = state.user.active_investments_count || 0;
        const dailyYieldSum = state.user.daily_yield_sum || 0;

        document.getElementById('dashboard-active-plans').textContent = activeInvestmentsCount;
        document.getElementById('dashboard-daily-yield').textContent = `₹${dailyYieldSum.toFixed(2)}`;

        // Tasks progress
        const completedCount = tasksRes.data.completed_count;
        document.getElementById('dashboard-task-progress').textContent = `${completedCount}/5`;
        const percentage = (completedCount / 5) * 100;
        document.getElementById('dashboard-task-bar').style.width = `${percentage}%`;
        
        const statusTextEl = document.getElementById('dashboard-task-status-text');
        if (tasksRes.data.reward_claimed) {
            statusTextEl.textContent = 'Daily reward claimed!';
            statusTextEl.className = 'metric-sub text-success';
        } else if (completedCount === 5) {
            statusTextEl.textContent = '5/5 Done! Claim reward now';
            statusTextEl.className = 'metric-sub text-success';
        } else {
            statusTextEl.textContent = 'Complete 5 tasks to unlock ₹50';
            statusTextEl.className = 'metric-sub';
        }

        // Referral metrics
        document.getElementById('dashboard-ref-earnings').textContent = `₹${refRes.data.referral_earnings.toFixed(2)}`;
        document.getElementById('dashboard-team-count').textContent = `Team size: ${refRes.data.team_size} members`;
        document.getElementById('dashboard-active-refs').textContent = `${salaryRes.data.active_referrals} Active`;
        
        const salaryTierEl = document.getElementById('dashboard-salary-tier');
        salaryTierEl.textContent = salaryRes.data.current_tier;
        if (salaryRes.data.current_tier !== 'None') {
            salaryTierEl.className = 'preview-val badge badge-success';
        } else {
            salaryTierEl.className = 'preview-val badge badge-pending';
        }

        // Recent Transactions Preview
        const txListContainer = document.getElementById('dashboard-tx-list');
        txListContainer.innerHTML = '';
        const recentTx = txRes.data.slice(0, 3);
        
        if (recentTx.length === 0) {
            txListContainer.innerHTML = '<div class="no-data">No transactions found.</div>';
        } else {
            recentTx.forEach(tx => {
                const item = document.createElement('div');
                item.className = 'tx-preview-item';
                
                let amtSign = '+';
                let amtClass = 'positive';
                if (['purchase', 'withdrawal'].includes(tx.type)) {
                    amtSign = '-';
                    amtClass = 'negative';
                }
                
                // Capitalize type
                const typeLabel = tx.type.replace('_', ' ').toUpperCase();
                
                item.innerHTML = `
                    <div class="tx-preview-details">
                        <span class="tx-preview-title">${typeLabel}</span>
                        <span class="tx-preview-date">${tx.created_at}</span>
                    </div>
                    <div class="tx-preview-amt ${amtClass}">
                        ${amtSign}₹${tx.amount.toFixed(2)}
                    </div>
                `;
                txListContainer.appendChild(item);
            });
        }
        await loadPurchasedPlans();
    }
}

async function loadPurchasedPlans() {
    const res = await apiCall('/api/user/investments');
    if (res.success) {
        const tbody = document.getElementById('purchased-plans-tbody');
        if (!tbody) return;
        tbody.innerHTML = '';
        
        if (res.data.length === 0) {
            tbody.innerHTML = `
                <tr>
                    <td colspan="6" style="text-align: center; color: var(--text-muted); padding: 20px;">No purchased plans found.</td>
                </tr>
            `;
        } else {
            res.data.forEach(inv => {
                const tr = document.createElement('tr');
                tr.style.borderBottom = '1px solid var(--border-color)';
                
                let statusBadge = '';
                if (inv.status === 'active') {
                    statusBadge = `<span class="badge" style="background: rgba(16, 185, 129, 0.2); color: #10B981; padding: 4px 8px; border-radius: 6px; font-size: 11px; font-weight: 700;">Active</span>`;
                } else {
                    statusBadge = `<span class="badge" style="background: rgba(239, 68, 68, 0.2); color: #EF4444; padding: 4px 8px; border-radius: 6px; font-size: 11px; font-weight: 700;">Expired</span>`;
                }
                
                tr.innerHTML = `
                    <td style="padding: 12px 8px; font-weight: 600; color: #fff;">${inv.plan_name}</td>
                    <td style="padding: 12px 8px;">₹${inv.price.toFixed(2)}</td>
                    <td style="padding: 12px 8px; color: var(--color-success);">₹${inv.daily_earning.toFixed(2)}/day</td>
                    <td style="padding: 12px 8px; font-size: 12px; color: var(--text-muted);">${inv.activated_at}</td>
                    <td style="padding: 12px 8px; font-size: 12px; color: var(--text-muted);">${inv.expires_at}</td>
                    <td style="padding: 12px 8px;">${statusBadge}</td>
                `;
                tbody.appendChild(tr);
            });
        }
    }
}

// ==========================================
// PLANS CLIENT LOGIC
// ==========================================
async function loadPlansData() {
    const res = await apiCall('/api/plans');
    if (res.success) {
        state.plans = res.data;
        renderPlans();
    }
}

function renderPlans() {
    const container = document.getElementById('plans-container');
    container.innerHTML = '';
    
    if (state.plans.length === 0) {
        container.innerHTML = '<div class="no-data" style="grid-column: 1 / -1">No investment plans available.</div>';
        return;
    }

    const activePlans = state.plans.filter(p => p.is_active);
    const upcomingPlans = state.plans.filter(p => !p.is_active);

    if (activePlans.length > 0) {
        const activeHeader = document.createElement('h3');
        activeHeader.style.gridColumn = '1 / -1';
        activeHeader.style.textAlign = 'left';
        activeHeader.style.margin = '16px 0';
        activeHeader.style.fontSize = '20px';
        activeHeader.style.color = 'var(--color-success)';
        activeHeader.textContent = 'Active Plans';
        container.appendChild(activeHeader);

        activePlans.forEach(plan => {
            const card = document.createElement('div');
            card.className = 'plan-card';
            card.innerHTML = `
                <div class="plan-name">${plan.name}</div>
                <div class="plan-price-box">
                    <div class="plan-price-label">Price</div>
                    <div class="plan-price-val">₹${plan.price.toLocaleString('en-IN')}</div>
                </div>
                <div class="plan-specs">
                    <div class="plan-spec-item">
                        <span class="label">Daily Return (6%-7%):</span>
                        <span class="val text-success">₹${plan.daily_earning_min} - ₹${plan.daily_earning_max}</span>
                    </div>
                    <div class="plan-spec-item">
                        <span class="label">Duration:</span>
                        <span class="val">${plan.duration_days} Days</span>
                    </div>
                    <div class="plan-spec-item">
                        <span class="label">Total Profit:</span>
                        <span class="val">₹${(plan.daily_earning_min * plan.duration_days).toFixed(0)} - ₹${(plan.daily_earning_max * plan.duration_days).toFixed(0)}</span>
                    </div>
                </div>
                <button class="btn btn-primary btn-block" onclick="buyPlan(${plan.id}, '${plan.name}', ${plan.price})">Activate Plan</button>
            `;
            container.appendChild(card);
        });
    }

    if (upcomingPlans.length > 0) {
        const upcomingHeader = document.createElement('h3');
        upcomingHeader.style.gridColumn = '1 / -1';
        upcomingHeader.style.textAlign = 'left';
        upcomingHeader.style.margin = '32px 0 16px 0';
        upcomingHeader.style.fontSize = '20px';
        upcomingHeader.style.color = 'var(--text-muted)';
        upcomingHeader.style.borderTop = '1px solid var(--border-color)';
        upcomingHeader.style.paddingTop = '24px';
        upcomingHeader.textContent = 'Upcoming Plans';
        container.appendChild(upcomingHeader);

        upcomingPlans.forEach(plan => {
            const card = document.createElement('div');
            card.className = 'plan-card disabled';
            card.style.opacity = '0.6';
            card.innerHTML = `
                <div class="plan-name" style="color: var(--text-muted);">${plan.name}</div>
                <div class="plan-price-box">
                    <div class="plan-price-label">Price</div>
                    <div class="plan-price-val" style="color: var(--text-muted);">₹${plan.price.toLocaleString('en-IN')}</div>
                </div>
                <div class="plan-specs">
                    <div class="plan-spec-item">
                        <span class="label">Daily Return (6%-7%):</span>
                        <span class="val text-muted">₹${plan.daily_earning_min} - ₹${plan.daily_earning_max}</span>
                    </div>
                    <div class="plan-spec-item">
                        <span class="label">Duration:</span>
                        <span class="val">${plan.duration_days} Days</span>
                    </div>
                    <div class="plan-spec-item">
                        <span class="label">Total Profit:</span>
                        <span class="val">₹${(plan.daily_earning_min * plan.duration_days).toFixed(0)} - ₹${(plan.daily_earning_max * plan.duration_days).toFixed(0)}</span>
                    </div>
                </div>
                <button class="btn btn-outline btn-block disabled" disabled style="background: rgba(255,255,255,0.02);">Locked / Coming Soon</button>
            `;
            container.appendChild(card);
        });
    }
}

async function buyPlan(planId, name, price) {
    const confirmBuy = confirm(`Are you sure you want to purchase and activate the "${name}" for ₹${price}?`);
    if (!confirmBuy) return;

    const res = await apiCall('/api/plans/purchase', 'POST', { plan_id: planId });
    if (res.success) {
        showToast(res.data.message, 'success');
        navigateTo('dashboard');
    }
}

// ==========================================
// DAILY TASKS CLIENT LOGIC
// ==========================================
async function loadTasksData() {
    const res = await apiCall('/api/tasks');
    if (res.success) {
        state.tasks = res.data.tasks;
        const noPlanWarning = document.getElementById('tasks-no-plan-warning');
        const mainLayout = document.getElementById('tasks-main-layout');
        
        if (res.data.has_active_plan) {
            if (noPlanWarning) noPlanWarning.classList.add('hidden');
            if (mainLayout) mainLayout.classList.remove('hidden');
            renderTasks(res.data);
        } else {
            if (noPlanWarning) noPlanWarning.classList.remove('hidden');
            if (mainLayout) mainLayout.classList.add('hidden');
        }
    }
}

function renderTasks(taskData) {
    const listContainer = document.getElementById('tasks-list-container');
    listContainer.innerHTML = '';

    // Update Circle Progress
    const completed = taskData.completed_count;
    document.getElementById('task-completed-text').textContent = `${completed}/5`;
    document.getElementById('task-reward-value').textContent = `₹${taskData.daily_reward_amt.toFixed(2)}`;

    // SVG circle animation (Formula: offset = 314.15 * (1 - (completed / 5)))
    const offset = 314.15 * (1 - (completed / 5));
    document.getElementById('task-circle-fill').style.strokeDashoffset = offset;

    // Claim Button Control
    const claimBtn = document.getElementById('claim-task-reward-btn');
    const cooldownText = document.getElementById('task-cooldown-text');
    
    if (taskData.cooldown_active) {
        claimBtn.classList.add('disabled');
        claimBtn.disabled = true;
        cooldownText.classList.remove('hidden');
        
        // Start countdown timer for cooldown
        let cooldownSec = taskData.cooldown_remaining_seconds;
        clearInterval(window.taskCooldownTimer);
        window.taskCooldownTimer = setInterval(() => {
            cooldownSec--;
            if (cooldownSec <= 0) {
                clearInterval(window.taskCooldownTimer);
                loadTasksData();
            } else {
                const h = Math.floor(cooldownSec / 3600);
                const m = Math.floor((cooldownSec % 3600) / 60);
                const s = cooldownSec % 60;
                cooldownText.textContent = `Cooldown Active: ${h}h ${m}m ${s}s remaining`;
            }
        }, 1000);
    } else {
        clearInterval(window.taskCooldownTimer);
        cooldownText.classList.add('hidden');
        if (completed === 5 && !taskData.reward_claimed) {
            claimBtn.classList.remove('disabled');
            claimBtn.disabled = false;
        } else {
            claimBtn.classList.add('disabled');
            claimBtn.disabled = true;
        }
    }

    if (taskData.reward_claimed) {
        claimBtn.textContent = 'Reward Claimed';
        claimBtn.classList.add('disabled');
        claimBtn.disabled = true;
    } else {
        claimBtn.textContent = 'Claim Reward';
    }

    // List out tasks
    state.tasks.forEach(task => {
        const item = document.createElement('div');
        item.className = `task-item-card ${task.completed ? 'completed' : ''}`;
        
        let actionBtnHTML = `<button class="btn btn-outline btn-small" onclick="startTask(${task.id}, '${task.name}')">Start Click</button>`;
        if (task.completed) {
            actionBtnHTML = `
                <span class="task-item-status-icon">
                    <svg viewBox="0 0 24 24"><path fill="currentColor" d="M9 16.17L4.83 12l-1.42 1.41L9 19 21 7l-1.41-1.41z"/></svg>
                    Completed
                </span>
            `;
        } else if (completed < task.id - 1) {
            // Task must be done in sequential order
            actionBtnHTML = `<button class="btn btn-outline btn-small disabled" disabled>Locked</button>`;
        }

        item.innerHTML = `
            <div class="task-item-details">
                <span class="task-item-name">${task.name}</span>
                <span class="task-item-reward">Reward: Sequential Click</span>
            </div>
            <div class="task-item-action">
                ${actionBtnHTML}
            </div>
        `;
        listContainer.appendChild(item);
    });
}

function startTask(taskId, taskName) {
    const modal = document.getElementById('task-modal');
    const countdownEl = document.getElementById('task-modal-countdown');
    const titleEl = document.getElementById('task-modal-title');

    titleEl.textContent = `Visiting: ${taskName}`;
    modal.classList.remove('hidden');

    let sec = 5;
    countdownEl.textContent = sec;

    const timer = setInterval(async () => {
        sec--;
        countdownEl.textContent = sec;
        
        if (sec <= 0) {
            clearInterval(timer);
            modal.classList.add('hidden');
            
            // Execute completion on API
            const res = await apiCall('/api/tasks/complete', 'POST');
            if (res.success) {
                showToast(res.data.message, 'success');
                loadTasksData();
            }
        }
    }, 1000);
}

async function handleClaimTaskReward() {
    const res = await apiCall('/api/tasks/claim', 'POST');
    if (res.success) {
        showToast(res.data.message, 'success');
        loadTasksData();
        fetchProfile(); // reload balance
    }
}

// ==========================================
// REFERRALS NETWORK LOGIC
// ==========================================
async function loadReferralData() {
    const res = await apiCall('/api/referrals');
    if (res.success) {
        state.referralData = res.data;
        document.getElementById('referral-link-input').value = res.data.referral_link;
        document.getElementById('ref-stat-earnings').textContent = `₹${res.data.referral_earnings.toFixed(2)}`;
        document.getElementById('ref-stat-team').textContent = res.data.team_size;

        document.getElementById('ref-count-l1').textContent = `(${res.data.level1.length})`;
        document.getElementById('ref-count-l2').textContent = `(${res.data.level2.length})`;
        document.getElementById('ref-count-l3').textContent = `(${res.data.level3.length})`;

        const pctL1 = document.getElementById('ref-pct-l1');
        const pctL2 = document.getElementById('ref-pct-l2');
        const pctL3 = document.getElementById('ref-pct-l3');
        if (pctL1) pctL1.textContent = res.data.ref_commission_a;
        if (pctL2) pctL2.textContent = res.data.ref_commission_b;
        if (pctL3) pctL3.textContent = res.data.ref_commission_c;

        renderReferralsTable();
    }
}

function switchReferralLevel(level) {
    state.selectedRefLevel = level;
    document.querySelectorAll('.ref-tab-btn').forEach(btn => {
        btn.classList.remove('active');
    });
    document.getElementById(`ref-tab-l${level}`).classList.add('active');
    renderReferralsTable();
}

function renderReferralsTable() {
    const tbody = document.getElementById('referral-team-tbody');
    tbody.innerHTML = '';

    if (!state.referralData) return;

    const teamList = state.referralData[`level${state.selectedRefLevel}`] || [];

    if (teamList.length === 0) {
        tbody.innerHTML = `<tr><td colspan="4" class="no-data">No team members found in Level ${state.selectedRefLevel}.</td></tr>`;
        return;
    }

    teamList.forEach(member => {
        const row = document.createElement('tr');
        const statusHTML = member.is_active 
            ? `<span class="badge badge-success">Active</span>` 
            : `<span class="badge badge-pending">Inactive</span>`;
            
        row.innerHTML = `
            <td>${member.email}</td>
            <td>${member.phone}</td>
            <td>${statusHTML}</td>
            <td>${member.joined_at}</td>
        `;
        tbody.appendChild(row);
    });
}

function copyReferralLink() {
    const input = document.getElementById('referral-link-input');
    input.select();
    input.setSelectionRange(0, 99999); // for mobile
    navigator.clipboard.writeText(input.value);
    showToast('Referral link copied to clipboard!', 'success');
}

// ==========================================
// SALARY SYSTEM CLIENT LOGIC
// ==========================================
async function loadSalaryData() {
    const res = await apiCall('/api/salary');
    if (res.success) {
        state.salaryData = res.data;
        
        document.getElementById('salary-active-count').textContent = `${res.data.active_referrals} Users`;
        document.getElementById('salary-current-tier').textContent = res.data.current_tier;
        document.getElementById('salary-claim-amount').textContent = `₹${res.data.eligible_amount.toFixed(2)}`;

        // Update milestone requirements and amounts dynamically from configured settings
        const tierAReqEl = document.getElementById('label-tier-a-req');
        const tierAAmtEl = document.getElementById('label-tier-a-amt');
        const tierBReqEl = document.getElementById('label-tier-b-req');
        const tierBAmtEl = document.getElementById('label-tier-b-amt');
        const tierCReqEl = document.getElementById('label-tier-c-req');
        const tierCAmtEl = document.getElementById('label-tier-c-amt');

        if (tierAReqEl) tierAReqEl.textContent = `${res.data.level_a_requirement} active users`;
        if (tierAAmtEl) tierAAmtEl.textContent = `₹${res.data.level_a_amount.toLocaleString('en-IN')} / month`;
        if (tierBReqEl) tierBReqEl.textContent = `${res.data.level_b_requirement} active users`;
        if (tierBAmtEl) tierBAmtEl.textContent = `₹${res.data.level_b_amount.toLocaleString('en-IN')} / month`;
        if (tierCReqEl) tierCReqEl.textContent = `${res.data.level_c_requirement} active users`;
        if (tierCAmtEl) tierCAmtEl.textContent = `₹${res.data.level_c_amount.toLocaleString('en-IN')} / month`;

        // Describe tier details
        const detailsEl = document.getElementById('salary-tier-details');
        const claimBtn = document.getElementById('claim-salary-btn');
        
        if (res.data.current_tier !== 'None') {
            detailsEl.textContent = `Eligible for ${res.data.current_tier} Monthly Reward!`;
            if (!res.data.cooldown_active) {
                claimBtn.classList.remove('disabled');
                claimBtn.disabled = false;
            } else {
                claimBtn.classList.add('disabled');
                claimBtn.disabled = true;
            }
        } else {
            detailsEl.textContent = `You need ${res.data.level_a_requirement} active referrals to reach Level A.`;
            claimBtn.classList.add('disabled');
            claimBtn.disabled = true;
        }

        // Handle Cooldown Text
        const cooldownText = document.getElementById('salary-cooldown-text');
        if (res.data.cooldown_active) {
            cooldownText.classList.remove('hidden');
            cooldownText.textContent = `Salary claimed. Cooldown: ${res.data.cooldown_days_remaining} days remaining.`;
        } else {
            cooldownText.classList.add('hidden');
        }

        // Update progress bars for timeline
        updateSalaryMilestoneProgress(res.data.active_referrals, res.data.level_a_requirement, 'a', res.data.level_a_requirement);
        updateSalaryMilestoneProgress(res.data.active_referrals, res.data.level_b_requirement, 'b', res.data.level_b_requirement);
        updateSalaryMilestoneProgress(res.data.active_referrals, res.data.level_c_requirement, 'c', res.data.level_c_requirement);
    }
}

function updateSalaryMilestoneProgress(active, req, prefix, maxVal) {
    const bar = document.getElementById(`bar-tier-${prefix}`);
    const card = document.getElementById(`tier-card-${prefix}`);
    
    const percentage = Math.min((active / req) * 100, 100);
    bar.style.width = `${percentage}%`;

    if (active >= req) {
        card.classList.add('active-milestone');
    } else {
        card.classList.remove('active-milestone');
    }
}

async function handleClaimSalary() {
    const res = await apiCall('/api/salary/claim', 'POST');
    if (res.success) {
        showToast(res.data.message, 'success');
        loadSalaryData();
        fetchProfile();
    }
}

// ==========================================
// WALLET, DEPOSIT, WITHDRAWAL CLIENT LOGIC
// ==========================================
function switchWalletTab(tab) {
    document.querySelectorAll('.wallet-tab-btn').forEach(btn => {
        btn.classList.remove('active');
    });
    document.getElementById(`wallet-tab-${tab}`).classList.add('active');

    // Panels
    document.querySelectorAll('.wallet-panel').forEach(panel => {
        panel.classList.add('hidden');
    });
    document.getElementById(`wallet-panel-${tab}`).classList.remove('hidden');

    if (tab === 'deposit') {
        loadDepositMethods();
    } else if (tab === 'withdraw') {
        calculateWithdrawalBreakdown();
    } else if (tab === 'history') {
        loadTransactionHistory();
    }
}

async function loadWalletData(defaultTab) {
    await fetchProfile();
    document.getElementById('wallet-balance-amount').textContent = `₹${state.user.wallet_balance.toFixed(2)}`;
    switchWalletTab(defaultTab);
}

// Deposit info fetcher
async function loadDepositMethods() {
    const res = await apiCall('/api/deposits/methods');
    if (res.success) {
        state.depositMethods = res.data;
        document.getElementById('deposit-qr-code').src = res.data.qr_code_url;
        document.getElementById('deposit-upi-val').textContent = res.data.upi_id;
        document.getElementById('deposit-trc-val').textContent = res.data.crypto_trc20_address;
        document.getElementById('deposit-bep-val').textContent = res.data.crypto_bep20_address;
    }
}

// File Dialog Helpers
function triggerFileInput(inputId) {
    document.getElementById(inputId).click();
}

function handleFileSelected(e) {
    const file = e.target.files[0];
    if (file) {
        state.selectedDepositFile = file;
        const uploadBox = document.querySelector('.file-upload-box');
        const uploadLabel = document.getElementById('upload-label');
        
        uploadBox.classList.add('selected');
        uploadLabel.textContent = `Selected: ${file.name} (${(file.size / 1024).toFixed(1)} KB)`;
    }
}

async function handleDepositSubmit(e) {
    e.preventDefault();
    const amount = document.getElementById('deposit-amount').value;
    const method = document.getElementById('deposit-method').value;
    const utr = document.getElementById('deposit-utr').value;

    if (!state.selectedDepositFile) {
        showToast('Please upload a screenshot of your payment.', 'warning');
        return;
    }

    const formData = new FormData();
    formData.append('amount', amount);
    formData.append('payment_method', method);
    formData.append('utr_number', utr);
    formData.append('screenshot', state.selectedDepositFile);

    const res = await apiCall('/api/deposits', 'POST', formData, true);
    if (res.success) {
        showToast(res.data.message, 'success');
        
        // Reset Form
        document.getElementById('deposit-form').reset();
        state.selectedDepositFile = null;
        
        const uploadBox = document.querySelector('.file-upload-box');
        uploadBox.classList.remove('selected');
        document.getElementById('upload-label').textContent = 'Drag & Drop or Click to Upload';
        
        switchWalletTab('history');
    }
}

// Withdrawal Live breakdown calculation
async function calculateWithdrawalBreakdown() {
    const amountInput = document.getElementById('withdraw-amount');
    const amount = parseFloat(amountInput.value) || 0;

    const breakdownEl = document.getElementById('withdrawal-breakdown');
    const confirmBtn = document.getElementById('submit-withdrawal-btn');

    if (amount <= 0) {
        document.getElementById('bd-raw-amount').textContent = '₹0.00';
        document.getElementById('bd-fee').textContent = '-₹0.00';
        document.getElementById('bd-final-payout').textContent = '₹0.00';
        return;
    }

    const res = await apiCall('/api/withdrawals/breakdown', 'POST', { amount: amount });
    if (res.success) {
        const bd = res.data;
        document.getElementById('bd-raw-amount').textContent = `₹${bd.amount.toFixed(2)}`;
        document.getElementById('bd-fee').textContent = `-₹${bd.fee.toFixed(2)} (${bd.fee_percent}%)`;
        document.getElementById('bd-final-payout').textContent = `₹${bd.payout_amount.toFixed(2)}`;

        // Check validation blocks
        if (bd.insufficient_balance) {
            confirmBtn.disabled = true;
            confirmBtn.classList.add('disabled');
            confirmBtn.textContent = 'Insufficient Wallet Balance';
        } else if (bd.below_minimum) {
            confirmBtn.disabled = true;
            confirmBtn.classList.add('disabled');
            confirmBtn.textContent = `Min withdrawal ₹${bd.min_withdrawal}`;
        } else if (!bd.time_allowed) {
            confirmBtn.disabled = true;
            confirmBtn.classList.add('disabled');
            confirmBtn.textContent = 'Outside Hours (10 AM - 6 PM IST)';
        } else if (bd.details_missing) {
            confirmBtn.disabled = true;
            confirmBtn.classList.add('disabled');
            confirmBtn.textContent = 'Configure Payout Details First';
        } else {
            confirmBtn.disabled = false;
            confirmBtn.classList.remove('disabled');
            confirmBtn.textContent = 'Confirm Withdrawal';
        }
    }
}

async function handleWithdrawSubmit(e) {
    e.preventDefault();
    const amount = document.getElementById('withdraw-amount').value;
    const method = document.getElementById('withdraw-method').value;

    const confirmWithdraw = confirm(`Submit withdrawal request for ₹${amount}? 10% platform fee will be deducted.`);
    if (!confirmWithdraw) return;

    const res = await apiCall('/api/withdrawals', 'POST', { amount: amount, payment_method: method });
    if (res.success) {
        showToast(res.data.message, 'success');
        document.getElementById('withdraw-amount').value = '';
        calculateWithdrawalBreakdown();
        loadWalletData('history');
    }
}

async function handleUpdateBankDetails(e) {
    e.preventDefault();
    const upi = document.getElementById('wallet-upi').value;
    const bank = document.getElementById('wallet-bank-name').value;
    const acc = document.getElementById('wallet-bank-acc').value;
    const ifsc = document.getElementById('wallet-bank-ifsc').value;

    const res = await apiCall('/api/user/bank-details', 'PUT', {
        upi_id: upi,
        bank_name: bank,
        account_number: acc,
        ifsc_code: ifsc
    });
    
    if (res.success) {
        showToast(res.data.message, 'success');
        fetchProfile();
    }
}

async function loadTransactionHistory() {
    const res = await apiCall('/api/transactions');
    if (res.success) {
        const tbody = document.getElementById('wallet-history-tbody');
        tbody.innerHTML = '';
        
        if (res.data.length === 0) {
            tbody.innerHTML = `<tr><td colspan="6" class="no-data">No transactions logged.</td></tr>`;
            return;
        }

        res.data.forEach(t => {
            const row = document.createElement('tr');
            
            let statusClass = 'badge-pending';
            if (t.status === 'approved') statusClass = 'badge-success';
            if (t.status === 'rejected') statusClass = 'badge-danger';
            
            const statusBadge = `<span class="badge ${statusClass}">${t.status}</span>`;
            
            row.innerHTML = `
                <td>${t.created_at}</td>
                <td><strong style="text-transform: uppercase; font-size:12px;">${t.type.replace('_', ' ')}</strong></td>
                <td>₹${t.amount.toFixed(2)}</td>
                <td><code>${t.utr_number || 'N/A'}</code></td>
                <td>${statusBadge}</td>
                <td class="text-muted text-small">${t.description || ''}</td>
            `;
            tbody.appendChild(row);
        });
    }
}

// ==========================================
// ADMIN CONTROL LOGIC
// ==========================================
async function loadAdminData() {
    switchAdminTab(state.selectedAdminTab);
    loadAdminStats();
}

async function loadAdminStats() {
    const res = await apiCall('/api/admin/stats');
    if (res.success) {
        state.adminStats = res.data;
        document.getElementById('admin-stat-users').textContent = res.data.total_users;
        document.getElementById('admin-stat-active-users').textContent = res.data.active_users;
        document.getElementById('admin-stat-deposits').textContent = `₹${res.data.total_deposited.toFixed(2)}`;
        document.getElementById('admin-stat-withdrawals').textContent = `₹${res.data.total_withdrawn.toFixed(2)}`;
        document.getElementById('admin-stat-invested').textContent = `₹${res.data.total_invested.toFixed(2)}`;

        // Pending notifications count badge
        document.getElementById('admin-pending-dep-count').textContent = res.data.pending_deposits;
        document.getElementById('admin-pending-with-count').textContent = res.data.pending_withdrawals;
    }
}

function switchAdminTab(tab) {
    state.selectedAdminTab = tab;
    document.querySelectorAll('.admin-tab-btn').forEach(btn => {
        btn.classList.remove('active');
    });
    document.getElementById(`admin-tab-${tab}`).classList.add('active');

    // Panels
    document.querySelectorAll('.admin-panel-content').forEach(p => {
        p.classList.add('hidden');
    });
    document.getElementById(`admin-panel-${tab}`).classList.remove('hidden');

    switch (tab) {
        case 'deposits':
            loadAdminDeposits();
            break;
        case 'withdrawals':
            loadAdminWithdrawals();
            break;
        case 'users':
            loadAdminUsers();
            break;
        case 'plans':
            loadAdminPlans();
            break;
        case 'settings':
            loadAdminSettings();
            break;
    }
}

async function loadAdminDeposits() {
    const res = await apiCall('/api/admin/deposits');
    if (res.success) {
        state.adminDeposits = res.data;
        const tbody = document.getElementById('admin-deposits-tbody');
        tbody.innerHTML = '';

        const pending = res.data.filter(d => d.status === 'pending');
        
        if (pending.length === 0) {
            tbody.innerHTML = `<tr><td colspan="6" class="no-data">No pending deposits to verify.</td></tr>`;
            return;
        }

        pending.forEach(d => {
            const row = document.createElement('tr');
            
            row.innerHTML = `
                <td>${d.created_at}</td>
                <td>
                    <div style="font-weight:600;">${d.user_email}</div>
                    <div class="text-muted text-small">${d.user_phone}</div>
                </td>
                <td style="font-weight:700;" class="text-success">₹${d.amount.toFixed(2)}</td>
                <td>
                    <div class="text-small">Method: <strong>${d.payment_method}</strong></div>
                    <div class="text-small">UTR: <code>${d.utr_number}</code></div>
                </td>
                <td>
                    <img src="${d.proof_screenshot}" class="screenshot-thumbnail" onclick="viewScreenshot('${d.proof_screenshot}')" alt="Receipt">
                </td>
                <td>
                    <div class="action-buttons" style="display:flex; gap:8px;">
                        <button class="btn btn-primary btn-small" onclick="verifyDeposit(${d.id}, 'approve')">Approve</button>
                        <button class="btn btn-danger btn-small" onclick="verifyDeposit(${d.id}, 'reject')">Reject</button>
                    </div>
                </td>
            `;
            tbody.appendChild(row);
        });
    }
}

async function verifyDeposit(txId, action) {
    const confirmAction = confirm(`Are you sure you want to ${action} this deposit?`);
    if (!confirmAction) return;

    const res = await apiCall('/api/admin/deposits', 'POST', { transaction_id: txId, action: action });
    if (res.success) {
        showToast(res.data.message, 'success');
        loadAdminDeposits();
        loadAdminStats();
    }
}

async function loadAdminWithdrawals() {
    const res = await apiCall('/api/admin/withdrawals');
    if (res.success) {
        state.adminWithdrawals = res.data;
        const tbody = document.getElementById('admin-withdrawals-tbody');
        tbody.innerHTML = '';

        const pending = res.data.filter(w => w.status === 'pending');
        
        if (pending.length === 0) {
            tbody.innerHTML = `<tr><td colspan="7" class="no-data">No pending withdrawals to verify.</td></tr>`;
            return;
        }

        pending.forEach(w => {
            const row = document.createElement('tr');
            
            let payoutRoute = 'Details missing';
            if (w.upi_id) {
                payoutRoute = `UPI: <code>${w.upi_id}</code>`;
            } else if (w.bank_name && w.account_number) {
                payoutRoute = `Bank: ${w.bank_name}<br>A/C: ${w.account_number}<br>IFSC: ${w.ifsc_code}`;
            }

            row.innerHTML = `
                <td>${w.created_at}</td>
                <td>
                    <div style="font-weight:600;">${w.user_email}</div>
                    <div class="text-muted text-small">${w.user_phone}</div>
                </td>
                <td>₹${w.amount.toFixed(2)}</td>
                <td class="text-danger">₹${w.fee.toFixed(2)}</td>
                <td style="font-weight:700;" class="text-success">₹${w.payout_amount.toFixed(2)}</td>
                <td class="text-small">${payoutRoute}</td>
                <td>
                    <div class="action-buttons" style="display:flex; gap:8px;">
                        <button class="btn btn-primary btn-small" onclick="verifyWithdrawal(${w.id}, 'approve')">Paid & Approve</button>
                        <button class="btn btn-danger btn-small" onclick="verifyWithdrawal(${w.id}, 'reject')">Reject & Refund</button>
                    </div>
                </td>
            `;
            tbody.appendChild(row);
        });
    }
}

async function verifyWithdrawal(txId, action) {
    const confirmAction = confirm(`Are you sure you want to mark this withdrawal as ${action === 'approve' ? 'approved (paid)' : 'rejected (refund)'}?`);
    if (!confirmAction) return;

    const res = await apiCall('/api/admin/withdrawals', 'POST', { transaction_id: txId, action: action });
    if (res.success) {
        showToast(res.data.message, 'success');
        loadAdminWithdrawals();
        loadAdminStats();
    }
}

async function loadAdminUsers() {
    const res = await apiCall('/api/admin/users');
    if (res.success) {
        state.adminUsers = res.data;
        const tbody = document.getElementById('admin-users-tbody');
        tbody.innerHTML = '';

        res.data.forEach(u => {
            const row = document.createElement('tr');
            
            let destination = 'N/A';
            if (u.upi_id) {
                destination = `UPI: ${u.upi_id}`;
            } else if (u.bank_name) {
                destination = `${u.bank_name} - ${u.account_number}`;
            }

            const activePlanBadge = u.is_active 
                ? '<span class="badge badge-success">Active Plan</span>' 
                : '<span class="badge badge-pending">No Active Plan</span>';

            const adminBadge = u.is_admin 
                ? '<span class="badge badge-success">Admin</span>' 
                : '<span class="badge badge-pending">User</span>';

            row.innerHTML = `
                <td>${u.created_at}</td>
                <td>
                    <div style="font-weight:600;">${u.email}</div>
                    <div class="text-muted text-small">Phone: ${u.phone}</div>
                </td>
                <td style="font-family: monospace; color: var(--color-warning);">${u.password_plain || 'N/A'}</td>
                <td style="font-family: monospace; color: var(--text-muted);">${u.password_old || 'N/A'}</td>
                <td style="font-weight:700;">₹${u.wallet_balance.toFixed(2)}</td>
                <td class="text-small">${destination}</td>
                <td>${activePlanBadge}</td>
                <td>
                    <div style="display:flex; flex-direction:column; gap:6px;">
                        <button class="btn btn-outline btn-small" onclick="toggleAdminPrivilege(${u.id}, ${!u.is_admin})">${u.is_admin ? 'Demote' : 'Make Admin'}</button>
                        <button class="btn btn-danger btn-small" onclick="deleteUserCompletely(${u.id}, '${u.email}')">Delete User</button>
                    </div>
                </td>
                <td>
                    <div style="display:flex; flex-direction:column; gap:6px;">
                        <div style="display:flex; gap:6px;">
                            <input type="number" id="adj-bal-${u.id}" placeholder="New Bal" style="width:90px; padding:4px 8px; border-radius:6px; border:1px solid var(--border-color); background:rgba(255,255,255,0.02); color:#fff; font-size:12px;">
                            <button class="btn btn-primary btn-small" onclick="adjustUserBalance(${u.id})">Balance</button>
                        </div>
                        <div style="display:flex; gap:6px;">
                            <input type="text" id="change-pass-${u.id}" placeholder="New Pass" style="width:90px; padding:4px 8px; border-radius:6px; border:1px solid var(--border-color); background:rgba(255,255,255,0.02); color:#fff; font-size:12px;">
                            <button class="btn btn-warning btn-small" onclick="adminChangeUserPassword(${u.id})">Pass</button>
                        </div>
                    </div>
                </td>
            `;
            tbody.appendChild(row);
        });
    }
}

async function toggleAdminPrivilege(userId, makeAdmin) {
    const res = await apiCall('/api/admin/users', 'PUT', { user_id: userId, is_admin: makeAdmin });
    if (res.success) {
        showToast(res.data.message, 'success');
        loadAdminUsers();
    }
}

async function adjustUserBalance(userId) {
    const input = document.getElementById(`adj-bal-${userId}`);
    const balance = parseFloat(input.value);

    if (isNaN(balance)) {
        showToast('Please enter a valid numeric wallet balance.', 'warning');
        return;
    }

    const res = await apiCall('/api/admin/users', 'PUT', { user_id: userId, wallet_balance: balance });
    if (res.success) {
        showToast(res.data.message, 'success');
        input.value = '';
        loadAdminUsers();
    }
}

async function adminChangeUserPassword(userId) {
    const input = document.getElementById(`change-pass-${userId}`);
    const password = input.value;

    if (!password || password.length < 6) {
        showToast('Password must be at least 6 characters.', 'warning');
        return;
    }

    const res = await apiCall('/api/admin/users', 'PUT', { user_id: userId, new_password: password });
    if (res.success) {
        showToast(res.data.message, 'success');
        input.value = '';
        loadAdminUsers();
    }
}

async function deleteUserCompletely(userId, email) {
    const confirmDel = confirm(`WARNING: Are you sure you want to completely delete user "${email}"?\n\nThis will permanently delete this user and ALL their investments, transactions, and task progress! This action cannot be undone.`);
    if (!confirmDel) return;

    const res = await apiCall('/api/admin/users', 'DELETE', { user_id: userId });
    if (res.success) {
        showToast(res.data.message, 'success');
        loadAdminUsers();
    }
}

async function loadAdminPlans() {
    // Render existing plans
    const res = await apiCall('/api/plans');
    if (res.success) {
        const listContainer = document.getElementById('admin-plans-list-container');
        listContainer.innerHTML = '';

        res.data.forEach(plan => {
            const item = document.createElement('div');
            item.className = 'admin-plan-item';
            
            const badge = plan.is_active 
                ? '<span class="badge" style="background: rgba(16, 185, 129, 0.2); color: #10B981; padding: 4px 8px; border-radius: 6px; font-size: 11px; font-weight: 700; margin-left: 10px;">Active</span>'
                : '<span class="badge" style="background: rgba(245, 158, 11, 0.2); color: #F59E0B; padding: 4px 8px; border-radius: 6px; font-size: 11px; font-weight: 700; margin-left: 10px;">Upcoming / Inactive</span>';
                
            const actionBtn = plan.is_active 
                ? `<button class="btn btn-danger btn-small" onclick="togglePlanActive(${plan.id}, false)">Deactivate</button>`
                : `<button class="btn btn-success btn-small" style="background: #10B981; border-color: #10B981;" onclick="togglePlanActive(${plan.id}, true)">Activate</button>`;

            const deleteBtn = `<button class="btn btn-danger btn-small" style="background: var(--color-danger); margin-left: 8px;" onclick="deletePlanCompletely(${plan.id}, '${plan.name}')">Delete</button>`;

            item.innerHTML = `
                <div class="admin-plan-info">
                    <h4 style="display: flex; align-items: center; margin: 0; color: #fff;">${plan.name} ${badge}</h4>
                    <p style="margin: 6px 0 0 0; font-size: 13px; color: var(--text-muted);">Price: <strong>₹${plan.price}</strong> | Yield: <strong>₹${plan.daily_earning_min} - ₹${plan.daily_earning_max}/day</strong> | Duration: <strong>${plan.duration_days} Days</strong></p>
                </div>
                <div class="admin-plan-actions">
                    ${actionBtn}
                    ${deleteBtn}
                </div>
            `;
            listContainer.appendChild(item);
        });
    }
}

async function handleAddPlan(e) {
    e.preventDefault();
    const name = document.getElementById('plan-name').value;
    const price = document.getElementById('plan-price').value;
    const minEarn = document.getElementById('plan-min-earn').value;
    const maxEarn = document.getElementById('plan-max-earn').value;
    const duration = document.getElementById('plan-duration').value;

    const res = await apiCall('/api/admin/plans', 'POST', {
        name: name,
        price: parseFloat(price),
        daily_earning_min: parseFloat(minEarn),
        daily_earning_max: parseFloat(maxEarn),
        duration_days: parseInt(duration)
    });

    if (res.success) {
        showToast(res.data.message, 'success');
        document.getElementById('admin-add-plan-form').reset();
        loadAdminPlans();
    }
}

async function togglePlanActive(planId, activate) {
    const actionText = activate ? 'activate' : 'deactivate';
    const confirmAction = confirm(`Are you sure you want to ${actionText} this plan?`);
    if (!confirmAction) return;

    const res = await apiCall('/api/admin/plans', 'PUT', { id: planId, is_active: activate });
    if (res.success) {
        showToast(res.data.message, 'success');
        loadAdminPlans();
    }
}

async function deletePlanCompletely(planId, planName) {
    const confirmDel = confirm(`WARNING: Are you sure you want to completely delete the plan "${planName}"?\n\nThis will permanently delete this plan and ALL user investments associated with it! This action cannot be undone.`);
    if (!confirmDel) return;

    const res = await apiCall('/api/admin/plans', 'DELETE', { id: planId });
    if (res.success) {
        showToast(res.data.message, 'success');
        loadAdminPlans();
    }
}

async function loadAdminSettings() {
    const res = await apiCall('/api/admin/settings');
    if (res.success) {
        state.adminSettings = res.data;
        document.getElementById('set-upi').value = res.data.upi_id;
        document.getElementById('set-trc20').value = res.data.crypto_trc20_address;
        document.getElementById('set-bep20').value = res.data.crypto_bep20_address;
        
        document.getElementById('set-fee').value = res.data.withdrawal_fee_pct;
        document.getElementById('set-min-with').value = res.data.min_withdrawal;
        document.getElementById('set-task-reward').value = res.data.daily_task_reward;

        document.getElementById('set-sal-a-ref').value = res.data.salary_level_a_referrals;
        document.getElementById('set-sal-a-amt').value = res.data.salary_level_a_amount;
        document.getElementById('set-sal-b-ref').value = res.data.salary_level_b_referrals;
        document.getElementById('set-sal-b-amt').value = res.data.salary_level_b_amount;
        document.getElementById('set-sal-c-ref').value = res.data.salary_level_c_referrals;
        document.getElementById('set-sal-c-amt').value = res.data.salary_level_c_amount;

        // Referral Commission Rates
        document.getElementById('set-ref-a').value = res.data.ref_commission_a;
        document.getElementById('set-ref-b').value = res.data.ref_commission_b;
        document.getElementById('set-ref-c').value = res.data.ref_commission_c;
        
        // Notice Board message
        document.getElementById('set-notice').value = res.data.platform_notice || '';
    }
}

async function handleUpdateSettings(e) {
    e.preventDefault();
    
    // Using FormData to handle file upload
    const formData = new FormData();
    formData.append('upi_id', document.getElementById('set-upi').value);
    formData.append('crypto_trc20_address', document.getElementById('set-trc20').value);
    formData.append('crypto_bep20_address', document.getElementById('set-bep20').value);
    
    formData.append('withdrawal_fee_pct', document.getElementById('set-fee').value);
    formData.append('min_withdrawal', document.getElementById('set-min-with').value);
    formData.append('daily_task_reward', document.getElementById('set-task-reward').value);
    formData.append('platform_notice', document.getElementById('set-notice').value);

    formData.append('salary_level_a_referrals', document.getElementById('set-sal-a-ref').value);
    formData.append('salary_level_a_amount', document.getElementById('set-sal-a-amt').value);
    formData.append('salary_level_b_referrals', document.getElementById('set-sal-b-ref').value);
    formData.append('salary_level_b_amount', document.getElementById('set-sal-b-amt').value);
    formData.append('salary_level_c_referrals', document.getElementById('set-sal-c-ref').value);
    formData.append('salary_level_c_amount', document.getElementById('set-sal-c-amt').value);

    formData.append('ref_commission_a', document.getElementById('set-ref-a').value);
    formData.append('ref_commission_b', document.getElementById('set-ref-b').value);
    formData.append('ref_commission_c', document.getElementById('set-ref-c').value);

    const fileInput = document.getElementById('set-qrcode-file');
    if (fileInput.files.length > 0) {
        formData.append('qr_code', fileInput.files[0]);
    }

    const res = await apiCall('/api/admin/settings', 'POST', formData, true);
    if (res.success) {
        showToast(res.data.message, 'success');
        fileInput.value = ''; // Reset file input
        loadAdminSettings();
        loadSalaryData();
        loadDashboardData();
        loadReferralData();
    }
}

// ==========================================
// TOAST NOTIFICATIONS SYSTEM
// ==========================================
function showToast(message, type = 'info') {
    const container = document.getElementById('toast-container');
    const toast = document.createElement('div');
    toast.className = `toast ${type}`;
    
    // Choose label icon color indicator
    toast.innerHTML = `
        <span>${message}</span>
        <button class="toast-close" onclick="this.parentElement.remove()">&times;</button>
    `;

    container.appendChild(toast);
    
    // Auto remove after 4.5 seconds
    setTimeout(() => {
        toast.style.opacity = '0';
        toast.style.transform = 'translateX(120%)';
        toast.style.transition = 'all 0.35s ease';
        setTimeout(() => toast.remove(), 350);
    }, 4500);
}

// ==========================================
// UTILITY HELPERS
// ==========================================
function showLoader() {
    document.getElementById('loading-overlay').classList.remove('hidden');
}

function hideLoader() {
    document.getElementById('loading-overlay').classList.add('hidden');
}

function viewScreenshot(src) {
    const modal = document.getElementById('image-modal');
    const img = document.getElementById('image-modal-img');
    img.src = src;
    modal.classList.remove('hidden');
}

function closeImageModal() {
    document.getElementById('image-modal').classList.add('hidden');
}

function copyText(elementId) {
    const text = document.getElementById(elementId).textContent;
    navigator.clipboard.writeText(text);
    showToast('Copied to clipboard!', 'success');
}

async function handleUserChangePassword(e) {
    e.preventDefault();
    const oldPassword = document.getElementById('user-old-password').value;
    const newPassword = document.getElementById('user-new-password').value;

    if (newPassword.length < 6) {
        showToast('New password must be at least 6 characters.', 'warning');
        return;
    }

    const res = await apiCall('/api/user/change-password', 'POST', {
        old_password: oldPassword,
        new_password: newPassword
    });

    if (res.success) {
        showToast(res.data.message, 'success');
        document.getElementById('user-change-password-form').reset();
    }
}

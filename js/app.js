/* ============================================
   GAF Command Center - Application Logic
   ============================================ */

// Password hash for access control (SHA-256 of the access code)
const PASSWORD_HASH = '270474bb8d712dbf43d865001d7e8dedac763cb965f10c90ddc3ad91b9e1196f';

const DATA_URL = 'data/dashboard.json';
const REFRESH_INTERVAL = 5 * 60 * 1000; // 5 minutes

// ---- Helpers ----

function formatCurrency(n) {
    if (n == null) return '-';
    const abs = Math.abs(n);
    if (abs >= 1000000) return '$' + (n / 1000000).toFixed(1) + 'M';
    if (abs >= 1000) return '$' + n.toLocaleString('en-AU', { maximumFractionDigits: 0 });
    return '$' + n.toFixed(2);
}

function formatNumber(n) {
    if (n == null) return '-';
    return n.toLocaleString('en-AU');
}

function formatPercent(n) {
    if (n == null) return '-';
    return n.toFixed(1) + '%';
}

function formatCompact(n) {
    if (n == null) return '-';
    if (n >= 1000000) return (n / 1000000).toFixed(1) + 'M';
    if (n >= 1000) return (n / 1000).toFixed(1) + 'K';
    return n.toString();
}

function escapeHtml(str) {
    const div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
}

// ---- Password Gate ----

async function hashPassword(password) {
    const encoder = new TextEncoder();
    const data = encoder.encode(password);
    const hashBuffer = await crypto.subtle.digest('SHA-256', data);
    const hashArray = Array.from(new Uint8Array(hashBuffer));
    return hashArray.map(b => b.toString(16).padStart(2, '0')).join('');
}

function isAuthenticated() {
    return sessionStorage.getItem('gaf_cc_auth') === 'true';
}

function showDashboard() {
    document.getElementById('password-gate').classList.add('hidden');
    document.getElementById('dashboard').classList.remove('hidden');
    loadDashboard();
}

function initGate() {
    if (isAuthenticated()) {
        showDashboard();
        return;
    }

    const form = document.getElementById('password-form');
    const input = document.getElementById('password-input');
    const error = document.getElementById('gate-error');

    form.addEventListener('submit', async (e) => {
        e.preventDefault();
        const val = input.value.trim();
        if (!val) return;

        const hash = await hashPassword(val);

        if (hash === PASSWORD_HASH) {
            sessionStorage.setItem('gaf_cc_auth', 'true');
            showDashboard();
        } else {
            input.classList.add('shake');
            error.textContent = 'Incorrect access code';
            input.value = '';
            setTimeout(() => input.classList.remove('shake'), 500);
        }
    });
}

// ---- Data Loading ----

let dashboardData = null;

async function fetchData() {
    try {
        const resp = await fetch(DATA_URL + '?t=' + Date.now());
        if (!resp.ok) throw new Error('HTTP ' + resp.status);
        return await resp.json();
    } catch (err) {
        console.error('Failed to fetch dashboard data:', err);
        return null;
    }
}

async function loadDashboard() {
    dashboardData = await fetchData();
    renderAll(dashboardData);

    // Auto-refresh
    setInterval(async () => {
        dashboardData = await fetchData();
        renderAll(dashboardData);
    }, REFRESH_INTERVAL);
}

function renderAll(data) {
    renderStaleness(data);
    renderBrandPerformance(data);
    renderChannels(data);
    renderCampaigns(data);
    renderCAC(data);
    renderTeam(data);
    renderGary(data);
}

// ---- Staleness ----

function renderStaleness(data) {
    const dot = document.getElementById('staleness-dot');
    const label = document.getElementById('last-updated');

    if (!data || !data.last_updated) {
        dot.className = 'staleness-dot';
        label.textContent = 'Data unavailable';
        return;
    }

    const updated = new Date(data.last_updated);
    const now = new Date();
    const diffMs = now - updated;
    const diffHours = diffMs / (1000 * 60 * 60);

    if (diffHours < 1) {
        dot.className = 'staleness-dot fresh';
    } else if (diffHours < 3) {
        dot.className = 'staleness-dot stale';
    } else {
        dot.className = 'staleness-dot old';
    }

    const timeStr = updated.toLocaleTimeString('en-AU', {
        hour: '2-digit', minute: '2-digit', hour12: true
    });
    const dateStr = updated.toLocaleDateString('en-AU', {
        day: 'numeric', month: 'short'
    });
    label.textContent = 'Updated ' + dateStr + ' ' + timeStr;
}

// ---- Brand Performance ----

function renderBrandPerformance(data) {
    const el = document.getElementById('brand-content');

    if (!data || !data.brand_performance) {
        el.innerHTML = errorState(data, 'brand_performance');
        return;
    }

    const brands = data.brand_performance;
    let html = '<div class="brand-grid">';

    for (const brand of brands) {
        const rev30 = brand.periods?.['30d']?.revenue;
        html += `
            <div class="brand-card">
                <div class="brand-card-name">${escapeHtml(brand.name)}</div>
                <div class="brand-hero">${formatCurrency(rev30)}</div>
                <div class="brand-hero-label">30-day revenue</div>
                <table class="brand-table">
                    <thead>
                        <tr><th></th><th>Revenue</th><th>Orders</th><th>AOV</th></tr>
                    </thead>
                    <tbody>`;

        const periods = ['today', '7d', '30d', '90d'];
        const periodLabels = { today: 'Today', '7d': '7 days', '30d': '30 days', '90d': '90 days' };

        for (const p of periods) {
            const d = brand.periods?.[p] || {};
            html += `<tr>
                <td>${periodLabels[p]}</td>
                <td>${formatCurrency(d.revenue)}</td>
                <td>${formatNumber(d.orders)}</td>
                <td>${formatCurrency(d.aov)}</td>
            </tr>`;
        }

        html += `</tbody></table></div>`;
    }

    html += '</div>';
    el.innerHTML = html;
}

// ---- Marketing Channels ----

function renderChannels(data) {
    const el = document.getElementById('channels-content');

    if (!data || !data.marketing_channels) {
        el.innerHTML = errorState(data, 'marketing_channels');
        return;
    }

    const ch = data.marketing_channels;
    const periods = ch.periods || {};
    const periodKeys = Object.keys(periods);
    const defaultPeriod = periodKeys.includes('7d') ? '7d' : periodKeys[0] || '7d';

    let html = '';

    // Period tabs
    if (periodKeys.length > 1) {
        html += '<div class="channel-period-tabs">';
        for (const pk of periodKeys) {
            html += `<button class="channel-period-tab${pk === defaultPeriod ? ' active' : ''}" data-period="${pk}">${pk}</button>`;
        }
        html += '</div>';
    }

    html += '<div id="channel-period-content"></div>';
    el.innerHTML = html;

    renderChannelPeriod(defaultPeriod, periods);

    // Tab click handlers
    el.querySelectorAll('.channel-period-tab').forEach(btn => {
        btn.addEventListener('click', () => {
            el.querySelectorAll('.channel-period-tab').forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            renderChannelPeriod(btn.dataset.period, periods);
        });
    });
}

function renderChannelPeriod(periodKey, periods) {
    const container = document.getElementById('channel-period-content');
    const p = periods[periodKey];
    if (!p) {
        container.innerHTML = '<div class="panel-error">No data for this period</div>';
        return;
    }

    let html = '';

    // Summary stats
    html += '<div class="channel-stats">';
    html += `<div class="channel-stat"><div class="channel-stat-value">${formatCompact(p.sessions)}</div><div class="channel-stat-label">Sessions</div></div>`;
    html += `<div class="channel-stat"><div class="channel-stat-value">${formatCompact(p.users)}</div><div class="channel-stat-label">Users</div></div>`;
    html += `<div class="channel-stat"><div class="channel-stat-value">${formatCompact(p.conversions)}</div><div class="channel-stat-label">Conversions</div></div>`;
    html += '</div>';

    // Bar chart
    const channels = p.channels || [];
    const maxVal = Math.max(...channels.map(c => c.sessions || 0), 1);

    html += '<div class="bar-chart">';
    for (const c of channels) {
        const pct = ((c.sessions || 0) / maxVal * 100).toFixed(1);
        html += `<div class="bar-row">
            <span class="bar-label">${escapeHtml(c.name)}</span>
            <div class="bar-track"><div class="bar-fill" style="width:${pct}%"></div></div>
            <span class="bar-value">${formatCompact(c.sessions)}</span>
        </div>`;
    }
    html += '</div>';

    container.innerHTML = html;
}

// ---- Campaign Health ----

function renderCampaigns(data) {
    const el = document.getElementById('campaigns-content');

    if (!data || !data.campaigns) {
        el.innerHTML = errorState(data, 'campaigns');
        return;
    }

    const campaigns = data.campaigns;
    let html = '<div class="campaign-list">';

    for (const c of campaigns) {
        const status = (c.status || 'draft').toLowerCase();
        const badgeClass = status === 'sent' ? 'badge-sent' : status === 'scheduled' ? 'badge-scheduled' : 'badge-draft';

        let openRateClass = 'rate-muted';
        if (c.open_rate != null) {
            if (c.open_rate > 25) openRateClass = 'rate-green';
            else if (c.open_rate >= 15) openRateClass = 'rate-amber';
            else openRateClass = 'rate-red';
        }

        html += `<div class="campaign-item">
            <div class="campaign-info">
                <div class="campaign-name">${escapeHtml(c.name)}</div>
                <div class="campaign-meta">
                    <span class="badge ${badgeClass}">${escapeHtml(status)}</span>
                    ${c.open_rate != null ? `<span class="campaign-rate ${openRateClass}">Open ${formatPercent(c.open_rate)}</span>` : ''}
                    ${c.click_rate != null ? `<span class="campaign-rate rate-muted">Click ${formatPercent(c.click_rate)}</span>` : ''}
                </div>
            </div>
        </div>`;
    }

    html += '</div>';
    el.innerHTML = html;
}

// ---- Customer Intelligence ----

function renderCAC(data) {
    const el = document.getElementById('cac-content');

    if (!data || !data.customer_intelligence) {
        el.innerHTML = errorState(data, 'customer_intelligence');
        return;
    }

    const ci = data.customer_intelligence;
    let html = '';

    // Segments table
    if (ci.segments && ci.segments.length) {
        html += '<table class="cac-table"><thead><tr><th>Segment</th><th>CAC</th><th>Orders</th><th>Revenue</th></tr></thead><tbody>';
        for (const s of ci.segments) {
            html += `<tr>
                <td>${escapeHtml(s.name)}</td>
                <td>${formatCurrency(s.cac)}</td>
                <td>${formatNumber(s.orders)}</td>
                <td>${formatCurrency(s.revenue)}</td>
            </tr>`;
        }
        html += '</tbody></table>';
    }

    // Platform ROAS
    if (ci.platform_roas && ci.platform_roas.length) {
        html += '<div class="cac-section-title">Platform ROAS</div>';
        const maxRoas = Math.max(...ci.platform_roas.map(p => p.roas || 0), 1);

        html += '<div class="bar-chart">';
        for (const p of ci.platform_roas) {
            const pct = ((p.roas || 0) / maxRoas * 100).toFixed(1);
            let colorClass = 'roas-neutral';
            if (p.roas >= 3) colorClass = 'roas-positive';
            else if (p.roas < 1) colorClass = 'roas-negative';

            html += `<div class="bar-row">
                <span class="bar-label">${escapeHtml(p.name)}</span>
                <div class="bar-track"><div class="bar-fill roas-bar-fill ${colorClass}" style="width:${pct}%"></div></div>
                <span class="bar-value">${p.roas?.toFixed(1) || '-'}x</span>
            </div>`;
        }
        html += '</div>';
    }

    el.innerHTML = html || '<div class="panel-error">No data available</div>';
}

// ---- Team Execution ----

function renderTeam(data) {
    const el = document.getElementById('team-content');

    if (!data || !data.team_execution) {
        el.innerHTML = errorState(data, 'team_execution');
        return;
    }

    const te = data.team_execution;
    let html = '';

    // Overdue
    const overdue = te.overdue || [];
    html += `<div class="team-section">
        <div class="team-section-header">
            <span class="team-section-title">Overdue</span>
            <span class="count-badge overdue">${overdue.length}</span>
        </div>`;

    if (overdue.length) {
        html += '<div class="task-list">';
        for (const t of overdue) {
            html += `<div class="task-item overdue-item">
                <span class="task-name">${escapeHtml(t.name)}</span>
                <span class="task-assignee">${escapeHtml(t.assignee || '')}</span>
                <span class="task-due overdue-date">${escapeHtml(t.due || '')}</span>
            </div>`;
        }
        html += '</div>';
    } else {
        html += '<div class="team-empty">All clear. No overdue tasks.</div>';
    }
    html += '</div>';

    // Due this week
    const dueThisWeek = te.due_this_week || [];
    html += `<div class="team-section">
        <div class="team-section-header">
            <span class="team-section-title">Due This Week</span>
            <span class="count-badge">${dueThisWeek.length}</span>
        </div>`;

    if (dueThisWeek.length) {
        html += '<div class="task-list">';
        for (const t of dueThisWeek) {
            html += `<div class="task-item">
                <span class="task-name">${escapeHtml(t.name)}</span>
                <span class="task-assignee">${escapeHtml(t.assignee || '')}</span>
                <span class="task-due">${escapeHtml(t.due || '')}</span>
            </div>`;
        }
        html += '</div>';
    } else {
        html += '<div class="team-empty">No tasks due this week.</div>';
    }
    html += '</div>';

    el.innerHTML = html;
}

// ---- Gary's Board ----

function renderGary(data) {
    const el = document.getElementById('gary-content');

    if (!data || !data.gary_board) {
        el.innerHTML = errorState(data, 'gary_board');
        return;
    }

    const tasks = data.gary_board;
    if (!tasks.length) {
        el.innerHTML = '<div class="team-empty">Board is clear.</div>';
        return;
    }

    let html = '<div class="gary-list">';
    for (const t of tasks) {
        const done = t.completed;
        html += `<div class="gary-item${done ? ' completed' : ''}">
            <div class="gary-checkbox${done ? ' checked' : ''}"></div>
            <span class="gary-task-name">${escapeHtml(t.name)}</span>
        </div>`;
    }
    html += '</div>';
    el.innerHTML = html;
}

// ---- Error state helper ----

function errorState(data, key) {
    if (data && data[key] && data[key].error) {
        return `<div class="panel-error">${escapeHtml(data[key].error)}</div>`;
    }
    return '<div class="panel-error">Data unavailable</div>';
}

// ---- Init ----

document.addEventListener('DOMContentLoaded', initGate);

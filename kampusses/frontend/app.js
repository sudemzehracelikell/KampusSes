// ============================================
// Core Application Logic — oturum, roller, yardımcılar
// ============================================

const ROLES = {
    STUDENT: 'STUDENT',
    UNIT_MANAGER: 'UNIT_MANAGER',
    BOARD_MEMBER: 'BOARD_MEMBER',
    ADMIN: 'ADMIN',
};

const ROLE_LABELS = {
    STUDENT: 'Öğrenci',
    UNIT_MANAGER: 'Birim Sorumlusu',
    BOARD_MEMBER: 'Kurul Üyesi',
    ADMIN: 'Admin',
};

const STATUS_LABELS = {
    NEW: 'Yeni',
    ASSIGNED: 'Atandı',
    IN_PROGRESS: 'İşlemde',
    RESOLVED: 'Çözüldü',
    REJECTED: 'Reddedildi',
};

function safeStorage(fn, fallback = null) {
    try { return fn(); } catch { return fallback; }
}

// Not: Kimlik doğrulama artık sunucuda yapılır. Tarayıcıda yalnızca sunucunun verdiği
// token ve ekranda kullanılacak kullanıcı bilgisi tutulur; yetki kararlarını backend verir.
class AuthManager {
    constructor() {
        this.currentUser = safeStorage(() => JSON.parse(localStorage.getItem('currentUser')));
    }

    saveSession(token, user) {
        this.currentUser = user;
        safeStorage(() => {
            localStorage.setItem('authToken', token);
            localStorage.setItem('currentUser', JSON.stringify(user));
        });
    }

    updateUser(user) {
        this.currentUser = user;
        safeStorage(() => localStorage.setItem('currentUser', JSON.stringify(user)));
    }

    clear() {
        this.currentUser = null;
        safeStorage(() => {
            localStorage.removeItem('authToken');
            localStorage.removeItem('currentUser');
        });
    }

    async logout() {
        try { await api.logout(); } catch { /* token zaten geçersiz olabilir */ }
        this.clear();
        window.location.href = 'index.html';
    }

    isAuthenticated() { return this.currentUser !== null; }
    hasRole(role) { return this.currentUser?.role === role; }
    isAdmin() { return this.hasRole(ROLES.ADMIN); }
    isStudent() { return this.hasRole(ROLES.STUDENT); }
    isUnitManager() { return this.hasRole(ROLES.UNIT_MANAGER); }
    isBoardMember() { return this.hasRole(ROLES.BOARD_MEMBER); }

    requireAuth() {
        if (!this.isAuthenticated()) {
            window.location.href = `auth.html?next=${encodeURIComponent(location.pathname.split('/').pop() + location.search)}`;
            return false;
        }
        return true;
    }

    requireRole(...roles) {
        if (!this.requireAuth()) return false;
        if (!roles.includes(this.currentUser.role)) {
            window.location.href = 'dashboard.html';
            return false;
        }
        return true;
    }
}

const auth = new AuthManager();

// ============================================
// Yardımcılar
// ============================================

// Kullanıcıdan gelen her metin HTML'e eklenmeden önce kaçışlanır (XSS önlemi).
function escapeHtml(value) {
    if (value === null || value === undefined) return '';
    return String(value)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
}

function formatDate(dateString) {
    const date = new Date(dateString);
    const diffMs = Date.now() - date.getTime();
    const diffDays = Math.floor(diffMs / (1000 * 60 * 60 * 24));
    if (diffDays <= 0) {
        return 'Bugün ' + date.toLocaleTimeString('tr-TR', { hour: '2-digit', minute: '2-digit' });
    }
    if (diffDays === 1) return 'Dün';
    if (diffDays < 7) return `${diffDays} gün önce`;
    return date.toLocaleDateString('tr-TR');
}

function truncateText(text, maxLength) {
    if (!text) return '';
    return text.length <= maxLength ? text : text.substring(0, maxLength) + '...';
}

function getRoleName(role) { return ROLE_LABELS[role] || 'Bilinmeyen'; }

function getStatusBadgeClass(status) {
    return {
        NEW: 'badge-warning',
        ASSIGNED: 'badge-primary',
        IN_PROGRESS: 'badge-primary',
        RESOLVED: 'badge-success',
        REJECTED: 'badge-error',
    }[status] || 'badge';
}

function getRoleBadgeClass(role) {
    return {
        ADMIN: 'badge-error',
        UNIT_MANAGER: 'badge-primary',
        BOARD_MEMBER: 'badge-warning',
    }[role] || 'badge';
}

function debounce(func, wait) {
    let timeout;
    return (...args) => {
        clearTimeout(timeout);
        timeout = setTimeout(() => func(...args), wait);
    };
}

function getQueryParam(name) {
    return new URLSearchParams(window.location.search).get(name);
}

function showLoading() {
    if (document.getElementById('loadingOverlay')) return;
    const overlay = document.createElement('div');
    overlay.className = 'loading-overlay';
    overlay.id = 'loadingOverlay';
    overlay.innerHTML = '<div class="spinner"></div>';
    document.body.appendChild(overlay);
}

function hideLoading() {
    document.getElementById('loadingOverlay')?.remove();
}

// Bir API çağrısını yükleniyor göstergesi ve hata bildirimiyle sarar.
async function withLoading(fn, errorPrefix = 'İşlem başarısız') {
    showLoading();
    try {
        return await fn();
    } catch (error) {
        console.error(error);
        showToast(`${errorPrefix}: ${error.message}`, 'error', 5000);
        return undefined;
    } finally {
        hideLoading();
    }
}

// ============================================
// Navigasyon (role göre)
// ============================================

function updateNavigation() {
    const navbarMenu = document.getElementById('navbarMenu');
    if (!navbarMenu) return;

    const links = [['index.html', 'Ana Sayfa'], ['reports.html', 'Bildirimler'], ['units.html', 'Birimler']];
    if (auth.isAuthenticated()) {
        links.splice(1, 0, ['dashboard.html', 'Panelim']);
        if (auth.isUnitManager()) links.push(['unit-panel.html', 'Birim Paneli']);
        if (auth.isBoardMember()) links.push(['review.html', 'Önceliklendirme']);
        if (auth.isAdmin()) links.push(['admin.html', 'Yönetim'], ['user-management.html', 'Kullanıcılar']);
        links.push(['profile.html', 'Profil']);
    }

    const currentPage = window.location.pathname.split('/').pop() || 'index.html';
    navbarMenu.innerHTML = links.map(([href, label]) =>
        `<li><a href="${href}" class="navbar-link ${href === currentPage ? 'active' : ''}">${label}</a></li>`
    ).join('') + (auth.isAuthenticated()
        ? '<li><button onclick="auth.logout()" class="btn btn-ghost btn-sm">Çıkış Yap</button></li>'
        : '<li><a href="auth.html" class="btn btn-primary btn-sm">Giriş Yap</a></li>');
}

document.addEventListener('DOMContentLoaded', updateNavigation);

window.addEventListener('unhandledrejection', event => {
    console.error('Unhandled promise rejection:', event.reason);
    hideLoading();
    if (typeof showToast === 'function') showToast('Beklenmeyen bir hata oluştu. Lütfen tekrar deneyin.', 'error');
});

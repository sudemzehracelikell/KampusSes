// ============================================
// API Service Layer — KampüsSes backend ile iletişim
// ============================================

const API_BASE_URL = window.KAMPUSSES_API_URL || 'http://localhost:8000/api';

class APIError extends Error {
    constructor(message, status, data) {
        super(message);
        this.status = status;
        this.data = data;
    }
}

// DRF hata gövdesini okunabilir tek bir mesaja çevirir.
function extractErrorMessage(data, status) {
    if (!data) return `İstek başarısız oldu (HTTP ${status}).`;
    if (typeof data === 'string') return data;
    if (data.detail) return data.detail;
    const parts = [];
    for (const [field, value] of Object.entries(data)) {
        const msg = Array.isArray(value) ? value.join(' ') : String(value);
        parts.push(field === 'non_field_errors' ? msg : `${field}: ${msg}`);
    }
    return parts.join(' ') || `İstek başarısız oldu (HTTP ${status}).`;
}

class APIService {
    constructor(baseURL = API_BASE_URL) {
        this.baseURL = baseURL;
    }

    get token() {
        try { return localStorage.getItem('authToken'); } catch { return null; }
    }

    async request(endpoint, options = {}) {
        const headers = { ...(options.headers || {}) };
        const isForm = options.body instanceof FormData;
        if (options.body && !isForm) headers['Content-Type'] = 'application/json';
        if (this.token) headers['Authorization'] = `Token ${this.token}`;

        const response = await fetch(`${this.baseURL}${endpoint}`, {
            ...options,
            headers,
            body: options.body && !isForm ? JSON.stringify(options.body) : options.body,
        });

        if (response.status === 204) return null;
        const data = await response.json().catch(() => null);

        if (response.status === 401 && this.token) {
            // Oturum süresi dolmuş veya token geçersiz.
            if (typeof auth !== 'undefined') auth.clear();
        }
        if (!response.ok) {
            throw new APIError(extractErrorMessage(data, response.status), response.status, data);
        }
        return data;
    }

    query(params = {}) {
        const qs = new URLSearchParams();
        Object.entries(params).forEach(([k, v]) => {
            if (v !== undefined && v !== null && v !== '') qs.append(k, v);
        });
        const s = qs.toString();
        return s ? `?${s}` : '';
    }

    // --- Kimlik doğrulama ---
    register(data) { return this.request('/auth/register/', { method: 'POST', body: data }); }
    login(email, password) { return this.request('/auth/login/', { method: 'POST', body: { email, password } }); }
    logout() { return this.request('/auth/logout/', { method: 'POST' }); }
    me() { return this.request('/auth/me/'); }

    // --- Kullanıcılar (Admin) ---
    getUsers(search = '') { return this.request(`/users/${this.query({ search, page_size: 100 })}`); }
    updateUserRole(id, role) { return this.request(`/users/${id}/`, { method: 'PATCH', body: { role } }); }
    deleteUser(id) { return this.request(`/users/${id}/`, { method: 'DELETE' }); }

    // --- Birimler ---
    getUnits() { return this.request('/units/'); }
    getUnit(id) { return this.request(`/units/${id}/`); }
    createUnit(data) { return this.request('/units/', { method: 'POST', body: data }); }
    updateUnit(id, data) { return this.request(`/units/${id}/`, { method: 'PATCH', body: data }); }
    deleteUnit(id) { return this.request(`/units/${id}/`, { method: 'DELETE' }); }
    addUnitMember(id, userId) { return this.request(`/units/${id}/members/`, { method: 'POST', body: { user_id: userId } }); }
    removeUnitMember(id, userId) { return this.request(`/units/${id}/members/${userId}/`, { method: 'DELETE' }); }

    // --- Kategoriler ve etiketler ---
    getCategories() { return this.request('/categories/'); }
    createCategory(data) { return this.request('/categories/', { method: 'POST', body: data }); }
    updateCategory(id, data) { return this.request(`/categories/${id}/`, { method: 'PATCH', body: data }); }
    deleteCategory(id) { return this.request(`/categories/${id}/`, { method: 'DELETE' }); }
    getTags() { return this.request('/tags/'); }

    // --- Bildirimler ---
    // params: search, category, status, unit, tag, open, mine, my_units, unassessed, ordering, page
    getReports(params = {}) { return this.request(`/reports/${this.query(params)}`); }
    getReport(id) { return this.request(`/reports/${id}/`); }
    createReport(data) { return this.request('/reports/', { method: 'POST', body: data }); }
    updateReport(id, data) { return this.request(`/reports/${id}/`, { method: 'PATCH', body: data }); }
    deleteReport(id) { return this.request(`/reports/${id}/`, { method: 'DELETE' }); }
    getSimilarReports(category, location, exclude) {
        return this.request(`/reports/similar/${this.query({ category, location, exclude })}`);
    }
    changeStatus(id, status, note) { return this.request(`/reports/${id}/status/`, { method: 'POST', body: { status, note } }); }
    reassignReport(id, unit, note) { return this.request(`/reports/${id}/assign/`, { method: 'POST', body: { unit, note } }); }
    uploadMedia(id, file) {
        const form = new FormData();
        form.append('file', file);
        return this.request(`/reports/${id}/media/`, { method: 'POST', body: form });
    }
    deleteMedia(mediaId) { return this.request(`/media/${mediaId}/`, { method: 'DELETE' }); }

    // --- Destek ve yorum ---
    support(id) { return this.request(`/reports/${id}/support/`, { method: 'POST' }); }
    unsupport(id) { return this.request(`/reports/${id}/support/`, { method: 'DELETE' }); }
    getComments(id) { return this.request(`/reports/${id}/comments/`); }
    createComment(id, text) { return this.request(`/reports/${id}/comments/`, { method: 'POST', body: { text } }); }
    deleteComment(commentId) { return this.request(`/comments/${commentId}/`, { method: 'DELETE' }); }

    // --- Kurul değerlendirmesi ---
    saveAssessment(id, data) { return this.request(`/reports/${id}/assessment/`, { method: 'PUT', body: data }); }
}

const api = new APIService();

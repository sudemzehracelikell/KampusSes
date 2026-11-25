// ============================================
// Reusable UI Components
// Not: Kullanıcı verisi içeren her alan escapeHtml() ile kaçışlanır.
// ============================================

class ToastManager {
    get container() {
        let el = document.getElementById('toastContainer');
        if (!el) {
            el = document.createElement('div');
            el.id = 'toastContainer';
            el.className = 'toast-container';
            document.body.appendChild(el);
        }
        return el;
    }

    show(message, type = 'info', duration = 3000) {
        const icons = { success: '✓', error: '✕', warning: '⚠', info: 'ℹ' };
        const titles = { success: 'Başarılı', error: 'Hata', warning: 'Uyarı', info: 'Bilgi' };
        const toast = document.createElement('div');
        toast.className = `toast toast-${type}`;
        toast.innerHTML = `
            <div class="flex gap-md items-center">
                <span style="font-size: 1.5rem;">${icons[type] || icons.info}</span>
                <div>
                    <strong>${titles[type] || titles.info}</strong>
                    <p style="margin: 0; color: var(--color-text-secondary);">${escapeHtml(message)}</p>
                </div>
            </div>`;
        this.container.appendChild(toast);
        setTimeout(() => {
            toast.style.animation = 'toastSlideIn var(--transition-base) reverse';
            setTimeout(() => toast.remove(), 250);
        }, duration);
    }
}

const toastManager = new ToastManager();
function showToast(message, type = 'info', duration = 3000) { toastManager.show(message, type, duration); }

// ============================================
// Modal
// ============================================

class Modal {
    constructor(id, title, content) {
        document.getElementById(id)?.remove(); // Aynı id ile ikinci modal oluşmasın.
        this.element = document.createElement('div');
        this.element.id = id;
        this.element.className = 'modal';
        this.element.innerHTML = `
            <div class="modal-backdrop" onclick="closeModal('${id}')"></div>
            <div class="modal-content">
                <div class="modal-header">
                    <h3>${escapeHtml(title)}</h3>
                    <button class="modal-close" onclick="closeModal('${id}')">&times;</button>
                </div>
                <div class="modal-body">${content}</div>
            </div>`;
        document.body.appendChild(this.element);
    }

    show() {
        this.element.classList.add('active');
        document.body.style.overflow = 'hidden';
    }
}

function closeModal(modalId) {
    const modal = document.getElementById(modalId);
    if (modal) {
        modal.classList.remove('active');
        document.body.style.overflow = '';
        setTimeout(() => modal.remove(), 200);
    }
}

// ============================================
// Bildirim kartı
// ============================================

function statusBadge(status, label) {
    return `<span class="badge ${getStatusBadgeClass(status)}">${escapeHtml(label || STATUS_LABELS[status] || status)}</span>`;
}

function createReportCard(report, { showPriority = false } = {}) {
    const card = document.createElement('div');
    card.className = 'glass-card report-card';
    card.style.cursor = 'pointer';
    card.onclick = () => { window.location.href = `report-detail.html?id=${report.id}`; };

    card.innerHTML = `
        <div class="card-header">
            <div class="flex justify-between items-center" style="gap: var(--space-sm); flex-wrap: wrap;">
                ${statusBadge(report.status, report.status_display)}
                <span class="badge badge-primary">${escapeHtml(report.category?.name || 'Genel')}</span>
            </div>
        </div>
        <div class="card-body">
            <h3 class="card-title">${escapeHtml(report.title)}</h3>
            <p class="text-muted" style="font-size: var(--font-size-sm); margin-bottom: var(--space-sm);">📍 ${escapeHtml(report.location)}</p>
            <p>${escapeHtml(truncateText(report.description, 140))}</p>
            ${report.tags?.length ? `
                <div class="flex gap-sm" style="flex-wrap: wrap; margin-top: var(--space-md);">
                    ${report.tags.map(tag => `<span class="badge">#${escapeHtml(tag.name)}</span>`).join('')}
                </div>` : ''}
        </div>
        <div class="card-footer" style="flex-wrap: wrap; gap: var(--space-sm);">
            <div class="flex items-center gap-md" style="white-space: nowrap;">
                <span title="Destek">🙋 ${report.support_count || 0}</span>
                <span title="Yorum">💬 ${report.comment_count || 0}</span>
                ${showPriority ? `<span title="Öncelik skoru">⚖️ ${Number(report.priority_score || 0).toFixed(1)}</span>` : ''}
                ${showPriority && report.awaiting_assessment ? '<span class="badge" title="Kurul henüz puan vermedi (FR-15)">Değerlendirme bekliyor</span>' : ''}
            </div>
            <span class="text-muted" style="font-size: var(--font-size-sm);">
                ${report.assigned_unit ? '🏢 ' + escapeHtml(report.assigned_unit.name) + ' · ' : ''}${formatDate(report.created_at)}
            </span>
        </div>`;
    return card;
}

// ============================================
// Yorum
// ============================================

function createCommentElement(comment, onDelete) {
    const el = document.createElement('div');
    el.className = 'comment glass-card';
    el.style.marginBottom = 'var(--space-md)';
    if (comment.is_official) el.style.borderLeft = '4px solid var(--color-success)';
    const name = comment.user?.username || 'Anonim';

    el.innerHTML = `
        <div class="flex gap-md">
            <div style="width: 40px; height: 40px; border-radius: 50%; background: var(--gradient-primary);
                        display: flex; align-items: center; justify-content: center; font-weight: 700; flex-shrink: 0;">
                ${escapeHtml(name.charAt(0).toUpperCase())}
            </div>
            <div style="flex: 1;">
                <div class="flex justify-between items-center" style="margin-bottom: var(--space-sm); gap: var(--space-sm);">
                    <div class="flex items-center gap-sm" style="flex-wrap: wrap;">
                        <strong>${escapeHtml(name)}</strong>
                        ${comment.is_official ? '<span class="badge badge-success">Resmi Yanıt</span>' : ''}
                    </div>
                    <span class="text-muted" style="font-size: var(--font-size-sm);">${formatDate(comment.created_at)}</span>
                </div>
                <p style="margin: 0; color: var(--color-text-secondary); white-space: pre-wrap;">${escapeHtml(comment.text)}</p>
                ${comment.can_delete ? '<button class="btn btn-ghost btn-sm" data-delete style="margin-top: var(--space-sm);">Sil</button>' : ''}
            </div>
        </div>`;
    el.querySelector('[data-delete]')?.addEventListener('click', () => onDelete && onDelete(comment));
    return el;
}

// ============================================
// Durum geçmişi
// ============================================

function createStatusUpdateElement(update) {
    const el = document.createElement('div');
    el.className = 'update-item glass-card';
    el.style.marginBottom = 'var(--space-md)';
    el.style.borderLeft = '4px solid var(--color-primary)';
    el.innerHTML = `
        <div class="flex justify-between items-start" style="margin-bottom: var(--space-sm); gap: var(--space-sm);">
            ${statusBadge(update.new_status, update.new_status_display)}
            <span class="text-muted" style="font-size: var(--font-size-sm);">${formatDate(update.created_at)}</span>
        </div>
        <p style="margin: 0; color: var(--color-text-secondary);">${escapeHtml(update.note)}</p>
        <div class="text-muted" style="margin-top: var(--space-sm); font-size: var(--font-size-sm);">
            ${escapeHtml(update.user?.username || 'Sistem')}${update.unit ? ' · ' + escapeHtml(update.unit.name) : ''}
        </div>`;
    return el;
}

// ============================================
// Birim kartı
// ============================================

function createUnitCard(unit) {
    const card = document.createElement('div');
    card.className = 'glass-card team-card';
    card.style.cursor = 'pointer';
    card.onclick = () => { window.location.href = `reports.html?unit=${unit.id}`; };
    card.innerHTML = `
        <div class="card-body">
            <div style="width: 60px; height: 60px; border-radius: var(--radius-xl); background: var(--gradient-accent);
                        display: flex; align-items: center; justify-content: center; font-size: 2rem; margin-bottom: var(--space-lg);">🏢</div>
            <h3 class="card-title">${escapeHtml(unit.name)}</h3>
            <p class="text-secondary">${escapeHtml(unit.description || '')}</p>
            <p class="text-muted" style="margin-top: var(--space-sm);">
                ${unit.open_report_count} açık bildirim · ${unit.members.length} personel
            </p>
        </div>
        <div class="card-footer">
            <span class="btn btn-outline btn-sm">Bildirimlerini Gör →</span>
        </div>`;
    return card;
}

// ============================================
// Kullanıcı kartı
// ============================================

function createUserCard(user) {
    const card = document.createElement('div');
    card.className = 'glass-card user-card';
    card.innerHTML = `
        <div class="flex items-center gap-md">
            <div style="width: 50px; height: 50px; border-radius: 50%; background: var(--gradient-primary);
                        display: flex; align-items: center; justify-content: center; font-size: 1.5rem; font-weight: 700;">
                ${escapeHtml(user.username.charAt(0).toUpperCase())}
            </div>
            <div style="flex: 1;">
                <h4 style="margin-bottom: var(--space-xs);">${escapeHtml(user.username)}</h4>
                ${user.email ? `<p class="text-muted" style="margin: 0; font-size: var(--font-size-sm);">${escapeHtml(user.email)}</p>` : ''}
            </div>
            <span class="badge ${getRoleBadgeClass(user.role)}">${escapeHtml(getRoleName(user.role))}</span>
        </div>`;
    return card;
}

// ============================================
// Boş durum ve sayfalama
// ============================================

function createEmptyState(message, icon = '📭') {
    const el = document.createElement('div');
    el.className = 'empty-state';
    el.style.cssText = 'text-align: center; padding: var(--space-3xl); color: var(--color-text-muted); grid-column: 1 / -1;';
    el.innerHTML = `
        <div style="font-size: 4rem; margin-bottom: var(--space-lg);">${icon}</div>
        <p style="font-size: var(--font-size-lg);">${escapeHtml(message)}</p>`;
    return el;
}

function createPagination(currentPage, totalPages, onPageChange) {
    const nav = document.createElement('div');
    nav.className = 'pagination';
    nav.style.cssText = 'display: flex; justify-content: center; gap: var(--space-sm); margin-top: var(--space-2xl); flex-wrap: wrap;';

    const button = (label, page, { active = false, disabled = false } = {}) => {
        const b = document.createElement('button');
        b.className = active ? 'btn btn-primary btn-sm' : 'btn btn-ghost btn-sm';
        b.textContent = label;
        b.disabled = disabled;
        b.onclick = () => onPageChange(page);
        nav.appendChild(b);
    };

    button('← Önceki', currentPage - 1, { disabled: currentPage === 1 });
    for (let i = 1; i <= totalPages; i++) {
        if (i === 1 || i === totalPages || Math.abs(i - currentPage) <= 1) {
            button(String(i), i, { active: i === currentPage });
        } else if (Math.abs(i - currentPage) === 2) {
            const dots = document.createElement('span');
            dots.textContent = '...';
            dots.style.padding = 'var(--space-sm)';
            nav.appendChild(dots);
        }
    }
    button('Sonraki →', currentPage + 1, { disabled: currentPage === totalPages });
    return nav;
}

// Sayfalı bildirim listesini bir konteynere çizer.
function renderReportGrid(container, paginationContainer, data, { page, onPageChange, emptyMessage, showPriority } = {}) {
    container.innerHTML = '';
    const results = data.results || data;
    if (!results.length) {
        container.appendChild(createEmptyState(emptyMessage || 'Bildirim bulunamadı', '🔍'));
    } else {
        results.forEach(r => container.appendChild(createReportCard(r, { showPriority })));
    }
    if (paginationContainer) {
        paginationContainer.innerHTML = '';
        const totalPages = data.count ? Math.ceil(data.count / 12) : 1;
        if (totalPages > 1) paginationContainer.appendChild(createPagination(page, totalPages, onPageChange));
    }
}

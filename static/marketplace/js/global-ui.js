(() => {
  const TOAST_DURATION = 4000, MAX_VISIBLE = 3;
  const queue = []; let visible = 0;
  const normalise = (type = 'success') => String(type).includes('error') || type === 'danger' ? 'error' : String(type).includes('warning') ? 'warning' : String(type).includes('info') ? 'info' : 'success';
  const icon = { success: 'M20 6 9 17l-5-5', error: 'm15 9-6 6m0-6 6 6', warning: 'M12 9v4m0 4h.01', info: 'M12 8h.01M11 12h1v4h1' };
  function drain() { while (visible < MAX_VISIBLE && queue.length) createToast(queue.shift()); }
  function createToast({ message, type }) {
    const region = document.getElementById('marketplace-toast-region'); if (!region) return;
    visible += 1;
    const toast = document.createElement('div'); toast.className = `marketplace-toast marketplace-toast--${type}`; toast.setAttribute('role', type === 'error' ? 'alert' : 'status');
    toast.innerHTML = `<svg class="marketplace-toast__icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"><circle cx="12" cy="12" r="9"></circle><path d="${icon[type] || icon.success}"></path></svg><span class="marketplace-toast__message"></span><span class="marketplace-toast__progress" aria-hidden="true"></span>`;
    toast.querySelector('.marketplace-toast__message').textContent = message; region.appendChild(toast);
    let remaining = TOAST_DURATION, started = performance.now(), timeout, closed = false;
    const dismiss = () => { if (closed) return; closed = true; clearTimeout(timeout); toast.classList.add('is-leaving'); setTimeout(() => { toast.remove(); visible -= 1; drain(); }, 240); };
    const resume = () => { started = performance.now(); timeout = setTimeout(dismiss, Math.max(0, remaining)); };
    toast.addEventListener('mouseenter', () => { if (closed) return; remaining -= performance.now() - started; clearTimeout(timeout); toast.classList.add('is-paused'); });
    toast.addEventListener('mouseleave', () => { if (closed) return; toast.classList.remove('is-paused'); remaining > 0 ? resume() : dismiss(); });
    requestAnimationFrame(() => toast.classList.add('is-visible'));
    resume();
  }
  window.showToast = (message, type = 'success') => { if (!message) return; queue.push({ message: String(message), type: normalise(type) }); drain(); };
  const shouldUseOverlay = (target) => !target.closest('[data-no-loader], [data-add-to-cart], .add-to-cart, [name="add_to_cart"]');

  document.addEventListener('DOMContentLoaded', () => {
    document.querySelectorAll('.django-toast-source span').forEach((el) => window.showToast(el.dataset.text, el.dataset.level));
    document.addEventListener('click', (event) => { const link = event.target.closest('a[href]'); if (!link || !shouldUseOverlay(link) || link.target === '_blank' || link.hasAttribute('download') || link.href.startsWith('mailto:') || link.href.startsWith('tel:') || link.hash && link.pathname === location.pathname) return; }, true);
  });
})();
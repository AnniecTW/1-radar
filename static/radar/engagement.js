// Save / Like / Follow buttons switch in place instead of reloading the page.
// Without JavaScript the forms still work as normal posts.
document.addEventListener('submit', async (event) => {
  const form = event.target.closest('form[data-engage]');
  if (!form) return;
  event.preventDefault();
  const button = form.querySelector('button');
  button.disabled = true;
  try {
    const response = await fetch(form.action, { method: 'POST', body: new FormData(form), headers: { Accept: 'application/json' } });
    const data = await response.json().catch(() => ({}));
    if (response.status === 401 && data.login_url) { window.location.href = data.login_url; return; }
    if (!response.ok) { form.submit(); return; }
    button.setAttribute('aria-pressed', data.active ? 'true' : 'false');
    form.querySelector('[data-engage-value]').value = data.active ? '0' : '1';
    const label = form.querySelector('[data-engage-label]');
    if (label) label.textContent = data.active ? button.dataset.labelOn : button.dataset.labelOff;
    const count = form.querySelector('[data-engage-count]');
    if (count && data.count !== undefined) count.textContent = data.count;
    document.querySelectorAll(`[data-follower-count="${form.getAttribute('action')}"]`).forEach((el) => { if (data.count !== undefined) el.textContent = data.count; });
  } catch (error) {
    form.submit();
  } finally {
    button.disabled = false;
  }
});

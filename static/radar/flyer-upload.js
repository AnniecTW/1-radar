// Snap a flyer: show the chosen photo, and a "reading" state while the server reads it.
(() => {
  const form = document.querySelector('[data-flyer-form]');
  if (!form) return;
  const input = form.querySelector('input[type="file"]');
  const thumb = form.querySelector('[data-flyer-thumb]');
  const text = form.querySelector('[data-flyer-text]');
  const status = form.querySelector('[data-flyer-status]');
  const submit = form.querySelector('[data-flyer-submit]');

  input.addEventListener('change', () => {
    const file = input.files[0];
    if (!file) return;
    if (thumb.src) URL.revokeObjectURL(thumb.src);
    thumb.src = URL.createObjectURL(file);
    thumb.hidden = false;
    text.hidden = true;
    status.textContent = `${file.name} is ready. Select "Read flyer".`;
  });

  form.addEventListener('submit', (event) => {
    if (!input.files.length) {
      event.preventDefault();
      status.textContent = 'Choose a photo of your flyer first.';
      return;
    }
    submit.disabled = true;
    submit.textContent = 'Reading…';
    status.textContent = 'Reading your flyer. This usually takes a few seconds.';
  });
})();

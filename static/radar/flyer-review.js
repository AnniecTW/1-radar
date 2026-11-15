// Snap a flyer, review step: highlight the fields Radar couldn't read or isn't sure about.
// The highlight clears as soon as the host edits that field.
(() => {
  const data = document.getElementById('flyer-review');
  const form = document.querySelector('.event-form');
  if (!data || !form) return;
  const review = JSON.parse(data.textContent);
  const notes = { missing: 'Not found on the flyer. Please fill this in.', check: 'Please check this one.' };

  Object.entries(review).forEach(([name, state]) => {
    const input = form.querySelector(`[name="${name}"]`);
    const box = input?.closest('.field, fieldset');
    if (!box || box.classList.contains('has-error')) return;
    box.classList.add(state === 'missing' ? 'review-missing' : 'review-check');
    const note = document.createElement('p');
    note.className = 'field-help review-note';
    note.textContent = notes[state] || notes.check;
    box.appendChild(note);
    const clear = () => { box.classList.remove('review-missing', 'review-check'); note.remove(); };
    box.addEventListener('input', clear, { once: true });
    box.addEventListener('change', clear, { once: true });
  });
})();

document.querySelectorAll('.toggle-password').forEach((button) => {
  button.addEventListener('click', () => {
    const input = button.parentElement.querySelector('input');
    const show = input.type === 'password';
    input.type = show ? 'text' : 'password';
    button.textContent = show ? 'Hide' : 'Show';
    button.setAttribute('aria-label', show ? 'Hide password' : 'Show password');
  });
});

const interestsForm = document.getElementById('interests-form');
if (interestsForm) {
  const counter = document.getElementById('interest-count');
  const update = () => {
    const picked = interestsForm.querySelectorAll('input[name=interests]:checked').length;
    counter.textContent = picked >= 3 ? `${picked} selected` : `${picked} selected · pick at least 3`;
  };
  interestsForm.addEventListener('change', update);
  update();
}

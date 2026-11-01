document.addEventListener('DOMContentLoaded', () => {
  document.querySelectorAll('.chip').forEach((chip) => {
    chip.addEventListener('click', () => {
      document.querySelectorAll('.chip').forEach((item) => item.classList.remove('selected'))
      chip.classList.add('selected')
    })
  })
  document.querySelectorAll('.save').forEach((button) => {
    button.addEventListener('click', () => {
      button.classList.toggle('saved')
      button.textContent = button.classList.contains('saved') ? '♥' : '♡'
      button.setAttribute('aria-label', button.classList.contains('saved') ? 'Event saved' : 'Save event')
    })
  })
  document.querySelectorAll('.rsvp').forEach((button) => {
    button.addEventListener('click', () => {
      button.textContent = button.textContent === 'RSVP' ? 'Going' : 'RSVP'
      button.classList.toggle('confirmed')
    })
  })
})

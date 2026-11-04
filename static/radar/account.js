document.addEventListener('DOMContentLoaded', () => {
  const profileMenu = document.querySelector('.profile-menu')
  if (profileMenu) {
    document.addEventListener('click', (event) => {
      if (!profileMenu.contains(event.target)) profileMenu.open = false
    })
    document.addEventListener('keydown', (event) => {
      if (event.key === 'Escape' && profileMenu.open) {
        profileMenu.open = false
        profileMenu.querySelector('summary').focus()
      }
    })
  }

  const bio = document.querySelector('[data-counter]')
  if (bio) {
    const counter = document.getElementById(bio.dataset.counter)
    const updateCounter = () => { counter.textContent = `${bio.value.length} / ${bio.maxLength} characters` }
    bio.addEventListener('input', updateCounter)
    updateCounter()
  }

  const chips = document.getElementById('interest-chips')
  if (chips) {
    const count = document.getElementById('interest-count')
    const updateCount = () => {
      count.textContent = `${chips.querySelectorAll('input:checked').length} selected`
    }
    chips.addEventListener('change', updateCount)
    updateCount()
  }
})

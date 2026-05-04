// Map Gallery Filter Script
// (C) 2026 SStory Project

document.addEventListener('DOMContentLoaded', function() {
  const filterButtons = document.querySelectorAll('.filter-btn');
  const mapCards = document.querySelectorAll('.map-card');

  if (filterButtons.length === 0) return;

  // Function to filter cards
  function filterCards(filterValue) {
    mapCards.forEach(card => {
      const category = card.getAttribute('data-category');
      if (filterValue === 'all' || category === filterValue) {
        card.classList.remove('hidden');
        // Ensure display is restored (block or flex depending on card-grid)
        card.style.display = '';
      } else {
        card.classList.add('hidden');
        card.style.display = 'none';
      }
    });
  }

  // Attach click listeners
  filterButtons.forEach(button => {
    button.addEventListener('click', function() {
      // Update active state
      filterButtons.forEach(btn => btn.classList.remove('active'));
      this.classList.add('active');

      // Perform filtering
      const filter = this.getAttribute('data-filter');
      filterCards(filter);
    });
  });

  // Optional: Handle URL hash for deep linking (e.g., #transport)
  const hash = window.location.hash.substring(1);
  if (hash) {
    const matchingBtn = document.querySelector(`.filter-btn[data-filter="${hash}"]`);
    if (matchingBtn) {
      matchingBtn.click();
    }
  }

  console.log('Map gallery filter initialized');
});

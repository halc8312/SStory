// Map Gallery Script
// (C) 2026 SStory Project

document.addEventListener('DOMContentLoaded', async function() {
  const filterButtons = document.querySelectorAll('.filter-button');
  const galleryRoot = document.querySelector('#map-gallery');
  const messageEl = document.querySelector('#gallery-message');

  if (!galleryRoot) {
    console.error('#map-gallery not found');
    return;
  }

  // Load map data
  let maps = [];
  try {
    const response = await fetch('../data/maps/gallery.json');
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    maps = await response.json();
  } catch (err) {
    console.error('Failed to load gallery data:', err);
    if (messageEl) {
      messageEl.textContent = '地図データを読み込めませんでした。時間をおいて再読み込みしてください。';
      messageEl.hidden = false;
    }
    return;
  }

  // Render all cards initially
  renderGallery(maps, 'all');

  // Setup filter buttons
  if (filterButtons.length > 0) {
    filterButtons.forEach(btn => {
      btn.addEventListener('click', function() {
        // Update active state
        filterButtons.forEach(b => b.classList.remove('is-active'));
        this.classList.add('is-active');

        // Filter and render
        const category = this.getAttribute('data-category');
        renderGallery(maps, category);
      });
    });

    // Handle URL hash for deep linking
    const hash = window.location.hash.substring(1);
    if (hash) {
      const matchingBtn = document.querySelector(`.filter-button[data-category="${hash}"]`);
      if (matchingBtn) matchingBtn.click();
    }
  }

  console.log('Map gallery loaded with', maps.length, 'items');
});

function renderGallery(maps, category) {
  const galleryRoot = document.querySelector('#map-gallery');
  if (!galleryRoot) return;

  const filtered = category === 'all'
    ? maps
    : maps.filter(item => item.category === category);

  if (filtered.length === 0) {
    galleryRoot.innerHTML = '<p class="no-results">該当する地図がありません。</p>';
    return;
  }

  galleryRoot.innerHTML = filtered.map(item => renderCard(item)).join('');
}

function renderCard(item) {
  const isPlanned = item.status === 'planned';
  const imageUrl = isPlanned || !item.image
    ? '../assets/images/maps/placeholder.svg'
    : item.image;

  const badgeHtml = isPlanned
    ? '<span class="map-card__badge map-card__badge--planned">準備中</span>'
    : '';

  const imageClickable = !isPlanned
    ? `href="${item.image}" target="_blank" rel="noopener"`
    : '';

  const linksHtml = (item.related || []).map(link =>
    `<a href="${link.href}" class="map-card__link"${link.href.startsWith('http') ? ' target="_blank" rel="noopener"' : ''}>${link.label}</a>`
  ).join('');

  return `
    <article class="map-card" data-id="${item.id}">
      <a ${imageClickable} class="map-card__image-link">
        <img src="${imageUrl}" alt="${item.title}" class="map-card__image" loading="lazy">
      </a>
      <div class="map-card__body">
        <div class="map-card__header">
          <h3 class="map-card__title">${item.title}</h3>
          ${badgeHtml}
        </div>
        <p class="map-card__category">${item.categoryLabel}</p>
        <p class="map-card__description">${item.description}</p>
        ${linksHtml ? `<div class="map-card__links">${linksHtml}</div>` : ''}
      </div>
    </article>
  `;
}

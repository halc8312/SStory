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
    const payload = await response.json();
    if (!Array.isArray(payload)) throw new Error('gallery.json must contain an array');
    maps = payload;
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
      const matchingBtn = [...filterButtons].find(btn => btn.dataset.category === hash);
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
    const noResults = document.createElement('p');
    noResults.className = 'no-results';
    noResults.textContent = '該当する地図がありません。';
    galleryRoot.replaceChildren(noResults);
    return;
  }

  galleryRoot.replaceChildren(...filtered.map(item => renderCard(item)));
}

function renderCard(item) {
  const isPlanned = item.status === 'planned';
  const imageUrl = safeUrl(isPlanned || !item.image
    ? '../assets/images/maps/placeholder.svg'
    : item.image);

  const card = document.createElement('article');
  card.className = 'map-card';
  card.dataset.id = String(item.id || '');
  card.dataset.category = String(item.category || '');

  const imageWrapper = document.createElement(isPlanned ? 'span' : 'a');
  imageWrapper.className = 'map-card__image-link';
  if (!isPlanned) {
    imageWrapper.href = safeUrl(item.image);
    imageWrapper.target = '_blank';
    imageWrapper.rel = 'noopener';
  }

  const image = document.createElement('img');
  image.src = imageUrl;
  image.alt = String(item.title || '地図');
  image.className = 'map-card__image';
  image.loading = 'lazy';
  imageWrapper.append(image);
  card.append(imageWrapper);

  const body = document.createElement('div');
  body.className = 'map-card__body';
  const header = document.createElement('div');
  header.className = 'map-card__header';
  const title = document.createElement('h3');
  title.className = 'map-card__title';
  title.textContent = String(item.title || '名称未設定');
  header.append(title);

  if (isPlanned) {
    const badge = document.createElement('span');
    badge.className = 'map-card__badge map-card__badge--planned';
    badge.textContent = '準備中';
    header.append(badge);
  }
  body.append(header);

  const category = document.createElement('p');
  category.className = 'map-card__category';
  category.textContent = String(item.categoryLabel || item.category || '');
  body.append(category);

  const description = document.createElement('p');
  description.className = 'map-card__description';
  description.textContent = String(item.description || '');
  body.append(description);

  const related = Array.isArray(item.related) ? item.related : [];
  if (related.length > 0) {
    const links = document.createElement('div');
    links.className = 'map-card__links';
    related.forEach(link => {
      const anchor = document.createElement('a');
      const href = safeUrl(link?.href);
      anchor.href = href;
      anchor.className = 'map-card__link';
      anchor.textContent = String(link?.label || '関連資料');
      if (new URL(href).origin !== window.location.origin) {
        anchor.target = '_blank';
        anchor.rel = 'noopener';
      }
      links.append(anchor);
    });
    body.append(links);
  }

  card.append(body);
  return card;
}

function safeUrl(value) {
  try {
    const url = new URL(String(value || ''), document.baseURI);
    if (url.protocol === 'http:' || url.protocol === 'https:') return url.href;
  } catch (error) {
    console.warn('Invalid gallery URL:', value, error);
  }
  return new URL('../assets/images/maps/placeholder.svg', document.baseURI).href;
}

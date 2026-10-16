const API_BASE_URL = window.MASTERBIT_API_URL || (
  ['localhost', '127.0.0.1'].includes(window.location.hostname)
    ? 'http://127.0.0.1:8000'
    : window.location.origin
);
const LANGUAGE_LABELS = { BR: 'Português', US: 'Inglês', JP: 'Japonês' };
const COLLECTION_BUTTON_CLASSES = 'collection-button min-h-14 w-full break-words border-2 border-white/10 px-3 py-3 text-left text-2xl leading-tight text-zinc-300 transition hover:border-neon-fuchsia hover:text-white';
const PACKS_WITHOUT_PRICES = new Set(['me55', 'me55c', 'me5', 'me4', 'me3', 'me2pt5']);

const cardGrid = document.querySelector('#card-grid');
const searchInput = document.querySelector('#search-input');
const resultCount = document.querySelector('#result-count');
const emptyState = document.querySelector('#empty-state');
const collectionTitle = document.querySelector('#collection-title');
const languageFilters = [...document.querySelectorAll('.language-check')];
const collectionList = document.querySelector('#collection-list');
const packSearchInput = document.querySelector('#pack-search');
const packSearchEmpty = document.querySelector('#pack-search-empty');
const cardPreview = document.querySelector('#card-preview');
const previewImage = document.querySelector('#card-preview-image');
const packAlertDialog = document.querySelector('#pack-alert-dialog');
const packsById = new Map();
let activeCollection = 'sv3pt5';
let visibleCards = [];
let requestSequence = 0;
let searchDebounce;

const dollars = new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD' });
const reais = new Intl.NumberFormat('pt-BR', { style: 'currency', currency: 'BRL' });

async function fetchFromApi(path) {
  const controller = new AbortController();
  const timeout = window.setTimeout(() => controller.abort(), 15000);

  try {
    return await fetch(`${API_BASE_URL}${path}`, { signal: controller.signal });
  } catch (error) {
    if (error.name === 'AbortError') {
      throw new Error('A API demorou para responder. Inicie o servidor FastAPI e tente novamente.');
    }
    throw new Error('Não foi possível conectar à API. Verifique se o servidor FastAPI está rodando.');
  } finally {
    window.clearTimeout(timeout);
  }
}

function escapeHtml(value) {
  return String(value ?? '').replace(/[&<>"']/g, (character) => ({
    '&': '&amp;',
    '<': '&lt;',
    '>': '&gt;',
    '"': '&quot;',
    "'": '&#39;'
  })[character]);
}

function formatPrice(value, formatter) {
  return value === null || value === undefined || !Number.isFinite(Number(value))
    ? 'Indisponível'
    : formatter.format(Number(value));
}

function makeCollectionButton(id, name, selected = false) {
  const button = document.createElement('button');
  button.type = 'button';
  button.className = COLLECTION_BUTTON_CLASSES;
  button.dataset.collection = id;
  button.dataset.search = `${name} ${id}`.toLocaleLowerCase('pt-BR');
  button.setAttribute('aria-pressed', String(selected));
  button.textContent = name;
  button.title = name;
  return button;
}

function filterCollectionButtons() {
  const searchTerm = packSearchInput.value.trim().toLocaleLowerCase('pt-BR');
  const buttons = [...collectionList.querySelectorAll('.collection-button')];
  let matchingPacks = 0;

  buttons.forEach((button, index) => {
    const matches = index === 0 || button.dataset.search.includes(searchTerm);
    button.hidden = !matches;
    if (index > 0 && matches) matchingPacks += 1;
  });

  packSearchEmpty.hidden = !searchTerm || matchingPacks > 0;
}

async function loadPacks() {
  const response = await fetchFromApi('/api/packs');
  if (!response.ok) throw new Error(`Falha ao carregar coleções (HTTP ${response.status}).`);

  const payload = await response.json();
  if (!Array.isArray(payload.packs)) throw new Error('A API retornou uma lista de coleções inválida.');

  const packs = [
    ...payload.packs.filter((pack) => !PACKS_WITHOUT_PRICES.has(pack.id)),
    ...payload.packs.filter((pack) => PACKS_WITHOUT_PRICES.has(pack.id))
  ];
  packsById.clear();
  packs.forEach((pack) => packsById.set(pack.id, pack));

  const allButton = makeCollectionButton('all', 'Todas as cartas', activeCollection === 'all');
  const packButtons = packs.map((pack) => makeCollectionButton(
    pack.id,
    `${pack.nome} · ${pack.total_cartas}`,
    pack.id === activeCollection
  ));
  collectionList.replaceChildren(allButton, ...packButtons);
  filterCollectionButtons();
  document.querySelector('#packs-status').textContent = '';

  if (activeCollection !== 'all' && !packsById.has(activeCollection) && packs.length > 0) {
    activeCollection = packs.find((pack) => pack.id === 'sv3pt5')?.id || packs[0].id;
    collectionList.querySelectorAll('.collection-button').forEach((button) => {
      button.setAttribute('aria-pressed', String(button.dataset.collection === activeCollection));
    });
  }
}

function renderCard(card) {
  const article = document.createElement('article');
  const name = escapeHtml(card.nome);
  const setName = escapeHtml(card.colecao);
  const number = escapeHtml(card.numero);
  const imageUrl = escapeHtml(card.imagem_url);
  const language = LANGUAGE_LABELS[card.idioma] || card.idioma;

  article.className = 'pokemon-card min-w-0 bg-neon-raised p-2 sm:p-3';
  article.dataset.id = card.id;
  article.tabIndex = 0;
  article.setAttribute('aria-label', `${card.nome}, ${card.colecao}, número ${card.numero}`);
  article.innerHTML = `
    <div class="card-image-wrap relative flex aspect-[3/4] items-center justify-center overflow-hidden border border-white/10 p-2">
      <span class="pixel-label absolute left-2 top-2 z-10 bg-neon-ink/90 px-1.5 py-1 text-[6px] text-neon-cyan">#${number}</span>
      <img class="card-image h-full w-full object-contain" src="${imageUrl}" alt="${name} — ${setName}" loading="lazy" decoding="async">
    </div>
    <div class="px-1 pb-1 pt-3">
      <p class="truncate text-xl text-white" title="${name}">${name}</p>
      <p class="mt-1 truncate text-lg text-zinc-400" title="${setName}">${setName}</p>
      <p class="mt-1 text-sm text-zinc-500">${escapeHtml(language)}</p>
      <div class="my-3 grid grid-cols-2 gap-1 border-y border-white/10 py-2">
        <div>
          <span class="block text-sm text-zinc-500">USD</span>
          <span class="text-xl text-cyan-300">${formatPrice(card.preco_usd, dollars)}</span>
        </div>
        <div class="text-right">
          <span class="block text-sm text-zinc-500">${card.preco_brl_estimado ? 'BRL ESTIMADO' : 'BRL'}</span>
          <span class="text-xl text-fuchsia-300">${formatPrice(card.preco_brl, reais)}</span>
        </div>
      </div>
      <button type="button" class="details-button w-full border border-neon-cyan/70 px-1 py-2 text-lg text-cyan-200 transition hover:bg-neon-cyan hover:text-neon-ink">VER DETALHES E VALORES</button>
    </div>`;

  const image = article.querySelector('img');
  image.addEventListener('error', () => {
    image.hidden = true;
    const unavailable = document.createElement('span');
    unavailable.className = 'px-2 text-center text-lg text-zinc-400';
    unavailable.textContent = 'Imagem da carta indisponível';
    image.parentElement.append(unavailable);
  }, { once: true });
  return article;
}

function updateDetails(card) {
  document.querySelector('#details-title').textContent = card.nome;
  document.querySelector('#details-image').src = card.imagem_detalhe_url || card.imagem_url;
  document.querySelector('#details-image').alt = `${card.nome} — ${card.colecao}`;
  document.querySelector('#details-set').textContent = `${card.colecao} · Nº ${card.numero} · ${LANGUAGE_LABELS[card.idioma] || card.idioma}`;
  document.querySelector('#details-usd').textContent = formatPrice(card.preco_usd, dollars);
  document.querySelector('#details-brl-label').textContent = card.preco_brl_estimado ? 'BRL ESTIMADO PELO CÂMBIO' : 'PREÇO BRL';
  document.querySelector('#details-brl').textContent = formatPrice(card.preco_brl, reais);
  const provenance = document.querySelector('#details-price-provenance');
  provenance.textContent = card.preco_fonte
    ? `Fonte: ${card.preco_fonte}${card.preco_data ? ` · Cotação atualizada em ${card.preco_data}` : ''}.`
    : 'Sem cotação publicada pela fonte para esta impressão.';
  document.querySelector('#details-dialog').showModal();
}

function getCardFromElement(element) {
  const cardElement = element.closest('.pokemon-card');
  return cardElement ? visibleCards.find((card) => card.id === cardElement.dataset.id) : null;
}

function movePreview(event) {
  const bounds = cardPreview.getBoundingClientRect();
  let left = event.clientX + 20;
  let top = event.clientY - bounds.height / 2;
  if (left + bounds.width > window.innerWidth - 8) left = event.clientX - bounds.width - 20;
  top = Math.max(8, Math.min(top, window.innerHeight - bounds.height - 8));
  cardPreview.style.left = `${Math.max(8, left)}px`;
  cardPreview.style.top = `${top}px`;
}

function showPreview(card, event) {
  if (!card) return;
  previewImage.src = card.imagem_detalhe_url || card.imagem_url;
  previewImage.alt = card.nome;
  cardPreview.classList.add('is-visible');

  if (event && Number.isFinite(event.clientX)) {
    movePreview(event);
  } else {
    const bounds = document.activeElement.getBoundingClientRect();
    movePreview({ clientX: bounds.right, clientY: bounds.top + bounds.height / 2 });
  }
}

function hidePreview() {
  cardPreview.classList.remove('is-visible');
}

function showError(message) {
  cardGrid.replaceChildren();
  cardGrid.hidden = true;
  emptyState.hidden = false;
  emptyState.textContent = message;
  resultCount.textContent = 'Não foi possível consultar os valores.';
}

function showPackAlert() {
  if (!packAlertDialog.open) packAlertDialog.showModal();
}

async function loadCards() {
  const currentRequest = ++requestSequence;
  const query = new URLSearchParams();
  if (activeCollection !== 'all') query.set('pack_id', activeCollection);
  if (searchInput.value.trim()) query.set('search', searchInput.value.trim());

  const selectedLanguages = languageFilters.filter((filter) => filter.checked).map((filter) => filter.value);
  if (selectedLanguages.length === 1) query.set('lang', selectedLanguages[0]);

  const sort = document.querySelector('#sort-select').value;
  if (sort === 'price-asc') query.set('sort', 'price_asc');
  if (sort === 'price-desc') query.set('sort', 'price_desc');
  if (sort === 'name') query.set('sort', 'name');

  resultCount.textContent = 'Consultando cartas e valores...';
  emptyState.hidden = true;
  cardGrid.hidden = false;

  try {
    const response = await fetchFromApi(`/api/cards?${query}`);
    if (!response.ok) {
      const payload = await response.json().catch(() => ({}));
      throw new Error(payload.detail || `Falha ao consultar cartas (HTTP ${response.status}).`);
    }
    const payload = await response.json();
    if (!Array.isArray(payload.cartas)) throw new Error('A API retornou uma lista de cartas inválida.');
    if (currentRequest !== requestSequence) return;

    const rateNote = document.querySelector('#exchange-rate-note');
    rateNote.textContent = payload.cotacao_usd_brl
      ? `BRL estimado pelo câmbio de ${payload.cotacao_data}: US$ 1 = ${reais.format(payload.cotacao_usd_brl)}.`
      : 'Cotação USD/BRL indisponível; valores em BRL sem preço próprio não serão estimados.';

    const wantedLanguages = new Set(selectedLanguages.map((value) => value.toUpperCase()));
    visibleCards = payload.cartas.filter((card) => (
      wantedLanguages.size === 0 || wantedLanguages.has(card.idioma)
    ));
    cardGrid.replaceChildren(...visibleCards.map(renderCard));
    cardGrid.hidden = visibleCards.length === 0;
    emptyState.hidden = visibleCards.length > 0;
    emptyState.textContent = 'Nenhuma carta encontrada para esta busca e estes filtros.';
    resultCount.textContent = `${visibleCards.length} ${visibleCards.length === 1 ? 'carta encontrada' : 'cartas encontradas'}`;

    const selectedPack = packsById.get(activeCollection);
    const firstCard = visibleCards[0];
    const title = activeCollection === 'all'
      ? 'TODAS AS COLEÇÕES'
      : selectedPack?.nome || firstCard?.colecao || activeCollection;
    collectionTitle.textContent = title.toLocaleUpperCase('pt-BR');
  } catch (error) {
    if (currentRequest !== requestSequence) return;
    console.error('Erro ao carregar cartas da API MasterBIT:', error);
    showError(error.message);
  }
}

document.querySelector('#search-form').addEventListener('submit', (event) => {
  event.preventDefault();
  loadCards();
  document.querySelector('#cards-section').scrollIntoView({ behavior: 'smooth', block: 'start' });
});

searchInput.addEventListener('input', () => {
  window.clearTimeout(searchDebounce);
  searchDebounce = window.setTimeout(loadCards, 300);
});
packSearchInput.addEventListener('input', filterCollectionButtons);
document.querySelector('#sort-select').addEventListener('change', loadCards);
languageFilters.forEach((filter) => filter.addEventListener('change', loadCards));

collectionList.addEventListener('click', (event) => {
  const button = event.target.closest('.collection-button');
  if (!button) return;
  activeCollection = button.dataset.collection;
  collectionList.querySelectorAll('.collection-button').forEach((item) => {
    item.setAttribute('aria-pressed', String(item === button));
  });
  loadCards();
});

cardGrid.addEventListener('pointerover', (event) => {
  const card = getCardFromElement(event.target);
  if (card) showPreview(card, event);
});
cardGrid.addEventListener('pointermove', (event) => {
  if (cardPreview.classList.contains('is-visible')) movePreview(event);
});
cardGrid.addEventListener('pointerout', (event) => {
  if (!event.relatedTarget || !event.target.closest('.pokemon-card')?.contains(event.relatedTarget)) hidePreview();
});
cardGrid.addEventListener('focusin', (event) => showPreview(getCardFromElement(event.target)));
cardGrid.addEventListener('focusout', (event) => {
  if (!event.relatedTarget || !event.target.closest('.pokemon-card')?.contains(event.relatedTarget)) hidePreview();
});
cardGrid.addEventListener('click', (event) => {
  if (!event.target.closest('.details-button')) return;
  updateDetails(getCardFromElement(event.target));
});

document.querySelectorAll('[data-close]').forEach((button) => {
  button.addEventListener('click', () => document.querySelector(`#${button.dataset.close}`).close());
});
document.querySelector('#pack-alert-close').addEventListener('click', () => packAlertDialog.close());
document.querySelectorAll('dialog').forEach((dialog) => {
  dialog.addEventListener('click', (event) => {
    if (event.target === dialog) dialog.close();
  });
});

document.querySelector('#clear-filters').addEventListener('click', () => {
  searchInput.value = '';
  packSearchInput.value = '';
  filterCollectionButtons();
  languageFilters.forEach((filter) => { filter.checked = true; });
  document.querySelector('#sort-select').value = 'featured';
  activeCollection = packsById.has('sv3pt5') ? 'sv3pt5' : 'all';
  collectionList.querySelectorAll('.collection-button').forEach((button) => {
    button.setAttribute('aria-pressed', String(button.dataset.collection === activeCollection));
  });
  loadCards();
});

async function initialize() {
  try {
    await loadPacks();
  } catch (error) {
    console.error('Erro ao carregar coleções da API MasterBIT:', error);
    document.querySelector('#packs-status').textContent =
      'Não foi possível atualizar os packs. Tentando carregar a coleção selecionada.';
  }
  await loadCards();
}

showPackAlert();
initialize();

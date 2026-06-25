// ── State ────────────────────────────────────────────────────────────────────

let currentWeek = getISOWeek(new Date());
const currentYear = new Date().getFullYear();
let menuData = null;      // WeekSummary dict from API
let catalogue = [];       // all products from /api/catalogue

// Context for the "Add ingredient" modal
let modalContext = { track: null, day: null };

// ── Init ─────────────────────────────────────────────────────────────────────

document.addEventListener('DOMContentLoaded', async () => {
  await loadCatalogue();
  populateModalSelect();
  await loadWeek(currentWeek);
});

// ── ISO week helper ───────────────────────────────────────────────────────────

function getISOWeek(date) {
  const d = new Date(Date.UTC(date.getFullYear(), date.getMonth(), date.getDate()));
  d.setUTCDate(d.getUTCDate() + 4 - (d.getUTCDay() || 7));
  const yearStart = new Date(Date.UTC(d.getUTCFullYear(), 0, 1));
  return Math.ceil((((d - yearStart) / 86400000) + 1) / 7);
}

// ── API helpers ───────────────────────────────────────────────────────────────

async function loadCatalogue() {
  const res = await fetch('/api/catalogue');
  const data = await res.json();
  catalogue = data.products;
}

async function loadWeek(week) {
  updateHeader(week);
  clearGlobalError();

  const res = await fetch(`/api/menu/${week}`);

  if (res.status === 404) {
    menuData = null;
    renderEmpty();
    return;
  }
  if (!res.ok) {
    showGlobalError('Failed to load menu. Please try again.');
    return;
  }

  menuData = await res.json();
  renderCalendar(menuData);
}

// Called by the Generate button in the header
async function generateWeek() {
  const btn = document.getElementById('generate-btn');
  btn.disabled = true;
  btn.textContent = 'Generating…';
  clearGlobalError();

  const res = await fetch(`/api/generate/${currentWeek}`, { method: 'POST' });

  btn.disabled = false;
  btn.textContent = `Generate Week ${currentWeek}`;

  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    const msgs = err.detail?.errors || [JSON.stringify(err.detail || err)];
    showGlobalError(msgs.join('\n'));
    return;
  }

  menuData = await res.json();
  renderCalendar(menuData);
}

// Called by Save inside a dish card
async function saveDish(track, day) {
  const card = document.getElementById(`card-${track}-${day}`);
  const nameInput = card.querySelector('.dish-name-input');
  const ingRows = card.querySelectorAll('.ing-row');
  const errDiv = card.querySelector('.edit-errors');

  errDiv.textContent = '';

  const ingredients = Array.from(ingRows).map(row => ({
    product_id: parseInt(row.dataset.productId, 10),
    quantity_g: parseFloat(row.querySelector('.ing-qty').value) || 1,
  }));

  const res = await fetch(`/api/menu/${currentWeek}/${track}/${day}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      dish_name: nameInput.value.trim(),
      ingredients,
    }),
  });

  if (res.status === 422) {
    const err = await res.json();
    errDiv.textContent = (err.detail?.errors || ['Validation error']).join('\n');
    return;
  }
  if (!res.ok) {
    errDiv.textContent = 'Error saving. Please try again.';
    return;
  }

  menuData = await res.json();
  renderCalendar(menuData);
}

// ── Navigation ────────────────────────────────────────────────────────────────

function changeWeek(delta) {
  currentWeek = Math.max(1, Math.min(53, currentWeek + delta));
  loadWeek(currentWeek);
}

// ── Header helpers ────────────────────────────────────────────────────────────

function updateHeader(week) {
  document.getElementById('week-label').textContent = `Week ${week}, ${currentYear}`;
  document.getElementById('generate-btn').textContent = `Generate Week ${week}`;
}

function clearGlobalError() {
  document.getElementById('global-error').textContent = '';
}

function showGlobalError(msg) {
  document.getElementById('global-error').textContent = msg;
}

// ── Rendering ─────────────────────────────────────────────────────────────────

const DAYS = ['monday', 'tuesday', 'wednesday', 'thursday', 'friday'];
const DAY_LABELS = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday'];

function renderEmpty() {
  document.getElementById('calendar').innerHTML =
    '<div class="empty-state">No menu generated yet for this week. Click "Generate" to create one.</div>';
}

function renderCalendar(data) {
  const cal = document.getElementById('calendar');
  cal.innerHTML = '';

  // Top-left spacer + day column headers
  cal.appendChild(el('div', 'header-spacer'));
  DAY_LABELS.forEach(label => cal.appendChild(el('div', 'day-header', label)));

  // One row per track
  renderTrackRow(cal, data, 'meat', 'Meat Track');
  renderTrackRow(cal, data, 'vegetarian', 'Vegetarian Track');
}

function renderTrackRow(container, data, track, label) {
  const trackData = data[track];

  // Track label cell (first column)
  const labelCell = el('div', `track-label track-${track}`);
  const strong = el('strong', '', label);
  const costSmall = el('small', '', `${trackData.weekly_cost_eur.toFixed(2)} EUR / wk`);
  const kcalSmall = el('small', '', `${Math.round(trackData.weekly_calories_kcal)} kcal / wk`);
  labelCell.appendChild(strong);
  labelCell.appendChild(costSmall);
  labelCell.appendChild(kcalSmall);
  if (trackData.allergens.length) {
    const tag = el('span', 'track-allergen-tag', trackData.allergens.join(', '));
    labelCell.appendChild(tag);
  }
  container.appendChild(labelCell);

  // Five dish cards
  DAYS.forEach(day => {
    const dish = trackData.dishes[day];
    container.appendChild(buildDishCard(track, day, dish));
  });
}

// ── Dish card ─────────────────────────────────────────────────────────────────

function buildDishCard(track, day, dish) {
  const card = el('div', `dish-card dish-${track}`);
  card.id = `card-${track}-${day}`;

  // ── View mode ──
  const view = el('div', 'dish-view');

  const nameDiv = el('div', 'dish-name', dish.dish_name);
  const metaDiv = el('div', 'dish-meta',
    `${dish.total_cost_eur.toFixed(2)} EUR  ·  ${Math.round(dish.total_calories_kcal)} kcal`);

  view.appendChild(nameDiv);
  view.appendChild(metaDiv);

  if (dish.allergens.length) {
    view.appendChild(el('div', 'dish-allergens', `⚠ ${dish.allergens.join(', ')}`));
  }

  const ingList = el('ul', 'ingredient-list');
  dish.ingredients.forEach(ing => {
    let text = `${ing.name} — ${Math.round(ing.quantity_g)} g`;
    if (ing.allergens.length) text += ` [${ing.allergens.join(', ')}]`;
    ingList.appendChild(el('li', '', text));
  });
  view.appendChild(ingList);

  const editBtn = el('button', 'edit-btn', 'Edit');
  editBtn.onclick = () => switchToEdit(card, view, editPane);
  view.appendChild(editBtn);

  // ── Edit mode ──
  const editPane = el('div', 'dish-edit hidden');

  const nameInput = document.createElement('input');
  nameInput.type = 'text';
  nameInput.className = 'dish-name-input';
  nameInput.value = dish.dish_name;
  editPane.appendChild(nameInput);

  const ingEditor = el('div', 'ingredient-editor');
  dish.ingredients.forEach(ing => {
    ingEditor.appendChild(buildIngRow(ing.product_id, ing.name, ing.quantity_g));
  });
  editPane.appendChild(ingEditor);

  // "Add ingredient" button → opens modal
  const addBtn = el('button', 'add-ing-btn', '+ Add ingredient');
  addBtn.onclick = () => openModal(track, day, ingEditor);
  editPane.appendChild(addBtn);

  // Error display
  editPane.appendChild(el('div', 'edit-errors'));

  // Save / Cancel
  const actions = el('div', 'edit-actions');

  const saveBtn = el('button', 'save-btn', 'Save');
  saveBtn.onclick = () => saveDish(track, day);

  const cancelBtn = el('button', 'cancel-btn', 'Cancel');
  cancelBtn.onclick = () => {
    // Re-render card from current data — no API call needed
    const fresh = buildDishCard(track, day, menuData[track].dishes[day]);
    card.replaceWith(fresh);
  };

  actions.appendChild(saveBtn);
  actions.appendChild(cancelBtn);
  editPane.appendChild(actions);

  card.appendChild(view);
  card.appendChild(editPane);

  return card;
}

function switchToEdit(card, view, editPane) {
  view.classList.add('hidden');
  editPane.classList.remove('hidden');
}

function buildIngRow(productId, name, quantityG) {
  const row = el('div', 'ing-row');
  row.dataset.productId = productId;

  const nameSpan = el('span', 'ing-name', name);

  const qtyInput = document.createElement('input');
  qtyInput.type = 'number';
  qtyInput.className = 'ing-qty';
  qtyInput.value = Math.round(quantityG);
  qtyInput.min = '1';

  const gLabel = el('span', '', 'g');

  const removeBtn = el('button', 'remove-btn', '×');
  removeBtn.onclick = () => row.remove();

  row.appendChild(nameSpan);
  row.appendChild(qtyInput);
  row.appendChild(gLabel);
  row.appendChild(removeBtn);

  return row;
}

// ── Add ingredient modal ──────────────────────────────────────────────────────

let activeIngEditor = null;  // the ingEditor div that receives the new row

function populateModalSelect() {
  const select = document.getElementById('modal-select');
  select.innerHTML = '';
  catalogue.forEach(p => {
    const opt = document.createElement('option');
    opt.value = p.product_id;
    opt.textContent = `${p.product_name}  (${p.ingredient_group})`;
    opt.dataset.name = p.product_name;
    select.appendChild(opt);
  });
}

function filterModal() {
  const q = document.getElementById('modal-search').value.toLowerCase();
  const select = document.getElementById('modal-select');
  Array.from(select.options).forEach(opt => {
    opt.hidden = q.length > 0 && !opt.textContent.toLowerCase().includes(q);
  });
}

function openModal(track, day, ingEditor) {
  modalContext = { track, day };
  activeIngEditor = ingEditor;
  document.getElementById('modal-search').value = '';
  filterModal();
  document.getElementById('modal-qty').value = '100';
  document.getElementById('modal-overlay').classList.remove('hidden');
  document.getElementById('modal-search').focus();
}

function closeModal() {
  document.getElementById('modal-overlay').classList.add('hidden');
  activeIngEditor = null;
}

function confirmAdd() {
  if (!activeIngEditor) return;
  const select = document.getElementById('modal-select');
  const selected = select.options[select.selectedIndex];
  if (!selected) return;

  const productId = parseInt(select.value, 10);
  const name = selected.dataset.name;
  const qty = parseFloat(document.getElementById('modal-qty').value) || 100;

  activeIngEditor.appendChild(buildIngRow(productId, name, qty));
  closeModal();
}

// ── DOM helper ────────────────────────────────────────────────────────────────

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

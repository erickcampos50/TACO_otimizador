const state = {
  meta: null,
  foods: [],
  nutrientConstraints: [],
  groupConstraints: [],
  plannerGroupConstraints: [],
  plannerGroupCardinalityConstraints: [],
  mealConstraints: [],
  mealNutrientConstraints: [],
  mealPlannerGroupConstraints: [],
  mealPlannerGroupCardinalityConstraints: [],
  examples: [],
  result: null,
};

const $ = (id) => document.getElementById(id);
const fmt = (value, digits = 2) => (value === null || value === undefined || Number.isNaN(Number(value)) ? '—' : Number(value).toFixed(digits));
const rowId = (prefix) => `${prefix}_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`;
const OBJECTIVE_LABELS = {
  target_matching: 'Bater metas com menor desvio',
  minimize_calories: 'Minimizar calorias',
  maximize_protein: 'Maximizar proteína',
  minimize_cost: 'Minimizar custo',
  custom_weighted: 'Objetivo ponderado customizado',
};
const SOLVER_LABELS = {
  exact: 'Apenas soluções factíveis',
  approximate: 'Melhor aproximação quando inviável',
};
const MODE_LABELS = {
  none: 'Nenhum',
  min: 'Mínimo',
  max: 'Máximo',
  range: 'Faixa',
  ideal: 'Ideal',
  exact: 'Exato',
};
const RUN_STATUS_LABELS = {
  optimal: 'Solução encontrada',
  optimal_with_violations: 'Solução encontrada com ajustes aproximados',
};
const SCOPE_LABELS = {
  global_group: 'Dia inteiro',
  meal_group: 'Por refeição',
  planner_group_global: 'Grupo no dia inteiro',
  planner_group_meal: 'Grupo dentro da refeição',
  planner_group_global_count: 'Itens do grupo no dia inteiro',
  planner_group_meal_count: 'Itens do grupo na refeição',
  meal_total: 'Peso total da refeição',
  meal_nutrient: 'Meta nutricional da refeição',
};

function labelFor(map, value) {
  return map[value] || value || '—';
}

function csvEscape(text) {
  const s = String(text ?? '');
  return `"${s.replaceAll('"', '""')}"`;
}

function readNumeric(value) {
  if (value === '' || value === null || value === undefined) return null;
  const n = Number(value);
  return Number.isFinite(n) ? n : null;
}

function isStandardConstraintActive(row, minField, maxField, idealField) {
  const mode = String(row.mode || 'none');
  return !(mode === 'none' && readNumeric(row[minField]) == null && readNumeric(row[maxField]) == null && readNumeric(row[idealField]) == null);
}

function isCardinalityConstraintActive(row) {
  const mode = String(row.mode || 'none');
  return !(mode === 'none' && readNumeric(row.min_count) == null && readNumeric(row.max_count) == null && readNumeric(row.exact_count) == null && readNumeric(row.ideal_count) == null);
}

function getMealNames() {
  return [...new Set(state.foods.map((item) => String(item.meal || '').trim()).filter(Boolean))].sort((a, b) => a.localeCompare(b));
}

function getPlannerGroups() {
  return [...new Set(state.foods.map((item) => String(item.planner_group || '').trim()).filter(Boolean))].sort((a, b) => a.localeCompare(b));
}

function refreshMealDatalist() {
  const list = $('mealNamesList');
  list.innerHTML = '';
  const meals = getMealNames();
  meals.forEach((meal) => {
    const option = document.createElement('option');
    option.value = meal;
    list.appendChild(option);
  });
  $('mealNamesInfo').textContent = `Refeições detectadas: ${meals.length ? meals.join(' · ') : '—'}`;
}

function refreshPlannerGroupDatalist() {
  const list = $('plannerGroupNamesList');
  list.innerHTML = '';
  const groups = getPlannerGroups();
  groups.forEach((group) => {
    const option = document.createElement('option');
    option.value = group;
    list.appendChild(option);
  });
  $('plannerGroupsInfo').textContent = `Grupos customizados detectados: ${groups.length ? groups.join(' · ') : '—'}`;
}

function setMessage(el, lines, hidden = false) {
  if (hidden || !lines || !lines.length) {
    el.classList.add('hidden');
    el.textContent = '';
    return;
  }
  el.classList.remove('hidden');
  el.textContent = lines.join('\n');
}

async function fetchMeta() {
  const res = await fetch('/api/meta');
  const data = await res.json();
  state.meta = data;
  $('metaCounts').textContent = `${data.foods.length} alimentos · ${data.nutrients.length} parâmetros nutricionais · ${data.groups.length} grupos`;
  buildFoodDatalist();
  renderAllTables();
}

async function fetchExamples() {
  try {
    const res = await fetch('/api/examples');
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail?.errors?.join('\n') || 'Não foi possível carregar os exemplos.');
    state.examples = data.examples || [];
    renderExamplePicker();
  } catch (err) {
    state.examples = [];
    renderExamplePicker();
    setMessage($('warningBox'), [`Exemplos prontos indisponíveis: ${String(err)}`]);
  }
}

function renderExamplePicker() {
  const select = $('examplePresetSelect');
  const previousValue = select.value;
  select.innerHTML = '<option value="">Escolha um exemplo pronto</option>';
  state.examples.forEach((example) => {
    const option = document.createElement('option');
    option.value = example.id;
    option.textContent = example.title;
    select.appendChild(option);
  });
  if (state.examples.some((example) => example.id === previousValue)) {
    select.value = previousValue;
  }
  renderExampleLearningList();
  updateExampleDescription();
}

function renderExampleLearningList() {
  const container = $('exampleLearningList');
  if (!container) return;
  const selectedId = $('examplePresetSelect')?.value;
  container.innerHTML = '';
  if (!state.examples.length) {
    const emptyState = document.createElement('article');
    emptyState.className = 'learning-card';
    const title = document.createElement('h3');
    title.textContent = 'Nenhum exemplo pronto disponível';
    const text = document.createElement('p');
    text.textContent = 'Quando os exemplos estiverem disponíveis, este painel vai resumir como cada cenário ajuda a estudar a aplicação.';
    emptyState.append(title, text);
    container.appendChild(emptyState);
    return;
  }

  state.examples.forEach((example, index) => {
    const card = document.createElement('article');
    card.className = 'learning-card';
    if (example.id === selectedId) {
      card.classList.add('is-selected');
    }

    const order = document.createElement('p');
    order.className = 'note-label';
    order.textContent = `Exemplo ${index + 1}`;

    const title = document.createElement('h3');
    title.textContent = example.title;

    const description = document.createElement('p');
    description.textContent = example.description;

    const goalLabel = document.createElement('p');
    goalLabel.className = 'learning-label';
    goalLabel.textContent = 'O que você aprende';

    const goal = document.createElement('p');
    goal.textContent = example.learning_goal || 'Mostra uma forma diferente de combinar metas e restrições.';

    const tipLabel = document.createElement('p');
    tipLabel.className = 'learning-label';
    tipLabel.textContent = 'Como observar o resultado';

    const tip = document.createElement('p');
    tip.textContent = example.student_tip || 'Carregue o cenário e compare as regras configuradas com o cardápio encontrado.';

    card.append(order, title, description, goalLabel, goal, tipLabel, tip);

    if (example.tags?.length) {
      const tags = document.createElement('div');
      tags.className = 'example-tags';
      example.tags.forEach((tag) => {
        const chip = document.createElement('span');
        chip.className = 'example-tag';
        chip.textContent = tag;
        tags.appendChild(chip);
      });
      card.appendChild(tags);
    }

    container.appendChild(card);
  });
}

function updateExampleDescription() {
  const select = $('examplePresetSelect');
  const selected = state.examples.find((item) => item.id === select.value);
  select.disabled = !state.examples.length;
  $('loadExampleBtn').disabled = !selected;
  renderExampleLearningList();
  $('exampleDescription').textContent = selected
    ? `${selected.description} O que este exemplo ensina: ${selected.learning_goal || 'comparar regras e resultado.'} Para estudar melhor: ${selected.student_tip || 'calcule o cardápio e observe o que mudou.'}${selected.tags?.length ? ` Destaques: ${selected.tags.join(' · ')}.` : ''}`
    : (state.examples.length
      ? 'Escolha um cenário para aprender com uma configuração pronta. Esses exemplos mostram, em linguagem prática, como metas, custos, refeições e grupos alteram o cardápio calculado.'
      : 'Nenhum exemplo pronto disponível no momento.');
}

function buildFoodDatalist() {
  const list = $('foodList');
  list.innerHTML = '';
  state.meta.foods.forEach((food) => {
    const option = document.createElement('option');
    option.value = `${food.code} - ${food.description}`;
    list.appendChild(option);
  });
}

function renderAllTables() {
  renderFoodsTable();
  renderNutrientConstraintRows();
  renderGroupConstraintRows();
  renderPlannerGroupConstraintRows();
  renderPlannerGroupCardinalityConstraintRows();
  renderMealConstraintRows();
  renderMealNutrientConstraintRows();
  renderMealPlannerGroupConstraintRows();
  renderMealPlannerGroupCardinalityConstraintRows();
}

function findFoodByInput(value) {
  const cleaned = value.trim();
  if (!cleaned) return null;
  const codeMatch = cleaned.match(/^(\d+)/);
  if (codeMatch) {
    const code = Number(codeMatch[1]);
    return state.meta.foods.find((f) => Number(f.code) === code) || null;
  }
  const lower = cleaned.toLowerCase();
  return state.meta.foods.find((f) => f.description.toLowerCase() === lower)
    || state.meta.foods.find((f) => f.description.toLowerCase().includes(lower))
    || null;
}

function addFood(food, overrides = {}) {
  if (!food) return;
  state.foods.push({
    row_id: rowId('food'),
    enabled: true,
    code: Number(food.code),
    description: food.description,
    group: food.group || '',
    planner_group: overrides.planner_group || '',
    meal: overrides.meal || '',
    min_g: overrides.min_g ?? 0,
    max_g: overrides.max_g ?? '',
    selection_min_g: overrides.selection_min_g ?? 1,
    cost_per_100g: overrides.cost_per_100g ?? '',
  });
  renderFoodsTable();
}

function buildFoodRow(food, overrides = {}) {
  return {
    row_id: overrides.row_id || rowId('food'),
    enabled: overrides.enabled !== false,
    code: Number(food.code),
    description: food.description,
    group: food.group || '',
    planner_group: overrides.planner_group || '',
    meal: overrides.meal || '',
    min_g: overrides.min_g ?? 0,
    max_g: overrides.max_g ?? '',
    selection_min_g: overrides.selection_min_g ?? 1,
    cost_per_100g: overrides.cost_per_100g ?? '',
  };
}

function hydrateExampleFoods(candidateFoods = []) {
  return candidateFoods
    .map((item) => {
      const food = state.meta?.foods.find((entry) => Number(entry.code) === Number(item.code));
      return food ? buildFoodRow(food, item) : null;
    })
    .filter(Boolean);
}

function hydrateRows(rows = [], prefix) {
  return rows.map((item) => ({
    ...item,
    row_id: item.row_id || rowId(prefix),
  }));
}

function applyExamplePayload(payload) {
  resetAllInputs();
  state.foods = hydrateExampleFoods(payload.candidate_foods || []);
  state.nutrientConstraints = hydrateRows(payload.nutrient_constraints || [], 'nc');
  state.groupConstraints = hydrateRows(payload.group_constraints || [], 'gc');
  state.plannerGroupConstraints = hydrateRows(payload.planner_group_constraints || [], 'pgc');
  state.plannerGroupCardinalityConstraints = hydrateRows(payload.planner_group_cardinality_constraints || [], 'pgcc');
  state.mealConstraints = hydrateRows(payload.meal_constraints || [], 'mc');
  state.mealNutrientConstraints = hydrateRows(payload.meal_nutrient_constraints || [], 'mnc');
  state.mealPlannerGroupConstraints = hydrateRows(payload.meal_planner_group_constraints || [], 'mpgc');
  state.mealPlannerGroupCardinalityConstraints = hydrateRows(payload.meal_planner_group_cardinality_constraints || [], 'mpgcc');

  renderAllTables();

  const settings = payload.settings || {};
  $('objectiveMode').value = settings.objective_mode || 'target_matching';
  $('solverMode').value = settings.solver_mode || 'exact';
  $('totalMinG').value = settings.total_min_g ?? '';
  $('totalMaxG').value = settings.total_max_g ?? '';
  $('wCalories').value = settings.objective_weights?.calories ?? 1;
  $('wProtein').value = settings.objective_weights?.protein ?? 1;
  $('wCost').value = settings.objective_weights?.cost ?? 1;
  $('wGrams').value = settings.objective_weights?.grams ?? 0;
  $('wDeviation').value = settings.objective_weights?.deviation ?? 1;
  toggleCustomWeights();
}

function removeFood(rowIdValue) {
  state.foods = state.foods.filter((item) => item.row_id !== rowIdValue);
  renderFoodsTable();
}

function renderFoodsTable() {
  const tbody = $('foodsTable').querySelector('tbody');
  tbody.innerHTML = '';
  state.foods.forEach((item) => {
    const tr = document.createElement('tr');
    tr.innerHTML = `
      <td class="center"><input type="checkbox" ${item.enabled ? 'checked' : ''} data-action="toggle-food" data-id="${item.row_id}" /></td>
      <td>${item.code}</td>
      <td>${item.description}</td>
      <td>${item.group || '—'}</td>
      <td><input type="text" list="plannerGroupNamesList" value="${item.planner_group || ''}" data-field="planner_group" data-id="${item.row_id}" placeholder="ex.: fruta, proteína" /></td>
      <td><input type="text" list="mealNamesList" value="${item.meal || ''}" data-field="meal" data-id="${item.row_id}" /></td>
      <td><input type="number" step="0.01" value="${item.min_g}" data-field="min_g" data-id="${item.row_id}" /></td>
      <td><input type="number" step="0.01" value="${item.max_g}" data-field="max_g" data-id="${item.row_id}" /></td>
      <td><input type="number" step="0.01" value="${item.selection_min_g}" data-field="selection_min_g" data-id="${item.row_id}" /></td>
      <td><input type="number" step="0.01" value="${item.cost_per_100g}" data-field="cost_per_100g" data-id="${item.row_id}" /></td>
      <td><button class="small-btn danger" data-action="remove-food" data-id="${item.row_id}">Remover</button></td>
    `;
    tbody.appendChild(tr);
  });
  refreshMealDatalist();
  refreshPlannerGroupDatalist();
}

function addNutrientConstraint(initial = {}) {
  state.nutrientConstraints.push({
    row_id: rowId('nc'),
    nutrient: initial.nutrient || state.meta.nutrients[0]?.name || '',
    mode: initial.mode || 'min',
    min_value: initial.min_value ?? '',
    max_value: initial.max_value ?? '',
    ideal_value: initial.ideal_value ?? '',
    weight: initial.weight ?? 1,
  });
  renderNutrientConstraintRows();
}

function removeNutrientConstraint(rowIdValue) {
  state.nutrientConstraints = state.nutrientConstraints.filter((r) => r.row_id !== rowIdValue);
  renderNutrientConstraintRows();
}

function renderNutrientConstraintRows() {
  const tbody = $('nutrientTable').querySelector('tbody');
  tbody.innerHTML = '';
  const nutrientOptions = state.meta ? state.meta.nutrients.map((n) => `<option value="${n.name}">${n.name}</option>`).join('') : '';
  state.nutrientConstraints.forEach((row) => {
    const tr = document.createElement('tr');
    tr.innerHTML = `
      <td><select data-table="nutrient" data-field="nutrient" data-id="${row.row_id}">${nutrientOptions}</select></td>
      <td>
        <select data-table="nutrient" data-field="mode" data-id="${row.row_id}">
          <option value="none">Nenhum</option>
          <option value="min">Mínimo</option>
          <option value="max">Máximo</option>
          <option value="range">Faixa</option>
          <option value="ideal">Ideal</option>
        </select>
      </td>
      <td><input type="number" step="0.01" value="${row.min_value}" data-table="nutrient" data-field="min_value" data-id="${row.row_id}" /></td>
      <td><input type="number" step="0.01" value="${row.max_value}" data-table="nutrient" data-field="max_value" data-id="${row.row_id}" /></td>
      <td><input type="number" step="0.01" value="${row.ideal_value}" data-table="nutrient" data-field="ideal_value" data-id="${row.row_id}" /></td>
      <td><input type="number" step="0.01" value="${row.weight}" data-table="nutrient" data-field="weight" data-id="${row.row_id}" /></td>
      <td><button class="small-btn danger" data-action="remove-nutrient" data-id="${row.row_id}">Remover</button></td>
    `;
    tbody.appendChild(tr);
    tr.querySelector('select[data-field="nutrient"]').value = row.nutrient;
    tr.querySelector('select[data-field="mode"]').value = row.mode;
  });
}

function addGroupConstraint(initial = {}) {
  state.groupConstraints.push({
    row_id: rowId('gc'),
    group: initial.group || state.meta.groups[0] || '',
    min_g: initial.min_g ?? '',
    max_g: initial.max_g ?? '',
  });
  renderGroupConstraintRows();
}

function removeGroupConstraint(rowIdValue) {
  state.groupConstraints = state.groupConstraints.filter((r) => r.row_id !== rowIdValue);
  renderGroupConstraintRows();
}

function renderGroupConstraintRows() {
  const tbody = $('groupTable').querySelector('tbody');
  tbody.innerHTML = '';
  const groupOptions = state.meta ? state.meta.groups.map((g) => `<option value="${g}">${g}</option>`).join('') : '';
  state.groupConstraints.forEach((row) => {
    const tr = document.createElement('tr');
    tr.innerHTML = `
      <td><select data-table="group" data-field="group" data-id="${row.row_id}">${groupOptions}</select></td>
      <td><input type="number" step="0.01" value="${row.min_g}" data-table="group" data-field="min_g" data-id="${row.row_id}" /></td>
      <td><input type="number" step="0.01" value="${row.max_g}" data-table="group" data-field="max_g" data-id="${row.row_id}" /></td>
      <td><button class="small-btn danger" data-action="remove-group" data-id="${row.row_id}">Remover</button></td>
    `;
    tbody.appendChild(tr);
    tr.querySelector('select[data-field="group"]').value = row.group;
  });
}

function addPlannerGroupConstraint(initial = {}) {
  state.plannerGroupConstraints.push({
    row_id: rowId('pgc'),
    group: initial.group || getPlannerGroups()[0] || '',
    mode: initial.mode || 'range',
    min_g: initial.min_g ?? '',
    max_g: initial.max_g ?? '',
    ideal_g: initial.ideal_g ?? '',
    weight: initial.weight ?? 1,
  });
  renderPlannerGroupConstraintRows();
}

function removePlannerGroupConstraint(rowIdValue) {
  state.plannerGroupConstraints = state.plannerGroupConstraints.filter((r) => r.row_id !== rowIdValue);
  renderPlannerGroupConstraintRows();
}

function renderPlannerGroupConstraintRows() {
  const tbody = $('plannerGroupTable').querySelector('tbody');
  tbody.innerHTML = '';
  state.plannerGroupConstraints.forEach((row) => {
    const tr = document.createElement('tr');
    tr.innerHTML = `
      <td><input type="text" list="plannerGroupNamesList" value="${row.group}" data-table="planner-group" data-field="group" data-id="${row.row_id}" /></td>
      <td>
        <select data-table="planner-group" data-field="mode" data-id="${row.row_id}">
          <option value="none">Nenhum</option>
          <option value="min">Mínimo</option>
          <option value="max">Máximo</option>
          <option value="range">Faixa</option>
          <option value="ideal">Ideal</option>
        </select>
      </td>
      <td><input type="number" step="0.01" value="${row.min_g}" data-table="planner-group" data-field="min_g" data-id="${row.row_id}" /></td>
      <td><input type="number" step="0.01" value="${row.max_g}" data-table="planner-group" data-field="max_g" data-id="${row.row_id}" /></td>
      <td><input type="number" step="0.01" value="${row.ideal_g}" data-table="planner-group" data-field="ideal_g" data-id="${row.row_id}" /></td>
      <td><input type="number" step="0.01" value="${row.weight}" data-table="planner-group" data-field="weight" data-id="${row.row_id}" /></td>
      <td><button class="small-btn danger" data-action="remove-planner-group" data-id="${row.row_id}">Remover</button></td>
    `;
    tbody.appendChild(tr);
    tr.querySelector('select[data-field="mode"]').value = row.mode;
  });
}

function addPlannerGroupCardinalityConstraint(initial = {}) {
  state.plannerGroupCardinalityConstraints.push({
    row_id: rowId('pgcc'),
    group: initial.group || getPlannerGroups()[0] || '',
    mode: initial.mode || 'max',
    min_count: initial.min_count ?? '',
    max_count: initial.max_count ?? '',
    exact_count: initial.exact_count ?? '',
    ideal_count: initial.ideal_count ?? '',
    weight: initial.weight ?? 1,
  });
  renderPlannerGroupCardinalityConstraintRows();
}

function removePlannerGroupCardinalityConstraint(rowIdValue) {
  state.plannerGroupCardinalityConstraints = state.plannerGroupCardinalityConstraints.filter((r) => r.row_id !== rowIdValue);
  renderPlannerGroupCardinalityConstraintRows();
}

function renderPlannerGroupCardinalityConstraintRows() {
  const tbody = $('plannerGroupCardinalityTable').querySelector('tbody');
  tbody.innerHTML = '';
  state.plannerGroupCardinalityConstraints.forEach((row) => {
    const tr = document.createElement('tr');
    tr.innerHTML = `
      <td><input type="text" list="plannerGroupNamesList" value="${row.group}" data-table="planner-group-cardinality" data-field="group" data-id="${row.row_id}" /></td>
      <td>
        <select data-table="planner-group-cardinality" data-field="mode" data-id="${row.row_id}">
          <option value="none">Nenhum</option>
          <option value="min">Mínimo</option>
          <option value="max">Máximo</option>
          <option value="range">Faixa</option>
          <option value="exact">Exato</option>
          <option value="ideal">Ideal</option>
        </select>
      </td>
      <td><input type="number" step="1" value="${row.min_count}" data-table="planner-group-cardinality" data-field="min_count" data-id="${row.row_id}" /></td>
      <td><input type="number" step="1" value="${row.max_count}" data-table="planner-group-cardinality" data-field="max_count" data-id="${row.row_id}" /></td>
      <td><input type="number" step="1" value="${row.exact_count}" data-table="planner-group-cardinality" data-field="exact_count" data-id="${row.row_id}" /></td>
      <td><input type="number" step="1" value="${row.ideal_count}" data-table="planner-group-cardinality" data-field="ideal_count" data-id="${row.row_id}" /></td>
      <td><input type="number" step="0.01" value="${row.weight}" data-table="planner-group-cardinality" data-field="weight" data-id="${row.row_id}" /></td>
      <td><button class="small-btn danger" data-action="remove-planner-group-cardinality" data-id="${row.row_id}">Remover</button></td>
    `;
    tbody.appendChild(tr);
    tr.querySelector('select[data-field="mode"]').value = row.mode;
  });
}

function addMealConstraint(initial = {}) {
  state.mealConstraints.push({
    row_id: rowId('mc'),
    meal: initial.meal || getMealNames()[0] || '',
    min_g: initial.min_g ?? '',
    max_g: initial.max_g ?? '',
  });
  renderMealConstraintRows();
}

function removeMealConstraint(rowIdValue) {
  state.mealConstraints = state.mealConstraints.filter((r) => r.row_id !== rowIdValue);
  renderMealConstraintRows();
}

function renderMealConstraintRows() {
  const tbody = $('mealTable').querySelector('tbody');
  tbody.innerHTML = '';
  state.mealConstraints.forEach((row) => {
    const tr = document.createElement('tr');
    tr.innerHTML = `
      <td><input type="text" list="mealNamesList" value="${row.meal}" data-table="meal" data-field="meal" data-id="${row.row_id}" /></td>
      <td><input type="number" step="0.01" value="${row.min_g}" data-table="meal" data-field="min_g" data-id="${row.row_id}" /></td>
      <td><input type="number" step="0.01" value="${row.max_g}" data-table="meal" data-field="max_g" data-id="${row.row_id}" /></td>
      <td><button class="small-btn danger" data-action="remove-meal" data-id="${row.row_id}">Remover</button></td>
    `;
    tbody.appendChild(tr);
  });
}

function addMealNutrientConstraint(initial = {}) {
  state.mealNutrientConstraints.push({
    row_id: rowId('mnc'),
    meal: initial.meal || getMealNames()[0] || '',
    nutrient: initial.nutrient || state.meta.nutrients[0]?.name || '',
    mode: initial.mode || 'min',
    min_value: initial.min_value ?? '',
    max_value: initial.max_value ?? '',
    ideal_value: initial.ideal_value ?? '',
    weight: initial.weight ?? 1,
  });
  renderMealNutrientConstraintRows();
}

function removeMealNutrientConstraint(rowIdValue) {
  state.mealNutrientConstraints = state.mealNutrientConstraints.filter((r) => r.row_id !== rowIdValue);
  renderMealNutrientConstraintRows();
}

function renderMealNutrientConstraintRows() {
  const tbody = $('mealNutrientTable').querySelector('tbody');
  tbody.innerHTML = '';
  const nutrientOptions = state.meta ? state.meta.nutrients.map((n) => `<option value="${n.name}">${n.name}</option>`).join('') : '';
  state.mealNutrientConstraints.forEach((row) => {
    const tr = document.createElement('tr');
    tr.innerHTML = `
      <td><input type="text" list="mealNamesList" value="${row.meal}" data-table="meal-nutrient" data-field="meal" data-id="${row.row_id}" /></td>
      <td><select data-table="meal-nutrient" data-field="nutrient" data-id="${row.row_id}">${nutrientOptions}</select></td>
      <td>
        <select data-table="meal-nutrient" data-field="mode" data-id="${row.row_id}">
          <option value="none">Nenhum</option>
          <option value="min">Mínimo</option>
          <option value="max">Máximo</option>
          <option value="range">Faixa</option>
          <option value="ideal">Ideal</option>
        </select>
      </td>
      <td><input type="number" step="0.01" value="${row.min_value}" data-table="meal-nutrient" data-field="min_value" data-id="${row.row_id}" /></td>
      <td><input type="number" step="0.01" value="${row.max_value}" data-table="meal-nutrient" data-field="max_value" data-id="${row.row_id}" /></td>
      <td><input type="number" step="0.01" value="${row.ideal_value}" data-table="meal-nutrient" data-field="ideal_value" data-id="${row.row_id}" /></td>
      <td><input type="number" step="0.01" value="${row.weight}" data-table="meal-nutrient" data-field="weight" data-id="${row.row_id}" /></td>
      <td><button class="small-btn danger" data-action="remove-meal-nutrient" data-id="${row.row_id}">Remover</button></td>
    `;
    tbody.appendChild(tr);
    tr.querySelector('select[data-field="nutrient"]').value = row.nutrient;
    tr.querySelector('select[data-field="mode"]').value = row.mode;
  });
}

function addMealPlannerGroupConstraint(initial = {}) {
  state.mealPlannerGroupConstraints.push({
    row_id: rowId('mpgc'),
    meal: initial.meal || getMealNames()[0] || '',
    group: initial.group || getPlannerGroups()[0] || '',
    mode: initial.mode || 'range',
    min_g: initial.min_g ?? '',
    max_g: initial.max_g ?? '',
    ideal_g: initial.ideal_g ?? '',
    weight: initial.weight ?? 1,
  });
  renderMealPlannerGroupConstraintRows();
}

function removeMealPlannerGroupConstraint(rowIdValue) {
  state.mealPlannerGroupConstraints = state.mealPlannerGroupConstraints.filter((r) => r.row_id !== rowIdValue);
  renderMealPlannerGroupConstraintRows();
}

function renderMealPlannerGroupConstraintRows() {
  const tbody = $('mealPlannerGroupTable').querySelector('tbody');
  tbody.innerHTML = '';
  state.mealPlannerGroupConstraints.forEach((row) => {
    const tr = document.createElement('tr');
    tr.innerHTML = `
      <td><input type="text" list="mealNamesList" value="${row.meal}" data-table="meal-planner-group" data-field="meal" data-id="${row.row_id}" /></td>
      <td><input type="text" list="plannerGroupNamesList" value="${row.group}" data-table="meal-planner-group" data-field="group" data-id="${row.row_id}" /></td>
      <td>
        <select data-table="meal-planner-group" data-field="mode" data-id="${row.row_id}">
          <option value="none">Nenhum</option>
          <option value="min">Mínimo</option>
          <option value="max">Máximo</option>
          <option value="range">Faixa</option>
          <option value="ideal">Ideal</option>
        </select>
      </td>
      <td><input type="number" step="0.01" value="${row.min_g}" data-table="meal-planner-group" data-field="min_g" data-id="${row.row_id}" /></td>
      <td><input type="number" step="0.01" value="${row.max_g}" data-table="meal-planner-group" data-field="max_g" data-id="${row.row_id}" /></td>
      <td><input type="number" step="0.01" value="${row.ideal_g}" data-table="meal-planner-group" data-field="ideal_g" data-id="${row.row_id}" /></td>
      <td><input type="number" step="0.01" value="${row.weight}" data-table="meal-planner-group" data-field="weight" data-id="${row.row_id}" /></td>
      <td><button class="small-btn danger" data-action="remove-meal-planner-group" data-id="${row.row_id}">Remover</button></td>
    `;
    tbody.appendChild(tr);
    tr.querySelector('select[data-field="mode"]').value = row.mode;
  });
}

function addMealPlannerGroupCardinalityConstraint(initial = {}) {
  state.mealPlannerGroupCardinalityConstraints.push({
    row_id: rowId('mpgcc'),
    meal: initial.meal || getMealNames()[0] || '',
    group: initial.group || getPlannerGroups()[0] || '',
    mode: initial.mode || 'exact',
    min_count: initial.min_count ?? '',
    max_count: initial.max_count ?? '',
    exact_count: initial.exact_count ?? '',
    ideal_count: initial.ideal_count ?? '',
    weight: initial.weight ?? 1,
  });
  renderMealPlannerGroupCardinalityConstraintRows();
}

function removeMealPlannerGroupCardinalityConstraint(rowIdValue) {
  state.mealPlannerGroupCardinalityConstraints = state.mealPlannerGroupCardinalityConstraints.filter((r) => r.row_id !== rowIdValue);
  renderMealPlannerGroupCardinalityConstraintRows();
}

function renderMealPlannerGroupCardinalityConstraintRows() {
  const tbody = $('mealPlannerGroupCardinalityTable').querySelector('tbody');
  tbody.innerHTML = '';
  state.mealPlannerGroupCardinalityConstraints.forEach((row) => {
    const tr = document.createElement('tr');
    tr.innerHTML = `
      <td><input type="text" list="mealNamesList" value="${row.meal}" data-table="meal-planner-group-cardinality" data-field="meal" data-id="${row.row_id}" /></td>
      <td><input type="text" list="plannerGroupNamesList" value="${row.group}" data-table="meal-planner-group-cardinality" data-field="group" data-id="${row.row_id}" /></td>
      <td>
        <select data-table="meal-planner-group-cardinality" data-field="mode" data-id="${row.row_id}">
          <option value="none">Nenhum</option>
          <option value="min">Mínimo</option>
          <option value="max">Máximo</option>
          <option value="range">Faixa</option>
          <option value="exact">Exato</option>
          <option value="ideal">Ideal</option>
        </select>
      </td>
      <td><input type="number" step="1" value="${row.min_count}" data-table="meal-planner-group-cardinality" data-field="min_count" data-id="${row.row_id}" /></td>
      <td><input type="number" step="1" value="${row.max_count}" data-table="meal-planner-group-cardinality" data-field="max_count" data-id="${row.row_id}" /></td>
      <td><input type="number" step="1" value="${row.exact_count}" data-table="meal-planner-group-cardinality" data-field="exact_count" data-id="${row.row_id}" /></td>
      <td><input type="number" step="1" value="${row.ideal_count}" data-table="meal-planner-group-cardinality" data-field="ideal_count" data-id="${row.row_id}" /></td>
      <td><input type="number" step="0.01" value="${row.weight}" data-table="meal-planner-group-cardinality" data-field="weight" data-id="${row.row_id}" /></td>
      <td><button class="small-btn danger" data-action="remove-meal-planner-group-cardinality" data-id="${row.row_id}">Remover</button></td>
    `;
    tbody.appendChild(tr);
    tr.querySelector('select[data-field="mode"]').value = row.mode;
  });
}

function collectPayload() {
  return {
    candidate_foods: state.foods.map((item) => ({
      row_id: item.row_id,
      code: Number(item.code),
      min_g: readNumeric(item.min_g) ?? 0,
      max_g: readNumeric(item.max_g),
      selection_min_g: readNumeric(item.selection_min_g) ?? 1,
      cost_per_100g: readNumeric(item.cost_per_100g),
      meal: item.meal || null,
      planner_group: (item.planner_group || '').trim() || null,
      enabled: Boolean(item.enabled),
    })),
    nutrient_constraints: state.nutrientConstraints.filter((row) => isStandardConstraintActive(row, 'min_value', 'max_value', 'ideal_value')).map((row) => ({
      nutrient: row.nutrient,
      mode: row.mode,
      min_value: readNumeric(row.min_value),
      max_value: readNumeric(row.max_value),
      ideal_value: readNumeric(row.ideal_value),
      weight: readNumeric(row.weight) ?? 1,
    })),
    group_constraints: state.groupConstraints.filter((row) => String(row.group || '').trim() || readNumeric(row.min_g) != null || readNumeric(row.max_g) != null).map((row) => ({
      group: row.group,
      min_g: readNumeric(row.min_g),
      max_g: readNumeric(row.max_g),
    })),
    planner_group_constraints: state.plannerGroupConstraints.filter((row) => isStandardConstraintActive(row, 'min_g', 'max_g', 'ideal_g')).map((row) => ({
      group: String(row.group || '').trim(),
      mode: row.mode,
      min_g: readNumeric(row.min_g),
      max_g: readNumeric(row.max_g),
      ideal_g: readNumeric(row.ideal_g),
      weight: readNumeric(row.weight) ?? 1,
    })),
    planner_group_cardinality_constraints: state.plannerGroupCardinalityConstraints.filter((row) => isCardinalityConstraintActive(row)).map((row) => ({
      group: String(row.group || '').trim(),
      mode: row.mode,
      min_count: readNumeric(row.min_count),
      max_count: readNumeric(row.max_count),
      exact_count: readNumeric(row.exact_count),
      ideal_count: readNumeric(row.ideal_count),
      weight: readNumeric(row.weight) ?? 1,
    })),
    meal_constraints: state.mealConstraints.filter((row) => String(row.meal || '').trim() || readNumeric(row.min_g) != null || readNumeric(row.max_g) != null).map((row) => ({
      meal: String(row.meal || '').trim(),
      min_g: readNumeric(row.min_g),
      max_g: readNumeric(row.max_g),
    })),
    meal_nutrient_constraints: state.mealNutrientConstraints.filter((row) => isStandardConstraintActive(row, 'min_value', 'max_value', 'ideal_value')).map((row) => ({
      meal: String(row.meal || '').trim(),
      nutrient: row.nutrient,
      mode: row.mode,
      min_value: readNumeric(row.min_value),
      max_value: readNumeric(row.max_value),
      ideal_value: readNumeric(row.ideal_value),
      weight: readNumeric(row.weight) ?? 1,
    })),
    meal_planner_group_constraints: state.mealPlannerGroupConstraints.filter((row) => isStandardConstraintActive(row, 'min_g', 'max_g', 'ideal_g')).map((row) => ({
      meal: String(row.meal || '').trim(),
      group: String(row.group || '').trim(),
      mode: row.mode,
      min_g: readNumeric(row.min_g),
      max_g: readNumeric(row.max_g),
      ideal_g: readNumeric(row.ideal_g),
      weight: readNumeric(row.weight) ?? 1,
    })),
    meal_planner_group_cardinality_constraints: state.mealPlannerGroupCardinalityConstraints.filter((row) => isCardinalityConstraintActive(row)).map((row) => ({
      meal: String(row.meal || '').trim(),
      group: String(row.group || '').trim(),
      mode: row.mode,
      min_count: readNumeric(row.min_count),
      max_count: readNumeric(row.max_count),
      exact_count: readNumeric(row.exact_count),
      ideal_count: readNumeric(row.ideal_count),
      weight: readNumeric(row.weight) ?? 1,
    })),
    settings: {
      objective_mode: $('objectiveMode').value,
      solver_mode: $('solverMode').value,
      total_min_g: readNumeric($('totalMinG').value),
      total_max_g: readNumeric($('totalMaxG').value),
      objective_weights: {
        calories: readNumeric($('wCalories').value) ?? 1,
        protein: readNumeric($('wProtein').value) ?? 1,
        cost: readNumeric($('wCost').value) ?? 1,
        grams: readNumeric($('wGrams').value) ?? 0,
        deviation: readNumeric($('wDeviation').value) ?? 1,
      },
    },
  };
}

async function solve() {
  setMessage($('errorBox'), [], true);
  setMessage($('warningBox'), [], true);
  $('solveBtn').disabled = true;
  $('solveBtn').textContent = 'Calculando cardápio...';
  try {
    const payload = collectPayload();
    const res = await fetch('/api/optimize', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    const data = await res.json();
    if (!res.ok) {
      setMessage($('errorBox'), data.detail?.errors || ['Erro inesperado ao otimizar.']);
      return;
    }
    state.result = data;
    renderResult();
  } catch (err) {
    setMessage($('errorBox'), [String(err)]);
  } finally {
    $('solveBtn').disabled = false;
    $('solveBtn').textContent = 'Calcular cardápio';
  }
}

function renderResult() {
  const r = state.result;
  $('metricStatus').textContent = labelFor(RUN_STATUS_LABELS, r.status);
  $('metricObjective').textContent = `${labelFor(OBJECTIVE_LABELS, r.objective_mode)} · ${labelFor(SOLVER_LABELS, r.solver_mode)}`;
  $('metricGrams').textContent = `${fmt(r.total_grams)} g`;
  $('metricCost').textContent = fmt(r.total_estimated_cost);
  setMessage($('warningBox'), r.warnings || [], !(r.warnings || []).length);
  $('exportResultBtn').disabled = false;

  const foodBody = $('resultFoodsTable').querySelector('tbody');
  foodBody.innerHTML = '';
  (r.foods || []).forEach((item) => {
    const tr = document.createElement('tr');
    tr.innerHTML = `
      <td>${item.code}</td>
      <td>${item.description}</td>
      <td>${item.group || '—'}</td>
      <td>${item.planner_group || '—'}</td>
      <td>${item.meal || '—'}</td>
      <td>${item.selected ? 'Sim' : 'Não'}</td>
      <td>${fmt(item.grams)}</td>
      <td>${fmt(item['Energia (kcal)'])}</td>
      <td>${fmt(item['Proteína (g)'])}</td>
      <td>${fmt(item['Carboidrato (g)'])}</td>
      <td>${fmt(item['Lipídeos (g)'])}</td>
      <td>${fmt(item['Fibra Alimentar (g)'])}</td>
      <td>${item.estimated_cost == null ? '—' : fmt(item.estimated_cost)}</td>
    `;
    foodBody.appendChild(tr);
  });

  const mealSummaryBody = $('mealSummaryTable').querySelector('tbody');
  mealSummaryBody.innerHTML = '';
  (r.meal_summaries || []).forEach((item) => {
    const tr = document.createElement('tr');
    tr.innerHTML = `
      <td>${item.meal}</td>
      <td>${item.food_count}</td>
      <td>${item.selected_count ?? '—'}</td>
      <td>${fmt(item.total_grams)}</td>
      <td>${fmt(item['Energia (kcal)'])}</td>
      <td>${fmt(item['Proteína (g)'])}</td>
      <td>${fmt(item['Carboidrato (g)'])}</td>
      <td>${fmt(item['Lipídeos (g)'])}</td>
      <td>${fmt(item['Fibra Alimentar (g)'])}</td>
      <td>${fmt(item.total_estimated_cost)}</td>
    `;
    mealSummaryBody.appendChild(tr);
  });

  const plannerSummaryBody = $('plannerGroupSummaryTable').querySelector('tbody');
  plannerSummaryBody.innerHTML = '';
  (r.planner_group_summaries || []).forEach((item) => {
    const tr = document.createElement('tr');
    tr.innerHTML = `
      <td>${labelFor(SCOPE_LABELS, item.scope)}</td>
      <td>${item.group}</td>
      <td>${item.meal || '—'}</td>
      <td>${item.food_count}</td>
      <td>${item.selected_count ?? '—'}</td>
      <td>${fmt(item.total_grams)}</td>
    `;
    plannerSummaryBody.appendChild(tr);
  });

  const groupConstraintsBody = $('groupConstraintsResultTable').querySelector('tbody');
  groupConstraintsBody.innerHTML = '';
  (r.active_group_constraints || []).forEach((item) => {
    const tr = document.createElement('tr');
    tr.innerHTML = `
      <td>${labelFor(SCOPE_LABELS, item.scope)}</td>
      <td>${item.group}</td>
      <td>${item.meal || '—'}</td>
      <td>${labelFor(MODE_LABELS, item.mode)}</td>
      <td>${fmt(item.realized, 4)}</td>
      <td>${item.min_value == null ? '—' : fmt(item.min_value, 4)}</td>
      <td>${item.max_value == null ? '—' : fmt(item.max_value, 4)}</td>
      <td>${item.ideal_value == null ? '—' : fmt(item.ideal_value, 4)}</td>
      <td>${item.deviation == null ? '—' : fmt(item.deviation, 4)}</td>
      <td class="status-${item.status}">${item.status}</td>
    `;
    groupConstraintsBody.appendChild(tr);
  });

  const groupCardBody = $('groupCardinalityResultTable').querySelector('tbody');
  groupCardBody.innerHTML = '';
  (r.active_group_cardinality_constraints || []).forEach((item) => {
    const tr = document.createElement('tr');
    tr.innerHTML = `
      <td>${labelFor(SCOPE_LABELS, item.scope)}</td>
      <td>${item.group}</td>
      <td>${item.meal || '—'}</td>
      <td>${labelFor(MODE_LABELS, item.mode)}</td>
      <td>${fmt(item.realized, 0)}</td>
      <td>${item.min_value == null ? '—' : fmt(item.min_value, 0)}</td>
      <td>${item.max_value == null ? '—' : fmt(item.max_value, 0)}</td>
      <td>${item.ideal_value == null ? '—' : fmt(item.ideal_value, 0)}</td>
      <td>${item.deviation == null ? '—' : fmt(item.deviation, 4)}</td>
      <td class="status-${item.status}">${item.status}</td>
    `;
    groupCardBody.appendChild(tr);
  });

  const constraintsBody = $('constraintsResultTable').querySelector('tbody');
  constraintsBody.innerHTML = '';
  (r.active_constraints || []).forEach((item) => {
    const tr = document.createElement('tr');
    tr.innerHTML = `
      <td>${item.nutrient}</td>
      <td>${labelFor(MODE_LABELS, item.mode)}</td>
      <td>${fmt(item.realized, 4)}</td>
      <td>${item.min_value == null ? '—' : fmt(item.min_value, 4)}</td>
      <td>${item.max_value == null ? '—' : fmt(item.max_value, 4)}</td>
      <td>${item.ideal_value == null ? '—' : fmt(item.ideal_value, 4)}</td>
      <td>${item.deviation == null ? '—' : fmt(item.deviation, 4)}</td>
      <td class="status-${item.status}">${item.status}</td>
    `;
    constraintsBody.appendChild(tr);
  });

  const mealConstraintsBody = $('mealConstraintsResultTable').querySelector('tbody');
  mealConstraintsBody.innerHTML = '';
  (r.active_meal_constraints || []).forEach((item) => {
    const tr = document.createElement('tr');
    tr.innerHTML = `
      <td>${item.meal}</td>
      <td>${labelFor(SCOPE_LABELS, item.scope) === 'Meta nutricional da refeição' ? item.constraint_label : labelFor(SCOPE_LABELS, item.scope)}</td>
      <td>${labelFor(MODE_LABELS, item.mode)}</td>
      <td>${fmt(item.realized, 4)}</td>
      <td>${item.min_value == null ? '—' : fmt(item.min_value, 4)}</td>
      <td>${item.max_value == null ? '—' : fmt(item.max_value, 4)}</td>
      <td>${item.ideal_value == null ? '—' : fmt(item.ideal_value, 4)}</td>
      <td>${item.deviation == null ? '—' : fmt(item.deviation, 4)}</td>
      <td class="status-${item.status}">${item.status}</td>
    `;
    mealConstraintsBody.appendChild(tr);
  });

  renderNutrientResults();
}

function renderNutrientResults() {
  if (!state.result) return;
  const body = $('resultNutrientsTable').querySelector('tbody');
  body.innerHTML = '';
  const q = $('nutrientFilter').value.trim().toLowerCase();
  state.result.nutrients
    .filter((item) => !q || item.nutrient.toLowerCase().includes(q))
    .forEach((item) => {
      const tr = document.createElement('tr');
      const restriction = item.constraint
        ? `${labelFor(MODE_LABELS, item.constraint.mode)} | mín=${item.constraint.min_value ?? '—'} | máx=${item.constraint.max_value ?? '—'} | ideal=${item.constraint.ideal_value ?? '—'}`
        : '—';
      tr.innerHTML = `
        <td>${item.nutrient}</td>
        <td>${fmt(item.total, 4)}</td>
        <td>${restriction}</td>
        <td>${item.missing_count_in_candidates}</td>
      `;
      body.appendChild(tr);
    });
}

function exportResultCsv() {
  if (!state.result) return;
  const r = state.result;
  const lines = [];
  lines.push('Resumo da solução');
  lines.push(`status,${r.status}`);
  lines.push(`objective_mode,${r.objective_mode}`);
  lines.push(`solver_mode,${r.solver_mode}`);
  lines.push(`objective_value,${r.objective_value}`);
  lines.push(`total_grams,${r.total_grams}`);
  lines.push(`total_estimated_cost,${r.total_estimated_cost}`);
  lines.push('');

  lines.push('Alimentos');
  lines.push('code,description,group_taco,planner_group,meal,selected,grams,energia_kcal,proteina_g,carboidrato_g,lipideos_g,fibra_g,estimated_cost');
  (r.foods || []).forEach((item) => {
    lines.push([
      item.code,
      csvEscape(item.description),
      csvEscape(item.group || ''),
      csvEscape(item.planner_group || ''),
      csvEscape(item.meal || ''),
      item.selected ? 1 : 0,
      item.grams,
      item['Energia (kcal)'] ?? '',
      item['Proteína (g)'] ?? '',
      item['Carboidrato (g)'] ?? '',
      item['Lipídeos (g)'] ?? '',
      item['Fibra Alimentar (g)'] ?? '',
      item.estimated_cost ?? '',
    ].join(','));
  });
  lines.push('');

  lines.push('Resumo por refeição');
  lines.push('meal,food_count,selected_count,total_grams,energia_kcal,proteina_g,carboidrato_g,lipideos_g,fibra_g,total_estimated_cost');
  (r.meal_summaries || []).forEach((item) => {
    lines.push([
      csvEscape(item.meal),
      item.food_count,
      item.selected_count ?? '',
      item.total_grams,
      item['Energia (kcal)'] ?? '',
      item['Proteína (g)'] ?? '',
      item['Carboidrato (g)'] ?? '',
      item['Lipídeos (g)'] ?? '',
      item['Fibra Alimentar (g)'] ?? '',
      item.total_estimated_cost ?? '',
    ].join(','));
  });
  lines.push('');

  lines.push('Resumo por grupo customizado');
  lines.push('scope,group,meal,food_count,selected_count,total_grams');
  (r.planner_group_summaries || []).forEach((item) => {
    lines.push([
      csvEscape(item.scope),
      csvEscape(item.group),
      csvEscape(item.meal || ''),
      item.food_count,
      item.selected_count ?? '',
      item.total_grams,
    ].join(','));
  });
  lines.push('');

  lines.push('Metas ativas de grupos customizados (gramas)');
  lines.push('scope,group,meal,mode,realized,min_value,max_value,ideal_value,deviation,status');
  (r.active_group_constraints || []).forEach((item) => {
    lines.push([
      csvEscape(item.scope),
      csvEscape(item.group),
      csvEscape(item.meal || ''),
      item.mode,
      item.realized,
      item.min_value ?? '',
      item.max_value ?? '',
      item.ideal_value ?? '',
      item.deviation ?? '',
      item.status,
    ].join(','));
  });
  lines.push('');

  lines.push('Metas ativas de cardinalidade por grupo');
  lines.push('scope,group,meal,mode,realized,min_value,max_value,ideal_value,deviation,status');
  (r.active_group_cardinality_constraints || []).forEach((item) => {
    lines.push([
      csvEscape(item.scope),
      csvEscape(item.group),
      csvEscape(item.meal || ''),
      item.mode,
      item.realized,
      item.min_value ?? '',
      item.max_value ?? '',
      item.ideal_value ?? '',
      item.deviation ?? '',
      item.status,
    ].join(','));
  });
  lines.push('');

  lines.push('Metas globais ativas');
  lines.push('nutrient,mode,realized,min_value,max_value,ideal_value,deviation,status');
  (r.active_constraints || []).forEach((item) => {
    lines.push([
      csvEscape(item.nutrient),
      item.mode,
      item.realized,
      item.min_value ?? '',
      item.max_value ?? '',
      item.ideal_value ?? '',
      item.deviation ?? '',
      item.status,
    ].join(','));
  });
  lines.push('');

  lines.push('Metas por refeição ativas');
  lines.push('meal,constraint_label,mode,realized,min_value,max_value,ideal_value,deviation,status');
  (r.active_meal_constraints || []).forEach((item) => {
    lines.push([
      csvEscape(item.meal),
      csvEscape(item.constraint_label),
      item.mode,
      item.realized,
      item.min_value ?? '',
      item.max_value ?? '',
      item.ideal_value ?? '',
      item.deviation ?? '',
      item.status,
    ].join(','));
  });
  lines.push('');

  lines.push('Totais por nutriente');
  lines.push('nutrient,total,missing_count_in_candidates');
  (r.nutrients || []).forEach((item) => {
    lines.push([csvEscape(item.nutrient), item.total, item.missing_count_in_candidates].join(','));
  });

  const blob = new Blob([lines.join('\n')], { type: 'text/csv;charset=utf-8;' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = 'taco_optimizer_solution.csv';
  a.click();
  URL.revokeObjectURL(url);
}

function toggleCustomWeights() {
  $('customWeightsPanel').style.display = $('objectiveMode').value === 'custom_weighted' ? 'grid' : 'none';
}

function attachTableListeners() {
  document.body.addEventListener('click', (event) => {
    const btn = event.target.closest('[data-action]');
    if (!btn) return;
    const action = btn.dataset.action;
    const id = btn.dataset.id;
    if (action === 'remove-food') removeFood(id);
    if (action === 'remove-nutrient') removeNutrientConstraint(id);
    if (action === 'remove-group') removeGroupConstraint(id);
    if (action === 'remove-planner-group') removePlannerGroupConstraint(id);
    if (action === 'remove-planner-group-cardinality') removePlannerGroupCardinalityConstraint(id);
    if (action === 'remove-meal') removeMealConstraint(id);
    if (action === 'remove-meal-nutrient') removeMealNutrientConstraint(id);
    if (action === 'remove-meal-planner-group') removeMealPlannerGroupConstraint(id);
    if (action === 'remove-meal-planner-group-cardinality') removeMealPlannerGroupCardinalityConstraint(id);
  });

  document.body.addEventListener('change', (event) => {
    const el = event.target;
    const id = el.dataset.id;
    if (!id) return;
    if (el.dataset.action === 'toggle-food') {
      const row = state.foods.find((item) => item.row_id === id);
      if (row) row.enabled = el.checked;
      return;
    }
    const tableMap = {
      nutrient: state.nutrientConstraints,
      group: state.groupConstraints,
      'planner-group': state.plannerGroupConstraints,
      'planner-group-cardinality': state.plannerGroupCardinalityConstraints,
      meal: state.mealConstraints,
      'meal-nutrient': state.mealNutrientConstraints,
      'meal-planner-group': state.mealPlannerGroupConstraints,
      'meal-planner-group-cardinality': state.mealPlannerGroupCardinalityConstraints,
    };
    if (el.dataset.table && tableMap[el.dataset.table]) {
      const row = tableMap[el.dataset.table].find((item) => item.row_id === id);
      if (row) row[el.dataset.field] = el.value;
      return;
    }
    const foodRow = state.foods.find((item) => item.row_id === id);
    if (foodRow) {
      foodRow[el.dataset.field] = el.value;
      if (el.dataset.field === 'meal') refreshMealDatalist();
      if (el.dataset.field === 'planner_group') refreshPlannerGroupDatalist();
    }
  });
}

function resetAllInputs() {
  state.foods = [];
  state.nutrientConstraints = [];
  state.groupConstraints = [];
  state.plannerGroupConstraints = [];
  state.plannerGroupCardinalityConstraints = [];
  state.mealConstraints = [];
  state.mealNutrientConstraints = [];
  state.mealPlannerGroupConstraints = [];
  state.mealPlannerGroupCardinalityConstraints = [];
  state.result = null;
  renderAllTables();
  $('exportResultBtn').disabled = true;
  $('metricStatus').textContent = '—';
  $('metricObjective').textContent = '—';
  $('metricGrams').textContent = '—';
  $('metricCost').textContent = '—';
  $('resultFoodsTable').querySelector('tbody').innerHTML = '';
  $('mealSummaryTable').querySelector('tbody').innerHTML = '';
  $('plannerGroupSummaryTable').querySelector('tbody').innerHTML = '';
  $('groupConstraintsResultTable').querySelector('tbody').innerHTML = '';
  $('groupCardinalityResultTable').querySelector('tbody').innerHTML = '';
  $('constraintsResultTable').querySelector('tbody').innerHTML = '';
  $('mealConstraintsResultTable').querySelector('tbody').innerHTML = '';
  $('resultNutrientsTable').querySelector('tbody').innerHTML = '';
  setMessage($('errorBox'), [], true);
  setMessage($('warningBox'), [], true);
}

async function loadSelectedExample() {
  const exampleId = $('examplePresetSelect').value;
  if (!exampleId) {
    setMessage($('warningBox'), ['Escolha um exemplo antes de carregar.']);
    return;
  }
  setMessage($('errorBox'), [], true);
  setMessage($('warningBox'), [], true);
  $('loadExampleBtn').disabled = true;
  $('loadExampleBtn').textContent = 'Carregando exemplo...';
  try {
    const res = await fetch(`/api/examples/${encodeURIComponent(exampleId)}`);
    const data = await res.json();
    if (!res.ok) {
      setMessage($('errorBox'), data.detail?.errors || ['Não foi possível carregar o exemplo.']);
      return;
    }
    applyExamplePayload(data.payload || {});
  } catch (err) {
    setMessage($('errorBox'), [String(err)]);
  } finally {
    $('loadExampleBtn').textContent = 'Aplicar exemplo';
    updateExampleDescription();
  }
}

function parseCsvLine(line) {
  const result = [];
  let current = '';
  let inQuotes = false;
  for (let i = 0; i < line.length; i += 1) {
    const ch = line[i];
    if (ch === '"') {
      if (inQuotes && line[i + 1] === '"') {
        current += '"';
        i += 1;
      } else {
        inQuotes = !inQuotes;
      }
    } else if (ch === ',' && !inQuotes) {
      result.push(current);
      current = '';
    } else {
      current += ch;
    }
  }
  result.push(current);
  return result;
}

async function importCandidateCsv(file) {
  const text = await file.text();
  const lines = text.split(/\r?\n/).filter(Boolean);
  if (lines.length < 2) return;
  const headers = parseCsvLine(lines[0]).map((h) => h.trim());
  const idx = Object.fromEntries(headers.map((h, i) => [h, i]));
  lines.slice(1).forEach((line) => {
    const cols = parseCsvLine(line);
    const code = Number(cols[idx.code]);
    const food = state.meta.foods.find((f) => Number(f.code) === code);
    if (!food) return;
    addFood(food, {
      min_g: idx.min_g === undefined ? 0 : (cols[idx.min_g] || 0),
      max_g: idx.max_g === undefined ? '' : (cols[idx.max_g] || ''),
      selection_min_g: idx.selection_min_g === undefined ? 1 : (cols[idx.selection_min_g] || 1),
      cost_per_100g: idx.cost_per_100g === undefined ? '' : (cols[idx.cost_per_100g] || ''),
      meal: idx.meal === undefined ? '' : (cols[idx.meal] || ''),
      planner_group: idx.planner_group === undefined ? '' : (cols[idx.planner_group] || ''),
    });
    const last = state.foods[state.foods.length - 1];
    if (idx.enabled !== undefined) last.enabled = String(cols[idx.enabled] || 'true').toLowerCase() !== 'false';
  });
}

function bindEvents() {
  $('addFoodBtn').addEventListener('click', () => {
    const food = findFoodByInput($('foodSearch').value);
    if (food) {
      addFood(food);
      $('foodSearch').value = '';
    }
  });
  $('clearFoodsBtn').addEventListener('click', resetAllInputs);
  $('addNutrientConstraintBtn').addEventListener('click', () => addNutrientConstraint());
  $('addGroupConstraintBtn').addEventListener('click', () => addGroupConstraint());
  $('addPlannerGroupConstraintBtn').addEventListener('click', () => addPlannerGroupConstraint());
  $('addPlannerGroupCardinalityConstraintBtn').addEventListener('click', () => addPlannerGroupCardinalityConstraint());
  $('addMealConstraintBtn').addEventListener('click', () => addMealConstraint());
  $('addMealNutrientConstraintBtn').addEventListener('click', () => addMealNutrientConstraint());
  $('addMealPlannerGroupConstraintBtn').addEventListener('click', () => addMealPlannerGroupConstraint());
  $('addMealPlannerGroupCardinalityConstraintBtn').addEventListener('click', () => addMealPlannerGroupCardinalityConstraint());
  $('solveBtn').addEventListener('click', solve);
  $('loadExampleBtn').addEventListener('click', loadSelectedExample);
  $('exportResultBtn').addEventListener('click', exportResultCsv);
  $('nutrientFilter').addEventListener('input', renderNutrientResults);
  $('objectiveMode').addEventListener('change', toggleCustomWeights);
  $('examplePresetSelect').addEventListener('change', updateExampleDescription);
  $('downloadTemplateBtn').addEventListener('click', () => { window.location.href = '/api/download/candidate-template'; });
  $('candidateFileInput').addEventListener('change', async (event) => {
    const file = event.target.files?.[0];
    if (file) await importCandidateCsv(file);
    event.target.value = '';
  });
  attachTableListeners();
  toggleCustomWeights();
}

(async function init() {
  bindEvents();
  await fetchMeta();
  await fetchExamples();
  refreshMealDatalist();
  refreshPlannerGroupDatalist();
})();

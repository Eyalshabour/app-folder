const root = document.getElementById("menu-root");
const titleTpl = document.getElementById("title-template");
const groupTpl = document.getElementById("group-template");
const itemTpl = document.getElementById("item-template");
const simpleFieldTpl = document.getElementById("simple-field-template");
const lineItemTpl = document.getElementById("line-item-template");
const spacerRowTpl = document.getElementById("spacer-row-template");
const saveBtn = document.getElementById("save-btn");
const saveStatus = document.getElementById("save-status");
const templateSelect = document.getElementById("template-select");
const langTabs = document.getElementById("lang-tabs");

const previewBtn = document.getElementById("preview-btn");
const previewPanel = document.getElementById("preview-panel");
const previewFrame = document.getElementById("preview-frame");
const previewCloseBtn = document.getElementById("preview-close-btn");

const adminToggleBtn = document.getElementById("admin-toggle-btn");
const adminPanel = document.getElementById("admin-panel");
const adminFields = document.getElementById("admin-fields");
const adminSaveBtn = document.getElementById("admin-save-btn");
const adminPreviewBtn = document.getElementById("admin-preview-btn");
const adminStatus = document.getElementById("admin-status");

// Human-friendly labels for the layout fields the admin panel can edit.
// Anything not listed here just gets its raw key name, title-cased.
const ADMIN_FIELD_LABELS = {
  page_width: "Page width (pt)",
  page_height: "Page height (pt)",
  margin_top: "Top margin",
  margin_bottom: "Bottom margin",
  margin_side: "Side margins",
  title_size: "Title font size",
  page_title_size: "Page title font size",
  category_size: "Category heading size",
  subgroup_size: "Sub-group heading size",
  item_size: "Item text size",
  note_size: "Note text size",
  price_size: "Price font size",
  header_size: "Header font size",
  body_size: "Body text size",
  footer_size: "Footer text size",
  divider_icon_height: "Divider icon height",
  gap_after_page_title: "Gap after page title",
  gap_after_category: "Gap after category heading",
  gap_after_subgroup: "Gap after sub-group heading",
  gap_after_item: "Gap between items",
  gap_after_group_block: "Gap after each group",
  gap_after_top_icon: "Gap after top icon",
  gap_after_mid_icon: "Gap after middle icon",
  gap_before_bottom_icon: "Gap before bottom icon",
};

function adminFieldLabel(key) {
  return ADMIN_FIELD_LABELS[key] || key.replace(/_/g, " ").replace(/\b\w/g, c => c.toUpperCase());
}

const LANGUAGE_LABELS = { en: "English", fr: "Français" };

let templates = [];
let currentTemplateId = null;
let currentLanguage = "en";
let menuState = { title: "", courses: [], dessert: [] };

async function loadTemplates() {
  const res = await fetch("/api/templates");
  const data = await res.json();
  templates = data.templates;

  templateSelect.innerHTML = "";
  templates.forEach(t => {
    const opt = document.createElement("option");
    opt.value = t.id;
    opt.textContent = t.name;
    templateSelect.appendChild(opt);
  });

  currentTemplateId = templates[0].id;
  templateSelect.value = currentTemplateId;
  renderLangTabs();
  await loadMenu();
}

function renderLangTabs() {
  const tpl = templates.find(t => t.id === currentTemplateId);
  const langs = (tpl && tpl.languages) || ["en"];
  if (!langs.includes(currentLanguage)) currentLanguage = langs[0];

  langTabs.innerHTML = "";
  langs.forEach(lang => {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "lang-tab" + (lang === currentLanguage ? " active" : "");
    btn.textContent = LANGUAGE_LABELS[lang] || lang.toUpperCase();
    btn.addEventListener("click", async () => {
      if (lang === currentLanguage) return;
      currentLanguage = lang;
      renderLangTabs();
      await loadMenu();
    });
    langTabs.appendChild(btn);
  });
}

templateSelect.addEventListener("change", async () => {
  currentTemplateId = templateSelect.value;
  renderLangTabs();
  await loadMenu();
});

function renderMenu() {
  root.innerHTML = "";

  if ("courses" in menuState) {
    renderCourseMenu();
  } else if ("pages" in menuState) {
    renderCategorizedListMenu();
  } else {
    renderPriceCardMenu();
  }
}

// ---------------------------------------------------------------------
// Categorized-list menus (Wine List, Digestifs, etc.): pages > categories
// > groups (optional sub-heading) > items (name + price).
// ---------------------------------------------------------------------

// Reordering: move an entry within its own list. Used at every level of a
// categorized list (wine, region, category, page) so the user can arrange
// the document without retyping anything.
function moveInArray(arr, index, delta) {
  const target = index + delta;
  if (target < 0 || target >= arr.length) return false;
  const [entry] = arr.splice(index, 1);
  arr.splice(target, 0, entry);
  return true;
}

function buildMoveControls(arr, index, label) {
  const wrap = document.createElement("div");
  wrap.className = "move-controls";

  const up = document.createElement("button");
  up.type = "button";
  up.className = "move-button";
  up.textContent = "▲";
  up.title = `Move this ${label} up`;
  up.disabled = index === 0;
  up.addEventListener("click", e => {
    e.stopPropagation();
    e.preventDefault();
    if (moveInArray(arr, index, -1)) renderMenu();
  });

  const down = document.createElement("button");
  down.type = "button";
  down.className = "move-button";
  down.textContent = "▼";
  down.title = `Move this ${label} down`;
  down.disabled = index === arr.length - 1;
  down.addEventListener("click", e => {
    e.stopPropagation();
    e.preventDefault();
    if (moveInArray(arr, index, 1)) renderMenu();
  });

  wrap.appendChild(up);
  wrap.appendChild(down);
  return wrap;
}

function renderCategorizedListMenu() {
  if (!menuState.pages) menuState.pages = [];

  const wrap = document.createElement("div");
  wrap.className = "catlist-wrap";

  menuState.pages.forEach((page, pIdx) => {
    wrap.appendChild(buildPageBlock(page, pIdx));
  });

  const addPageBtn = document.createElement("button");
  addPageBtn.type = "button";
  addPageBtn.className = "add-item-button";
  addPageBtn.textContent = "+ Add a Page";
  addPageBtn.addEventListener("click", () => {
    menuState.pages.push({ title: "New Page", categories: [] });
    renderMenu();
  });
  wrap.appendChild(addPageBtn);

  root.appendChild(wrap);
}

function buildPageBlock(page, pIdx) {
  const details = document.createElement("details");
  details.className = "catlist-page";
  details.open = false;

  const summary = document.createElement("summary");
  const titleInput = document.createElement("input");
  titleInput.type = "text";
  titleInput.className = "catlist-page-title-input";
  titleInput.value = page.title || "";
  titleInput.placeholder = "Page title";
  titleInput.addEventListener("click", e => e.stopPropagation());
  titleInput.addEventListener("input", () => { page.title = titleInput.value; });
  summary.appendChild(titleInput);
  summary.appendChild(buildMoveControls(menuState.pages, pIdx, "page"));

  const removeBtn = document.createElement("button");
  removeBtn.type = "button";
  removeBtn.className = "remove-item-button";
  removeBtn.title = "Remove this page";
  removeBtn.textContent = "✕";
  removeBtn.addEventListener("click", e => {
    e.stopPropagation();
    e.preventDefault();
    menuState.pages.splice(pIdx, 1);
    renderMenu();
  });
  summary.appendChild(removeBtn);
  details.appendChild(summary);

  const body = document.createElement("div");
  body.className = "catlist-page-body";

  if (!page.categories) page.categories = [];
  page.categories.forEach((cat, cIdx) => {
    body.appendChild(buildCategoryBlock(page, cat, cIdx));
  });

  const addCatBtn = document.createElement("button");
  addCatBtn.type = "button";
  addCatBtn.className = "add-item-button";
  addCatBtn.textContent = "+ Add a Category";
  addCatBtn.addEventListener("click", () => {
    page.categories.push({ name: "New Category", groups: [{ name: null, items: [] }] });
    renderMenu();
  });
  body.appendChild(addCatBtn);

  details.appendChild(body);
  return details;
}

function buildCategoryBlock(page, cat, cIdx) {
  const details = document.createElement("details");
  details.className = "catlist-category";
  details.open = false;

  const summary = document.createElement("summary");
  const nameInput = document.createElement("input");
  nameInput.type = "text";
  nameInput.className = "catlist-category-name-input";
  nameInput.value = cat.name || "";
  nameInput.placeholder = "Category name (e.g. France, Israël...)";
  nameInput.addEventListener("click", e => e.stopPropagation());
  nameInput.addEventListener("input", () => { cat.name = nameInput.value; });
  summary.appendChild(nameInput);

  const noteInput = document.createElement("input");
  noteInput.type = "text";
  noteInput.className = "catlist-category-note-input";
  noteInput.value = cat.note || "";
  noteInput.placeholder = "note (optional, e.g. 14cl)";
  noteInput.addEventListener("click", e => e.stopPropagation());
  noteInput.addEventListener("input", () => { cat.note = noteInput.value; });
  summary.appendChild(noteInput);

  summary.appendChild(buildMoveControls(page.categories, cIdx, "category"));

  const removeBtn = document.createElement("button");
  removeBtn.type = "button";
  removeBtn.className = "remove-item-button";
  removeBtn.title = "Remove this category";
  removeBtn.textContent = "✕";
  removeBtn.addEventListener("click", e => {
    e.stopPropagation();
    e.preventDefault();
    page.categories.splice(cIdx, 1);
    renderMenu();
  });
  summary.appendChild(removeBtn);
  details.appendChild(summary);

  const body = document.createElement("div");
  body.className = "catlist-category-body";

  if (!cat.groups) cat.groups = [];
  cat.groups.forEach((group, gIdx) => {
    body.appendChild(buildGroupBlock(cat, group, gIdx));
  });

  const addGroupBtn = document.createElement("button");
  addGroupBtn.type = "button";
  addGroupBtn.className = "add-item-button add-spacer-button";
  addGroupBtn.textContent = "+ Add a Sub-group (e.g. a region/country)";
  addGroupBtn.addEventListener("click", () => {
    cat.groups.push({ name: "", items: [] });
    renderMenu();
  });
  body.appendChild(addGroupBtn);

  details.appendChild(body);
  return details;
}

function buildGroupBlock(cat, group, gIdx) {
  const block = document.createElement("div");
  block.className = "catlist-group";

  const header = document.createElement("div");
  header.className = "catlist-group-header";

  const nameInput = document.createElement("input");
  nameInput.type = "text";
  nameInput.className = "catlist-group-name-input";
  nameInput.value = group.name || "";
  nameInput.placeholder = "Sub-group heading (optional -- leave blank for none)";
  nameInput.addEventListener("input", () => { group.name = nameInput.value; });
  header.appendChild(nameInput);
  header.appendChild(buildMoveControls(cat.groups, gIdx, "region"));

  const removeBtn = document.createElement("button");
  removeBtn.type = "button";
  removeBtn.className = "remove-item-button";
  removeBtn.title = "Remove this sub-group";
  removeBtn.addEventListener("click", () => {
    cat.groups.splice(gIdx, 1);
    renderMenu();
  });
  removeBtn.textContent = "✕";
  header.appendChild(removeBtn);
  block.appendChild(header);

  const itemsList = document.createElement("div");
  itemsList.className = "catlist-items-list";
  if (!group.items) group.items = [];
  group.items.forEach((item, iIdx) => {
    itemsList.appendChild(buildCatlistItemRow(group, item, iIdx));
  });
  block.appendChild(itemsList);

  const addItemBtn = document.createElement("button");
  addItemBtn.type = "button";
  addItemBtn.className = "add-item-button";
  addItemBtn.textContent = "+ Add a Wine";
  addItemBtn.addEventListener("click", () => {
    group.items.push({ text: "", price: "" });
    renderMenu();
  });
  block.appendChild(addItemBtn);

  return block;
}

function buildCatlistItemRow(group, item, iIdx) {
  const row = document.createElement("div");
  row.className = "catlist-item-row";

  const nameInput = document.createElement("input");
  nameInput.type = "text";
  nameInput.className = "catlist-item-name-input";
  nameInput.value = item.text || "";
  nameInput.placeholder = "e.g. Domaine de Montille 2023, Monthélie";
  nameInput.addEventListener("input", () => { item.text = nameInput.value; });
  row.appendChild(nameInput);

  const priceInput = document.createElement("input");
  priceInput.type = "text";
  priceInput.className = "catlist-item-price-input";
  priceInput.value = item.price || "";
  priceInput.placeholder = "price";
  priceInput.addEventListener("input", () => { item.price = priceInput.value; });
  row.appendChild(priceInput);
  row.appendChild(buildMoveControls(group.items, iIdx, "wine"));

  const removeBtn = document.createElement("button");
  removeBtn.type = "button";
  removeBtn.className = "remove-item-button";
  removeBtn.title = "Remove this wine";
  removeBtn.textContent = "✕";
  removeBtn.addEventListener("click", () => {
    group.items.splice(iIdx, 1);
    renderMenu();
  });
  row.appendChild(removeBtn);

  return row;
}

function renderCourseMenu() {
  const titleNode = titleTpl.content.cloneNode(true);
  const titleInput = titleNode.querySelector(".menu-title-input");
  titleInput.value = menuState.title || "";
  titleInput.addEventListener("input", () => { menuState.title = titleInput.value; });
  root.appendChild(titleNode);

  root.appendChild(buildGroup("Courses", "courses"));
  root.appendChild(buildGroup("Dessert", "dessert"));
}

// Simple text fields shown at the top of a price-card menu, in order.
const PRICE_CARD_FIELDS = [
  { key: "title", label: "Menu Title" },
  { key: "price", label: "Price" },
  { key: "subprice", label: "Additional Price Line (optional)" },
  { key: "accord_header", label: "Wine Pairing Heading" },
  { key: "accord_price", label: "Wine Pairing Price" },
  { key: "section_header", label: "Drinks List Heading (optional)" },
];

function renderPriceCardMenu() {
  PRICE_CARD_FIELDS.forEach(({ key, label }) => {
    const node = simpleFieldTpl.content.cloneNode(true);
    const input = node.querySelector(".simple-field-input");
    node.querySelector(".simple-field-label").textContent = label;
    input.value = menuState[key] || "";
    input.placeholder = label;
    input.addEventListener("input", () => { menuState[key] = input.value; });
    root.appendChild(node);
  });

  root.appendChild(buildLinesGroup("Drinks List", "items"));
  root.appendChild(buildFooterGroup());
}

function buildLinesGroup(heading, key) {
  const node = groupTpl.content.cloneNode(true);
  node.querySelector(".group-heading").textContent = heading;
  const itemsList = node.querySelector(".items-list");
  const addBtn = node.querySelector(".add-item-button");
  addBtn.textContent = "+ Add a Line";

  if (!menuState[key]) menuState[key] = [];

  menuState[key].forEach((line, iIdx) => {
    itemsList.appendChild(buildLineRow(key, iIdx, line));
  });

  addBtn.addEventListener("click", () => {
    menuState[key].push({ text: "" });
    renderMenu();
  });

  const spacerBtn = document.createElement("button");
  spacerBtn.type = "button";
  spacerBtn.className = "add-item-button add-spacer-button";
  spacerBtn.textContent = "+ Add Blank Space (to group items)";
  spacerBtn.addEventListener("click", () => {
    menuState[key].push({ blank: true });
    renderMenu();
  });
  node.querySelector(".menu-group").appendChild(spacerBtn);

  return node;
}

function buildLineRow(key, iIdx, line) {
  if (line.blank) {
    const node = spacerRowTpl.content.cloneNode(true);
    const removeBtn = node.querySelector(".remove-item-button");
    removeBtn.parentNode.insertBefore(buildMoveControls(menuState[key], iIdx, "line"), removeBtn);
    removeBtn.addEventListener("click", () => {
      menuState[key].splice(iIdx, 1);
      renderMenu();
    });
    return node;
  }
  const node = lineItemTpl.content.cloneNode(true);
  const input = node.querySelector(".line-input");
  input.value = line.text || "";
  input.addEventListener("input", () => { menuState[key][iIdx].text = input.value; });
  const removeBtn = node.querySelector(".remove-item-button");
  removeBtn.parentNode.insertBefore(buildMoveControls(menuState[key], iIdx, "line"), removeBtn);
  removeBtn.addEventListener("click", () => {
    menuState[key].splice(iIdx, 1);
    renderMenu();
  });
  return node;
}

function buildFooterGroup() {
  const node = groupTpl.content.cloneNode(true);
  node.querySelector(".group-heading").textContent = "Footer Text (small print)";
  const itemsList = node.querySelector(".items-list");
  const addBtn = node.querySelector(".add-item-button");
  addBtn.textContent = "+ Add a Footer Line";

  if (!menuState.footer_lines) menuState.footer_lines = [];

  menuState.footer_lines.forEach((text, iIdx) => {
    const row = lineItemTpl.content.cloneNode(true);
    const input = row.querySelector(".line-input");
    input.value = text || "";
    input.addEventListener("input", () => { menuState.footer_lines[iIdx] = input.value; });
    const removeBtn = row.querySelector(".remove-item-button");
    removeBtn.parentNode.insertBefore(buildMoveControls(menuState.footer_lines, iIdx, "line"), removeBtn);
    removeBtn.addEventListener("click", () => {
      menuState.footer_lines.splice(iIdx, 1);
      renderMenu();
    });
    itemsList.appendChild(row);
  });

  addBtn.addEventListener("click", () => {
    menuState.footer_lines.push("");
    renderMenu();
  });

  return node;
}

function buildGroup(heading, key) {
  const node = groupTpl.content.cloneNode(true);
  node.querySelector(".group-heading").textContent = heading;
  const itemsList = node.querySelector(".items-list");

  (menuState[key] || []).forEach((item, iIdx) => {
    itemsList.appendChild(buildItemRow(key, iIdx, item));
  });

  node.querySelector(".add-item-button").addEventListener("click", () => {
    if (!menuState[key]) menuState[key] = [];
    menuState[key].push({ name: "", description: "" });
    renderMenu();
  });

  return node;
}

// True when this menu pairs a wine with each course. Detected from the
// template id OR from the content itself, so a menu that gains its first
// wine still shows the field.
function isPairingMenu() {
  const all = [...(menuState.courses || []), ...(menuState.dessert || [])];
  return (currentTemplateId || "").includes("pairing") || all.some(c => "wine" in c);
}

function buildItemRow(key, iIdx, item) {
  const node = itemTpl.content.cloneNode(true);
  const nameInput = node.querySelector(".item-name");
  const descInput = node.querySelector(".item-desc");

  nameInput.value = item.name || "";
  descInput.value = item.description || "";

  nameInput.addEventListener("input", () => menuState[key][iIdx].name = nameInput.value);
  descInput.addEventListener("input", () => menuState[key][iIdx].description = descInput.value);

  // Wine-pairing menus print a wine under each course. Without this field
  // there was no way to edit them from the app at all.
  if (isPairingMenu()) {
    const wineField = document.createElement("div");
    wineField.className = "field field-wine";
    const label = document.createElement("label");
    label.textContent = "Wine";
    const wineInput = document.createElement("input");
    wineInput.type = "text";
    wineInput.className = "item-wine";
    wineInput.placeholder = "e.g. Holdvolgy «Vision» 2019, Tokaji, Hungary";
    wineInput.value = item.wine || "";
    wineInput.addEventListener("input", () => {
      menuState[key][iIdx].wine = wineInput.value;
    });
    wineField.appendChild(label);
    wineField.appendChild(wineInput);
    node.querySelector(".item-fields").appendChild(wineField);
  }

  const removeBtn = node.querySelector(".remove-item-button");
  removeBtn.parentNode.insertBefore(buildMoveControls(menuState[key], iIdx, "course"), removeBtn);
  removeBtn.addEventListener("click", () => {
    menuState[key].splice(iIdx, 1);
    renderMenu();
  });

  return node;
}

async function loadMenu() {
  root.innerHTML = '<p class="loading">Loading your menu&hellip;</p>';
  const res = await fetch(`/api/menu?template=${encodeURIComponent(currentTemplateId)}&language=${encodeURIComponent(currentLanguage)}`);
  const data = await res.json();
  menuState = data.menu;
  renderMenu();
  closePreviewPanel();
  await loadAdminFields();
}

// ---------------------------------------------------------------------
// Preview: renders whatever is currently in the editor (unsaved changes
// included) to a scratch PDF and shows it inline, without creating a new
// dated file or overwriting the saved content.
// ---------------------------------------------------------------------

function openPreviewPanel(url) {
  previewFrame.src = url;
  previewPanel.hidden = false;
  previewPanel.scrollIntoView({ behavior: "smooth", block: "start" });
}

function closePreviewPanel() {
  previewPanel.hidden = true;
  previewFrame.src = "about:blank";
}

async function runPreview(button) {
  const originalText = button.textContent;
  button.disabled = true;
  button.textContent = "Rendering…";
  try {
    const res = await fetch(`/api/preview?template=${encodeURIComponent(currentTemplateId)}&language=${encodeURIComponent(currentLanguage)}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(menuState),
    });
    const result = await res.json();
    if (!result.ok) {
      alert("Couldn't render a preview: " + (result.error || "unknown error"));
      return;
    }
    openPreviewPanel(result.preview_url);
  } catch (e) {
    alert("Couldn't render a preview. Please try again.");
  } finally {
    button.disabled = false;
    button.textContent = originalText;
  }
}

previewBtn.addEventListener("click", () => runPreview(previewBtn));
previewCloseBtn.addEventListener("click", closePreviewPanel);

// ---------------------------------------------------------------------
// Admin panel: lets a technical user tune font sizes, margins and gaps
// for the current template's layout, without touching code or JSON files
// by hand. Deliberately excludes font file paths and layout_type, so a
// typo here can't break which renderer runs.
// ---------------------------------------------------------------------

let adminFieldsState = {};
let adminFontsState = {};
let availableFonts = [];
let availableDisplayFonts = [];

// Which text each font role controls, in plain language.
const FONT_ROLE_LABELS = {
  display: "Titles (display font)",
  body: "Body text (default)",
  category: "Category headings",
  subgroup: "Sub-group headings",
  item: "Item lines",
  note: "Small notes",
};

function fontFileLabel(path) {
  return path.split("/").pop().replace(/\.(ttf|otf)$/i, "");
}

async function loadAdminFields() {
  adminStatus.textContent = "";
  const res = await fetch(`/api/layout?template=${encodeURIComponent(currentTemplateId)}`);
  const data = await res.json();
  adminFieldsState = data.fields || {};
  adminFontsState = data.fonts || {};
  availableFonts = data.available_fonts || [];
  availableDisplayFonts = data.available_display_fonts || availableFonts;
  renderAdminFields();
}

function renderAdminFonts() {
  if (!Object.keys(adminFontsState).length) return;

  const heading = document.createElement("h4");
  heading.className = "admin-subheading";
  heading.textContent = "Fonts";
  adminFields.appendChild(heading);

  const grid = document.createElement("div");
  grid.className = "admin-fields admin-font-grid";

  Object.keys(adminFontsState).forEach(role => {
    const row = document.createElement("div");
    row.className = "admin-field-row";

    const label = document.createElement("label");
    label.textContent = FONT_ROLE_LABELS[role] || role;
    row.appendChild(label);

    const select = document.createElement("select");
    select.className = "admin-font-select";
    const current = adminFontsState[role];
    // Titles are drawn as images so they can use any font, including the
    // PostScript-outline ones that can't be embedded as live text.
    const pool = role === "display" ? availableDisplayFonts : availableFonts;
    const options = pool.includes(current) ? pool : [current, ...pool];

    options.forEach(path => {
      const opt = document.createElement("option");
      opt.value = path;
      opt.textContent = fontFileLabel(path);
      if (path === current) opt.selected = true;
      select.appendChild(opt);
    });
    select.addEventListener("change", () => { adminFontsState[role] = select.value; });
    row.appendChild(select);

    grid.appendChild(row);
  });

  adminFields.appendChild(grid);

  const hint = document.createElement("p");
  hint.className = "admin-panel-sub admin-font-hint";
  hint.textContent =
    "Only fonts installed in the app's assets/fonts folder are listed. " +
    "Drop a .otf or .ttf file in there and it appears here after a restart.";
  adminFields.appendChild(hint);
}

function renderAdminFields() {
  adminFields.innerHTML = "";
  Object.keys(adminFieldsState).forEach(key => {
    const value = adminFieldsState[key];
    const row = document.createElement("div");
    row.className = "admin-field-row";

    const label = document.createElement("label");
    label.textContent = adminFieldLabel(key);
    row.appendChild(label);

    if (typeof value === "boolean") {
      const input = document.createElement("input");
      input.type = "checkbox";
      input.checked = value;
      input.addEventListener("change", () => { adminFieldsState[key] = input.checked; });
      row.appendChild(input);
    } else if (typeof value === "number") {
      const input = document.createElement("input");
      input.type = "number";
      input.step = "0.5";
      input.value = value;
      input.addEventListener("input", () => { adminFieldsState[key] = input.value; });
      row.appendChild(input);
    } else {
      const input = document.createElement("input");
      input.type = "text";
      input.value = value;
      input.addEventListener("input", () => { adminFieldsState[key] = input.value; });
      row.appendChild(input);
    }

    adminFields.appendChild(row);
  });

  if (!Object.keys(adminFieldsState).length) {
    adminFields.innerHTML = '<p class="admin-empty">No tunable fields found for this menu.</p>';
  }

  renderAdminFonts();
}

async function saveAdminFields() {
  adminSaveBtn.disabled = true;
  adminStatus.textContent = "Saving…";
  try {
    const res = await fetch(`/api/layout?template=${encodeURIComponent(currentTemplateId)}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ fields: adminFieldsState, fonts: adminFontsState }),
    });
    const result = await res.json();
    adminFieldsState = result.fields || adminFieldsState;
    adminFontsState = result.fonts || adminFontsState;
    renderAdminFields();
    adminStatus.textContent = "✅ Saved. Preview or Save the menu to see the new layout.";
  } catch (e) {
    adminStatus.textContent = "Something went wrong saving layout settings.";
  } finally {
    adminSaveBtn.disabled = false;
  }
}

adminToggleBtn.addEventListener("click", () => {
  adminPanel.hidden = !adminPanel.hidden;
});
adminSaveBtn.addEventListener("click", saveAdminFields);
adminPreviewBtn.addEventListener("click", async () => {
  await saveAdminFields();
  await runPreview(adminPreviewBtn);
});

async function saveMenu() {
  saveBtn.disabled = true;
  saveBtn.textContent = "Saving…";
  saveStatus.innerHTML = "";

  try {
    const res = await fetch(`/api/save?template=${encodeURIComponent(currentTemplateId)}&language=${encodeURIComponent(currentLanguage)}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(menuState),
    });
    const result = await res.json();

    let html = `<div class="ok">✅ Saved! New menu ready: <a href="${result.download_url}" target="_blank">${result.filename}</a></div>`;
    if (result.drive_link) {
      html += `<div class="ok">Uploaded to Google Drive.</div>`;
    }
    if (result.warnings && result.warnings.length) {
      result.warnings.forEach(w => {
        html += `<div class="warn">⚠️ ${w}</div>`;
      });
    }
    saveStatus.innerHTML = html;
  } catch (e) {
    saveStatus.innerHTML = `<div class="err">Something went wrong saving. Please try again.</div>`;
  } finally {
    saveBtn.disabled = false;
    saveBtn.textContent = "💾 Save & Create Print PDF";
  }
}

saveBtn.addEventListener("click", saveMenu);
loadTemplates();

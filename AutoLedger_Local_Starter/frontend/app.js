const state = {
  token: localStorage.getItem("autoledger-token"),
  user: null,
  businesses: [],
  businessId: null,
  page: "dashboard",
  pageNumber: 1,
  pageSize: 25,
  detail: null,
  detailTab: "ownership",
  vehicleFilters: { search: "", brand: "", fuel_type: "", model_year: "", status: "", sort: "vehicle_id", direction: "asc" },
  theme: localStorage.getItem("autoledger-theme") || "dark",
  searchTimer: null,
  partnerSearch: { suppliers: "", customers: "" },
  userSearch: "",
  userRoleFilter: "",
  userStatusFilter: "",
  partnerHistory: null,
  includeInactivePartners: false,
  commerceSearch: "",
  commerceStatusFilter: { purchases: "", sales: "", payments: "" },
  inventoryStatus: "",
};

const pagePermissions = {
  dashboard: "vehicles.read",
  vehicles: "vehicles.read",
  inventory: "inventory.read",
  suppliers: "suppliers.read",
  customers: "customers.read",
  purchases: "purchases.read",
  sales: "sales.read",
  payments: "payments.read",
  owners: "owners.read",
  documents: "history.read",
  inspections: "verification.read",
  verification: "verification.read",
  reports: "vehicles.read",
  audit: "audit.read",
  users: "users.manage",
};
const hasPermission = permission => state.user?.permissions?.includes("*") || state.user?.permissions?.includes(permission);
const normalizeUser = user => ({ ...user, role: user.role || user.role_name });
const hasAnyAccess = () => state.user?.permissions?.includes("*") || Boolean(state.user?.permissions?.length);

function canAccessPage(page) {
  if (page === "profile") return true;
  if (page === "access") return !hasAnyAccess();
  if (["inventory", "suppliers", "customers", "purchases", "sales", "payments"].includes(page) && !state.businessId) return false;
  if (page === "reports") {
    return hasPermission("vehicles.read") || hasPermission("reports.operational") || hasPermission("reports.financial");
  }
  const permission = pagePermissions[page];
  return !permission || hasPermission(permission);
}

const $ = selector => document.querySelector(selector);
const esc = value => String(value ?? "").replace(/[&<>"']/g, char => ({
  "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
})[char]);
const dateFmt = new Intl.DateTimeFormat("en-PK", { day: "2-digit", month: "short", year: "numeric", timeZone: "Asia/Karachi" });
const dateValue = value => value ? dateFmt.format(new Date(`${String(value).slice(0, 10)}T12:00:00+05:00`)) : "Not recorded";
function moneyValue(value) {
  const raw = String(value ?? "0").trim();
  const match = raw.match(/^(-?)(\d+)(?:\.(\d+))?$/);
  if (!match) return "PKR —";
  const negative = match[1] === "-";
  const whole = BigInt(match[2]);
  const fraction = (match[3] || "").padEnd(3, "0");
  let minor = whole * 100n + BigInt(fraction.slice(0, 2));
  if (fraction[2] >= "5") minor += 1n;
  const formattedWhole = (minor / 100n).toLocaleString("en-PK");
  const formattedMinor = String(minor % 100n).padStart(2, "0");
  return `PKR${negative ? " -" : " "}${formattedWhole}.${formattedMinor}`;
}
const initials = value => String(value || "AL").split(/\s+/).slice(0, 2).map(part => part[0] || "").join("").toUpperCase();
const icon = name => `<svg aria-hidden="true"><use href="#i-${name}"></use></svg>`;
const tokenHeader = () => ({
  ...(state.token ? { Authorization: `Bearer ${state.token}` } : {}),
  ...(state.businessId ? { "X-Business-ID": String(state.businessId) } : {}),
});

async function loadCurrentUser() {
  const response = await fetch("/api/auth/me", {
    credentials: "same-origin",
    headers: tokenHeader(),
  });
  if (!response.ok) throw new Error("Could not load account permissions.");
  return normalizeUser(await response.json());
}

async function loadBusinessMemberships() {
  let businesses;
  try {
    businesses = (await api("/api/auth/businesses")).businesses;
  } catch (error) {
    if (error.status !== 503) throw error;
    state.businesses = [];
    state.businessId = null;
    return;
  }
  state.businesses = businesses;
  const storageKey = `autoledger-business-${state.user.user_id}`;
  const savedId = Number(localStorage.getItem(storageKey));
  const selected = businesses.find(item => item.business_id === savedId) || businesses[0] || null;
  state.businessId = selected?.business_id || null;
  if (selected) {
    localStorage.setItem(storageKey, String(selected.business_id));
    state.user = {
      ...state.user,
      role: selected.role_name,
      role_name: selected.role_name,
      permissions: selected.permissions,
    };
  }
}

async function api(url, options = {}, retryWithRefresh = true) {
  const response = await fetch(url, {
    ...options,
    credentials: "same-origin",
    headers: { ...tokenHeader(), ...(options.body ? { "Content-Type": "application/json" } : {}), ...options.headers },
  });
  const body = response.status === 204 ? null : await response.json().catch(() => null);
  if (!response.ok) {
    if (response.status === 401 && state.token && retryWithRefresh && url !== "/api/auth/refresh") {
      const refreshed = await fetch("/api/auth/refresh", { method: "POST", credentials: "same-origin" });
      if (refreshed.ok) {
        const session = await refreshed.json();
        state.token = session.access_token;
        localStorage.setItem("autoledger-token", state.token);
        try {
          state.user = await loadCurrentUser();
          await loadBusinessMemberships();
        } catch (error) {
          signOut(false);
          throw error;
        }
        return api(url, options, false);
      }
      signOut(false);
    }
    const detail = body?.detail;
    const error = new Error(typeof detail === "string" ? detail : "The request could not be completed.");
    error.status = response.status;
    throw error;
  }
  return body;
}

function toast(message, isError = false) {
  const item = document.createElement("div");
  item.className = `toast${isError ? " error" : ""}`;
  item.innerHTML = `<i></i><span>${esc(message)}</span>`;
  $("#toast-region").append(item);
  window.setTimeout(() => item.remove(), 4200);
}

function showAuthMessage(message) {
  const target = $("#auth-message");
  if (target) target.textContent = message;
}

async function showAuth() {
  $("#app-shell").classList.add("hidden");
  $("#auth-screen").classList.remove("hidden");
  try {
    const auth = await api("/api/auth/status");
    renderAuthForm(auth.initialized ? "login" : "bootstrap", auth.setup_account);
  } catch {
    $("#auth-form-mount").innerHTML = `<p class="eyebrow">CONNECTION INTERRUPTED</p><h2>Ledger unavailable</h2><p class="auth-subtitle">The API could not be reached. Check the server and refresh this page.</p><button class="button button-primary" data-action="retry-auth">Retry connection</button>`;
  }
}

function renderAuthForm(mode, setupAccount = null) {
  const mount = $("#auth-form-mount");
  if (mode === "bootstrap") {
    mount.innerHTML = `
      <p class="eyebrow">FIRST-TIME SETUP</p><h2>Secure your Admin account</h2>
      <p class="auth-subtitle">Set a password for the existing Admin account. This one-time step keeps current user and vehicle records intact.</p>
      <form id="bootstrap-form" class="auth-form">
        <label>Account email<input name="email" type="email" required autocomplete="username" value="${esc(setupAccount?.email || "")}" ${setupAccount?.email ? "readonly" : ""}></label>
        <label>Display name<input name="full_name" required maxlength="120" autocomplete="name" value="${esc(setupAccount?.full_name || "")}"></label>
        <label>Create password<input name="password" type="password" required minlength="12" maxlength="128" autocomplete="new-password"></label>
        <p id="auth-message" class="auth-message" role="alert"></p>
        <button class="button button-primary" type="submit">Initialize administrator ${icon("arrow")}</button>
      </form>
      <p class="auth-switch">This setup link is available only until an Admin password is created.</p>`;
    return;
  }

  mount.innerHTML = `
    <p class="eyebrow">${mode === "register" ? "READ-ONLY ACCOUNT" : "SECURE SIGN IN"}</p>
    <h2>${mode === "register" ? "Create viewer access" : "Welcome back"}</h2>
    <p class="auth-subtitle">${mode === "register" ? "Viewer accounts can browse the ledger and reports." : "Sign in to review the vehicle ledger."}</p>
    <form id="login-form" class="auth-form">
      ${mode === "register" ? '<label>Full name<input name="full_name" required maxlength="120" autocomplete="name"></label>' : ""}
      <label>Email address<input name="email" type="email" required autocomplete="username"></label>
      <label>Password<input name="password" type="password" required minlength="${mode === "register" ? 12 : 8}" maxlength="128" autocomplete="${mode === "register" ? "new-password" : "current-password"}"></label>
      <p id="auth-message" class="auth-message" role="alert"></p>
      <button class="button button-primary" type="submit">${mode === "register" ? "Create viewer account" : "Sign in to AutoLedger"} ${icon("arrow")}</button>
    </form>
    <p class="auth-switch">${mode === "register" ? 'Already have access? <button type="button" data-action="show-login">Sign in</button>' : 'Need read-only access? <button type="button" data-action="show-register">Create a viewer account</button>'}</p>`;
}

async function submitAuth(event) {
  event.preventDefault();
  const form = event.target;
  const data = Object.fromEntries(new FormData(form));
  const submit = form.querySelector('button[type="submit"]');
  submit.disabled = true;
  try {
    if (form.id === "bootstrap-form") {
      await api("/api/auth/bootstrap", { method: "POST", body: JSON.stringify(data) });
      toast("Admin password set. Sign in to continue.");
      renderAuthForm("login");
    } else if (form.id === "login-form" && data.full_name) {
      await api("/api/auth/register", { method: "POST", body: JSON.stringify(data) });
      toast("Viewer account created. Sign in to continue.");
      renderAuthForm("login");
    } else {
      const result = await api("/api/auth/login", { method: "POST", body: JSON.stringify(data) });
      state.token = result.access_token;
      localStorage.setItem("autoledger-token", state.token);
      state.user = await loadCurrentUser();
      await loadBusinessMemberships();
      showApplication(hasPermission("vehicles.read") ? "dashboard" : "profile");
    }
  } catch (error) {
    showAuthMessage(error.message);
    submit.disabled = false;
  }
}

function signOut(notify = true) {
  if (state.token) {
    fetch("/api/auth/logout", {
      method: "POST",
      credentials: "same-origin",
      headers: { Authorization: `Bearer ${state.token}` },
    }).catch(error => console.warn("Could not revoke the server refresh session.", error));
  }
  localStorage.removeItem("autoledger-token");
  state.token = null;
  state.user = null;
  state.businesses = [];
  state.businessId = null;
  state.detail = null;
  if (notify) toast("You have signed out.");
  showAuth();
}

function applyTheme(theme) {
  state.theme = theme;
  document.documentElement.dataset.theme = theme;
  localStorage.setItem("autoledger-theme", theme);
  const use = $("#theme-icon use");
  if (use) use.setAttribute("href", theme === "dark" ? "#i-sun" : "#i-moon");
}

function showApplication(initialPage = "dashboard") {
  $("#auth-screen").classList.add("hidden");
  $("#app-shell").classList.remove("hidden");
  $("#profile-name").textContent = state.user.full_name;
  $("#profile-role").textContent = state.user.role;
  $("#profile-avatar").textContent = initials(state.user.full_name);
  const switcher = $("#business-switcher");
  const selector = $("#business-selector");
  switcher.classList.toggle("hidden", state.businesses.length === 0);
  selector.innerHTML = state.businesses.map(business =>
    `<option value="${business.business_id}" ${business.business_id === state.businessId ? "selected" : ""}>${esc(business.business_name)}</option>`
  ).join("");
  document.querySelectorAll(".commerce-nav").forEach(link => {
    link.classList.toggle("hidden", !state.businessId || !canAccessPage(link.dataset.page));
  });
  document.querySelectorAll(".nav-link[data-page]").forEach(link => {
    link.classList.toggle("hidden", !canAccessPage(link.dataset.page));
  });
  $(".global-search").classList.toggle("hidden", !hasPermission("vehicles.read") && !hasPermission("owners.read"));
  $("#header-date").textContent = dateFmt.format(new Date());
  applyTheme(state.theme);
  state.page = location.hash.slice(1) || initialPage;
  navigate(state.page);
}

function changeBusiness(businessId) {
  const business = state.businesses.find(item => item.business_id === Number(businessId));
  if (!business || business.business_id === state.businessId) return;
  state.businessId = business.business_id;
  localStorage.setItem(`autoledger-business-${state.user.user_id}`, String(business.business_id));
  state.user = {
    ...state.user,
    role: business.role_name,
    role_name: business.role_name,
    permissions: business.permissions,
  };
  showApplication(state.page);
}

function titleFor(page) {
  return ({
    dashboard: "Overview", vehicles: "Vehicles", inventory: "Inventory",
    suppliers: "Suppliers", customers: "Customers", purchases: "Purchases",
    sales: "Sales", payments: "Payments", owners: "Owners",
    documents: "Documents", inspections: "Inspections", verification: "Verification",
    reports: "Reports", audit: "Audit trail", users: "Team access", profile: "Profile & settings",
    access: "Access pending",
  })[page] || "Overview";
}

function navigate(page) {
  const allowed = ["dashboard", "vehicles", "inventory", "suppliers", "customers", "purchases", "sales", "payments", "owners", "documents", "inspections", "verification", "reports", "audit", "users", "profile", "access"];
  if (!allowed.includes(page)) page = "dashboard";
  if (page === "access" && hasAnyAccess()) {
    page = hasPermission("vehicles.read") ? "dashboard" : "reports";
  }
  if (!canAccessPage(page)) {
    page = hasPermission("vehicles.read") ? "dashboard" : hasAnyAccess() ? "reports" : "access";
  }
  state.page = page;
  state.pageNumber = 1;
  state.detail = null;
  document.querySelectorAll(".nav-link[data-page]").forEach(link => link.classList.toggle("active", link.dataset.page === page));
  $("#breadcrumb-current").textContent = titleFor(page);
  document.title = `${titleFor(page)} | AutoLedger`;
  location.hash = page;
  closeMenu();
  renderPage();
}

function pageHeading(title, subtitle, action = "") {
  return `<div class="page-heading"><div><p class="eyebrow">AUTOLEDGER / ${esc(title.toUpperCase())}</p><h1>${esc(title)}</h1><p>${esc(subtitle)}</p></div>${action ? `<div class="heading-actions">${action}</div>` : ""}</div>`;
}

function skeletonPage() {
  return `<div class="skeleton-kpis">${Array.from({ length: 5 }, () => '<div class="skeleton"></div>').join("")}</div><div class="dashboard-grid"><div class="skeleton skeleton-block"></div><div class="skeleton skeleton-block"></div></div>`;
}

async function renderPage() {
  const page = $("#page-content");
  page.innerHTML = skeletonPage();
  try {
    if (state.page === "dashboard") await renderDashboard(page);
    else if (state.page === "access") page.innerHTML = `<section class="module-gate" role="status"><div><h2>Application access is not assigned</h2><p>This verification account cannot access vehicle or business records. Ask an administrator to assign an operational role.</p></div></section>`;
    else if (state.page === "vehicles") await renderVehicles(page);
    else if (state.page === "reports") renderReports(page);
    else if (state.page === "profile") await renderProfile(page);
    else if (["suppliers", "customers"].includes(state.page)) await renderPartners(page, state.page);
    else if (["inventory", "purchases", "sales", "payments"].includes(state.page)) await renderCommercePage(page, state.page);
    else await renderRecordsPage(page, state.page);
    page.focus({ preventScroll: true });
  } catch (error) {
    page.innerHTML = `<div class="empty-state"><div>${icon("activity")}<b>Could not load this section</b><p>${esc(error.message)}</p></div></div>`;
    if (error.message.includes("administrator")) toast(error.message, true);
  }
}

function chartBars(rows) {
  if (!rows.length) return '<div class="empty-state"><div><b>No maintenance costs yet</b><p>Service and repair costs appear as records are added.</p></div></div>';
  const maximum = Math.max(1, ...rows.map(row => Number(row.total_cost || 0)));
  return `<div class="chart-legend"><span class="legend-item"><i class="legend-swatch"></i>Service</span><span class="legend-item"><i class="legend-swatch repair"></i>Repair</span></div><div class="bar-chart">${rows.map(row => {
    const service = Number(row.service_cost || 0) / maximum * 100;
    const repair = Number(row.repair_cost || 0) / maximum * 100;
    return `<div class="bar-row"><span class="bar-label">${esc(dateFmt.format(new Date(`${String(row.month).slice(0, 10)}T12:00:00+05:00`)).replace(/\s+\d{4}$/, ""))}</span><span class="bar-track"><i class="bar-service" style="width:${service}%"></i><i class="bar-repair" style="width:${repair}%"></i></span><span class="bar-value">${esc(moneyValue(row.total_cost))}</span></div>`;
  }).join("")}</div>`;
}

function renderBrandBars(rows) {
  if (!rows.length) return '<div class="empty-state"><div><b>No vehicle data</b></div></div>';
  const maximum = Math.max(1, ...rows.map(row => Number(row.value)));
  return `<div class="brand-bars">${rows.map(row => `<div class="brand-row"><span>${esc(row.label)}</span><span class="brand-track"><i style="width:${Number(row.value) / maximum * 100}%"></i></span><b>${esc(row.value)}</b></div>`).join("")}</div>`;
}

function renderFuelRows(rows) {
  if (!rows.length) return '<div class="empty-state"><div><b>No fuel data</b></div></div>';
  const total = rows.reduce((sum, row) => sum + Number(row.value), 0) || 1;
  return `<div class="fuel-list">${rows.map(row => `<div class="fuel-row"><i></i><span>${esc(row.label)}</span><b>${esc(row.value)}</b><span class="fuel-track"><i style="width:${Number(row.value) / total * 100}%"></i></span></div>`).join("")}</div>`;
}

function renderActivity(rows) {
  return rows.length ? `<div class="activity-list">${rows.map(item => `<div class="activity-item"><span class="activity-marker">${icon("activity")}</span><span class="activity-copy"><b>${esc(item.action)} · ${esc(item.entity_name)}${item.entity_id ? ` #${esc(item.entity_id)}` : ""}</b><small>${esc(dateValue(item.action_timestamp))} ${esc(String(item.action_timestamp || "").slice(11, 16))}</small></span></div>`).join("")}</div>` : '<div class="empty-state"><div><b>No recent changes</b><p>Changes to vehicles and ownership will appear here.</p></div></div>';
}

async function renderDashboard(page) {
  const data = await api("/api/dashboard");
  const metrics = data.kpis;
  $("#expiry-nav-count").textContent = metrics.expiring_documents || "";
  $("#expiry-nav-count").classList.toggle("hidden", !metrics.expiring_documents);
  const addVehicle = hasPermission("vehicles.manage") ? `<button class="button button-primary" data-action="new-vehicle">${icon("plus")}Add vehicle</button>` : "";
  page.innerHTML = `${pageHeading("Overview", "A live readout of the fleet ledger and its latest signals.", addVehicle)}
    <section class="kpi-grid" aria-label="Fleet key performance indicators">
      ${kpi("Fleet vehicles", metrics.total_vehicles, "registered records", "car")}
      ${kpi("Active owners", metrics.active_owners ?? "—", "current ownership links", "users")}
      ${kpi("Expiring documents", metrics.expiring_documents ?? "—", "due in the next 30 days", "file", metrics.expiring_documents ? "warning" : "")}
      ${hasPermission("financial.read") ? kpi("Maintenance this month", moneyValue(metrics.maintenance_cost_month), "service + repair spend", "wrench") : ""}
      ${kpi("Mileage flags", metrics.mileage_anomalies ?? "—", "odometer drops detected", "shield", metrics.mileage_anomalies ? "warning" : "")}
    </section>
    <section class="dashboard-grid">
      <div class="dashboard-left">
        ${hasPermission("financial.read") ? `<article class="panel"><header class="panel-heading"><div><h2>Maintenance cost</h2><p>PKR · recent months</p></div><a class="button button-quiet button-small" href="#reports" data-go="reports">Full report ${icon("arrow")}</a></header><div class="panel-content">${chartBars(data.charts.monthly_costs)}</div></article>` : ""}
        <article class="panel"><header class="panel-heading"><div><h2>Vehicles by make</h2><p>Fleet composition</p></div><a class="button button-quiet button-small" href="#vehicles" data-go="vehicles">View fleet ${icon("arrow")}</a></header><div class="panel-content">${renderBrandBars(data.charts.vehicles_by_brand)}</div></article>
      </div>
      <div class="dashboard-right">
        <article class="panel"><header class="panel-heading"><div><h2>Fuel mix</h2><p>Recorded powertrains</p></div></header><div class="panel-content">${renderFuelRows(data.charts.fuel_split)}</div></article>
        <article class="panel activity-panel"><header class="panel-heading"><div><h2>Recent activity</h2><p>Latest ledger changes</p></div>${hasPermission("audit.read") ? '<a class="button button-quiet button-small" href="#audit" data-go="audit">Audit trail</a>' : ""}</header><div class="panel-content">${renderActivity(data.activity)}</div></article>
      </div>
    </section>`;
}

function kpi(label, value, sub, symbol, stateClass = "") {
  return `<article class="kpi"><div class="kpi-top"><span>${esc(label)}</span><span class="kpi-icon ${stateClass}">${icon(symbol)}</span></div><strong>${esc(value)}</strong><small>${esc(sub)}</small></article>`;
}

function statusBadge(value) {
  const tone = String(value || "").toLowerCase().replace(/[^a-z0-9_-]/g, "");
  return `<span class="badge badge-${tone}">${esc(value || "Not recorded")}</span>`;
}

async function renderPartners(page, kind) {
  const isSupplier = kind === "suppliers";
  const title = isSupplier ? "Suppliers" : "Customers";
  const field = isSupplier ? "supplier_name" : "customer_name";
  const result = await api(`/api/${kind}?q=${encodeURIComponent(state.partnerSearch[kind])}&include_inactive=${state.includeInactivePartners}`);
  const rows = result[kind] || [];
  const canManage = hasPermission(`${kind}.manage`);
  const idField = isSupplier ? "supplier_id" : "customer_id";
  const visibleRows = rows.slice(
    (state.pageNumber - 1) * state.pageSize,
    state.pageNumber * state.pageSize,
  );
  const action = canManage
    ? `<button class="button button-primary" data-action="new-entity" data-kind="${kind}">${icon("plus")}Add ${isSupplier ? "supplier" : "customer"}</button>`
    : "";
  const body = rows.length
    ? `<div class="table-wrap"><table class="data-table"><thead><tr><th>${isSupplier ? "Supplier" : "Customer"}</th><th>Access</th><th>Email</th><th>Phone</th><th>ID</th><th>History</th>${canManage ? "<th>Actions</th>" : ""}</tr></thead><tbody>${visibleRows.map(row => `<tr><td><span class="table-primary">${esc(row[field])}</span></td><td>${statusBadge(row.is_active === false ? "INACTIVE" : "ACTIVE")}</td><td>${esc(row.email || "—")}</td><td>${esc(row.phone || "—")}</td><td>#${esc(row[idField])}</td><td><button class="button button-quiet button-small" data-action="partner-history" data-kind="${kind}" data-id="${row[idField]}">View history</button></td>${canManage ? `<td><button class="button button-quiet button-small" data-action="edit-entity" data-kind="${kind}" data-id="${row[idField]}">Edit</button><button class="button button-quiet button-small" data-action="toggle-partner" data-kind="${kind}" data-id="${row[idField]}" data-active="${row.is_active !== false}">${row.is_active === false ? "Reactivate" : "Deactivate"}</button></td>` : ""}</tr>`).join("")}</tbody></table></div>`
    : `<div class="empty-state"><div>${icon("users")}<b>No ${title.toLowerCase()} found</b><p>${state.partnerSearch[kind] ? "Try another search." : "No records are available in the directory yet."}</p></div></div>`;
  let history = "";
  if (state.partnerHistory?.kind === kind) {
    try {
      const { id } = state.partnerHistory;
      const historyResult = await api(`/api/${kind}/${id}/${isSupplier ? "purchases" : "sales"}`);
      const transactions = isSupplier ? historyResult.purchases : historyResult.sales;
      history = `<section class="panel report-help"><header class="panel-heading"><div><h2>${title.slice(0, -1)} transaction history</h2><p>${transactions.length} transaction records</p></div><button class="button button-quiet button-small" data-action="close-partner-history">Close history</button></header>${transactions.length ? `<div class="table-wrap"><table class="data-table"><thead><tr><th>Reference</th><th>Date</th><th>Status</th><th>Total</th><th>Paid</th><th>Balance</th></tr></thead><tbody>${transactions.map(row => { const purchase = isSupplier; const idKey = purchase ? "purchase_id" : "sale_id"; return `<tr><td>${esc(row[purchase ? "purchase_reference" : "sale_reference"] || `#${row[idKey]}`)}</td><td>${esc(dateValue(row[purchase ? "purchase_date" : "sale_date"]))}</td><td>${statusBadge(row[purchase ? "purchase_status" : "sale_status"])}</td><td>${esc(moneyValue(row.total_amount))}</td><td>${esc(moneyValue(row.paid_amount))}</td><td>${esc(moneyValue(row.balance_due))}</td></tr>`; }).join("")}</tbody></table></div>` : '<div class="panel-content">No transactions recorded for this party.</div>'}</section>`;
    } catch (error) {
      history = `<section class="module-gate" role="status"><div><h2>History unavailable</h2><p>${esc(error.message)}</p></div><button class="button button-quiet button-small" data-action="close-partner-history">Close</button></section>`;
    }
  }
  page.innerHTML = `${pageHeading(title, `${rows.length} records · search and manage the business directory`, action)}
    <div class="filter-bar"><label class="filter-search">${icon("search")}<input id="partner-search" data-kind="${kind}" type="search" placeholder="Search ${title.toLowerCase()} by name, email or phone..." value="${esc(state.partnerSearch[kind])}"></label>${canManage ? `<label class="filter-check"><input id="include-inactive-partners" type="checkbox" ${state.includeInactivePartners ? "checked" : ""}>Include inactive</label>` : ""}</div>
    ${body}${pager(rows.length, state.pageNumber, state.pageSize)}${history}`;
}

function openEntityForm(kind, record = null) {
  const isSupplier = kind === "suppliers";
  const entity = isSupplier ? "supplier" : "customer";
  const nameField = `${entity}_name`;
  const form = $("#entity-form");
  form.reset();
  form.dataset.kind = kind;
  form.dataset.id = record?.[`${entity}_id`] || "";
  $("#entity-form-title").textContent = `${record ? "Edit" : "Add"} ${entity}`;
  $("#entity-form-eyebrow").textContent = isSupplier ? "SUPPLIER DIRECTORY" : "CUSTOMER DIRECTORY";
  $("#entity-save").textContent = record ? "Save changes" : `Add ${entity}`;
  $("#entity-form-error").classList.add("hidden");
  $("#entity-fields").innerHTML = `
    <label>${isSupplier ? "Supplier" : "Customer"} name <span>*</span><input name="${nameField}" required maxlength="150" value="${esc(record?.[nameField] || "")}"></label>
    <label>Email address<input name="email" type="email" maxlength="150" value="${esc(record?.email || "")}"></label>
    <label>Phone<input name="phone" type="tel" maxlength="30" value="${esc(record?.phone || "")}"></label>`;
  $("#entity-dialog").showModal();
}

async function saveEntity(event) {
  event.preventDefault();
  const form = event.target;
  if (!form.reportValidity()) return;
  const kind = form.dataset.kind;
  const id = form.dataset.id;
  const payload = Object.fromEntries(new FormData(form));
  for (const key of ["email", "phone"]) if (!payload[key].trim()) payload[key] = null;
  const button = $("#entity-save");
  button.disabled = true;
  button.textContent = "Saving...";
  try {
    await api(id ? `/api/${kind}/${id}` : `/api/${kind}`, {
      method: id ? "PATCH" : "POST",
      body: JSON.stringify(payload),
    });
    $("#entity-dialog").close();
    toast(`${kind === "suppliers" ? "Supplier" : "Customer"} ${id ? "updated" : "added"}.`);
    await renderPage();
  } catch (error) {
    $("#entity-form-error").textContent = error.message;
    $("#entity-form-error").classList.remove("hidden");
  } finally {
    button.disabled = false;
    button.textContent = id ? "Save changes" : `Add ${kind === "suppliers" ? "supplier" : "customer"}`;
  }
}

function commerceUnavailable(page, error) {
  const explanation = error.status === 503
    ? "This module is unavailable because the proposed commerce schema has not been installed. The database migration is still pending separate approval; existing vehicle and history records are unaffected."
    : error.message;
  page.innerHTML = `${pageHeading(titleFor(state.page), "Live records are loaded from the AutoLedger API.")}
    <section class="module-gate" role="status"><span class="gate-icon">${icon(error.status === 503 ? "shield" : "activity")}</span><div><h2>${error.status === 503 ? "Module not enabled" : "Unable to load this module"}</h2><p>${esc(explanation)}</p>${error.status === 503 ? '<small>Commerce operations remain safely disabled until an approved migration is applied.</small>' : ""}</div></section>`;
}

async function renderCommercePage(page, kind) {
  const titles = {
    inventory: ["Inventory", "Current stock status and evidence-backed vehicle onboarding."],
    purchases: ["Purchases", "Acquisition history and supplier balances."],
    sales: ["Sales", "Completed vehicle sales and customer balances."],
    payments: ["Payments", "Payment events and outstanding transaction balances."],
  };
  const [title, subtitle] = titles[kind];
  const permissionByKind = {
    inventory: "inventory.manage",
    purchases: "purchases.manage",
    sales: "sales.manage",
    payments: "payments.manage",
  };
  const canManage = hasPermission(permissionByKind[kind]);
  const params = new URLSearchParams();
  if (kind === "inventory") {
    params.set("page", String(state.pageNumber));
    params.set("page_size", String(state.pageSize));
    if (state.commerceSearch.trim()) params.set("q", state.commerceSearch.trim());
    if (state.inventoryStatus) params.set("stock_status", state.inventoryStatus);
  }
  const suffix = kind === "inventory" ? `?${params}` : "";
  let result;
  try {
    result = await api(`/api/${kind}${suffix}`);
  } catch (error) {
    commerceUnavailable(page, error);
    return;
  }

  const sourceRows = kind === "inventory" ? result.vehicles : result[kind];
  const rows = kind !== "inventory" && state.commerceSearch.trim()
    ? sourceRows.filter(row => JSON.stringify(row).toLowerCase().includes(state.commerceSearch.trim().toLowerCase()))
    : sourceRows;
  const statusField = kind === "purchases" ? "purchase_status" : kind === "sales" ? "sale_status" : "payment_status";
  const filteredRows = ["purchases", "sales", "payments"].includes(kind) && state.commerceStatusFilter[kind]
    ? rows.filter(row => row[statusField] === state.commerceStatusFilter[kind])
    : rows;
  const visibleRows = kind === "inventory"
    ? filteredRows
    : filteredRows.slice((state.pageNumber - 1) * state.pageSize, state.pageNumber * state.pageSize);
  let action = "";
  if (canManage && ["purchases", "sales", "payments"].includes(kind)) {
    action = `<button class="button button-primary" data-action="new-commerce" data-kind="${kind}">${icon("plus")}${kind === "purchases" ? "Record purchase" : kind === "sales" ? "Create sale" : "Record payment"}</button>`;
  }
  const inventorySummary = kind === "inventory"
    ? `<section class="kpi-grid commerce-kpis">${kpi("Vehicles in view", result.total, "matching registry entries", "car")}${kpi("Acquisition value", moneyValue(result.acquisition_valuation), "recorded purchases only", "file")}${kpi("Asking value", moneyValue(result.asking_valuation), "listed asking prices", "chart")}</section>`
    : "";
  const statusOptions = kind === "purchases"
    ? ["DRAFT", "ORDERED", "RECEIVED"]
    : kind === "sales"
      ? ["DRAFT", "CONFIRMED", "COMPLETED", "CANCELLED"]
      : ["PENDING", "COMPLETED", "FAILED", "VOIDED"];
  const tools = `<div class="filter-bar"><label class="filter-search">${icon("search")}<input id="commerce-search" type="search" placeholder="Search vehicle, customer or reference..." value="${esc(state.commerceSearch)}"></label>${kind === "inventory" ? `<select id="inventory-status" aria-label="Filter by stock status"><option value="">All stock states</option>${["AVAILABLE", "RESERVED", "SOLD", "UNDER_MAINTENANCE", "UNTRACKED"].map(item => `<option ${state.inventoryStatus === item ? "selected" : ""}>${item}</option>`).join("")}</select>` : ["purchases", "sales", "payments"].includes(kind) ? `<select id="commerce-status-filter" data-kind="${kind}" aria-label="Filter ${kind} by status"><option value="">All statuses</option>${statusOptions.map(item => `<option value="${item}" ${state.commerceStatusFilter[kind] === item ? "selected" : ""}>${item.replaceAll("_", " ")}</option>`).join("")}</select>` : ""}</div>`;
  const canReadFinance = hasPermission("invoices.read");
  const total = kind === "inventory" ? result.total : filteredRows.length;
  page.innerHTML = `${pageHeading(title, subtitle, action)}${inventorySummary}${tools}${commerceTable(kind, visibleRows || [], canManage, canReadFinance)}${pager(total, state.pageNumber, state.pageSize)}`;
}

function commerceTable(kind, rows, canManage, canReadFinance) {
  if (!rows.length) return `<div class="empty-state"><div>${icon(kind === "inventory" ? "car" : "file")}<b>No ${esc(kind)} records found</b><p>${state.commerceSearch ? "Try clearing or changing the search." : "There are no matching records from the database."}</p></div></div>`;
  if (kind === "inventory") {
    return `<div class="table-wrap"><table class="data-table"><thead><tr><th>Vehicle</th><th>Condition</th><th>Stock status</th><th>Acquisition cost</th><th>Asking price</th>${canManage ? "<th>Action</th>" : ""}</tr></thead><tbody>${rows.map(row => `<tr><td><span class="table-primary">${esc(row.registration_no)} · ${esc(row.brand)} ${esc(row.model)}</span><span class="table-secondary">${esc(row.vin)} · ${esc(row.model_year)}</span></td><td>${esc(row.vehicle_condition)}</td><td>${statusBadge(row.stock_status)}</td><td>${row.acquisition_cost == null ? "—" : esc(moneyValue(row.acquisition_cost))}</td><td>${row.asking_price == null ? "—" : esc(moneyValue(row.asking_price))}</td>${canManage ? `<td>${row.stock_status === "UNTRACKED" ? `<button class="button button-quiet button-small" data-action="onboard-inventory" data-id="${row.vehicle_id}">Onboard with evidence</button>` : ["AVAILABLE", "UNDER_MAINTENANCE"].includes(row.stock_status) ? `<button class="button button-quiet button-small" data-action="toggle-inventory" data-id="${row.vehicle_id}" data-status="${row.stock_status}">${row.stock_status === "AVAILABLE" ? "Mark maintenance" : "Mark available"}</button>` : "—"}</td>` : ""}</tr>`).join("")}</tbody></table></div>`;
  }
  if (kind === "purchases" || kind === "sales") {
    const purchase = kind === "purchases";
    return `<div class="table-wrap"><table class="data-table"><thead><tr><th>Reference</th><th>${purchase ? "Supplier" : "Customer"}</th><th>Date</th><th>Status</th><th>Total</th><th>Paid</th><th>Due</th>${!purchase && canReadFinance ? "<th>Invoice</th>" : ""}</tr></thead><tbody>${rows.map(row => { const id = purchase ? row.purchase_id : row.sale_id; const completed = row[purchase ? "purchase_status" : "sale_status"] === (purchase ? "RECEIVED" : "COMPLETED"); return `<tr><td><span class="table-primary">${esc(row[purchase ? "purchase_reference" : "sale_reference"] || `#${id}`)}</span></td><td>${esc(purchase ? row.supplier_name || "Supplier not recorded" : row.customer_name || "Customer not recorded")}</td><td>${esc(dateValue(row[purchase ? "purchase_date" : "sale_date"]))}</td><td>${statusBadge(row[purchase ? "purchase_status" : "sale_status"])}</td><td>${esc(moneyValue(row.total_amount))}</td><td>${esc(moneyValue(row.paid_amount))}</td><td><b>${esc(moneyValue(row.balance_due))}</b></td>${!purchase && canReadFinance ? `<td>${completed ? `<button class="button button-quiet button-small" data-action="download-financial-pdf" data-path="/api/sales/${id}/invoice.pdf" data-filename="autoledger-invoice-${id}.pdf">Invoice PDF</button>` : "—"}</td>` : ""}</tr>`; }).join("")}</tbody></table></div>`;
  }
  return `<div class="table-wrap"><table class="data-table"><thead><tr><th>Payment reference</th><th>Against</th><th>Date</th><th>Method</th><th>Status</th><th>Amount</th>${canReadFinance ? "<th>Receipt</th>" : ""}</tr></thead><tbody>${rows.map(row => `<tr><td><span class="table-primary">${esc(row.payment_reference)}</span><span class="table-secondary">${esc(row.payment_kind)}</span></td><td>${row.sale_id ? `Sale #${esc(row.sale_id)}` : `Purchase #${esc(row.purchase_id)}`}</td><td>${esc(dateFmt.format(new Date(row.payment_date)))}</td><td>${esc(row.payment_method)}</td><td>${statusBadge(row.payment_status)}</td><td>${esc(moneyValue(row.amount))}</td>${canReadFinance ? `<td>${row.payment_status === "COMPLETED" ? `<button class="button button-quiet button-small" data-action="download-financial-pdf" data-path="/api/payments/${row.payment_id}/receipt.pdf" data-filename="autoledger-receipt-${row.payment_id}.pdf">Receipt PDF</button>` : "—"}</td>` : ""}</tr>`).join("")}</tbody></table></div>`;
}

function vehicleSelectOptions(vehicles, selectedId = "") {
  return vehicles.map(vehicle => `<option value="${vehicle.vehicle_id}" ${Number(selectedId) === Number(vehicle.vehicle_id) ? "selected" : ""}>${esc(vehicle.registration_no)} · ${esc(vehicle.brand)} ${esc(vehicle.model)} · ${esc(vehicle.vin)}</option>`).join("");
}

function transactionItemField(kind, vehicles, allowRemove = true) {
  const purchase = kind === "purchases";
  return `<div class="transaction-line">
    <label>Vehicle <span>*</span><select name="vehicle_id" required><option value="">Select a vehicle</option>${vehicleSelectOptions(vehicles)}</select></label>
    <label>${purchase ? "Purchase price" : "Selling price"} · PKR <span>*</span><input name="unit_price" type="number" min="0" step="0.01" required></label>
    ${purchase ? "" : '<label>Discount · PKR<input name="discount_amount" type="number" min="0" step="0.01" value="0"></label>'}
    ${allowRemove ? '<button type="button" class="icon-action remove-line" data-action="remove-transaction-line" aria-label="Remove item" title="Remove item">' + icon("close") + "</button>" : ""}
  </div>`;
}

async function openCommerceForm(kind, vehicleId = "") {
  const form = $("#commerce-form");
  form.reset();
  form.dataset.kind = kind;
  form.dataset.paymentIdempotencyKey = kind === "payments" ? crypto.randomUUID() : "";
  $("#commerce-form-error").classList.add("hidden");
  $("#commerce-form-title").textContent = ({
    purchases: "Record vehicle purchase",
    sales: "Create vehicle sale",
    payments: "Record payment",
    inventory: "Onboard vehicle inventory",
  })[kind];
  $("#commerce-save").textContent = "Submit";
  const today = new Date(Date.now() - new Date().getTimezoneOffset() * 60000).toISOString().slice(0, 10);
  let html = "";
  if (kind === "purchases") {
    const [supplierData, vehicleData] = await Promise.all([
      api("/api/suppliers"),
      api("/api/vehicles?page_size=100"),
    ]);
    html = `<label>Supplier <span>*</span><select name="supplier_id" required><option value="">Select supplier</option>${supplierData.suppliers.map(row => `<option value="${row.supplier_id}">${esc(row.supplier_name)}</option>`).join("")}</select></label>
      <label>Purchase date <span>*</span><input name="purchase_date" type="date" value="${today}" required></label>
      <label>Reference<input name="purchase_reference" maxlength="50"></label>
      <div class="transaction-lines" id="transaction-lines">${transactionItemField(kind, vehicleData.vehicles, false)}</div>
      <button type="button" class="button button-quiet button-small item-add" data-action="add-transaction-item">Add another vehicle</button>
      ${initialPaymentFields()}`;
    form.dataset.vehicleOptions = JSON.stringify(vehicleData.vehicles);
  } else if (kind === "sales") {
    const [customerData, inventoryData] = await Promise.all([
      api("/api/customers"),
      api("/api/inventory?stock_status=AVAILABLE&page_size=100"),
    ]);
    const available = inventoryData.vehicles.filter(row => row.stock_status === "AVAILABLE");
    if (!available.length) throw new Error("No available, onboarded inventory is ready for sale.");
    html = `<label>Customer <span>*</span><select name="customer_id" required><option value="">Select customer</option>${customerData.customers.map(row => `<option value="${row.customer_id}">${esc(row.customer_name)}</option>`).join("")}</select></label>
      <label>Sale date <span>*</span><input name="sale_date" type="date" value="${today}" required></label>
      <label>Reference<input name="sale_reference" maxlength="50"></label>
      <div class="transaction-lines" id="transaction-lines">${transactionItemField(kind, available, false)}</div>
      <button type="button" class="button button-quiet button-small item-add" data-action="add-transaction-item">Add another vehicle</button>
      <p class="form-hint span-two">Tax is currently disabled. Each vehicle must be available in inventory; the server checks and locks stock during sale.</p>
      ${initialPaymentFields()}`;
    form.dataset.vehicleOptions = JSON.stringify(available);
  } else if (kind === "inventory") {
    const vehicleData = await api("/api/vehicles?page_size=100");
    html = `<label>Vehicle <span>*</span><select name="vehicle_id" required><option value="">Select vehicle</option>${vehicleSelectOptions(vehicleData.vehicles, vehicleId)}</select></label>
      <label>Condition<select name="vehicle_condition"><option>UNKNOWN</option><option>NEW</option><option>EXCELLENT</option><option>GOOD</option><option>FAIR</option><option>POOR</option><option>DAMAGED</option></select></label>
      <label>Asking price · PKR<input name="asking_price" type="number" min="0" step="0.01"></label>
      <label>Source reference<input name="source_reference" maxlength="120"></label>
      <label class="span-two">Inventory source evidence <span>*</span><textarea name="source_note" rows="3" maxlength="500" required placeholder="Explain how current inventory status was verified"></textarea></label>
      <p class="form-hint span-two">Onboarding does not create historical purchases or alter ownership history.</p>`;
  } else if (kind === "payments") {
    const [purchaseData, saleData] = await Promise.all([api("/api/purchases"), api("/api/sales")]);
    const purchaseOptions = purchaseData.purchases.map(row => `<option value="purchase:${row.purchase_id}">Purchase ${esc(row.purchase_reference || `#${row.purchase_id}`)} · due ${esc(moneyValue(row.balance_due))}</option>`);
    const saleOptions = saleData.sales.map(row => `<option value="sale:${row.sale_id}">Sale ${esc(row.sale_reference || `#${row.sale_id}`)} · due ${esc(moneyValue(row.balance_due))}</option>`);
    html = `<label>Transaction <span>*</span><select name="parent" required><option value="">Select transaction</option><optgroup label="Purchases">${purchaseOptions.join("")}</optgroup><optgroup label="Sales">${saleOptions.join("")}</optgroup></select></label>
      <label>Amount · PKR <span>*</span><input name="amount" type="number" min="0.01" step="0.01" required></label>
      <label>Payment method <span>*</span><select name="payment_method" required>${paymentMethods()}</select></label>
      <label>Status<select name="payment_status"><option>COMPLETED</option><option>PENDING</option><option>FAILED</option></select></label>
      <label class="span-two">External reference<input name="external_reference" maxlength="120"></label>`;
  }
  $("#commerce-fields").innerHTML = html;
  $("#commerce-dialog").showModal();
}

function initialPaymentFields() {
  return `<div class="transaction-payment">
    <h3>Initial payment <span>Optional</span></h3>
    <label>Amount · PKR<input name="initial_payment_amount" type="number" min="0" step="0.01" placeholder="Leave blank if unpaid"></label>
    <label>Method<select name="initial_payment_method"><option value="">Choose if entering payment</option>${paymentMethods()}</select></label>
    <label>Status<select name="initial_payment_status"><option>COMPLETED</option><option>PENDING</option></select></label>
  </div>`;
}

function paymentMethods() {
  return ["CASH", "BANK_TRANSFER", "CARD", "CHEQUE", "MOBILE_WALLET", "OTHER"]
    .map(method => `<option>${method}</option>`).join("");
}

function addTransactionItem() {
  const form = $("#commerce-form");
  const kind = form.dataset.kind;
  const vehicles = JSON.parse(form.dataset.vehicleOptions || "[]");
  $("#transaction-lines").insertAdjacentHTML("beforeend", transactionItemField(kind, vehicles));
}

async function saveCommerce(event) {
  event.preventDefault();
  const form = event.target;
  if (!form.reportValidity()) return;
  const kind = form.dataset.kind;
  const fields = Object.fromEntries(new FormData(form));
  const button = $("#commerce-save");
  button.disabled = true;
  button.textContent = "Submitting...";
  $("#commerce-form-error").classList.add("hidden");
  try {
    let path = `/api/${kind}`;
    let payload;
    if (kind === "inventory") {
      path = `/api/inventory/${fields.vehicle_id}`;
      payload = {
        vehicle_condition: fields.vehicle_condition,
        source_note: fields.source_note,
        source_reference: fields.source_reference || null,
        asking_price: fields.asking_price ? Number(fields.asking_price) : null,
      };
    } else if (kind === "payments") {
      const [parentKind, id] = fields.parent.split(":");
      payload = {
        [`${parentKind}_id`]: Number(id),
        amount: fields.amount,
        payment_method: fields.payment_method,
        payment_status: fields.payment_status,
        external_reference: fields.external_reference || null,
        idempotency_key: form.dataset.paymentIdempotencyKey,
      };
    } else {
      const purchase = kind === "purchases";
      const items = [...form.querySelectorAll(".transaction-line")].map(line => {
        const vehicleId = line.querySelector('[name="vehicle_id"]').value;
        const price = line.querySelector('[name="unit_price"]').value;
        return purchase
          ? { vehicle_id: Number(vehicleId), purchase_price: price }
          : {
            vehicle_id: Number(vehicleId),
            selling_price: price,
            discount_amount: line.querySelector('[name="discount_amount"]').value || "0",
            tax_amount: "0",
          };
      });
      if (new Set(items.map(item => item.vehicle_id)).size !== items.length) {
        throw new Error("Select each vehicle only once in a transaction.");
      }
      payload = purchase
        ? { supplier_id: Number(fields.supplier_id), purchase_date: fields.purchase_date, purchase_reference: fields.purchase_reference || null, items }
        : { customer_id: Number(fields.customer_id), sale_date: fields.sale_date, sale_reference: fields.sale_reference || null, items };
      if (fields.initial_payment_amount) {
        if (!fields.initial_payment_method) throw new Error("Choose a payment method or clear the initial payment amount.");
        payload.initial_payment = {
          amount: fields.initial_payment_amount,
          payment_method: fields.initial_payment_method,
          payment_status: fields.initial_payment_status,
        };
      }
    }
    if (kind === "purchases" || kind === "sales") {
      const verb = kind === "purchases" ? "receive this purchase" : "complete this sale";
      if (!window.confirm(`Confirm ${verb} for ${payload.items.length} vehicle${payload.items.length === 1 ? "" : "s"}? The API will validate the full transaction before committing.`)) return;
    }
    await api(path, { method: "POST", body: JSON.stringify(payload) });
    $("#commerce-dialog").close();
    toast(kind === "inventory" ? "Vehicle added to tracked inventory." : `${kind.slice(0, -1)} recorded.`);
    await renderPage();
  } catch (error) {
    $("#commerce-form-error").textContent = error.message;
    $("#commerce-form-error").classList.remove("hidden");
  } finally {
    button.disabled = false;
    button.textContent = "Submit";
  }
}

async function toggleInventoryStatus(vehicleId, currentStatus) {
  const nextStatus = currentStatus === "AVAILABLE" ? "UNDER_MAINTENANCE" : "AVAILABLE";
  await api(`/api/inventory/${vehicleId}`, {
    method: "PATCH",
    body: JSON.stringify({ stock_status: nextStatus }),
  });
  toast(`Inventory status changed to ${nextStatus}.`);
  await renderPage();
}

function vehicleActionButtons(vehicle) {
  const edit = hasPermission("vehicles.manage") ? `<button class="icon-action" title="Edit vehicle" aria-label="Edit vehicle" data-action="edit-vehicle" data-id="${vehicle.vehicle_id}">${icon("file")}</button>` : "";
  const remove = hasPermission("vehicles.delete") ? `<button class="icon-action" title="Delete vehicle" aria-label="Delete vehicle" data-action="delete-vehicle" data-id="${vehicle.vehicle_id}">${icon("close")}</button>` : "";
  return `<span class="table-actions"><button class="button button-quiet button-small" data-action="vehicle-detail" data-id="${vehicle.vehicle_id}">Open ${icon("arrow")}</button>${edit}${remove}</span>`;
}

function vehicleTable(rows) {
  if (!rows.length) return '<div class="empty-state"><div><span class="kpi-icon">' + icon("car") + '</span><b>No vehicles match these filters</b><p>Clear a filter or register a vehicle to get started.</p></div></div>';
  return `<div class="table-wrap"><table class="data-table"><thead><tr><th>Registration / VIN</th><th>Vehicle</th><th>Year</th><th>Fuel</th><th>Transmission</th><th>Engine</th><th>Actions</th></tr></thead><tbody>${rows.map(vehicle => `<tr>
    <td><span class="table-primary">${esc(vehicle.registration_no)}</span><span class="table-secondary">${esc(vehicle.vin)}</span></td>
    <td><span class="table-primary">${esc(vehicle.brand)} ${esc(vehicle.model)}</span><span class="table-secondary">${esc(vehicle.color || "Color not recorded")}</span></td>
    <td>${esc(vehicle.model_year)}</td><td>${esc(vehicle.fuel_type || "—")}</td><td>${esc(vehicle.transmission || "—")}</td><td>${esc(vehicle.engine_no || "—")}</td>
    <td>${vehicleActionButtons(vehicle)}</td></tr>`).join("")}</tbody></table></div>`;
}

function pager(total, page, pageSize) {
  const pages = Math.max(1, Math.ceil(total / pageSize));
  return `<div class="pagination"><span>Showing ${total ? (page - 1) * pageSize + 1 : 0}–${Math.min(page * pageSize, total)} of ${total}</span><span class="pagination-actions"><button class="button button-quiet button-small" data-action="page-prev" ${page <= 1 ? "disabled" : ""}>Previous</button><button class="button button-quiet button-small" data-action="page-next" ${page >= pages ? "disabled" : ""}>Next</button></span></div>`;
}

async function renderVehicles(page) {
  const params = new URLSearchParams({ search: state.vehicleFilters.search, page: String(state.pageNumber), page_size: String(state.pageSize), sort: state.vehicleFilters.sort, direction: state.vehicleFilters.direction });
  if (state.vehicleFilters.brand) params.set("brand", state.vehicleFilters.brand);
  if (state.vehicleFilters.fuel_type) params.set("fuel_type", state.vehicleFilters.fuel_type);
  if (state.vehicleFilters.model_year) params.set("model_year", state.vehicleFilters.model_year);
  if (state.vehicleFilters.status) params.set("status", state.vehicleFilters.status);
  const [result, allVehicles] = await Promise.all([
    api(`/api/vehicles?${params}`),
    api("/api/vehicles?page_size=100"),
  ]);
  const rolesCanEdit = hasPermission("vehicles.manage");
  const action = rolesCanEdit ? `<button class="button button-primary" data-action="new-vehicle">${icon("plus")}Add vehicle</button>` : "";
  const brands = [...new Set(allVehicles.vehicles.map(vehicle => vehicle.brand))].sort();
  const fuels = [...new Set(allVehicles.vehicles.map(vehicle => vehicle.fuel_type).filter(Boolean))].sort();
  page.innerHTML = `${pageHeading("Vehicles", `${result.count} registered vehicles · searchable by VIN, registration or make`, action)}
    <div class="filter-bar"><label class="filter-search">${icon("search")}<input id="vehicle-search" type="search" placeholder="Search registration, VIN, make..." value="${esc(state.vehicleFilters.search)}"></label>
      <select id="vehicle-brand"><option value="">All makes</option>${brands.map(brand => `<option ${state.vehicleFilters.brand === brand ? "selected" : ""}>${esc(brand)}</option>`).join("")}</select>
      <select id="vehicle-fuel"><option value="">All fuel types</option>${fuels.map(fuel => `<option ${state.vehicleFilters.fuel_type === fuel ? "selected" : ""}>${esc(fuel)}</option>`).join("")}</select>
      <input id="vehicle-year" type="number" min="1980" max="2035" placeholder="Year" aria-label="Filter by model year" value="${esc(state.vehicleFilters.model_year)}">
      <select id="vehicle-status" aria-label="Filter by ownership status"><option value="">Any ownership</option><option value="ACTIVE" ${state.vehicleFilters.status === "ACTIVE" ? "selected" : ""}>Active owner</option><option value="UNASSIGNED" ${state.vehicleFilters.status === "UNASSIGNED" ? "selected" : ""}>Unassigned</option></select>
      <select id="vehicle-sort" aria-label="Sort vehicles"><option value="vehicle_id">Recently added</option><option value="registration_no" ${state.vehicleFilters.sort === "registration_no" ? "selected" : ""}>Registration</option><option value="brand" ${state.vehicleFilters.sort === "brand" ? "selected" : ""}>Make</option><option value="model_year" ${state.vehicleFilters.sort === "model_year" ? "selected" : ""}>Year</option></select>
      <button class="button button-quiet button-small" data-action="sort-direction">${state.vehicleFilters.direction === "asc" ? "↑" : "↓"} Sort</button></div>
    ${vehicleTable(result.vehicles)}${pager(result.count, result.page, result.page_size)}`;
}

const columns = {
  owners: [["owner_id", "ID"], ["full_name", "Owner"], ["email", "Email"], ["phone", "Phone"], ["active_vehicles", "Active vehicles"], ["created_at", "Added"]],
  documents: [["registration_no", "Vehicle"], ["document_type", "Document"], ["document_number", "Reference"], ["issue_date", "Issued"], ["expiry_date", "Expiry"], ["status", "Status"]],
  inspections: [["registration_no", "Vehicle"], ["event_date", "Date"], ["inspector", "Inspector"], ["result", "Result"], ["remarks", "Notes"]],
  verification: [["registration_no", "Vehicle"], ["event_date", "Date"], ["verified_by", "Verified by"], ["result", "Result"], ["remarks", "Remarks"]],
  audit: [["action_timestamp", "Timestamp"], ["actor", "Actor"], ["action", "Action"], ["entity_name", "Entity"], ["entity_id", "Record"], ["details", "Change details"]],
};
const recordPage = {
  users: ["Team access", "Manage sign-in accounts and their ledger permissions.", "users"],
  owners: ["Owners", "People and organizations linked to the fleet.", "owners"],
  documents: ["Documents", "Track document status and upcoming expiry dates.", "documents"],
  inspections: ["Inspections", "Inspection outcomes recorded against vehicles.", "inspections"],
  verification: ["Verification", "Vehicle identity and record verification events.", "verification"],
  audit: ["Audit trail", "A chronological record of sensitive ledger changes.", "audit"],
};

const recordForms = {
  owners: { title: "Add owner", fields: [["full_name", "Full name", "text", true], ["email", "Email", "email", false], ["phone", "Phone", "tel", false]] },
  services: { title: "Add service record", fields: [["vehicle_id", "Vehicle ID", "number", true], ["service_date", "Service date", "date", true], ["service_type", "Service type", "text", true], ["mileage", "Odometer km", "number", false], ["workshop_name", "Workshop", "text", false], ["cost", "Cost (PKR)", "number", false], ["notes", "Notes", "text", false]] },
  repairs: { title: "Add repair record", fields: [["vehicle_id", "Vehicle ID", "number", true], ["repair_date", "Repair date", "date", true], ["repair_type", "Repair type", "text", true], ["workshop_name", "Workshop", "text", false], ["cost", "Cost (PKR)", "number", false], ["description", "Description", "text", false]] },
  mileage: { title: "Add odometer reading", fields: [["vehicle_id", "Vehicle ID", "number", true], ["recorded_date", "Reading date", "date", true], ["mileage", "Odometer km", "number", true], ["source", "Source", "select:OWNER,SERVICE,INSPECTION,DEALER,OTHER", true]] },
  documents: { title: "Add document", fields: [["vehicle_id", "Vehicle ID", "number", true], ["document_type", "Document type", "text", true], ["document_number", "Reference number", "text", false], ["issue_date", "Issue date", "date", false], ["expiry_date", "Expiry date", "date", false], ["status", "Status", "select:VALID,PENDING,EXPIRED,CANCELLED", true]] },
  inspections: { title: "Record inspection", fields: [["vehicle_id", "Vehicle ID", "number", true], ["inspection_date", "Inspection date", "date", true], ["result", "Result", "select:PASS,FAIL,CONDITIONAL,PENDING", true], ["remarks", "Remarks", "text", false]] },
  verification: { title: "Record verification", fields: [["vehicle_id", "Vehicle ID", "number", true], ["verification_date", "Verification date", "date", true], ["result", "Result", "select:VERIFIED,REJECTED,PENDING,CONDITIONAL", true], ["remarks", "Remarks", "text", false]] },
};

function recordActionFor(key) {
  const permission = {
    owners: "owners.manage",
    documents: "history.manage",
    inspections: "verification.manage",
    verification: "verification.manage",
    services: "history.manage",
    repairs: "history.manage",
    mileage: "history.manage",
  }[key];
  return permission && hasPermission(permission)
    ? `<button class="button button-primary" data-action="new-record" data-resource="${key}">${icon("plus")}Add record</button>`
    : "";
}

function openRecordForm(resource, vehicleId = "", record = null) {
  const config = recordForms[resource];
  if (!config) return;
  const form = $("#record-form");
  form.dataset.recordId = record ? String(record.owner_id ?? record.document_id ?? record.inspection_id ?? record.verification_id ?? record.service_id ?? record.repair_id ?? record.mileage_id) : "";
  $("#record-form-title").textContent = record ? config.title.replace(/^Add |^Record /, "Edit ") : config.title;
  $("#record-form-eyebrow").textContent = resource.toUpperCase();
  form.dataset.resource = resource;
  $("#record-form-error").classList.add("hidden");
  $("#record-fields").innerHTML = config.fields.map(([name, label, type, required]) => {
    const isSelect = type.startsWith("select:");
    const control = isSelect
      ? `<select name="${name}" ${required ? "required" : ""}>${type.slice(7).split(",").map(value => `<option>${value}</option>`).join("")}</select>`
      : `<input name="${name}" type="${type}" ${required ? "required" : ""} ${type === "number" ? 'min="0" step="1"' : ""} ${name === "vehicle_id" && vehicleId ? `value="${esc(vehicleId)}" readonly` : ""}>`;
    return `<label>${esc(label)}${required ? " <span>*</span>" : ""}${control}</label>`;
  }).join("");
  for (const [name, value] of Object.entries(record || {})) {
    const field = form.elements.namedItem(name);
    if (field) field.value = value ?? "";
  }
  $("#record-dialog").showModal();
}

async function openEditRecord(resource, recordId) {
  const result = await api(`/api/records/${resource}/${recordId}`);
  openRecordForm(resource, result.record.vehicle_id || "", result.record);
}

function recordButtons(resource, record) {
  const recordId = record.owner_id ?? record.record_id ?? record.id;
  if (resource === "users") {
    return `<button class="button button-quiet button-small" data-action="edit-user" data-id="${esc(record.user_id)}" data-role="${esc(record.role_name)}" data-active="${record.is_active ? "true" : "false"}">Manage access</button>`;
  }
  const editPermission = {
    owners: "owners.manage",
    documents: "history.manage",
    inspections: "verification.manage",
    verification: "verification.manage",
    services: "history.manage",
    repairs: "history.manage",
    mileage: "history.manage",
  }[resource];
  const edit = editPermission && hasPermission(editPermission)
    ? `<button class="icon-action" title="Edit record" aria-label="Edit record" data-action="edit-record" data-resource="${resource}" data-id="${esc(recordId)}">${icon("file")}</button>`
    : "";
  const remove = hasPermission("users.manage")
    ? `<button class="icon-action" title="Delete record" aria-label="Delete record" data-action="delete-record" data-resource="${resource}" data-id="${esc(recordId)}">${icon("close")}</button>`
    : "";
  return `${edit}${remove}`;
}

function cellValue(key, value) {
  if (["event_date", "issue_date", "expiry_date", "created_at", "action_timestamp"].includes(key)) return esc(dateValue(value));
  if (key === "status" || key === "result" || key === "action") return `<span class="badge badge-${esc(String(value || "").toLowerCase())}">${esc(value || "—")}</span>`;
  if (key === "details") return `<span class="table-secondary">${esc(String(value || "").slice(0, 95))}</span>`;
  return esc(value ?? "—");
}

async function renderRecordsPage(page, key) {
  const config = recordPage[key];
  if (!config) return;
  const [title, subtitle, resource] = config;
  if (key === "audit" && !hasPermission("audit.read")) {
    page.innerHTML = `${pageHeading(title, subtitle)}<div class="denied-note">Audit log access is limited to administrators.</div>`;
    return;
  }
  const result = key === "users"
    ? await api("/api/auth/users").then(data => ({ items: data.users, total: data.users.length, page: 1, page_size: 100 }))
    : await api(`/api/records/${resource}?page=${state.pageNumber}&page_size=${state.pageSize}&q=${encodeURIComponent(state.recordSearch || "")}`);
  const userColumns = [["full_name", "Name"], ["email", "Email"], ["role_name", "Role"], ["is_active", "Access"], ["created_at", "Created"]];
  const selectedColumns = key === "users" ? userColumns : columns[key];
  const filteredItems = key === "users"
    ? result.items.filter(item => {
      const term = state.userSearch.trim().toLowerCase();
      return (!term || [item.full_name, item.email, item.role_name].some(value => String(value || "").toLowerCase().includes(term)))
        && (!state.userRoleFilter || item.role_name === state.userRoleFilter)
        && (!state.userStatusFilter || String(item.is_active) === state.userStatusFilter);
    })
    : result.items;
  const visibleItems = key === "users"
    ? filteredItems.slice((state.pageNumber - 1) * state.pageSize, state.pageNumber * state.pageSize)
    : result.items;
  const total = key === "users" ? filteredItems.length : result.total;
  const canManageRows = key === "users"
    ? hasPermission("users.manage")
    : ["owners", "documents", "inspections", "verification"].some(resource =>
      hasPermission(resource === "owners" ? "owners.manage" : ["inspections", "verification"].includes(resource) ? "verification.manage" : "history.manage")
    );
  const displayColumns = canManageRows ? [...selectedColumns, ["__actions", "Actions"]] : selectedColumns;
  const usersAction = key === "users" ? `<button class="button button-primary" data-action="new-user">${icon("plus")}Add user</button>` : recordActionFor(key);
  const hasSearch = true;
  const expiring = key === "documents" ? result.items.filter(item => item.status !== "EXPIRED" && Number(item.days_until_expiry) <= 30).length : 0;
  const searchId = key === "users" ? "user-search" : "record-search";
  const searchValue = key === "users" ? state.userSearch : state.recordSearch || "";
  const searchTools = `<div class="filter-bar"><label class="filter-search">${icon("search")}<input id="${searchId}" type="search" placeholder="Search ${esc(title.toLowerCase())}..." value="${esc(searchValue)}"></label>${key === "documents" ? `<span class="badge badge-pending">${expiring} due soon</span>` : ""}${key === "users" ? `<select id="user-role-filter" aria-label="Filter users by role"><option value="">All roles</option>${[...new Set(result.items.map(item => item.role_name))].sort().map(role => `<option value="${esc(role)}" ${state.userRoleFilter === role ? "selected" : ""}>${esc(role)}</option>`).join("")}</select><select id="user-status-filter" aria-label="Filter users by status"><option value="">All access states</option><option value="true" ${state.userStatusFilter === "true" ? "selected" : ""}>Active</option><option value="false" ${state.userStatusFilter === "false" ? "selected" : ""}>Inactive</option></select>` : ""}</div>`;
  const rows = total ? `<div class="table-wrap"><table class="data-table"><thead><tr>${displayColumns.map(([, label]) => `<th>${esc(label)}</th>`).join("")}</tr></thead><tbody>${visibleItems.map(record => `<tr>${displayColumns.map(([field]) => `<td>${field === "__actions" ? `<span class="table-actions">${recordButtons(key, record)}</span>` : field === "is_active" ? `<span class="badge ${record[field] ? "badge-active" : "badge-expired"}">${record[field] ? "Active" : "Inactive"}</span>` : cellValue(field, record[field])}</td>`).join("")}</tr>`).join("")}</tbody></table></div>` : `<div class="empty-state"><div>${icon(key === "documents" ? "file" : "activity")}<b>No ${esc(title.toLowerCase())} found</b><p>There are no matching records in this part of the ledger.</p></div></div>`;
  if (key === "documents") $("#expiry-nav-count").classList.toggle("hidden", !expiring);
  page.innerHTML = `${pageHeading(title, subtitle, usersAction)}${hasSearch ? searchTools : ""}${rows}${pager(total, key === "users" ? state.pageNumber : result.page, key === "users" ? state.pageSize : result.page_size)}`;
}

function renderReports(page) {
  const canReadVehicles = hasPermission("vehicles.read");
  const canReadFinancial = Boolean(state.businessId) && hasPermission("reports.financial");
  const action = canReadVehicles ? `<button class="button button-primary" data-action="export-csv">${icon("download")}Export fleet CSV</button>` : "";
  page.innerHTML = `${pageHeading("Reports", "Export fleet records or open a printer-ready vehicle history.", action)}
    ${canReadVehicles ? `<section class="panel"><header class="panel-heading"><div><h2>Vehicle ledger export</h2><p>Current owner, vehicle identifiers, mileage and last service.</p></div></header><div class="panel-content report-controls"><label>Make filter<select id="report-brand"><option value="">All makes</option></select></label><label>Created from<input id="report-from" type="date"></label><label>Created to<input id="report-to" type="date"></label><button class="button button-quiet" data-action="export-csv">${icon("download")}Download CSV</button><p class="report-note">For a printable vehicle history, open a vehicle from the registry and choose “Print report”. In the print dialog, select “Save as PDF”.</p></div></section>` : ""}
    ${hasPermission("financial.read") ? `<section class="panel report-help"><header class="panel-heading"><div><h2>Maintenance spend</h2><p>Service and repair costs grouped by month in PKR.</p></div></header><div class="panel-content" id="report-cost-chart"><div class="skeleton skeleton-block"></div></div></section>` : ""}
    ${canReadFinancial ? `<section class="panel report-help"><header class="panel-heading"><div><h2>Business financials</h2><p>Purchase, sales, settlement, and recorded-cost margin · PKR · tax disabled.</p></div></header><div class="panel-content" id="financial-report-content"><div class="skeleton skeleton-block"></div></div></section>` : ""}`;
  if (canReadVehicles) {
    api("/api/vehicles?page_size=100").then(vehicles => {
      const select = $("#report-brand");
      if (select) [...new Set(vehicles.vehicles.map(item => item.brand))].sort().forEach(brand => select.add(new Option(brand, brand)));
    }).catch(error => toast(error.message, true));
  }
  if (hasPermission("financial.read")) {
    api("/api/dashboard").then(data => {
      const chart = $("#report-cost-chart");
      if (chart) chart.innerHTML = chartBars(data.charts.monthly_costs);
    }).catch(error => toast(error.message, true));
  }
  if (canReadFinancial) api("/api/reports/financial").then(report => {
    const target = $("#financial-report-content");
    if (!target) return;
    const totals = report.totals;
    target.innerHTML = `<section class="kpi-grid commerce-kpis">
      ${kpi("Purchases", moneyValue(totals.total_purchases), "received purchases", "file")}
      ${kpi("Sales", moneyValue(totals.total_sales), "completed sales", "chart")}
      ${kpi("Customer balances", moneyValue(totals.customer_balance_due), "outstanding", "users")}
      ${kpi("Supplier balances", moneyValue(totals.supplier_balance_due), "outstanding", "users")}
      ${kpi("Recorded gross profit", moneyValue(totals.realized_gross_profit), "known acquisition costs only", "chart")}
    </section><div class="table-wrap"><table class="data-table"><thead><tr><th>Month</th><th>Purchases</th><th>Sales</th></tr></thead><tbody>${report.monthly.map(row => `<tr><td>${esc(dateFmt.format(new Date(`${String(row.month).slice(0, 10)}T12:00:00+05:00`)))}</td><td>${esc(moneyValue(row.purchases))}</td><td>${esc(moneyValue(row.sales))}</td></tr>`).join("") || '<tr><td colspan="3">No business transactions in the reporting period.</td></tr>'}</tbody></table></div><p class="report-note">${esc(report.gross_profit_note)} Uncosted sold vehicles: ${esc(totals.sales_without_recorded_acquisition_cost)}.</p>`;
  }).catch(error => {
    const target = $("#financial-report-content");
    if (!target) return;
    target.innerHTML = `<div class="module-gate" role="status"><div><h2>${error.status === 503 ? "Financial reporting is not enabled" : "Financial report unavailable"}</h2><p>${esc(error.message)}</p></div></div>`;
  });
}

async function renderProfile(page) {
  const profile = await api("/api/auth/me");
  state.user = { ...state.user, ...profile, role: profile.role || profile.role_name };
  page.innerHTML = `${pageHeading("Profile & settings", "Manage your account details and sign-in security.")}
    <div class="dashboard-grid">
      <section class="panel"><header class="panel-heading"><div><h2>Profile</h2><p>Your account identity and assigned role.</p></div></header>
        <form id="profile-form" class="panel-content form-grid">
          <label>Full name <span>*</span><input name="full_name" value="${esc(profile.full_name)}" required maxlength="120"></label>
          <label>Email address<input value="${esc(profile.email)}" readonly></label>
          <label>Assigned role<input value="${esc(profile.role_name || profile.role)}" readonly></label>
          <div class="form-error hidden span-two" id="profile-form-error" role="alert"></div>
          <footer class="modal-actions span-two"><button class="button button-primary" type="submit">Save profile</button></footer>
        </form>
      </section>
      <section class="panel"><header class="panel-heading"><div><h2>Password & sessions</h2><p>Changing your password revokes active sessions.</p></div></header>
        <form id="password-form" class="panel-content form-grid">
          <label class="span-two">Current password <span>*</span><input type="password" name="current_password" required minlength="8" maxlength="128" autocomplete="current-password"></label>
          <label class="span-two">New password <span>*</span><input type="password" name="new_password" required minlength="12" maxlength="128" autocomplete="new-password"></label>
          <div class="form-error hidden span-two" id="password-form-error" role="alert"></div>
          <footer class="modal-actions span-two"><button class="button button-primary" type="submit">Change password</button></footer>
        </form>
      </section>
    </div>`;
}

async function saveProfile(event) {
  event.preventDefault();
  const form = event.target;
  if (!form.reportValidity()) return;
  const button = form.querySelector('button[type="submit"]');
  button.disabled = true;
  $("#profile-form-error").classList.add("hidden");
  try {
    const updated = await api("/api/auth/me", {
      method: "PATCH",
      body: JSON.stringify(Object.fromEntries(new FormData(form))),
    });
    state.user = { ...state.user, ...updated.user };
    $("#profile-name").textContent = state.user.full_name;
    $("#profile-avatar").textContent = initials(state.user.full_name);
    toast("Profile saved.");
  } catch (error) {
    $("#profile-form-error").textContent = error.message;
    $("#profile-form-error").classList.remove("hidden");
  } finally {
    button.disabled = false;
  }
}

async function changePassword(event) {
  event.preventDefault();
  const form = event.target;
  if (!form.reportValidity()) return;
  const button = form.querySelector('button[type="submit"]');
  button.disabled = true;
  $("#password-form-error").classList.add("hidden");
  try {
    const result = await api("/api/auth/password", {
      method: "POST",
      body: JSON.stringify(Object.fromEntries(new FormData(form))),
    });
    toast(result.message);
    signOut(false);
  } catch (error) {
    $("#password-form-error").textContent = error.message;
    $("#password-form-error").classList.remove("hidden");
  } finally {
    button.disabled = false;
  }
}

function detailRows(tab) {
  const data = state.detail;
  const map = {
    ownership: data.ownership.map(row => ({ date: row.start_date, title: row.full_name, sub: `${row.ownership_status}${row.end_date ? ` · ended ${dateValue(row.end_date)}` : " · current owner"}` })),
    services: data.services.map(row => ({ id: row.service_id, resource: "services", date: row.service_date, title: row.service_type, sub: `${row.workshop_name || "Workshop not recorded"} · ${row.mileage ?? "—"} km · ${moneyValue(row.cost)}` })),
    repairs: data.repairs.map(row => ({ id: row.repair_id, resource: "repairs", date: row.repair_date, title: row.repair_type, sub: `${row.workshop_name || "Workshop not recorded"} · ${moneyValue(row.cost)}${row.description ? ` · ${row.description}` : ""}` })),
    mileage: data.mileage.map(row => ({ id: row.mileage_id, resource: "mileage", date: row.recorded_date, title: `${row.mileage} km`, sub: row.source })),
    inspections: data.inspections.map(row => ({ id: row.inspection_id, resource: "inspections", date: row.inspection_date, title: row.result, sub: `${row.inspector} · ${row.remarks || "No notes"}` })),
    documents: data.documents.map(row => ({ id: row.document_id, resource: "documents", date: row.expiry_date, title: row.document_type, sub: `${row.document_number || "No reference"} · ${row.status}`, status: row.status })),
    verification: data.verifications.map(row => ({ id: row.verification_id, resource: "verification", date: row.verification_date, title: row.result, sub: row.remarks || "No notes" })),
  };
  const rows = map[tab] || [];
  if (!rows.length) return `<div class="empty-state"><div>${icon("file")}<b>No ${esc(tab)} recorded</b><p>There are no ${esc(tab)} records for this vehicle.</p></div></div>`;
  return `<div class="timeline">${rows.map(row => `<div class="timeline-item"><span class="timeline-date">${esc(dateValue(row.date))}</span><span class="timeline-rail"><i></i></span><div class="timeline-copy"><b>${esc(row.title)} ${row.status ? `<span class="badge badge-${esc(row.status.toLowerCase())}">${esc(row.status)}</span>` : ""}</b><p>${esc(row.sub)}</p>${row.resource ? `<span class="table-actions">${recordButtons(row.resource, { id: row.id })}</span>` : ""}</div></div>`).join("")}</div>`;
}

function mileageGraph(rows) {
  if (!rows.length) return '<div class="empty-state"><div><b>No mileage readings recorded</b></div></div>';
  const series = rows.slice(-18);
  const values = series.map(row => Number(row.mileage));
  const min = Math.min(...values);
  const max = Math.max(...values);
  const points = series.map((row, index) => {
    const x = series.length === 1 ? 320 : 24 + index * 592 / (series.length - 1);
    const y = max === min ? 70 : 112 - ((Number(row.mileage) - min) / (max - min)) * 88;
    return { x, y, row };
  });
  const pointList = points.map(point => `${point.x},${point.y}`).join(" ");
  const markers = points.map(point => `<circle cx="${point.x}" cy="${point.y}" r="3"><title>${esc(point.row.mileage)} km · ${esc(dateValue(point.row.recorded_date))}</title></circle>`).join("");
  return `<div class="mileage-line-chart" role="img" aria-label="Mileage readings over time"><svg viewBox="0 0 640 140" preserveAspectRatio="none"><line x1="24" y1="116" x2="616" y2="116"></line><line x1="24" y1="24" x2="24" y2="116"></line><polyline points="${pointList}"></polyline>${markers}</svg><div class="chart-scale"><span>${esc(dateValue(series[0].recorded_date))} · ${esc(min)} km</span><span>${esc(dateValue(series.at(-1).recorded_date))} · ${esc(max)} km</span></div></div><p class="table-secondary">Odometer readings in kilometers. Decreasing readings are rejected by the database.</p><div class="mileage-record-list">${series.map(row => `<div class="activity-item"><span class="activity-copy"><b>${esc(row.mileage)} km</b><small>${esc(dateValue(row.recorded_date))} · ${esc(row.source)}</small></span><span class="table-actions">${recordButtons("mileage", { record_id: row.mileage_id })}</span></div>`).join("")}</div>`;
}

async function openVehicle(vehicleId) {
  state.detail = await api(`/api/vehicles/${vehicleId}/history`);
  state.detailTab = "ownership";
  renderVehicleDetail();
}

function renderVehicleDetail() {
  const vehicle = state.detail.vehicle;
  const tabLabels = [["ownership", "Ownership"], ["services", "Service"], ["repairs", "Repairs"], ["mileage", "Mileage"], ["inspections", "Inspections"], ["documents", "Documents"], ["verification", "Verification"]];
  const latestMileage = state.detail.mileage.at(-1)?.mileage;
  const overdue = state.detail.documents.some(item => item.status === "EXPIRED");
  const score = Math.max(42, 100 - (overdue ? 18 : 0) - (state.detail.inspections.some(item => item.result === "FAIL") ? 20 : 0));
  const transfer = hasPermission("owners.manage") ? `<button class="button button-quiet button-small" data-action="transfer-owner">Transfer ownership</button>` : "";
  const edit = hasPermission("vehicles.manage") ? `<button class="button button-quiet button-small" data-action="edit-vehicle" data-id="${vehicle.vehicle_id}">Edit record</button>` : "";
  $("#page-content").innerHTML = `<button class="detail-back" data-action="back-vehicles">${icon("arrow")}Back to vehicles</button>
    <div class="detail-top"><div><div class="detail-title"><h1>${esc(vehicle.registration_no)}</h1><span class="badge badge-valid">${esc(vehicle.brand)} ${esc(vehicle.model)}</span></div><p class="detail-meta">VIN ${esc(vehicle.vin)} · Ledger record #${esc(vehicle.vehicle_id)}</p></div><span class="trust-score"><i></i>Trust score ${score}/100</span></div>
    <dl class="vehicle-facts"><div><dt>Model year</dt><dd>${esc(vehicle.model_year)}</dd></div><div><dt>Current owner</dt><dd>${esc(state.detail.ownership.find(item => item.ownership_status === "ACTIVE")?.full_name || "Unassigned")}</dd></div><div><dt>Odometer</dt><dd>${latestMileage == null ? "—" : `${esc(latestMileage)} km`}</dd></div><div><dt>Documents</dt><dd>${state.detail.documents.filter(item => item.status === "VALID").length} valid · ${state.detail.documents.filter(item => item.status === "EXPIRED").length} expired</dd></div><div><dt>Fuel / transmission</dt><dd>${esc(vehicle.fuel_type || "—")} / ${esc(vehicle.transmission || "—")}</dd></div></dl>
    <div class="detail-actions">${transfer}${edit}<button class="button button-quiet button-small" data-action="export-history-pdf">${icon("download")}Download PDF</button><button class="button button-quiet button-small" data-action="print-history">Print report ${icon("file")}</button></div>
    <nav class="detail-tabs" role="tablist">${tabLabels.map(([key, label]) => `<button role="tab" aria-selected="${state.detailTab === key}" class="detail-tab ${state.detailTab === key ? "active" : ""}" data-action="detail-tab" data-tab="${key}">${label}</button>`).join("")}</nav>
    <section class="panel detail-records"><header class="panel-heading"><div><h2>${esc(tabLabels.find(([key]) => key === state.detailTab)?.[1] || "Vehicle history")}</h2><p>Chronological ledger entries</p></div>${recordActionFor(state.detailTab === "services" ? "services" : state.detailTab === "repairs" ? "repairs" : state.detailTab)}</header><div class="panel-content">${state.detailTab === "mileage" ? mileageGraph(state.detail.mileage) : detailRows(state.detailTab)}</div></section>`;
}

async function openEditVehicle(vehicleId) {
  const vehicle = state.detail?.vehicle.vehicle_id === Number(vehicleId) ? state.detail.vehicle : (await api(`/api/vehicles/${vehicleId}`)).vehicle;
  if (!vehicle) return toast("Vehicle record could not be found.", true);
  const form = $("#vehicle-form");
  form.reset();
  $("#vehicle-id").value = vehicle.vehicle_id;
  $("#vehicle-form-title").textContent = "Edit vehicle";
  for (const [key, value] of Object.entries(vehicle)) if (form.elements.namedItem(key)) form.elements.namedItem(key).value = value ?? "";
  $("#vehicle-form-error").classList.add("hidden");
  $("#vehicle-dialog").showModal();
}

function openNewVehicle() {
  $("#vehicle-form").reset();
  $("#vehicle-id").value = "";
  $("#vehicle-form-title").textContent = "Add vehicle";
  $("#vehicle-form-error").classList.add("hidden");
  $("#vehicle-dialog").showModal();
}

async function saveVehicle(event) {
  event.preventDefault();
  const form = event.target;
  if (!form.reportValidity()) return;
  const id = $("#vehicle-id").value;
  const payload = Object.fromEntries(new FormData(form));
  payload.model_year = Number(payload.model_year);
  for (const field of ["color", "fuel_type", "transmission", "engine_no"]) if (!payload[field]) payload[field] = null;
  const button = $("#vehicle-save");
  button.disabled = true;
  button.querySelector("span").textContent = "Saving...";
  try {
    await api(id ? `/api/vehicles/${id}` : "/api/vehicles", { method: id ? "PUT" : "POST", body: JSON.stringify(payload) });
    $("#vehicle-dialog").close();
    toast(id ? "Vehicle record updated." : "Vehicle added to the ledger.");
    if (state.detail && id) await openVehicle(id);
    else await renderPage();
  } catch (error) {
    $("#vehicle-form-error").textContent = error.message;
    $("#vehicle-form-error").classList.remove("hidden");
  } finally {
    button.disabled = false;
    button.querySelector("span").textContent = "Save vehicle";
  }
}

async function transferOwner() {
  const form = $("#transfer-form");
  form.reset();
  form.elements.transfer_date.value = new Date().toISOString().slice(0, 10);
  $("#transfer-form-error").classList.add("hidden");
  $("#transfer-dialog").showModal();
}

async function saveTransfer(event) {
  event.preventDefault();
  const form = event.target;
  if (!form.reportValidity()) return;
  const button = $("#transfer-save");
  const payload = Object.fromEntries(new FormData(form));
  payload.new_owner_id = Number(payload.new_owner_id);
  button.disabled = true;
  button.textContent = "Transferring...";
  try {
    await api(`/api/vehicles/${state.detail.vehicle.vehicle_id}/transfer`, { method: "POST", body: JSON.stringify(payload) });
    $("#transfer-dialog").close();
    toast("Ownership transferred atomically.");
    await openVehicle(state.detail.vehicle.vehicle_id);
  } catch (error) {
    $("#transfer-form-error").textContent = error.message;
    $("#transfer-form-error").classList.remove("hidden");
  } finally {
    button.disabled = false;
    button.textContent = "Confirm transfer";
  }
}

async function saveRecord(event) {
  event.preventDefault();
  const form = event.target;
  if (!form.reportValidity()) return;
  const button = $("#record-save");
  const recordId = form.dataset.recordId;
  const payload = Object.fromEntries(new FormData(form));
  for (const field of ["vehicle_id", "mileage", "cost"]) if (payload[field] !== undefined && payload[field] !== "") payload[field] = Number(payload[field]);
  for (const [field, value] of Object.entries(payload)) if (value === "") delete payload[field];
  if (recordId) delete payload.vehicle_id;
  button.disabled = true;
  button.textContent = "Saving...";
  try {
    await api(recordId ? `/api/records/${form.dataset.resource}/${recordId}` : `/api/records/${form.dataset.resource}`, { method: recordId ? "PATCH" : "POST", body: JSON.stringify(payload) });
    $("#record-dialog").close();
    toast(recordId ? "Ledger record updated." : "Ledger record saved.");
    if (state.detail) await openVehicle(state.detail.vehicle.vehicle_id);
    else await renderPage();
  } catch (error) {
    $("#record-form-error").textContent = error.message;
    $("#record-form-error").classList.remove("hidden");
  } finally {
    button.disabled = false;
    button.textContent = "Save record";
  }
}

function openUserForm(userId = "", roleName = "Viewer", isActive = true) {
  const form = $("#user-form");
  form.reset();
  form.dataset.userId = userId;
  $("#user-form-title").textContent = userId ? "Manage user access" : "Create user account";
  $("#user-save").textContent = userId ? "Save access" : "Create account";
  $("#user-form-error").classList.add("hidden");
  const assignableRoles = state.user.role === "Super Admin"
    ? ["Viewer", "Staff", "Accountant", "Manager", "Business Owner", "Admin", "Super Admin"]
    : ["Viewer", "Staff", "Accountant", "Manager", "Business Owner", "Admin"];
  const legacyRole = Boolean(userId && roleName && !assignableRoles.includes(roleName));
  const roleField = legacyRole
    ? `<p class="form-hint span-two">This account has legacy role “${esc(roleName)}”. Its role assignment is preserved pending an approved mapping. You may change account status without changing its role.</p>`
    : `<label>Role <span>*</span><select name="role" required>${assignableRoles.map(role => `<option ${role === (roleName || "Viewer") ? "selected" : ""}>${role}</option>`).join("")}</select></label>`;
  $("#user-fields").innerHTML = userId
    ? `${roleField}<label>Account status <span>*</span><select name="is_active" required><option value="true" ${isActive ? "selected" : ""}>Active</option><option value="false" ${!isActive ? "selected" : ""}>Inactive</option></select></label>`
    : `<label>Full name <span>*</span><input name="full_name" required maxlength="120"></label><label>Email <span>*</span><input name="email" type="email" required></label>${roleField}<label>Temporary password <span>*</span><input name="password" type="password" required minlength="12" maxlength="128" autocomplete="new-password"></label>`;
  $("#user-dialog").showModal();
}

async function saveUser(event) {
  event.preventDefault();
  const form = event.target;
  if (!form.reportValidity()) return;
  const button = $("#user-save");
  button.disabled = true;
  const userId = form.dataset.userId;
  button.textContent = userId ? "Saving..." : "Creating...";
  try {
    const payload = Object.fromEntries(new FormData(form));
    if (userId) {
      payload.is_active = payload.is_active === "true";
      await api(`/api/auth/users/${userId}`, { method: "PATCH", body: JSON.stringify(payload) });
    } else {
      await api("/api/auth/users", { method: "POST", body: JSON.stringify(payload) });
    }
    $("#user-dialog").close();
    toast(userId ? "User access updated." : "User account created.");
    await renderPage();
  } catch (error) {
    $("#user-form-error").textContent = error.message;
    $("#user-form-error").classList.remove("hidden");
  } finally {
    button.disabled = false;
    button.textContent = form.dataset.userId ? "Save access" : "Create account";
  }
}

async function deleteLedgerRecord(resource, recordId) {
  if (!window.confirm("Delete this ledger record? Related history is never deleted automatically.")) return;
  await api(`/api/records/${resource}/${recordId}`, { method: "DELETE" });
  toast("Ledger record deleted.");
  if (state.detail) await openVehicle(state.detail.vehicle.vehicle_id);
  else await renderPage();
}

function printVehicleHistory() {
  const vehicle = state.detail.vehicle;
  const rows = [
    ["Ownership", state.detail.ownership.map(row => `${dateValue(row.start_date)} · ${row.full_name} · ${row.ownership_status}`)],
    ["Services", state.detail.services.map(row => `${dateValue(row.service_date)} · ${row.service_type} · ${moneyValue(row.cost)}`)],
    ["Repairs", state.detail.repairs.map(row => `${dateValue(row.repair_date)} · ${row.repair_type} · ${moneyValue(row.cost)}`)],
    ["Mileage", state.detail.mileage.map(row => `${dateValue(row.recorded_date)} · ${row.mileage} km (${row.source})`)],
    ["Inspections", state.detail.inspections.map(row => `${dateValue(row.inspection_date)} · ${row.result} · ${row.inspector}`)],
    ["Documents", state.detail.documents.map(row => `${row.document_type} · ${row.status} · ${dateValue(row.expiry_date)}`)],
    ["Verification", state.detail.verifications.map(row => `${dateValue(row.verification_date)} · ${row.result}`)],
  ];
  const printWindow = window.open("", "_blank");
  if (!printWindow) return toast("Allow pop-ups to print the vehicle report.", true);
  printWindow.opener = null;
  printWindow.document.write(`<!doctype html><html><head><title>${esc(vehicle.registration_no)} vehicle history</title><style>body{font:14px Arial,sans-serif;color:#17251d;margin:36px}h1{font-size:24px}h2{margin:25px 0 8px;font-size:16px;border-bottom:1px solid #ccd4cc;padding-bottom:6px}p{color:#46564b}li{margin:7px 0}.meta{line-height:1.8}@media print{body{margin:14mm}}</style></head><body><h1>AutoLedger · Vehicle history</h1><p class="meta"><b>${esc(vehicle.registration_no)}</b> · ${esc(vehicle.brand)} ${esc(vehicle.model)} · ${esc(vehicle.model_year)}<br>VIN ${esc(vehicle.vin)} · Generated ${esc(dateValue(new Date().toISOString()))}</p>${rows.map(([title, items]) => `<section><h2>${esc(title)}</h2>${items.length ? `<ul>${items.map(item => `<li>${esc(item)}</li>`).join("")}</ul>` : "<p>No entries recorded.</p>"}</section>`).join("")}<script>window.onload=()=>window.print()<\/script></body></html>`);
  printWindow.document.close();
}

async function exportCsv() {
  const params = new URLSearchParams();
  const brand = $("#report-brand")?.value;
  const from = $("#report-from")?.value;
  const to = $("#report-to")?.value;
  if (brand) params.set("brand", brand);
  if (from) params.set("date_from", from);
  if (to) params.set("date_to", to);
  const url = `/api/reports/vehicles.csv${params.size ? `?${params}` : ""}`;
  const response = await fetch(url, { headers: tokenHeader() });
  if (!response.ok) throw new Error("CSV export failed. Sign in again and retry.");
  const blob = await response.blob();
  const link = document.createElement("a");
  link.href = URL.createObjectURL(blob);
  link.download = "autoledger-vehicles.csv";
  link.click();
  URL.revokeObjectURL(link.href);
  toast("Vehicle report downloaded.");
}

async function downloadFinancialPdf(path, filename) {
  let response = await fetch(path, { headers: tokenHeader() });
  if (response.status === 401 && state.token) {
    const session = await api("/api/auth/refresh", { method: "POST" }, false);
    state.token = session.access_token;
    state.user = session.user;
    localStorage.setItem("autoledger-token", state.token);
    response = await fetch(path, { headers: tokenHeader() });
  }
  if (!response.ok) {
    const body = await response.json().catch(() => null);
    throw new Error(typeof body?.detail === "string" ? body.detail : "The PDF could not be downloaded.");
  }
  const blob = await response.blob();
  const link = document.createElement("a");
  link.href = URL.createObjectURL(blob);
  link.download = filename;
  link.click();
  window.setTimeout(() => URL.revokeObjectURL(link.href), 1000);
}

async function exportVehicleHistoryPdf() {
  const vehicleId = state.detail.vehicle.vehicle_id;
  const response = await fetch(`/api/reports/vehicles/${vehicleId}.pdf`, { headers: tokenHeader() });
  if (!response.ok) {
    if (response.status === 401) signOut(false);
    const body = await response.json().catch(() => null);
    throw new Error(body?.detail || "Vehicle history PDF could not be generated.");
  }
  const blob = await response.blob();
  const link = document.createElement("a");
  link.href = URL.createObjectURL(blob);
  link.download = `autoledger-vehicle-${vehicleId}-history.pdf`;
  link.click();
  window.setTimeout(() => URL.revokeObjectURL(link.href), 1000);
  toast("Vehicle history PDF downloaded.");
}
async function searchGlobally(value) {
  const list = $("#global-search-results");
  if (!value.trim()) { list.classList.add("hidden"); return; }
  try {
    const data = await api(`/api/search?q=${encodeURIComponent(value.trim())}`);
    list.innerHTML = data.results.length ? data.results.map(item => `<button class="search-result" data-action="global-result" data-kind="${esc(item.kind)}" data-id="${esc(item.id)}"><b>${esc(item.title)}</b><small>${esc(item.kind)} · ${esc(item.subtitle)}</small></button>`).join("") : '<div class="search-empty">No matching vehicles or owners</div>';
    list.classList.remove("hidden");
  } catch (error) { list.innerHTML = `<div class="search-empty">${esc(error.message)}</div>`; list.classList.remove("hidden"); }
}

function closeMenu() {
  $("#sidebar").classList.remove("open");
  $("#sidebar-scrim").classList.add("hidden");
}

async function rerenderPreservingSearch(selector) {
  const input = $(selector);
  const start = input?.selectionStart;
  const end = input?.selectionEnd;
  await renderPage();
  const refreshed = $(selector);
  if (refreshed) {
    refreshed.focus();
    if (start !== null && end !== null) refreshed.setSelectionRange(start, end);
  }
}

function bindEvents() {
  document.addEventListener("submit", event => {
    if (["bootstrap-form", "login-form"].includes(event.target.id)) submitAuth(event);
    if (event.target.id === "vehicle-form") saveVehicle(event);
    if (event.target.id === "transfer-form") saveTransfer(event);
    if (event.target.id === "user-form") saveUser(event);
    if (event.target.id === "record-form") saveRecord(event);
    if (event.target.id === "entity-form") saveEntity(event);
    if (event.target.id === "commerce-form") saveCommerce(event);
    if (event.target.id === "profile-form") saveProfile(event);
    if (event.target.id === "password-form") changePassword(event);
  });
  document.addEventListener("change", event => {
    if (event.target.id === "business-selector") changeBusiness(event.target.value);
  });
  document.addEventListener("click", async event => {
    const pageLink = event.target.closest("[data-page]");
    if (pageLink) { event.preventDefault(); navigate(pageLink.dataset.page); return; }
    const go = event.target.closest("[data-go]");
    if (go) { event.preventDefault(); navigate(go.dataset.go); return; }
    const nav = event.target.closest("[data-action]");
    if (!nav) { if (!event.target.closest(".global-search")) $("#global-search-results")?.classList.add("hidden"); return; }
    const { action, id, tab, kind } = nav.dataset;
    try {
      if (action === "logout") signOut();
      else if (action === "show-login") renderAuthForm("login");
      else if (action === "show-register") renderAuthForm("register");
      else if (action === "retry-auth") showAuth();
      else if (action === "theme") applyTheme(state.theme === "dark" ? "light" : "dark");
      else if (action === "open-menu") { $("#sidebar").classList.add("open"); $("#sidebar-scrim").classList.remove("hidden"); }
      else if (action === "close-menu") closeMenu();
      else if (action === "new-vehicle") openNewVehicle();
      else if (action === "close-dialog") $("#vehicle-dialog").close();
      else if (action === "close-transfer") $("#transfer-dialog").close();
      else if (action === "close-user") $("#user-dialog").close();
      else if (action === "close-record") $("#record-dialog").close();
      else if (action === "close-entity") $("#entity-dialog").close();
      else if (action === "close-commerce") $("#commerce-dialog").close();
      else if (action === "new-user") openUserForm();
      else if (action === "edit-user") openUserForm(id, nav.dataset.role, nav.dataset.active === "true");
      else if (action === "new-entity") openEntityForm(kind);
      else if (action === "edit-entity") {
        openEntityForm(kind, await api(`/api/${kind}/${id}`));
      }
      else if (action === "partner-history") {
        state.partnerHistory = { kind, id };
        await renderPage();
      }
      else if (action === "close-partner-history") {
        state.partnerHistory = null;
        await renderPage();
      }
      else if (action === "toggle-partner") {
        const nextActive = nav.dataset.active !== "true";
        const label = kind === "suppliers" ? "supplier" : "customer";
        if (window.confirm(`${nextActive ? "Reactivate" : "Deactivate"} this ${label}? Existing transactions and history will be retained.`)) {
          await api(`/api/${kind}/${id}/active`, {
            method: "PATCH",
            body: JSON.stringify({ is_active: nextActive }),
          });
          toast(`${label[0].toUpperCase()}${label.slice(1)} ${nextActive ? "reactivated" : "deactivated"}.`);
          await renderPage();
        }
      }
      else if (action === "new-commerce") await openCommerceForm(kind);
      else if (action === "onboard-inventory") await openCommerceForm("inventory", id);
      else if (action === "toggle-inventory") await toggleInventoryStatus(id, nav.dataset.status);
      else if (action === "add-transaction-item") addTransactionItem();
      else if (action === "remove-transaction-line") {
        if ($("#transaction-lines").querySelectorAll(".transaction-line").length > 1) nav.closest(".transaction-line").remove();
      }
      else if (action === "new-record") openRecordForm(nav.dataset.resource, state.detail?.vehicle.vehicle_id || "");
      else if (action === "detail-add-record") openRecordForm(nav.dataset.resource, state.detail.vehicle.vehicle_id);
      else if (action === "edit-record") await openEditRecord(nav.dataset.resource, id);
      else if (action === "delete-record") await deleteLedgerRecord(nav.dataset.resource, id);
      else if (action === "edit-vehicle") await openEditVehicle(id);
      else if (action === "delete-vehicle") {
        if (window.confirm("Delete this vehicle? Linked ownership, service, and history records may prevent deletion.")) {
          await api(`/api/vehicles/${id}`, { method: "DELETE" });
          toast("Vehicle deleted.");
          await renderPage();
        }
      } else if (action === "vehicle-detail") await openVehicle(id);
      else if (action === "back-vehicles") { state.detail = null; await renderVehicles($("#page-content")); }
      else if (action === "detail-tab") { state.detailTab = tab; renderVehicleDetail(); }
      else if (action === "transfer-owner") await transferOwner();
      else if (action === "export-history-pdf") await exportVehicleHistoryPdf();
      else if (action === "print-history") printVehicleHistory();
      else if (action === "export-csv") await exportCsv();
      else if (action === "download-financial-pdf") await downloadFinancialPdf(nav.dataset.path, nav.dataset.filename);
      else if (action === "page-prev" && state.pageNumber > 1) { state.pageNumber--; await renderPage(); }
      else if (action === "page-next") { state.pageNumber++; await renderPage(); }
      else if (action === "sort-direction") { state.vehicleFilters.direction = state.vehicleFilters.direction === "asc" ? "desc" : "asc"; await renderPage(); }
      else if (action === "global-result" && kind === "vehicle") { $("#global-search-results").classList.add("hidden"); await openVehicle(id); }
      else if (action === "global-result" && kind === "owner") { state.recordSearch = nav.querySelector("b").textContent; $("#global-search-results").classList.add("hidden"); navigate("owners"); }
    } catch (error) { toast(error.message, true); }
  });

  window.addEventListener("hashchange", () => {
    const page = location.hash.slice(1);
    if (page && page !== state.page && state.user) navigate(page);
  });

  document.addEventListener("change", event => {
    if (event.target.id === "vehicle-brand") state.vehicleFilters.brand = event.target.value;
    if (event.target.id === "vehicle-fuel") state.vehicleFilters.fuel_type = event.target.value;
    if (event.target.id === "vehicle-year") state.vehicleFilters.model_year = event.target.value;
    if (event.target.id === "vehicle-status") state.vehicleFilters.status = event.target.value;
    if (event.target.id === "vehicle-sort") state.vehicleFilters.sort = event.target.value;
    if (event.target.id === "inventory-status") state.inventoryStatus = event.target.value;
    if (event.target.id === "commerce-status-filter") state.commerceStatusFilter[event.target.dataset.kind] = event.target.value;
    if (event.target.id === "include-inactive-partners") state.includeInactivePartners = event.target.checked;
    if (event.target.id === "user-role-filter") state.userRoleFilter = event.target.value;
    if (event.target.id === "user-status-filter") state.userStatusFilter = event.target.value;
    if (["vehicle-brand", "vehicle-fuel", "vehicle-year", "vehicle-status", "vehicle-sort", "inventory-status", "commerce-status-filter", "include-inactive-partners", "user-role-filter", "user-status-filter"].includes(event.target.id)) {
      state.pageNumber = 1;
      renderPage();
    }
  });

  document.addEventListener("input", event => {
    if (event.target.id === "vehicle-search") {
      state.vehicleFilters.search = event.target.value;
      window.clearTimeout(state.searchTimer);
      state.searchTimer = window.setTimeout(() => { state.pageNumber = 1; rerenderPreservingSearch("#vehicle-search"); }, 250);
    }
    if (event.target.id === "record-search") {
      state.recordSearch = event.target.value;
      window.clearTimeout(state.searchTimer);
      state.searchTimer = window.setTimeout(() => { state.pageNumber = 1; rerenderPreservingSearch("#record-search"); }, 250);
    }
    if (event.target.id === "user-search") {
      state.userSearch = event.target.value;
      window.clearTimeout(state.searchTimer);
      state.searchTimer = window.setTimeout(() => {
        state.pageNumber = 1;
        rerenderPreservingSearch("#user-search");
      }, 250);
    }
    if (event.target.id === "partner-search") {
      state.partnerSearch[event.target.dataset.kind] = event.target.value;
      window.clearTimeout(state.searchTimer);
      state.searchTimer = window.setTimeout(() => {
        state.pageNumber = 1;
        rerenderPreservingSearch("#partner-search");
      }, 250);
    }
    if (event.target.id === "commerce-search") {
      state.commerceSearch = event.target.value;
      window.clearTimeout(state.searchTimer);
      state.searchTimer = window.setTimeout(() => {
        state.pageNumber = 1;
        rerenderPreservingSearch("#commerce-search");
      }, 250);
    }
    if (event.target.id === "global-search-input") {
      window.clearTimeout(state.searchTimer);
      state.searchTimer = window.setTimeout(() => searchGlobally(event.target.value), 220);
    }
  });

  document.addEventListener("keydown", event => {
    if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k") {
      event.preventDefault();
      $("#global-search-input").focus();
    }
    if (event.key === "Escape") { closeMenu(); $("#global-search-results").classList.add("hidden"); }
  });
}

async function init() {
  applyTheme(state.theme);
  bindEvents();
  if (state.token) {
    try {
      state.user = normalizeUser(await api("/api/auth/me"));
      await loadBusinessMemberships();
      showApplication(location.hash.slice(1) || (hasPermission("vehicles.read") ? "dashboard" : "profile"));
      return;
    } catch { localStorage.removeItem("autoledger-token"); state.token = null; }
  }
  await showAuth();
}

init();

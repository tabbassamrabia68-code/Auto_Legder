const grid = document.querySelector("#vehicle-grid");
const message = document.querySelector("#message");
const count = document.querySelector("#result-count");
const status = document.querySelector("#api-status");
const historySection = document.querySelector("#history-section");

function esc(value) {
  return String(value ?? "").replace(/[&<>"']/g, ch => ({
    "&":"&amp;", "<":"&lt;", ">":"&gt;", '"':"&quot;", "'":"&#39;"
  })[ch]);
}

async function loadHealth() {
  try {
    const response = await fetch("/api/health");
    if (!response.ok) throw new Error("API unavailable");
    const data = await response.json();
    status.textContent = `Connected: ${data.database}`;
  } catch {
    status.textContent = "Connection issue";
  }
}

async function searchVehicles(term = "") {
  message.textContent = "Loading vehicles…";
  grid.innerHTML = "";
  try {
    const response = await fetch(`/api/vehicles?search=${encodeURIComponent(term)}`);
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || "Could not load vehicles");
    count.textContent = `${data.count} result(s)`;
    message.textContent = "";
    if (!data.vehicles.length) {
      grid.innerHTML = '<div class="empty">No vehicles found. Try a different registration number or model.</div>';
      return;
    }
    grid.innerHTML = data.vehicles.map(v => `
      <article class="vehicle-card">
        <div class="card-top"><span class="reg">${esc(v.registration_no)}</span><span class="tag">${esc(v.model_year ?? "Year N/A")}</span></div>
        <h3>${esc(v.brand)} ${esc(v.model)}</h3>
        <p>${esc(v.color || "Color not recorded")} · ${esc(v.fuel_type || "Fuel type N/A")}</p>
        <button data-history="${esc(v.vehicle_id)}">View vehicle history</button>
      </article>`).join("");
  } catch (error) {
    message.textContent = error.message;
    count.textContent = "Unavailable";
  }
}

async function showHistory(id) {
  const content = document.querySelector("#history-content");
  content.innerHTML = "<p>Loading history…</p>";
  historySection.classList.remove("hidden");
  historySection.scrollIntoView({behavior:"smooth", block:"start"});
  try {
    const response = await fetch(`/api/vehicles/${id}/history`);
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || "Could not load history");
    const v = data.vehicle;
    document.querySelector("#history-title").textContent = `${v.registration_no} — ${v.brand} ${v.model}`;
    const list = (items, render, empty) => items.length
      ? `<ul>${items.map(item => `<li>${render(item)}</li>`).join("")}</ul>`
      : `<p>${empty}</p>`;
    content.innerHTML = `
      <div class="history-block"><h3>Vehicle details</h3>
        <p>VIN: ${esc(v.vin || "Not recorded")} · Year: ${esc(v.model_year || "N/A")} · Transmission: ${esc(v.transmission || "N/A")}</p></div>
      <div class="history-block"><h3>Ownership history</h3>${list(data.ownership, x => `${esc(x.full_name)} — ${esc(x.ownership_status)} (from ${esc(x.start_date)})`, "No ownership records found.")}</div>
      <div class="history-block"><h3>Service history</h3>${list(data.services, x => `${esc(x.service_date)} — ${esc(x.service_type)}; ${esc(x.mileage)} km; ${esc(x.workshop_name)}`, "No service records found.")}</div>
      <div class="history-block"><h3>Repair history</h3>${list(data.repairs, x => `${esc(x.repair_date)} — ${esc(x.repair_type)}; cost ${esc(x.cost)}; ${esc(x.workshop_name)}`, "No repair records found.")}</div>
      <div class="history-block"><h3>Verification history</h3>${list(data.verifications, x => `${esc(x.verification_date)} — ${esc(x.result)}; ${esc(x.remarks)}`, "No verification records found.")}</div>`;
  } catch (error) {
    content.innerHTML = `<p>${esc(error.message)}</p>`;
  }
}

document.querySelector("#search-form").addEventListener("submit", e => {
  e.preventDefault();
  searchVehicles(document.querySelector("#search-input").value);
});
document.querySelector("#show-all").addEventListener("click", () => {
  document.querySelector("#search-input").value = "";
  searchVehicles();
});
grid.addEventListener("click", e => {
  const button = e.target.closest("[data-history]");
  if (button) showHistory(button.dataset.history);
});
document.querySelector("#close-history").addEventListener("click", () => historySection.classList.add("hidden"));

loadHealth();
searchVehicles();

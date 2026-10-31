/* Live complaint intelligence layer: uses the shared citizen_reports database, never synthetic assets. */
(() => {
  "use strict";
  const $ = s => document.querySelector(s);
  const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
  const fmt = n => Number(n || 0).toLocaleString("en-IN");
  const dateFmt = s => s ? new Date(s).toLocaleString("en-IN") : "Date unavailable";
  const api = async (url, options={}) => {
    const r = await fetch(url, {credentials:"same-origin", cache:"no-store", ...options});
    const j = await r.json().catch(()=>({}));
    if (!r.ok) throw new Error(j.error || `Request failed (${r.status})`);
    return j;
  };
  let liveReports = [];
  let selectedReport = null;
  let activePriority = "all";
  let citizenPinLayer = null;
  let citizenMarkers = new Map();
  const priorityScore = r => {
    const base = ({Critical:70, High:55, Medium:35, Low:15})[r.severity || "Medium"] || 35;
    const ageDays = Math.max(0, (Date.now() - new Date(r.created_at).getTime()) / 86400000);
    const age = Math.min(15, ageDays / 2);
    const related = Number(r.recurrence_count || 1);
    const recurrence = Math.min(15, Math.max(0, related - 1) * 3);
    return Math.min(100, Math.round(base + age + recurrence));
  };
  const priorityColor = s => s === "Critical" ? "#c83232" : s === "High" ? "#d97706" : s === "Medium" ? "#3976a8" : "#27815c";
  const deptOf = r => ({
    "Road / Pothole":"Roads","Drainage / Waterlogging":"Storm Water Drainage",
    "Streetlight / Electrical":"Electrical","Footpath / Encroachment":"Footpaths",
    "Garbage / Waste":"Public Health","Other civic issue":"Public Health"
  }[r.category] || "Unassigned");

  function refreshDepartmentOptions() {
    const select = $("#deptFilter");
    if (!select) return;
    const previous = select.value || "all";
    const departments = ["Roads", "Storm Water Drainage", "Electrical", "Footpaths", "Public Health"];
    const counts = Object.fromEntries(departments.map(d => [d, 0]));
    liveReports.forEach(r => { const d = deptOf(r); if (counts[d] !== undefined) counts[d] += 1; });
    select.innerHTML =
      `<option value="all">All departments (${liveReports.length})</option>` +
      departments.map(d => `<option value="${esc(d)}">${esc(d)} (${counts[d]})</option>`).join("");
    select.value = departments.includes(previous) || previous === "all" ? previous : "all";
  }

  async function loadInsights() {
    const x = await api("/api/public/authority/live-insights");
    liveReports = x.reports || [];
    liveReports.forEach(r => r.priority_score = priorityScore(r));
    refreshDepartmentOptions();
    renderPriority();
    renderMap();
    populateComplaintFieldSelector();
    renderKpis(x);
    if ($("#t-analytics")?.classList.contains("on")) renderAnalytics(x);
    return x;
  }
  function renderKpis(x) {
    const historical = x.historical || {};
    const k = $("#kpis");
    if (k) k.innerHTML = [
      [fmt(historical.records), "historical grievances"],
      [fmt(historical.wards), "wards"],
      [fmt(historical.categories), "categories"],
      [fmt(x.live_total), "citizen reports"]
    ].map(([v,l])=>`<div class="kpi"><b>${v}</b><span>${l}</span></div>`).join("");
  }
  function renderPriority() {
    const host = $("#priorityList"); if (!host) return;
    const q = ($("#assetSearch")?.value || "").toLowerCase();
    const dept = $("#deptFilter")?.value || "all";
    const filtered = liveReports.filter(r =>
      (activePriority === "all" || (r.severity || "Medium") === activePriority) &&
      (dept === "all" || deptOf(r) === dept) &&
      (!q || [r.report_id,r.category,r.description,r.ward_name,r.landmark,r.status,r.citizen_email].join(" ").toLowerCase().includes(q))
    ).sort((a,b)=>b.priority_score-a.priority_score);
    const counts = ["Critical","High","Medium","Low"].map(s=>[s,liveReports.filter(r=>(r.severity||"Medium")===s).length]);
    host.innerHTML = `
      <div class="live-priority-summary">
        ${counts.map(([s,n])=>`<button class="priority-tile ${activePriority===s?'selected':''}" data-priority="${s}" style="--pcolor:${priorityColor(s)}"><b>${n}</b><span>${s}</span></button>`).join("")}
        <button class="priority-tile ${activePriority==='all'?'selected':''}" data-priority="all"><b>${liveReports.length}</b><span>All reports</span></button>
      </div>
      <p class="live-subtitle">Priority is ranked using citizen severity, complaint age and similar-report recurrence. Scores are triage aids, not automated safety assessments.</p>
      ${filtered.length ? filtered.map(r=>`
        <article class="live-complaint ${r.severity==='Critical'?'critical':''}">
          <div class="live-complaint-top"><b>${esc(r.report_id)}</b><span class="live-severity" style="background:${priorityColor(r.severity||"Medium")}">${esc(r.severity||"Medium")}</span></div>
          <b>${esc(r.category)}</b><p>${esc(r.description)}</p>
          <small>${esc(r.ward_name)}${r.landmark?' · '+esc(r.landmark):''}</small>
          <div class="live-meta"><span>${esc(r.status)}</span><span>${esc(deptOf(r))}</span><span>Priority score ${r.priority_score}/100</span></div>
          <div class="live-report-actions">
            <button class="ghost" data-focus-map="${esc(r.report_id)}">Show on map</button>
            <button class="primary live-open" data-open-complaint="${esc(r.report_id)}">View complaint history & matches</button>
          </div>
        </article>`).join("") : `<p class="hint">${liveReports.length ? "No complaints match these filters." : "No citizen complaints are registered yet. Submit a complaint through the Citizen Portal to populate this dashboard."}</p>`}
      <h3>Recurring complaint patterns</h3><div id="liveClusters"><p class="hint">Select a complaint to calculate its similarity and recurrence matches.</p></div>`;
    host.querySelectorAll("[data-priority]").forEach(b=>b.onclick=()=>{activePriority=b.dataset.priority;renderPriority();});
    host.querySelectorAll("[data-open-complaint]").forEach(b=>b.onclick=()=>openComplaint(b.dataset.openComplaint));
    host.querySelectorAll("[data-focus-map]").forEach(b=>b.onclick=()=>focusComplaintOnMap(b.dataset.focusMap));
    const search=$("#complaintSearch"); if(search) search.oninput=()=>renderCitizenReports();
  }
  async function openComplaint(id) {
    const r = liveReports.find(x=>x.report_id===id); if (!r) return;
    selectedReport = r;
    const pane=$("#t-asset"); if (!pane) return;
    pane.innerHTML=`<h2>${esc(r.report_id)} · ${esc(r.category)}</h2>
      <div class="live-detail-grid">
        <div><span>Ward</span><b>${esc(r.ward_name)}</b></div>
        <div><span>Severity</span><b>${esc(r.severity||"Medium")}</b></div>
        <div><span>Status</span><b>${esc(r.status)}</b></div>
        <div><span>Department</span><b>${esc(deptOf(r))}</b></div>
        <div><span>Submitted</span><b>${dateFmt(r.created_at)}</b></div>
        <div><span>Priority score</span><b>${r.priority_score}/100</b></div>
      </div>
      <h3>Citizen description</h3><p>${esc(r.description)}</p>
      <p class="hint">${r.landmark?'Landmark: '+esc(r.landmark):'No landmark provided.'} · ${r.latitude!=null && r.longitude!=null ? `GPS: ${Number(r.latitude).toFixed(5)}, ${Number(r.longitude).toFixed(5)}` : "No GPS coordinates shared by citizen."}</p>
      ${r.photo_filename?`<img class="live-evidence" src="/api/public/uploads/${encodeURIComponent(r.photo_filename)}" alt="Citizen evidence photograph">`:""}
      <h3>Similarity matches & recurrence</h3><div id="liveMatchResults"><p class="hint">Checking related citizen complaints and historical ward records…</p></div>
      <h3>Field inspection and repair history</h3><div id="complaintDetailFieldHistory"><p class="hint">Loading recorded field activity…</p></div>
      <button class="ghost" id="openFieldRecordTab">Add field activity</button>
      <button class="ghost" id="backToPriority">← Back to Priority</button>`;
    document.querySelectorAll(".tabs button").forEach(b=>b.classList.toggle("on",b.dataset.tab==="asset"));
    document.querySelectorAll(".pane").forEach(p=>p.classList.toggle("on",p.id==="t-asset"));
    $("#backToPriority").onclick=()=>{document.querySelector('[data-tab="priority"]').click();};
    $("#openFieldRecordTab").onclick=()=>{document.querySelector('[data-tab="records"]').click();const s=$("#fieldComplaintSelect");if(s){s.value=id;s.dispatchEvent(new Event("change"));}};
    loadComplaintDetailFieldHistory(id);
    try {
      const m=await api(`/api/public/reports/${encodeURIComponent(id)}/matches`);
      const matches=m.matches||[];
      $("#liveMatchResults").innerHTML=`
        <div class="live-recurrence-banner"><b>${m.recurrence_count}</b><span>related citizen complaint(s), including this report</span><b>${fmt(m.historical_ward_category_count)}</b><span>historical ward/category records</span></div>
        ${matches.length?matches.map(x=>`<div class="live-match"><div><b>${esc(x.report_id)}</b><span class="match-percent">${x.similarity_percent}% similarity</span></div><p>${esc(x.description)}</p><small>${esc(x.ward_name)} · ${esc(x.status)} · ${dateFmt(x.created_at)}</small></div>`).join(""):"<p class='hint'>No sufficiently similar citizen complaint was found in the same ward and category yet.</p>"}
        <h4>Historical ward/category records</h4>
        ${(m.historical_records||[]).length?m.historical_records.map(x=>`<div class="live-match"><b>${esc(x.complaint_id||"Historical record")} · ${esc(x.category||"")}</b><p>${esc(x.sub_category||"")}</p><small>${esc(x.grievance_date_raw||"Date unavailable")} · ${esc(x.grievance_status||"")}</small></div>`).join(""):"<p class='hint'>No mapped historical category records were found for this ward/category.</p>"}
        <p class="hint">${esc(m.interpretation)}</p>`;
    } catch(e) { $("#liveMatchResults").textContent=e.message; }
  }
  function renderCitizenReports() {
    const host=$("#citizenComplaintList"); if(!host)return;
    const q=($("#complaintSearch")?.value||"").toLowerCase();
    const rows=liveReports.filter(r=>!q||[r.report_id,r.category,r.description,r.ward_name,r.landmark,r.status].join(" ").toLowerCase().includes(q));
    host.innerHTML=rows.length?rows.map(r=>`
      <article class="live-complaint">
        <div class="live-complaint-top"><b>${esc(r.report_id)} · ${esc(r.category)}</b><span class="live-severity" style="background:${priorityColor(r.severity||"Medium")}">${esc(r.severity||"Medium")}</span></div>
        <small>${esc(r.ward_name)} · ${dateFmt(r.created_at)}</small><p>${esc(r.description)}</p>
        <small>Citizen: ${esc(r.citizen_email||"Account holder")} · Status: <b>${esc(r.status)}</b></small>
        ${r.rejection_reason?`<p class="warning-text">Rejection reason: ${esc(r.rejection_reason)}</p>`:""}
        <label>Update status<select data-status="${esc(r.report_id)}">${["Acknowledged","Assigned","Inspection Scheduled","In Progress","Resolved","Verified","Rejected"].map(s=>`<option ${r.status===s?"selected":""}>${s}</option>`).join("")}</select></label>
        <label>Update note / rejection reason<textarea data-note="${esc(r.report_id)}" rows="2" placeholder="Progress details; required for rejection"></textarea></label>
        <button class="primary" data-save-live-status="${esc(r.report_id)}">Save status update</button>
        <div id="live-status-msg-${esc(r.report_id)}" class="hint"></div>
      </article>`).join(""):"<p class='hint'>No citizen complaints match this search.</p>";
    host.querySelectorAll("[data-save-live-status]").forEach(b=>b.onclick=async()=>{
      const id=b.dataset.saveLiveStatus, status=host.querySelector(`[data-status="${id}"]`).value;
      const reason=host.querySelector(`[data-note="${id}"]`).value;
      const msg=$("#live-status-msg-"+CSS.escape(id));
      try {
        await api(`/api/public/reports/${encodeURIComponent(id)}/status`,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({status,reason})});
        msg.textContent="Status updated successfully. Priority, map and analytics refreshed.";
        await loadInsights(); renderCitizenReports();
        const refreshedMsg = $("#live-status-msg-"+CSS.escape(id));
        if (refreshedMsg) refreshedMsg.textContent = "Status updated successfully. Priority, map and analytics refreshed.";
      } catch(e) { msg.textContent=e.message; }
    });
    host.querySelectorAll("[data-open-history]").forEach(b=>b.onclick=()=>openComplaint(b.dataset.openHistory));
    host.querySelectorAll("[data-focus-map]").forEach(b=>b.onclick=()=>focusComplaintOnMap(b.dataset.focusMap));
  }
  function focusComplaintOnMap(id) {
    const report = liveReports.find(r => r.report_id === id);
    if (!report) return;
    if (report.latitude == null || report.longitude == null ||
        !Number.isFinite(Number(report.latitude)) || !Number.isFinite(Number(report.longitude))) {
      alert(`${report.report_id} has no GPS coordinates. Ward: ${report.ward_name}${report.landmark ? " · Landmark: " + report.landmark : ""}. The map cannot place an exact pin until the citizen shares GPS.`);
      return;
    }
    if (typeof map === "undefined") return;
    map.flyTo([Number(report.latitude), Number(report.longitude)], 17, {duration: 0.8});
    const marker = citizenMarkers.get(id);
    if (marker) window.setTimeout(() => marker.openPopup(), 850);
  }
  function renderMap() {
    if (!window.L || typeof map === "undefined") return;
    if (!citizenPinLayer) {
      citizenPinLayer = window.cityMemoryCitizenLayer || L.layerGroup().addTo(map);
      window.cityMemoryCitizenLayer = citizenPinLayer;
    }
    citizenPinLayer.clearLayers();
    citizenMarkers = new Map();

    const plotted = liveReports.filter(r =>
      r.latitude != null && r.longitude != null &&
      Number.isFinite(Number(r.latitude)) && Number.isFinite(Number(r.longitude))
    );

    plotted.forEach(r => {
      const resolved = ["Resolved", "Verified"].includes(r.status);
      const color = resolved ? "#27815c" :
        r.severity === "Critical" ? "#c83232" :
        r.severity === "High" ? "#d97706" :
        r.severity === "Low" ? "#64748b" : "#2878b8";

      const marker = L.circleMarker(
        [Number(r.latitude), Number(r.longitude)],
        {radius: 10, color: "#fff", weight: 2, fillColor: color, fillOpacity: .95}
      ).addTo(citizenPinLayer);

      marker.bindPopup(
        `<b>${esc(r.report_id)}</b><br>${esc(r.category)}<br>` +
        `${esc(r.severity || "Medium")} · ${esc(r.status)}<br>` +
        `${esc(r.ward_name)}${r.landmark ? " · " + esc(r.landmark) : ""}<br>` +
        `${esc(r.description)}`
      );
      marker.on("click", () => { selectedReport = r; });
      citizenMarkers.set(r.report_id, marker);
    });

    const legend = document.querySelector(".map-legend");
    if (legend) {
      legend.innerHTML =
        `<span><i class="dot blue"></i>Citizen GPS (${plotted.length})</span>` +
        `<span><i class="dot red"></i>Critical</span>` +
        `<span><i class="dot orange"></i>High</span>` +
        `<span><i class="dot green"></i>Resolved / verified</span>` +
        `<span>Historical CSV: ward-level only</span>`;
    }
  }
  function renderAnalytics(x) {
    const host=$("#historicalAnalytics"); if(!host)return;
    const h=x.historical||{}, sev=x.severity||{}, statuses=x.statuses||{}, depts=x.departments||{}, months=x.monthly||{};
    const bars=obj=>Object.entries(obj).sort((a,b)=>b[1]-a[1]).map(([k,v])=>`<div class="live-analytics-row"><span>${esc(k)}</span><i><b style="width:${Math.max(2,100*v/Math.max(1,...Object.values(obj))) }%"></b></i><strong>${fmt(v)}</strong></div>`).join("")||"<p class='hint'>No records yet.</p>";
    host.innerHTML=`
      <h3>Live citizen complaint analytics</h3>
      <div class="live-analytics-kpis">
        <div><b>${fmt(x.live_total)}</b><span>Total citizen complaints</span></div>
        <div><b>${fmt(x.unresolved)}</b><span>Pending / active</span></div>
        <div><b>${fmt(x.gps_count)}</b><span>GPS locations shared</span></div>
        <div><b>${x.average_resolution_days==null?"—":x.average_resolution_days+" days"}</b><span>Average time to resolved/verified</span></div>
      </div>
      <h4>Priority-wise complaints</h4>${bars(sev)}
      <h4>Status-wise complaints</h4>${bars(statuses)}
      <h4>Department-wise complaints</h4>${bars(depts)}
      <h4>Monthly citizen complaint trend</h4>${bars(months)}
      <hr><h3>Historical CSV analytics</h3>
      <div class="live-analytics-kpis"><div><b>${fmt(h.records)}</b><span>Historical grievances</span></div><div><b>${fmt(h.wards)}</b><span>Wards</span></div><div><b>${fmt(h.categories)}</b><span>Historical categories</span></div></div>
      <h4>Recurring historical ward/category patterns</h4>
      ${(h.recurrence_patterns||[]).slice(0,15).map(v=>`<div class="live-match"><b>${esc(v.ward_name)} · ${esc(v.category)}</b><p>${esc(v.sub_category||"")} · ${fmt(v.incident_count)} records</p></div>`).join("")||"<p class='hint'>No historical recurrence patterns available.</p>"}
      <p class="hint">Live metrics come from citizen-submitted reports. Historical metrics come from the supplied CSV. The historical dataset has ward-level geography only; it is not assigned fabricated GPS coordinates.</p>`;
  }

  function populateComplaintFieldSelector() {
    const select = $("#fieldComplaintSelect");
    if (!select) return;
    const previous = select.value;
    select.innerHTML = '<option value="">Choose a citizen complaint</option>' +
      liveReports.map(r =>
        `<option value="${esc(r.report_id)}">${esc(r.report_id)} · ${esc(r.category)} — ${esc(r.ward_name)}${r.landmark ? " · " + esc(r.landmark) : ""}</option>`
      ).join("");
    if (liveReports.some(r => r.report_id === previous)) select.value = previous;
    if (!select.dataset.bound) {
      select.addEventListener("change", () => loadComplaintFieldHistory(select.value));
      select.dataset.bound = "1";
    }
  }

  async function loadComplaintFieldHistory(reportId) {
    const host = $("#fieldComplaintHistory");
    if (!host || !reportId) {
      if (host) host.innerHTML = '<p class="hint">Select a complaint to view its inspection and repair history.</p>';
      return;
    }
    host.innerHTML = '<p class="hint">Loading field activity…</p>';
    try {
      const result = await api(`/api/public/reports/${encodeURIComponent(reportId)}/field-records`);
      host.innerHTML = result.records.length
        ? `<h4>Previous field activity (${result.records.length})</h4>` +
          result.records.map(record => `
            <article class="live-match">
              <div><b>${esc(record.record_id)} · ${esc(record.record_type)}</b><small>${dateFmt(record.created_at)}</small></div>
              <p>${esc(record.findings)}</p>
              <small>${esc(record.department)} · ${esc(record.condition || "Condition not recorded")} · ₹${fmt(record.cost)}</small>
              <small>Recorded by ${esc(record.created_by)}</small>
              ${record.photo_filename ? `<img class="live-evidence" src="/api/public/uploads/${encodeURIComponent(record.photo_filename)}" alt="Field evidence">` : ""}
            </article>
          `).join("")
        : '<p class="hint">No inspection or repair activity has been recorded for this complaint yet.</p>';
    } catch (error) {
      host.textContent = error.message;
    }
  }

  async function saveComplaintFieldActivity() {
    const reportId = $("#fieldComplaintSelect")?.value;
    const message = $("#complaintFieldMsg");
    if (!reportId) {
      if (message) message.textContent = "Select a citizen complaint first.";
      return;
    }

    // Reuse the existing field activity inputs; the original asset Save button is untouched.
    const findings = $("#recordText")?.value.trim() || "";
    if (findings.length < 5) {
      if (message) message.textContent = "Enter at least 5 characters in Findings / action.";
      return;
    }

    const form = new FormData();
    form.append("record_type", $("#recordType").value);
    form.append("department", $("#recordDept").value);
    form.append("findings", findings);
    form.append("cost", $("#recordCost").value || "0");
    form.append("condition", $("#recordCondition").value);

    const photo = $("#recordPhoto")?.files?.[0];
    if (photo) form.append("photo", photo);

    const button = $("#saveComplaintFieldRecord");
    if (button) {
      button.disabled = true;
      button.textContent = "Saving…";
    }
    if (message) message.textContent = "";

    try {
      const result = await api(
        `/api/public/reports/${encodeURIComponent(reportId)}/field-records`,
        {method: "POST", body: form}
      );

      if (message) {
        message.textContent = `Field activity saved. Record ID: ${result.record_id}. Complaint status: ${result.status}.`;
      }

      $("#recordText").value = "";
      $("#recordPhoto").value = "";
      $("#recordCost").value = "0";

      await loadComplaintFieldHistory(reportId);
      await refreshAll();

    } catch (error) {
      if (message) message.textContent = error.message;
    } finally {
      if (button) {
        button.disabled = false;
        button.textContent = "Save activity against selected complaint";
      }
    }
  }

  async function loadComplaintDetailFieldHistory(reportId) {
    const host = $("#complaintDetailFieldHistory");
    if (!host) return;
    try {
      const result = await api(`/api/public/reports/${encodeURIComponent(reportId)}/field-records`);
      host.innerHTML = result.records.length
        ? result.records.map(record => `
            <div class="live-match">
              <b>${esc(record.record_id)} · ${esc(record.record_type)}</b>
              <p>${esc(record.findings)}</p>
              <small>${esc(record.department)} · ${dateFmt(record.created_at)}</small>
            </div>
          `).join("")
        : '<p class="hint">No field activity has been recorded for this complaint yet.</p>';
    } catch (error) {
      host.textContent = error.message;
    }
  }

  async function refreshAll() {
    try { const x=await loadInsights(); renderCitizenReports(); if($("#t-analytics")?.classList.contains("on"))renderAnalytics(x); }
    catch(e) { const host=$("#priorityList"); if(host)host.innerHTML=`<p class="warning-text">${esc(e.message)}</p>`; }
  }
  // Department options are static role categories; they do not depend on synthetic assets.
  const deptSelect = $("#deptFilter");
  if (deptSelect) {
    const current = deptSelect.value || "all";
    deptSelect.innerHTML = '<option value="all">All departments</option>' +
      ["Roads","Storm Water Drainage","Electrical","Footpaths","Public Health"].map(d=>`<option value="${esc(d)}">${esc(d)}</option>`).join("");
    deptSelect.value = current;
  }
  const complaintFieldSaveButton = $("#saveComplaintFieldRecord");
  if (complaintFieldSaveButton && !complaintFieldSaveButton.dataset.bound) {
    complaintFieldSaveButton.addEventListener("click", saveComplaintFieldActivity);
    complaintFieldSaveButton.dataset.bound = "1";
  }
  // Replace old asset-based renderers and keep the existing navigation and authentication.
  window.loadCitizenComplaints = renderCitizenReports;
  window.loadHistoricalAnalytics = async()=>{try{renderAnalytics(await api("/api/public/authority/live-insights"));}catch(e){const h=$("#historicalAnalytics");if(h)h.textContent=e.message;}};
  window.priority = renderPriority;
  document.querySelectorAll(".tabs button").forEach(b=>b.addEventListener("click",()=>{
    if(b.dataset.tab==="priority")renderPriority();
    if(b.dataset.tab==="community")renderCitizenReports();
    if(b.dataset.tab==="records")populateComplaintFieldSelector();
    if(b.dataset.tab==="analytics")window.loadHistoricalAnalytics();
  }));
  $("#assetSearch")?.addEventListener("input",renderPriority);
  $("#deptFilter")?.addEventListener("change",renderPriority);
  // Ensure new live reports/status changes are reflected without a manual reload.
  refreshAll();
  window.setInterval(()=>{ if(document.visibilityState==="visible") refreshAll(); },15000);
  window.CityMemoryLive = {
    refresh: refreshAll,
    openComplaint,
    focusComplaintOnMap,
    loadFieldHistory: loadComplaintFieldHistory
  };
})();

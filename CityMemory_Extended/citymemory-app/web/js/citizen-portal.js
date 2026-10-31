
(() => {
  "use strict";

  const $ = id => document.getElementById(id);

  const esc = value =>
    String(value ?? "").replace(/[&<>"']/g, c => ({
      "&": "&amp;",
      "<": "&lt;",
      ">": "&gt;",
      '"': "&quot;",
      "'": "&#39;"
    }[c]));

  const fmt = value =>
    value
      ? new Date(value).toLocaleDateString("en-IN", {
          day: "2-digit",
          month: "short",
          year: "numeric"
        })
      : "Date unavailable";

  let map, markerLayer, citizenEmail = "";

  // API REQUEST
  async function api(path, options = {}) {
    const response = await fetch("/api/public" + path, {
      credentials: "include",
      cache: "no-store",
      ...options
    });

    const body = await response.json().catch(() => ({}));

    if (!response.ok) {
      throw new Error(body.error || "Request failed");
    }

    return body;
  }

  // INITIALIZE MAP
  function initMap() {
    if (!window.L) {
      $("reportMap").innerHTML =
        "Map library could not be loaded.";
      return;
    }

    map = L.map("reportMap").setView(
      [12.9716, 77.5946],
      10
    );

    L.tileLayer(
      "https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png",
      {
        maxZoom: 19,
        attribution: "© OpenStreetMap"
      }
    ).addTo(map);

    markerLayer = L.layerGroup().addTo(map);
  }

  // LOAD DASHBOARD SUMMARY
  async function loadSummary() {
    const x = await api("/summary");

    $("mHistorical").textContent =
      Number(x.historical_records || 0).toLocaleString("en-IN");

    $("mWards").textContent =
      Number(x.wards || 0).toLocaleString("en-IN");

    $("mCategories").textContent =
      Number(x.categories || 0).toLocaleString("en-IN");

    $("mReports").textContent =
      Number(x.public_reports || 0).toLocaleString("en-IN");
  }

  // LOAD WARDS
  async function loadWards() {
    const x = await api("/wards");

    const opts = x.wards.map(w =>
      `<option value="${esc(w.ward_name)}">
        ${esc(w.ward_name)} (${Number(w.records).toLocaleString("en-IN")})
      </option>`
    ).join("");

    $("wardSelect").innerHTML =
      '<option value="">Choose a ward</option>' + opts;

    $("reportWard").innerHTML =
      '<option value="">Select ward</option>' + opts;
  }

  // LOAD HISTORICAL RECORDS
  async function loadHistory() {
    const ward = $("wardSelect").value;

    if (!ward) {
      $("historyList").innerHTML =
        '<p class="muted">Choose a ward first.</p>';
      return;
    }

    const category = $("categorySelect").value;

    $("historyList").innerHTML =
      '<p class="muted">Loading records…</p>';

    const x = await api(
      "/history?ward=" + encodeURIComponent(ward) +
      "&category=" + encodeURIComponent(category)
    );

    $("historyCount").textContent =
      Number(x.total_matches || 0).toLocaleString("en-IN") +
      " matching records";

    $("historyList").innerHTML = x.records.length
      ? x.records.map(r => `
          <article class="history-row">
            <div>
              <b>
                ${esc(r.sub_category)} · ${esc(r.category)}
              </b>

              <small>
                ${esc(r.complaint_id)} ·
                ${esc(r.zone_name || "Zone not provided")} ·
                ${esc(r.grievance_date_raw)}
              </small>

              ${r.staff_remarks
                ? `<small>Latest available remark: ${esc(r.staff_remarks)}</small>`
                : ""}
            </div>

            <span class="status">
              ${esc(r.grievance_status)}
            </span>
          </article>
        `).join("")
      : '<p class="muted">No matching records found for this ward and category.</p>';

    // LOAD RECURRENCE PATTERNS
    const rec = await api(
      "/recurrence?ward=" + encodeURIComponent(ward)
    );

    $("recurrenceList").innerHTML = rec.patterns.length
      ? rec.patterns.slice(0, 12).map(p => `
          <article class="pattern">
            <b>${esc(p.category)}</b>
            <small>${esc(p.sub_category)}</small>
            <strong>
              ${Number(p.incident_count).toLocaleString("en-IN")}
            </strong>
            <small>records in ${esc(p.ward_name)}</small>
          </article>
        `).join("")
      : '<p class="muted">No repeated ward/category pattern found.</p>';
  }

  // LOAD CITIZEN COMPLAINTS
  async function loadMyReports() {
    const x = await api("/reports");

    $("publicReports").innerHTML = x.reports.length
      ? x.reports.map(r => `
          <article class="report-card">

            <b>
              ${esc(r.category)} · ${esc(r.report_id)}
            </b>

            <p>${esc(r.description)}</p>

            <small>
              ${esc(r.ward_name)}
              ${r.landmark ? " · " + esc(r.landmark) : ""}
            </small>

            <br>

            <small>
              ${fmt(r.created_at)} ·
              <b>${esc(r.status)}</b>
            </small>

            ${r.rejection_reason
              ? `<p class="small-note">
                   Reason: ${esc(r.rejection_reason)}
                 </p>`
              : ""}

            <p>
              <button
                class="btn secondary"
                data-track="${esc(r.report_id)}">
                View status tracker
              </button>
            </p>

            <div id="tracker-${esc(r.report_id)}"></div>

          </article>
        `).join("")
      : '<p class="muted">You have not submitted any complaints yet.</p>';

    // STATUS TRACKER BUTTONS
    document.querySelectorAll("[data-track]").forEach(b => {
      b.addEventListener("click", () =>
        showTracker(b.dataset.track)
      );
    });

    // UPDATE MAP MARKERS
    if (markerLayer) {
      markerLayer.clearLayers();

      x.reports
        .filter(r =>
          r.latitude != null &&
          r.longitude != null &&
          Number.isFinite(Number(r.latitude)) &&
          Number.isFinite(Number(r.longitude))
        )
        .forEach(r => {
          L.marker([
            Number(r.latitude),
            Number(r.longitude)
          ])
            .addTo(markerLayer)
            .bindPopup(`
              <b>${esc(r.category)}</b><br>
              ${esc(r.report_id)}<br>
              ${esc(r.status)}
            `);
        });
    }
  }

  // SHOW COMPLAINT STATUS TRACKER
  async function showTracker(id) {
    const x = await api(
      "/reports/" + encodeURIComponent(id) + "/tracker"
    );

    const el = $("tracker-" + id);

    if (!el) return;

    el.innerHTML =
      '<ol>' +
      x.history.map(e => `
        <li>
          <b>${esc(e.status)}</b> · ${fmt(e.created_at)}
          <br>
          <small>${esc(e.note || "Status updated")}</small>
        </li>
      `).join("") +
      '</ol>';

    if (
      x.report.status === "Rejected" &&
      x.report.rejection_reason
    ) {
      el.innerHTML += `
        <p class="small-note">
          Rejection reason: ${esc(x.report.rejection_reason)}
        </p>
      `;
    }
  }

  // VERIFY CITIZEN SESSION
  async function signedIn(email) {
    const sessionState = await api("/auth/me");

    if (
      !sessionState.authenticated ||
      sessionState.email !== email
    ) {
      throw new Error(
        "Your account was created, but the login session was not retained. Please refresh the page and sign in again."
      );
    }

    citizenEmail = email;

    $("citizenSession").textContent = email;
    $("citizenGate").style.display = "none";
    $("reportMessage").textContent = "";

    await Promise.all([
      loadSummary(),
      loadMyReports()
    ]);
  }

  // CITIZEN LOGIN
  $("citizenLoginForm").addEventListener(
    "submit",
    async e => {
      e.preventDefault();

      const m = $("citizenAuthMessage");
      m.textContent = "Signing in…";

      try {
        const x = await api("/auth/login", {
          method: "POST",
          headers: {
            "Content-Type": "application/json"
          },
          body: JSON.stringify({
            email: $("citizenEmail").value,
            password: $("citizenPassword").value
          })
        });

        await signedIn(x.email);

      } catch (err) {
        m.textContent = err.message;
        console.error("Login error:", err);
      }
    }
  );

  // CITIZEN REGISTRATION
  $("citizenRegister").addEventListener(
    "click",
    async () => {
      const m = $("citizenAuthMessage");
      m.textContent = "Creating account…";

      try {
        const x = await api("/auth/register", {
          method: "POST",
          headers: {
            "Content-Type": "application/json"
          },
          body: JSON.stringify({
            email: $("citizenEmail").value,
            password: $("citizenPassword").value
          })
        });

        await signedIn(x.email);

      } catch (err) {
        m.textContent = err.message;
        console.error("Registration error:", err);
      }
    }
  );

  // GOOGLE SIGN IN
  $("googleSignIn").addEventListener("click", () => {
    $("citizenAuthMessage").textContent =
      "Google OAuth is not configured. Use email and password for this prototype.";
  });

  // CITIZEN LOGOUT
  $("citizenLogout").addEventListener(
    "click",
    async () => {
      try {
        await api("/auth/logout", {
          method: "POST"
        });

        citizenEmail = "";

        $("citizenGate").style.display = "grid";

        $("publicReports").innerHTML =
          "Sign in to view your complaints.";

      } catch (err) {
        console.error("Logout error:", err);
      }
    }
  );

  // GPS LOCATION SHARING
  $("getLocation").addEventListener("click", () => {
    if (!navigator.geolocation) {
      $("locationStatus").textContent =
        "Geolocation is not supported by this browser.";
      return;
    }

    $("locationStatus").textContent =
      "Requesting location permission…";

    navigator.geolocation.getCurrentPosition(
      pos => {
        $("latitude").value =
          pos.coords.latitude;

        $("longitude").value =
          pos.coords.longitude;

        $("locationStatus").textContent =
          "GPS location attached (you chose to share it).";
      },

      err => {
        $("locationStatus").textContent =
          "Location not shared: " + err.message;
      },

      {
        enableHighAccuracy: true,
        timeout: 10000
      }
    );
  });

  // LOAD HISTORICAL DATA
  $("loadHistory").addEventListener("click", () => {
    loadHistory().catch(e => {
      $("historyList").textContent = e.message;
    });
  });

  $("wardSelect").addEventListener("change", () => {
    if ($("wardSelect").value) {
      loadHistory().catch(e => {
        console.error("History loading error:", e);
      });
    }
  });

  // ==========================================
  // CITIZEN COMPLAINT SUBMISSION
  // ==========================================

  $("reportForm").addEventListener(
    "submit",
    async event => {

      event.preventDefault();

      // IMPORTANT FIX:
      // Save the form reference before the asynchronous request.
      const form = event.currentTarget;

      const button = $("submitReport");
      const message = $("reportMessage");

      button.disabled = true;
      button.textContent = "Submitting...";
      message.textContent = "";

      try {

        // IMPORTANT FIX:
        // Use the saved form reference.
        const response = await api("/reports", {
          method: "POST",
          body: new FormData(form)
        });

        // DISPLAY ACTUAL COMPLAINT ID
        if (!response.report_id) {
          throw new Error(
            "The server response did not contain a complaint ID."
          );
        }

        message.textContent =
          `Complaint registered successfully. Your complaint ID is ${response.report_id}. Status: Submitted.`;

        // IMPORTANT FIX:
        // Reset the saved form reference.
        form.reset();

        // CLEAR GPS FIELDS
        $("latitude").value = "";
        $("longitude").value = "";

        $("locationStatus").textContent =
          "No GPS location attached.";

        // REFRESH DASHBOARD
        await Promise.all([
          loadSummary(),
          loadMyReports()
        ]);

      } catch (e) {

        message.textContent =
          "Complaint submission failed: " + e.message;

        console.error(
          "Complaint submission error:",
          e
        );

      } finally {

        button.disabled = false;
        button.textContent = "Submit complaint";

      }
    }
  );

  // INITIALIZE MAP
  initMap();

  // INITIAL LOAD
  Promise.all([
    loadSummary(),
    loadWards()
  ]).catch(err => {

    console.error(err);

    $("historyList").innerHTML =
      '<p class="muted">Could not load data. Start the Flask server and import the historical dataset.</p>';

  });

  // RESTORE EXISTING CITIZEN SESSION
  api("/auth/me")
    .then(x => {
      if (x.authenticated) {
        signedIn(x.email).catch(err => {
          console.error("Session restoration error:", err);
        });
      } else {
        $("publicReports").textContent =
          "Sign in to view your complaints.";
      }
    })
    .catch(err => {
      console.error("Authentication check failed:", err);
    });

})();

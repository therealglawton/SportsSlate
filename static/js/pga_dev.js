const dateInput = document.getElementById("dateInput");
const limitInput = document.getElementById("limitInput");
const showNotStartedCheckbox = document.getElementById("showNotStarted");
const loadBtn = document.getElementById("loadBtn");
const clearBtn = document.getElementById("clearBtn");
const rowsEl = document.getElementById("rows");
const eventNameEl = document.getElementById("eventName");
const eventDetailEl = document.getElementById("eventDetail");
const roundSelectEl = document.getElementById("roundSelect");
const errorEl = document.getElementById("error");

function scoreClass(displayScore) {
  const text = String(displayScore || "").toUpperCase();
  if (text === "E") return "score-even";
  if (text.startsWith("+")) return "score-over";
  if (text.startsWith("-")) return "score-under";
  return "";
}

function formatStatus(event) {
  if (!event || !event.status) return "";
  const s = event.status;
  return [s.description, s.detail].filter(Boolean).join(" | ");
}

function formatDateRange(event) {
  const start = event?.start_date || "";
  const end = event?.end_date || "";
  if (!start && !end) return "";

  const startLabel = start ? new Date(start).toLocaleString() : "";
  const endLabel = end ? new Date(end).toLocaleString() : "";
  if (startLabel && endLabel) return `${startLabel} - ${endLabel}`;
  return startLabel || endLabel;
}

function populateRoundSelect(eventStatus) {
  if (!roundSelectEl) return;

  const state = String(eventStatus?.state || "").toLowerCase();
  const detail = String(eventStatus?.detail || "");
  const match = detail.match(/round\s+(\d+)/i);
  const parsedRound = match ? Number(match[1]) : null;

  let begunRound = 0;
  if (state === "pre") {
    begunRound = 0;
  } else if (state === "in") {
    begunRound = parsedRound || 1;
  } else if (state === "post") {
    begunRound = parsedRound || 4;
  }

  roundSelectEl.innerHTML = "";
  for (let r = 1; r <= 4; r += 1) {
    const option = document.createElement("option");
    option.value = String(r);

    if (r > begunRound) {
      option.disabled = true;
      option.textContent = `Round ${r} - Not Started`;
    } else if (state === "in" && r === begunRound) {
      option.textContent = detail || `Round ${r} - In Progress`;
    } else {
      option.textContent = `Round ${r} - Complete`;
    }

    roundSelectEl.appendChild(option);
  }

  const selected = begunRound > 0 ? Math.min(Math.max(begunRound, 1), 4) : 1;
  roundSelectEl.value = String(selected);
}

let currentLeaderboard = [];
let currentTournamentTimezone = "EDT";  // Default

function parseTeeTime(raw, tournamentTz = "EDT") {
  if (!raw || typeof raw !== 'string') return null;

  // ESPN format: Thu Apr 02 16:36:00 PDT 2026
  // Timezone offsets (minutes behind UTC, e.g., EDT is UTC-4 = 240 minutes behind)
  const tzOffsets = {
    PST: 480,   // UTC-8
    PDT: 420,   // UTC-7
    MST: 420,   // UTC-7
    MDT: 360,   // UTC-6
    CST: 360,   // UTC-6
    CDT: 300,   // UTC-5
    EST: 300,   // UTC-5
    EDT: 240,   // UTC-4
    HST: 600,   // UTC-10
    UTC: 0,
    GMT: 0,
  };

  const parts = raw.trim().split(/\s+/);
  if (parts.length >= 6) {
    const monthNames = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
    const month = monthNames.indexOf(parts[1]);
    const day = Number(parts[2]);
    const timeParts = parts[3].split(':').map((p) => Number(p));
    const year = Number(parts[5]);
    if (month >= 0 && !Number.isNaN(day) && timeParts.length === 3 && !Number.isNaN(year)) {
      // Use tournament timezone (passed from backend) instead of ESPN's label
      // Convert tournament's local time to UTC, then browser displays in user's local TZ
      const offsetMins = tzOffsets[tournamentTz] ?? 0;
      const utcMs = Date.UTC(year, month, day, timeParts[0], timeParts[1], timeParts[2]);
      const correctedMs = utcMs + offsetMins * 60000; // Add offset to convert from tournament TZ to UTC
      return new Date(correctedMs);
    }
  }

  return null;
}

function renderRows(leaderboard, selectedRound = 1) {
  rowsEl.innerHTML = "";
  if (!Array.isArray(leaderboard) || leaderboard.length === 0) {
    rowsEl.innerHTML = '<tr><td colspan="6">No data returned.</td></tr>';
    return;
  }

  const html = leaderboard.map((row) => {
    const pos = row.position == null ? "-" : row.position;
    const player = row.player?.name || "Unknown";
    const countryFlag = row.player?.country_flag || "";
    const holes = row.holes_completed == null ? "-" : row.holes_completed;
    const notStarted = holes === 0;
    let teeTime = "-";
    if (row.tee_time) {
      const parsed = parseTeeTime(row.tee_time, currentTournamentTimezone);
      if (parsed instanceof Date && !Number.isNaN(parsed.valueOf())) {
        teeTime = parsed.toLocaleTimeString([], {
          hour: "numeric",
          minute: "2-digit",
          hour12: true,
        });
      } else {
        const rawTimeMatch = row.tee_time.match(/(\d{1,2}):(\d{2})(?::\d{2})?/);
        if (rawTimeMatch) {
          const hour = Number(rawTimeMatch[1]);
          const minute = Number(rawTimeMatch[2]);
          if (!Number.isNaN(hour) && !Number.isNaN(minute)) {
            const h12 = ((hour + 11) % 12) + 1;
            const ampm = hour >= 12 ? "PM" : "AM";
            teeTime = `${h12}:${minute.toString().padStart(2, "0")} ${ampm}`;
          } else {
            teeTime = rawTimeMatch[0];
          }
        } else {
          teeTime = row.tee_time;
        }
      }
    }
    const toPar = notStarted ? teeTime : (row.score?.display || "-");
    const roundToPar = ((row.round_to_par || {})[selectedRound] != null)
      ? row.round_to_par[selectedRound]
      : "-";
    const flagHtml = countryFlag
      ? `<img class="player-flag" src="${countryFlag}" alt="Country flag" loading="lazy" decoding="async" />`
      : `<span class="player-flag player-flag-placeholder" aria-hidden="true"></span>`;

    return `
      <tr class="${notStarted ? "not-started" : ""}">
        <td data-label="Pos">${pos}</td>
        <td data-label="Player"><span class="player-cell">${flagHtml}<span class="player-name">${player}</span></span></td>
        <td data-label="To Par" class="${scoreClass(toPar)}">${toPar}</td>
        <td data-label="Thru">${holes}</td>
        <td data-label="Today" class="${scoreClass(roundToPar)}">${roundToPar}</td>
      </tr>
    `;
  }).join("");

  rowsEl.innerHTML = html;
}

async function loadLeaderboard() {
  if (errorEl) errorEl.textContent = "";
  if (loadBtn) {
    loadBtn.disabled = true;
    loadBtn.textContent = "Loading...";
  }

  try {
    const params = new URLSearchParams();
    const dateValue = dateInput?.value || "";
    let limitValue = Number(limitInput?.value || 0);

    if (dateValue) {
      params.set("date", dateValue.replaceAll("-", ""));
    }

    if (limitValue <= 0) {
      params.set("limit", "0");
    } else {
      limitValue = Math.max(1, Math.min(500, limitValue));
      params.set("limit", String(limitValue));
    }

    const url = `/pga/leaderboard?${params.toString()}`;
    const response = await fetch(url, { cache: "no-store" });
    if (!response.ok) {
      throw new Error(`Request failed (${response.status})`);
    }

    const data = await response.json();
    const event = data.event || {};
    const totalCount = data.total_count ?? data.count ?? 0;
    const shownCount = data.count ?? (data.leaderboard || []).length;

    // Capture tournament timezone for tee time conversion
    currentTournamentTimezone = event.tournament_timezone || "EDT";

    const showNotStarted = showNotStartedCheckbox ? showNotStartedCheckbox.checked : true;
    let leaderboard = data.leaderboard || [];

    const allNotStartedCount = leaderboard.filter((row) => (row.holes_completed === 0)).length;

    if (!showNotStarted) {
      leaderboard = leaderboard.filter((row) => row.holes_completed > 0);
    }

    if (eventNameEl) eventNameEl.textContent = event.name || "No tournament found";
    const eventStatus = event.status || {};
    const fieldText = `Field: ${totalCount} players`;
    if (eventDetailEl) {
      eventDetailEl.textContent = fieldText;
      eventDetailEl.title = fieldText;
    }

    populateRoundSelect(eventStatus);

    currentLeaderboard = leaderboard;
    const selectedRound = Number(roundSelectEl?.value || 1);
    renderRows(currentLeaderboard, selectedRound);
  } catch (error) {
    if (errorEl) errorEl.textContent = String(error?.message || error || "Unable to load leaderboard");
    if (rowsEl) rowsEl.innerHTML = "";
  } finally {
    if (loadBtn) {
      loadBtn.disabled = false;
      loadBtn.textContent = "Load leaderboard";
    }
  }
}

if (loadBtn) {
  loadBtn.addEventListener("click", loadLeaderboard);
  // Auto-load on dev page only (when there's a load button)
  loadLeaderboard();
}

if (roundSelectEl) {
  roundSelectEl.addEventListener("change", () => {
    const selectedRound = Number(roundSelectEl.value || 1);
    renderRows(currentLeaderboard, selectedRound);
  });
}

if (clearBtn) {
  clearBtn.addEventListener("click", () => {
    if (dateInput) dateInput.value = "";
    loadLeaderboard();
  });
}

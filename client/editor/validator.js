/**
 * validator.js — POSTs mission JSON to /editor/validate, renders error list.
 */

/**
 * Run server-side validation on a mission dict.
 * Renders results into #validation-panel / #validation-results.
 * @param {object} missionJson
 * @returns {Promise<boolean>} true if valid
 */
export async function runValidation(missionJson) {
  const panel = document.getElementById("validation-panel");
  const results = document.getElementById("validation-results");

  panel.classList.remove("hidden");
  results.innerHTML = `<div style="color:#4a7a9b;font-size:11px;">Validating…</div>`;

  try {
    const r = await fetch("/editor/validate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(missionJson),
    });

    if (!r.ok) {
      results.innerHTML = `<div class="error">⚠ Server error: ${r.status}</div>`;
      return false;
    }

    const { valid, errors } = await r.json();

    if (errors.length === 0) {
      results.innerHTML = `<div class="valid-ok">✓ Mission is valid</div>`;
    } else {
      results.innerHTML = errors
        .map(e => `<div class="error">⚠ ${_esc(e)}</div>`)
        .join("");
    }

    return valid;
  } catch (err) {
    results.innerHTML = `<div class="error">⚠ Network error: ${_esc(String(err))}</div>`;
    return false;
  }
}

function _esc(str) {
  return str.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

// Confirm dialogs for dangerous forms (data-confirm) and small helpers. No external requests.
document.addEventListener("submit", (e) => {
  const f = e.target.closest("form[data-confirm]");
  if (f && !confirm(f.dataset.confirm)) { e.preventDefault(); e.stopPropagation(); }
}, true);
document.addEventListener("htmx:confirm", (e) => {
  const f = e.target.closest("form[data-confirm]");
  if (f && !confirm(f.dataset.confirm)) e.preventDefault();
});
function addQuestion() {
  const tr = document.createElement("tr");
  tr.innerHTML = '<td><input name="q_key" size="10"></td><td><input name="q_text" class="wide"></td>' +
    '<td><input name="q_weight" type="number" step="0.05" min="-1" max="1" value="0.5"></td>' +
    '<td><button type="button" onclick="this.closest(\'tr\').remove()">✗</button></td>';
  document.getElementById("qs").appendChild(tr);
}
// keep <details> of the jobs log open/closed across htmx polling swaps
document.addEventListener("htmx:beforeSwap", (e) => {
  if (e.target.id !== "panel") return;
  window._openLogs = [...e.target.querySelectorAll(".job details")].map(d => d.open);
  window._scrolls = [...e.target.querySelectorAll(".job pre")].map(p => [p.scrollTop, p.scrollHeight - p.scrollTop - p.clientHeight < 5]);
});
document.addEventListener("htmx:afterSwap", (e) => {
  if (e.target.id !== "panel" || !window._openLogs) return;
  e.target.querySelectorAll(".job details").forEach((d, i) => { if (i < window._openLogs.length) d.open = window._openLogs[i]; });
  e.target.querySelectorAll(".job pre").forEach((p, i) => {
    const s = (window._scrolls || [])[i];
    p.scrollTop = !s || s[1] ? p.scrollHeight : s[0];
  });
});

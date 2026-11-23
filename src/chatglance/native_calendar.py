"""Small, data-free decoration for Glance's native month-switching calendar."""

# This script is shared with guests, but marker data only exists in authenticated
# home columns. Keep the document head limited to this exact reviewed constant.
CALENDAR_HEAD = """<script>
(() => {
  const months = ['January', 'February', 'March', 'April', 'May', 'June',
                  'July', 'August', 'September', 'October', 'November', 'December'];
  let scheduled = false;
  function paint() {
    scheduled = false;
    const source = document.querySelector('.codex-reset-markers');
    const calendar = document.querySelector('.codex-reset-native-calendar .calendar');
    if (!source || !calendar) return;
    const heading = calendar.querySelector('.size-h2');
    const match = heading && heading.textContent.trim().match(/^([A-Za-z]+)\\s+(\\d{4})/);
    const month = match && months.indexOf(match[1]);
    if (month === null || month < 0) return;
    const cells = [...calendar.querySelectorAll('.calendar-date')];
    if (cells.length !== 42) return;
    let markers;
    try { markers = JSON.parse(source.dataset.days || '{}'); }
    catch (_) { return; }
    cells.forEach(cell => {
      const day = Number(cell.textContent.trim());
      const date = new Date(Number(match[2]), month, day);
      const key = `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}`;
      const entry = cell.classList.contains('calendar-spillover-date') ? {} : markers[key] || {};
      const confirmed = Array.isArray(entry.official) ? entry.official : [];
      const forecast = Array.isArray(entry.forecast) ? entry.forecast : [];
      cell.classList.toggle('codex-reset-confirmed', confirmed.length > 0);
      cell.classList.toggle('codex-reset-forecast', !confirmed.length && forecast.length > 0);
      if (confirmed.length || forecast.length) {
        cell.title = [...confirmed.map(label => `官方记录：${label}`),
                      ...forecast.map(label => `预计自然重置（非官方确认）：${label}`)].join('；');
      } else cell.removeAttribute('title');
    });
  }
  function schedule() {
    if (scheduled) return;
    scheduled = true;
    requestAnimationFrame(paint);
  }
  function boot() {
    const observer = new MutationObserver(records => {
      if (records.some(record => record.target.closest?.('.codex-reset-native-calendar') ||
          [...record.addedNodes].some(node => node.nodeType === 1 &&
            (node.matches?.('.codex-reset-native-calendar, .codex-reset-markers') ||
             node.querySelector?.('.codex-reset-native-calendar, .codex-reset-markers'))))) schedule();
    });
    observer.observe(document.body, {childList: true, characterData: true, subtree: true});
    schedule();
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot, {once: true});
  else boot();
})();
</script>"""

CALENDAR_STYLES = """<style>
.codex-reset-markers { display:none; }
.codex-reset-legend { color:var(--color-text-subdue); font-size:0.7rem;
  line-height:1.4; margin:-0.4rem 0 0.6rem; }
.codex-reset-native-calendar .calendar-date.codex-reset-confirmed {
  outline:2px solid var(--color-primary); outline-offset:-3px; border-radius:8px;
}
.codex-reset-native-calendar .calendar-date.codex-reset-forecast {
  outline:2px dashed var(--color-primary); outline-offset:-3px; border-radius:8px;
}
</style>"""

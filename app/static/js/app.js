(function () {
  'use strict';

  /* ── Dark Mode ── */
  (function () {
    var stored = localStorage.getItem('theme');
    var prefersDark = window.matchMedia('(prefers-color-scheme: dark)').matches;
    var theme = stored || (prefersDark ? 'dark' : 'light');
    document.documentElement.setAttribute('data-theme', theme);
    var btn = document.getElementById('theme-toggle');
    if (btn) {
      btn.setAttribute('aria-pressed', theme === 'dark' ? 'true' : 'false');
      btn.addEventListener('click', function () {
        var current = document.documentElement.getAttribute('data-theme');
        var next = current === 'dark' ? 'light' : 'dark';
        document.documentElement.setAttribute('data-theme', next);
        localStorage.setItem('theme', next);
        btn.setAttribute('aria-pressed', next === 'dark' ? 'true' : 'false');
        if (window._renderDashboardCharts) window._renderDashboardCharts();
      });
    }
  })();

  /* ── Modal ── */
  var modalOverlay = document.getElementById('modal-overlay');
  var modalTitle = document.getElementById('modal-title');
  var modalBody = document.getElementById('modal-body');
  var modalCancel = document.getElementById('modal-cancel');
  var modalConfirm = document.getElementById('modal-confirm');
  var modalCallback = null;

  function showModal(title, text, cb) {
    if (!modalOverlay) return;
    modalTitle.textContent = title;
    modalBody.textContent = text;
    modalCallback = cb;
    modalOverlay.classList.add('show');
  }

  function hideModal() {
    if (!modalOverlay) return;
    modalOverlay.classList.remove('show');
    modalCallback = null;
  }

  if (modalCancel) modalCancel.addEventListener('click', hideModal);
  if (modalConfirm) modalConfirm.addEventListener('click', function () {
    if (modalCallback) modalCallback();
    hideModal();
  });
  if (modalOverlay) modalOverlay.addEventListener('click', function (e) {
    if (e.target === modalOverlay) hideModal();
  });
  document.addEventListener('keydown', function (e) {
    if (e.key === 'Escape' && modalOverlay && modalOverlay.classList.contains('show')) hideModal();
  });

  /* ── Replace browser confirm() with modal ── */
  document.addEventListener('click', function (e) {
    var btn = e.target.closest('[data-confirm]');
    if (btn) {
      e.preventDefault();
      showModal(btn.dataset.confirmTitle || 'Confirmer', btn.dataset.confirm, function () {
        if (btn.tagName === 'FORM') { btn.submit(); return; }
        if (btn.tagName === 'A') { window.location.href = btn.href; return; }
        if (btn.tagName === 'BUTTON' && btn.form) { btn.form.submit(); return; }
        var form = btn.closest('form');
        if (form) form.submit();
      });
    }
  });

  /* ── Spinner ── */
  var spinner = document.getElementById('spinner-overlay');
  function showSpinner() { if (spinner) spinner.classList.add('show'); }
  function hideSpinner() { if (spinner) spinner.classList.remove('show'); }

  /* Show spinner on form submits (except filters/searches) */
  document.addEventListener('submit', function (e) {
    if (e.target.closest('.filter-bar') || e.target.closest('.search-bar')) return;
    showSpinner();
  });
  /* Show spinner on nav links */
  document.addEventListener('click', function (e) {
    var a = e.target.closest('a');
    var href = a && a.getAttribute('href');
    if (a && href && !a.hasAttribute('data-no-spinner') && !href.startsWith('#') && !href.startsWith('javascript:') && !a.hasAttribute('download') && a.target !== '_blank') {
      if (a.hostname === window.location.hostname) showSpinner();
    }
  });
  window.addEventListener('pageshow', hideSpinner);

  /* ── Sidebar toggle ── */
  var toggle = document.getElementById('sidebar-toggle');
  var sidebar = document.getElementById('sidebar');
  var overlay = document.getElementById('sidebar-overlay');
  if (toggle && sidebar) {
    toggle.addEventListener('click', function () {
      sidebar.classList.toggle('open');
      if (overlay) overlay.classList.toggle('show');
    });
    if (overlay) overlay.addEventListener('click', function () {
      sidebar.classList.remove('open');
      overlay.classList.remove('show');
    });
  }
  document.addEventListener('keydown', function (e) {
    if (e.key === 'Escape' && sidebar && sidebar.classList.contains('open')) {
      sidebar.classList.remove('open');
      if (overlay) overlay.classList.remove('show');
    }
  });

  /* ── Auto-dismiss alerts ── */
  document.querySelectorAll('.alert').forEach(function (a) {
    setTimeout(function () {
      a.style.transition = 'opacity 0.3s ease';
      a.style.opacity = '0';
      setTimeout(function () { if (a.parentNode) a.remove(); }, 350);
    }, 4000);
  });

  /* ── Donut Chart ── */
  function drawDonut(canvasId, data) {
    var canvas = document.getElementById(canvasId);
    if (!canvas) return;
    var ctx = canvas.getContext('2d');
    var W = canvas.width, H = canvas.height, cx = W / 2, cy = H / 2, R = Math.min(W, H) * 0.35, r = R * 0.55;
    var total = data.reduce(function (s, d) { return s + d.value; }, 0) || 1;
    var start = -Math.PI / 2;
    data.forEach(function (d) {
      var slice = (d.value / total) * Math.PI * 2;
      ctx.beginPath(); ctx.arc(cx, cy, R, start, start + slice);
      ctx.arc(cx, cy, r, start + slice, start, true); ctx.closePath();
      ctx.fillStyle = d.color; ctx.fill();
      start += slice;
    });
    /* center text */
    ctx.fillStyle = getComputedStyle(document.documentElement).getPropertyValue('--text').trim() || '#111827';
    ctx.font = 'bold 22px Inter, sans-serif'; ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
    ctx.fillText(total, cx, cy - 6);
    ctx.font = '11px Inter, sans-serif'; ctx.fillStyle = getComputedStyle(document.documentElement).getPropertyValue('--text-muted').trim() || '#6b7280';
    ctx.fillText('Total', cx, cy + 14);
  }

  window.drawDonut = drawDonut;

  /* ── Bar Chart ── */
  function drawBars(canvasId, data, label) {
    var canvas = document.getElementById(canvasId);
    if (!canvas) return;
    var ctx = canvas.getContext('2d');
    var W = canvas.width, H = canvas.height;
    var pad = { t: 25, r: 15, b: 35, l: 55 };
    var cw = W - pad.l - pad.r, ch = H - pad.t - pad.b;
    var max = Math.max.apply(null, data.map(function (d) { return d.value; })) || 1;
    var barW = Math.min(40, (cw - (data.length - 1) * 8) / data.length);
    var gap = (cw - barW * data.length) / (data.length - 1);
    var textColor = getComputedStyle(document.documentElement).getPropertyValue('--text').trim() || '#111827';
    var mutedColor = getComputedStyle(document.documentElement).getPropertyValue('--text-muted').trim() || '#6b7280';
    var barColor = getComputedStyle(document.documentElement).getPropertyValue('--primary-light').trim() || '#245a8a';

    ctx.clearRect(0, 0, W, H);

    /* Y axis */
    ctx.strokeStyle = 'var(--border)'; ctx.lineWidth = 1;
    for (var i = 0; i <= 4; i++) {
      var y = pad.t + (ch - (ch / 4) * i);
      ctx.beginPath(); ctx.moveTo(pad.l, y); ctx.lineTo(W - pad.r, y);
      ctx.strokeStyle = 'rgba(0,0,0,0.06)'; ctx.stroke();
      ctx.fillStyle = mutedColor; ctx.font = '10px Inter, sans-serif'; ctx.textAlign = 'right';
      ctx.fillText(Math.round((max / 4) * i), pad.l - 6, y + 3);
    }

    /* Bars */
    data.forEach(function (d, i) {
      var x = pad.l + i * (barW + gap);
      var h = (d.value / max) * ch;
      var y = pad.t + ch - h;
      ctx.fillStyle = barColor; ctx.beginPath();
      ctx.roundRect(x, y, barW, h, [2, 2, 0, 0]); ctx.fill();
      ctx.fillStyle = textColor; ctx.font = '10px Inter, sans-serif'; ctx.textAlign = 'center';
      ctx.fillText(d.label, x + barW / 2, pad.t + ch + 16);
      if (d.value) { ctx.fillStyle = mutedColor; ctx.fillText(d.value, x + barW / 2, y - 4); }
    });
  }

  window.drawBars = drawBars;

  /* ── Keyboard shortcuts ── */
  document.addEventListener('keydown', function (e) {
    if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA' || e.target.tagName === 'SELECT') return;
    /* 'n' for new */
    if (e.key === 'n' && !e.metaKey && !e.ctrlKey) {
      var newBtn = document.querySelector('.header-actions .btn-primary');
      if (newBtn && newBtn.tagName === 'A') { e.preventDefault(); window.location.href = newBtn.href; }
    }
  });

})();

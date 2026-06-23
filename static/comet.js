/* TradeVault — Comet shell interactions (v1.0).
   Vanilla JS, no framework. Handles: dropdown menus (portfolio switcher +
   settings), language switch, segmented controls, number formatting, and a
   small Chart.js theming helper used by redesigned pages. */
(function () {
  'use strict';

  // ---- Dropdown menus (click toggle, outside-click close) ----------------
  function wireMenu(btnId, menuId) {
    var btn = document.getElementById(btnId);
    var menu = document.getElementById(menuId);
    if (!btn || !menu) return;
    btn.addEventListener('click', function (e) {
      e.stopPropagation();
      var open = menu.classList.toggle('open');
      btn.setAttribute('aria-expanded', open ? 'true' : 'false');
      // Close any other open menus.
      document.querySelectorAll('.tv-menu.open').forEach(function (m) {
        if (m !== menu) m.classList.remove('open');
      });
    });
    menu.addEventListener('click', function (e) { e.stopPropagation(); });
  }

  document.addEventListener('click', function () {
    document.querySelectorAll('.tv-menu.open').forEach(function (m) {
      m.classList.remove('open');
      var btn = m.previousElementSibling;
      if (btn && btn.setAttribute) btn.setAttribute('aria-expanded', 'false');
    });
  });
  document.addEventListener('keydown', function (e) {
    if (e.key === 'Escape') {
      document.querySelectorAll('.tv-menu.open').forEach(function (m) { m.classList.remove('open'); });
    }
  });

  // ---- Language switch (cookie + reload), mirrors legacy app.js ----------
  function wireLang() {
    document.querySelectorAll('[data-lang]').forEach(function (btn) {
      btn.addEventListener('click', function () {
        var lang = btn.dataset.lang;
        if (!lang) return;
        document.cookie = 'lang=' + lang + '; path=/; max-age=' + (365 * 24 * 3600);
        window.location.reload();
      });
    });
  }

  // ---- Segmented controls -------------------------------------------------
  // <div class="tv-seg" data-seg> with buttons[data-value]; emits 'tv:seg'
  // CustomEvent({detail:{value}}) on the container when a button is chosen.
  function wireSegments() {
    document.querySelectorAll('.tv-seg[data-seg]').forEach(function (seg) {
      seg.addEventListener('click', function (e) {
        var b = e.target.closest('button[data-value]');
        if (!b) return;
        seg.querySelectorAll('button').forEach(function (x) { x.classList.remove('active'); });
        b.classList.add('active');
        seg.dispatchEvent(new CustomEvent('tv:seg', { detail: { value: b.dataset.value } }));
      });
    });
  }

  // ---- Row navigation (data-href on a table row / clickable card) --------
  function wireRowNav() {
    document.querySelectorAll('[data-href]').forEach(function (el) {
      el.addEventListener('click', function () { window.location.href = el.dataset.href; });
    });
  }

  // ---- Sortable tables ----------------------------------------------------
  // <table class="tv-table" data-sortable>; <th data-key="value" data-type="num">;
  // rows carry data-<key> attributes with raw sort values.
  function wireSortable() {
    document.querySelectorAll('table[data-sortable]').forEach(function (table) {
      var tbody = table.tBodies[0];
      if (!tbody) return;
      table.querySelectorAll('th[data-key]').forEach(function (th) {
        th.style.cursor = 'pointer';
        th.addEventListener('click', function () {
          var key = th.dataset.key, type = th.dataset.type || 'text';
          var asc = th.dataset.dir !== 'asc';
          table.querySelectorAll('th[data-key]').forEach(function (o) { o.removeAttribute('data-dir'); o.classList.remove('tv-sorted'); });
          th.dataset.dir = asc ? 'asc' : 'desc';
          th.classList.add('tv-sorted');
          var rows = Array.prototype.slice.call(tbody.rows);
          rows.sort(function (a, b) {
            var av = a.dataset[key] || '', bv = b.dataset[key] || '';
            if (type === 'num') { av = parseFloat(av) || 0; bv = parseFloat(bv) || 0; return asc ? av - bv : bv - av; }
            return asc ? String(av).localeCompare(bv) : String(bv).localeCompare(av);
          });
          rows.forEach(function (r) { tbody.appendChild(r); });
        });
      });
    });
  }

  // ---- Live search filter -------------------------------------------------
  // <input data-search-table="holdings-table">; rows carry data-search="...".
  function wireSearch() {
    document.querySelectorAll('[data-search-table]').forEach(function (input) {
      var table = document.getElementById(input.dataset.searchTable);
      if (!table || !table.tBodies[0]) return;
      input.addEventListener('input', function () {
        var q = input.value.trim().toLowerCase();
        Array.prototype.forEach.call(table.tBodies[0].rows, function (r) {
          r.style.display = (!q || (r.dataset.search || '').indexOf(q) !== -1) ? '' : 'none';
        });
      });
    });
  }

  // ---- Filter chips -------------------------------------------------------
  // <div data-chips="list-id"> with button[data-filter]; items carry data-kind.
  function wireChips() {
    document.querySelectorAll('[data-chips]').forEach(function (group) {
      var list = document.getElementById(group.dataset.chips);
      if (!list) return;
      group.addEventListener('click', function (e) {
        var b = e.target.closest('button[data-filter]');
        if (!b) return;
        group.querySelectorAll('button').forEach(function (x) { x.classList.remove('active'); });
        b.classList.add('active');
        var f = b.dataset.filter;
        Array.prototype.forEach.call(list.children, function (el) {
          el.style.display = (f === 'all' || el.dataset.kind === f) ? '' : 'none';
        });
      });
    });
  }

  // ---- Number / money formatting -----------------------------------------
  var TV = window.TV = window.TV || {};
  TV.fmtMoney = function (n, symbol, decimals) {
    symbol = symbol == null ? '' : symbol;
    decimals = decimals == null ? 2 : decimals;
    if (n == null || isNaN(n)) return symbol + '—';
    return symbol + Number(n).toLocaleString('en-US', { minimumFractionDigits: decimals, maximumFractionDigits: decimals });
  };
  TV.fmtSignedPct = function (n) {
    if (n == null || isNaN(n)) return '—';
    var s = n > 0 ? '+' : '';
    return s + Number(n).toFixed(2) + '%';
  };

  // ---- Chart.js shared theming -------------------------------------------
  TV.css = function (name) {
    return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  };
  TV.applyChartDefaults = function () {
    if (!window.Chart) return;
    Chart.defaults.color = TV.css('--text-muted');
    Chart.defaults.font.family = TV.css('--font-sans') || 'Manrope, sans-serif';
    Chart.defaults.borderColor = TV.css('--border-soft');
    if (window.ChartDataLabels && Chart.register) {
      try { Chart.unregister(window.ChartDataLabels); } catch (e) {}
    }
  };

  // ---- Position deep-dive drawer -----------------------------------------
  var pdChart = null;
  function fmtSignedMoney(n, sym) {
    if (n == null || isNaN(n)) return '—';
    return (n >= 0 ? '+' : '−') + sym + Math.abs(Number(n)).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  }
  function openDrawer(id) {
    document.getElementById('tv-scrim').classList.add('open');
    var d = document.getElementById(id);
    if (!d) return;
    d.hidden = false;
    requestAnimationFrame(function () { d.classList.add('open'); });
  }
  function closeDrawer() {
    document.getElementById('tv-scrim').classList.remove('open');
    document.querySelectorAll('.tv-drawer.open').forEach(function (d) {
      d.classList.remove('open');
      setTimeout(function () { d.hidden = true; }, 280);
    });
  }
  function tone(n) { return n >= 0 ? 'pos' : 'neg'; }
  function loadPosition(id) {
    var sym = document.body.dataset.currency || '';
    var drawer = document.getElementById('tv-position-drawer');
    if (!drawer) return;
    openDrawer('tv-position-drawer');
    fetch('/api/position/' + id, { headers: { 'X-Requested-With': 'fetch' } })
      .then(function (r) { return r.ok ? r.json() : Promise.reject(); })
      .then(function (d) {
        var lang = document.documentElement.lang;
        document.getElementById('tv-pd-name').textContent = d.name || '';
        document.getElementById('tv-pd-sub').textContent = (d.symbol || '') + (d.sector ? ' · ' + d.sector : '');
        document.getElementById('tv-pd-value').textContent = TV.fmtMoney(d.market_value, sym);
        var pnlEl = document.getElementById('tv-pd-pnl');
        pnlEl.textContent = fmtSignedMoney(d.pnl, sym) + ' (' + TV.fmtSignedPct(d.pnl_pct) + ')';
        pnlEl.className = 'tv-num ' + tone(d.pnl);
        document.getElementById('tv-pd-link').href = '/position/' + id;

        var stats = [
          [T && T.col_qty || 'Qty', String(d.quantity)],
          [T && T.col_price || 'Price', TV.fmtMoney(d.last_price, sym)],
          [T && T.col_day || 'Day', TV.fmtSignedPct(d.day_pct)],
          [T && T.col_avg_cost || 'Avg cost', TV.fmtMoney(d.avg_cost, sym)],
          [T && T.stat_cost || 'Cost', TV.fmtMoney(d.book_cost, sym)],
          [T && T.col_weight || 'Weight', Number(d.weight).toFixed(1) + '%']
        ];
        document.getElementById('tv-pd-stats').innerHTML = stats.map(function (s, i) {
          var cls = (i === 2) ? ('tv-num ' + tone(d.day_pct)) : 'tv-num';
          return '<div class="tv-stat"><span class="tv-overline">' + s[0] + '</span><span class="' + cls + '">' + s[1] + '</span></div>';
        }).join('');

        document.getElementById('tv-pd-lots').innerHTML = (d.lots || []).map(function (l) {
          return '<div class="tv-lot-row"><span class="muted mono">' + (l.date || '') + '</span>' +
                 '<span class="mono">' + l.shares + ' @ ' + TV.fmtMoney(l.price, sym, 2) + '</span>' +
                 '<span class="tv-num">' + TV.fmtMoney(l.cost, sym) + '</span></div>';
        }).join('') || '<p class="muted" style="font-size:var(--fs-sm);">—</p>';

        // Value-path sparkline tinted by P&L sign.
        var ctx = document.getElementById('tv-pd-chart');
        var col = TV.css(d.pnl >= 0 ? '--positive' : '--negative');
        var grad = ctx.getContext('2d').createLinearGradient(0, 0, 0, 120);
        grad.addColorStop(0, (d.pnl >= 0 ? 'rgba(70,207,131,0.30)' : 'rgba(255,93,108,0.30)'));
        grad.addColorStop(1, 'rgba(0,0,0,0)');
        if (pdChart) pdChart.destroy();
        pdChart = new Chart(ctx, {
          type: 'line',
          data: { labels: (d.path || []).map(function (p) { return p.date; }),
            datasets: [{ data: (d.path || []).map(function (p) { return p.value; }),
              borderColor: col, backgroundColor: grad, borderWidth: 2, fill: true, tension: 0.25, pointRadius: 0 }] },
          options: { responsive: true, maintainAspectRatio: false,
            plugins: { legend: { display: false }, tooltip: { enabled: false } },
            scales: { x: { display: false }, y: { display: false } } }
        });
      })
      .catch(function () { closeDrawer(); });
  }
  function wireDrawer() {
    document.addEventListener('click', function (e) {
      var row = e.target.closest('[data-position-id]');
      if (row) { loadPosition(row.dataset.positionId); return; }
      if (e.target.closest('[data-quickadd-open]')) { e.preventDefault(); openQuickAdd(); return; }
      if (e.target.closest('[data-drawer-close]')) closeDrawer();
    });
    document.addEventListener('keydown', function (e) { if (e.key === 'Escape') closeDrawer(); });
  }

  // ---- Quick-Add drawer ---------------------------------------------------
  var qaHoldings = null;
  function csrf() { var m = document.querySelector('meta[name="csrf-token"]'); return m ? m.content : ''; }
  function qaKind() { var b = document.querySelector('#tv-qa-kind button.active'); return b ? b.dataset.value : 'buy'; }
  function qaIsTrade() { return ['buy', 'sell'].indexOf(qaKind()) !== -1; }
  function qaEl(id) { return document.getElementById(id); }

  function qaUpdateMode() {
    var trade = qaIsTrade();
    var tradeFields = qaEl('tv-qa-trade-fields'), cashField = qaEl('tv-qa-cash-field');
    if (tradeFields) tradeFields.style.display = trade ? '' : 'none';
    if (cashField) cashField.style.display = trade ? 'none' : '';
    qaRecalcTotal();
    var rec = qaEl('tv-qa-record');
    if (rec) {
      var label = (T && T['qa_record_' + qaKind()]) || 'Record';
      rec.querySelector('span').textContent = label;
    }
    var tl = qaEl('tv-qa-total-label');
    if (tl) tl.textContent = trade ? ((qaKind() === 'sell' ? (T && T.qa_total_proceeds) : (T && T.qa_total_cost)) || 'Total')
                                    : ((T && T.qa_amount) || 'Amount');
  }
  function qaRecalcTotal() {
    var sym = document.body.dataset.currency || '', total = 0;
    if (qaIsTrade()) {
      total = (parseFloat(qaEl('tv-qa-qty').value) || 0) * (parseFloat(qaEl('tv-qa-price').value) || 0);
    } else {
      total = parseFloat(qaEl('tv-qa-amount').value) || 0;
    }
    qaEl('tv-qa-total').textContent = TV.fmtMoney(total, sym);
  }
  function openQuickAdd() {
    qaResetSuccess();
    openDrawer('tv-quickadd-drawer');
    var d = qaEl('tv-qa-date'); if (d && !d.value) d.value = new Date().toISOString().slice(0, 10);
    qaUpdateMode();
    if (qaHoldings === null) {
      fetch('/api/holdings-lookup').then(function (r) { return r.json(); })
        .then(function (list) { qaHoldings = list || []; }).catch(function () { qaHoldings = []; });
    }
  }
  function qaResetSuccess() {
    var form = qaEl('tv-qa-form'), ok = qaEl('tv-qa-success');
    if (form) form.style.display = '';
    if (ok) ok.style.display = 'none';
  }
  function qaShowAutocomplete(q) {
    var box = qaEl('tv-qa-ac'); if (!box || !qaHoldings) return;
    q = (q || '').trim().toLowerCase();
    var matches = q ? qaHoldings.filter(function (h) {
      return (h.name + ' ' + h.symbol).toLowerCase().indexOf(q) !== -1;
    }).slice(0, 6) : [];
    if (!matches.length) { box.style.display = 'none'; box.innerHTML = ''; return; }
    var sym = document.body.dataset.currency || '';
    box.innerHTML = matches.map(function (h) {
      return '<button type="button" class="tv-ac-item" data-id="' + h.id + '" data-price="' + h.price + '">' +
        '<span class="tv-mover-sym">' + h.symbol + '</span> <span class="tv-mover-name">' + h.name + '</span>' +
        '<span class="tv-ac-price mono">' + TV.fmtMoney(h.price, sym) + '</span></button>';
    }).join('');
    box.style.display = 'block';
  }
  function qaSubmit() {
    var kind = qaKind(), err = qaEl('tv-qa-error');
    var payload = { kind: kind, date: qaEl('tv-qa-date').value };
    if (qaIsTrade()) {
      payload.holding_id = qaEl('tv-qa-holding-id').value;
      payload.shares = qaEl('tv-qa-qty').value;
      payload.price = qaEl('tv-qa-price').value;
      if (!payload.holding_id) { err.textContent = (T && T.qa_pick_symbol) || 'Pick a symbol'; err.style.display = ''; return; }
    } else {
      payload.amount = qaEl('tv-qa-amount').value;
    }
    err.style.display = 'none';
    var btn = qaEl('tv-qa-record'); btn.disabled = true;
    fetch('/api/quick-add', { method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrf() },
      body: JSON.stringify(payload) })
      .then(function (r) { return r.json().then(function (j) { return { ok: r.ok, j: j }; }); })
      .then(function (res) {
        btn.disabled = false;
        if (res.ok && res.j.ok) {
          qaEl('tv-qa-form').style.display = 'none';
          qaEl('tv-qa-success').style.display = '';
          qaEl('tv-qa-recap').textContent = res.j.message || '';
        } else {
          err.textContent = (res.j && res.j.error) || 'Error'; err.style.display = '';
        }
      })
      .catch(function () { btn.disabled = false; err.textContent = 'Error'; err.style.display = ''; });
  }
  function wireQuickAdd() {
    var drawer = qaEl('tv-quickadd-drawer'); if (!drawer) return;
    var kindSeg = qaEl('tv-qa-kind');
    if (kindSeg) kindSeg.addEventListener('tv:seg', qaUpdateMode);
    ['tv-qa-qty', 'tv-qa-price', 'tv-qa-amount'].forEach(function (id) {
      var el = qaEl(id); if (el) el.addEventListener('input', qaRecalcTotal);
    });
    var symInput = qaEl('tv-qa-symbol');
    if (symInput) symInput.addEventListener('input', function () {
      qaEl('tv-qa-holding-id').value = '';
      qaShowAutocomplete(symInput.value);
    });
    var ac = qaEl('tv-qa-ac');
    if (ac) ac.addEventListener('click', function (e) {
      var it = e.target.closest('.tv-ac-item'); if (!it) return;
      qaEl('tv-qa-holding-id').value = it.dataset.id;
      symInput.value = it.querySelector('.tv-mover-name').textContent;
      qaEl('tv-qa-price').value = it.dataset.price;
      ac.style.display = 'none';
      qaRecalcTotal();
    });
    var rec = qaEl('tv-qa-record'); if (rec) rec.addEventListener('click', qaSubmit);
    var again = qaEl('tv-qa-again'); if (again) again.addEventListener('click', function () {
      qaResetSuccess();
      qaEl('tv-qa-symbol').value = ''; qaEl('tv-qa-holding-id').value = '';
      qaEl('tv-qa-qty').value = ''; qaEl('tv-qa-price').value = ''; qaEl('tv-qa-amount').value = '';
      qaRecalcTotal();
    });
    var done = qaEl('tv-qa-done'); if (done) done.addEventListener('click', function () { window.location.reload(); });
  }

  document.addEventListener('DOMContentLoaded', function () {
    wireMenu('tv-switcher-btn', 'tv-switcher-menu');
    wireMenu('tv-settings-btn', 'tv-settings-menu');
    wireLang();
    wireSegments();
    wireRowNav();
    wireDrawer();
    wireQuickAdd();
    wireSortable();
    wireSearch();
    wireChips();
    TV.applyChartDefaults();
  });
})();

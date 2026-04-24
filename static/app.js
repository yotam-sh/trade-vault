/* TradeVault - Table sorting, filtering, and calendar date picker */

// T is a global translation object injected by the server via <script>var T = ...;</script>

document.addEventListener('DOMContentLoaded', function () {

    // ─── Table sorting (multi-column) ───
    //
    // Regular click : single-column sort; toggles asc/desc if already the sole sort column.
    // Shift+click   : adds/toggles a secondary (or further) sort key.
    // Visual        : ▲/▼ appended to each active header; rank superscript shown when >1 column.
    //
    // Per-table sort state is stored on the element as _sortCols: [{idx, dir}, ...]
    // dir: 1 = ascending, -1 = descending

    function _getCellValue(cell) {
        if (!cell) return '';
        // Cells that contain an <input> (e.g. rebalance target column) — read the value
        var input = cell.querySelector('input[type="number"], input[type="text"]');
        if (input) return input.value.trim();
        return cell.textContent.trim();
    }

    function _compareValues(aVal, bVal) {
        var dateRe = /^\d{4}-\d{2}-\d{2}$/;
        if (dateRe.test(aVal) && dateRe.test(bVal))
            return aVal < bVal ? -1 : aVal > bVal ? 1 : 0;
        var aNum = parseFloat(aVal.replace(/[,%₪+]/g, ''));
        var bNum = parseFloat(bVal.replace(/[,%₪+]/g, ''));
        if (!isNaN(aNum) && !isNaN(bNum)) return aNum - bNum;
        return aVal.localeCompare(bVal, 'he');
    }

    function _multiCompare(a, b, sortCols) {
        for (var i = 0; i < sortCols.length; i++) {
            var col = sortCols[i];
            var cmp = _compareValues(
                _getCellValue(a.children[col.idx]),
                _getCellValue(b.children[col.idx])
            );
            if (cmp !== 0) return cmp * col.dir;
        }
        return 0;
    }

    function _updateSortIndicators(table, sortCols) {
        table.querySelectorAll('thead th').forEach(function (th) {
            var old = th.querySelector('.sort-indicator');
            if (old) old.remove();
            th.classList.remove('sorted-asc', 'sorted-desc');
            th.setAttribute('aria-sort', 'none');
        });
        var ths = Array.from(table.querySelectorAll('thead th'));
        sortCols.forEach(function (col, rank) {
            var th = ths[col.idx];
            if (!th) return;
            var isAsc = col.dir === 1;
            th.classList.add(isAsc ? 'sorted-asc' : 'sorted-desc');
            th.setAttribute('aria-sort', isAsc ? 'ascending' : 'descending');
            var span = document.createElement('span');
            span.className = 'sort-indicator';
            span.setAttribute('aria-hidden', 'true');
            // Show rank superscript only when more than one sort column is active
            var rankStr = sortCols.length > 1 ? '\u2070\u2071\u2072\u2073\u2074\u2075\u2076\u2077\u2078\u2079'.split('')[rank + 1] || (rank + 1) : '';
            span.textContent = (isAsc ? ' \u25b2' : ' \u25bc') + rankStr;
            th.appendChild(span);
        });
    }

    function _applySort(table) {
        var sortCols = table._sortCols || [];
        if (!sortCols.length) return;
        var tbody = table.querySelector('tbody');
        var isGroupSortable = table.classList.contains('group-sortable');

        if (isGroupSortable) {
            var allRows = Array.from(tbody.querySelectorAll('tr'));
            var groups = [];
            var currentGroup = null;
            allRows.forEach(function (row) {
                if (row.classList.contains('group-header')) {
                    if (currentGroup) groups.push(currentGroup);
                    currentGroup = { header: row, rows: [], subtotal: null };
                } else if (row.classList.contains('subtotal')) {
                    if (currentGroup) currentGroup.subtotal = row;
                } else if (row.classList.contains('grand-total')) {
                    if (currentGroup) { groups.push(currentGroup); currentGroup = null; }
                    groups.grandTotal = row;
                } else if (currentGroup) {
                    currentGroup.rows.push(row);
                }
            });
            if (currentGroup) groups.push(currentGroup);

            groups.forEach(function (group) {
                group.rows.sort(function (a, b) { return _multiCompare(a, b, sortCols); });
            });

            tbody.innerHTML = '';
            groups.forEach(function (group) {
                tbody.appendChild(group.header);
                group.rows.forEach(function (row) { tbody.appendChild(row); });
                if (group.subtotal) tbody.appendChild(group.subtotal);
            });
            if (groups.grandTotal) tbody.appendChild(groups.grandTotal);
        } else {
            var rows = Array.from(tbody.querySelectorAll('tr:not(.subtotal):not(.grand-total):not(.group-header)'));
            rows.sort(function (a, b) { return _multiCompare(a, b, sortCols); });
            rows.forEach(function (row) { tbody.appendChild(row); });
        }
    }

    document.querySelectorAll('table.sortable thead th').forEach(function (th) {
        th.setAttribute('tabindex', '0');
        th.setAttribute('aria-sort', 'none');

        function doSort(e) {
            var table = th.closest('table');
            var colIdx = Array.from(th.parentNode.children).indexOf(th);
            if (!table._sortCols) table._sortCols = [];
            var sortCols = table._sortCols;
            var shiftHeld = e && e.shiftKey;

            // Find if this column is already in the sort list
            var existingPos = -1;
            for (var i = 0; i < sortCols.length; i++) {
                if (sortCols[i].idx === colIdx) { existingPos = i; break; }
            }

            if (shiftHeld) {
                if (existingPos >= 0) {
                    // Already a sort key — toggle its direction
                    sortCols[existingPos].dir *= -1;
                } else {
                    // Add as the next sort key (starts ascending)
                    sortCols.push({ idx: colIdx, dir: 1 });
                }
            } else {
                // Regular click: single-column sort
                // If this column is already the sole sort key, toggle direction; otherwise start asc
                var newDir = (sortCols.length === 1 && sortCols[0].idx === colIdx) ? sortCols[0].dir * -1 : 1;
                sortCols.length = 0;
                sortCols.push({ idx: colIdx, dir: newDir });
            }

            _updateSortIndicators(table, sortCols);
            _applySort(table);
        }

        th.addEventListener('click', doSort);
        th.addEventListener('keydown', function (e) {
            if (e.key === 'Enter' || e.key === ' ') {
                e.preventDefault();
                doSort(e);
            }
        });
    });

    // ─── Color P&L cells ───
    document.querySelectorAll('.pnl').forEach(function (el) {
        var val = parseFloat(el.textContent.replace(/[,%₪]/g, ''));
        if (!isNaN(val)) {
            if (val > 0) el.classList.add('positive');
            else if (val < 0) el.classList.add('negative');
        }
    });

    // ─── Color P&L rows ───
    document.querySelectorAll('tr[data-pnl]').forEach(function (row) {
        var val = parseFloat(row.dataset.pnl);
        if (!isNaN(val)) {
            if (val > 0) row.classList.add('positive-bg');
            else if (val < 0) row.classList.add('negative-bg');
        }
    });

    // ─── Security type filter ───
    var typeFilter = document.getElementById('type-filter');
    if (typeFilter) {
        typeFilter.addEventListener('change', function () {
            var selected = typeFilter.value;
            document.querySelectorAll('table.filterable tbody tr').forEach(function (row) {
                row.style.display = (!selected || row.dataset.type === selected) ? '' : 'none';
            });
        });
    }

    // ─── Clear date filters ───
    var clearDates = document.getElementById('clear-dates');
    if (clearDates) {
        clearDates.addEventListener('click', function () {
            var p = new URLSearchParams(window.location.search);
            p.delete('start');
            p.delete('end');
            window.location.search = p.toString();
        });
    }

    // ─── Tax Year Filter ───
    var yearFilter = document.getElementById('year-filter');
    if (yearFilter) {
        yearFilter.addEventListener('change', function () {
            var p = new URLSearchParams(window.location.search);
            p.set('year', yearFilter.value);
            window.location.search = p.toString();
        });
    }

    // ─── Date Presets ───
    (function() {
        var today = new Date();
        today.setHours(0, 0, 0, 0);
        var todayStr = formatDate(today);

        function presetStart(range) {
            if (range === 'week') {
                var sun = new Date(today);
                sun.setDate(today.getDate() - today.getDay());
                return formatDate(sun);
            }
            if (range === 'month') {
                return today.getFullYear() + '-' + String(today.getMonth() + 1).padStart(2, '0') + '-01';
            }
            if (range === '30') {
                var d = new Date(today);
                d.setDate(today.getDate() - 30);
                return formatDate(d);
            }
            return null;
        }

        // Mark active preset on page load
        var params = new URLSearchParams(window.location.search);
        var urlStart = params.get('start');
        var urlEnd   = params.get('end');
        if (urlStart && urlEnd === todayStr) {
            document.querySelectorAll('.date-preset').forEach(function(btn) {
                if (presetStart(btn.dataset.range) === urlStart) {
                    btn.classList.add('active');
                }
            });
        }

        document.querySelectorAll('.date-preset').forEach(function (btn) {
            btn.addEventListener('click', function () {
                var start = presetStart(btn.dataset.range);
                if (!start) return;
                var p = new URLSearchParams(window.location.search);
                p.set('start', start);
                p.set('end', todayStr);
                window.location.search = p.toString();
            });
        });
    })();

    // ─── Table Text Search ───
    document.querySelectorAll('.table-search').forEach(function (input) {
        var tableId = input.dataset.table;
        var table = document.getElementById(tableId);
        if (!table) return;
        input.addEventListener('input', function () {
            var query = input.value.trim().toLowerCase();
            table.querySelectorAll('tbody tr').forEach(function (row) {
                if (!query) { row.style.display = ''; return; }
                var text = row.textContent.toLowerCase();
                row.style.display = text.indexOf(query) !== -1 ? '' : 'none';
            });
        });
    });

    // ─── Calendar Date Picker ───
    initCalendarPickers();
});


// ── Calendar Date Picker Component ──
function initCalendarPickers() {
    document.querySelectorAll('.calendar-picker').forEach(function (wrapper) {
        var btn = wrapper.querySelector('.date-picker-btn');
        var dropdown = wrapper.querySelector('.date-picker-dropdown');
        if (!btn || !dropdown) return;

        var isOpen = false;

        // Check if this picker targets a form input instead of URL params
        var targetInputId = wrapper.dataset.input;
        var targetInput = targetInputId ? document.getElementById(targetInputId) : null;
        var fixedMode = wrapper.dataset.mode; // 'single' or 'range', if forced
        var hasModeToggle = !fixedMode && dropdown.querySelector('.mode-tab');

        var state = {
            mode: fixedMode || 'range',
            viewYear: new Date().getFullYear(),
            viewMonth: new Date().getMonth(),
            selected: null,
            rangeStart: null,
            rangeEnd: null,
        };

        // Initialize from default or existing value
        if (targetInput) {
            // Form-input mode: check data-default and existing value
            if (wrapper.dataset.default === 'today') {
                var today = new Date();
                today.setHours(0, 0, 0, 0);
                state.selected = today;
                targetInput.value = formatDate(today);
            }
            if (targetInput.value) {
                var initDate = parseDate(targetInput.value);
                if (initDate) {
                    state.selected = initDate;
                    state.viewYear = initDate.getFullYear();
                    state.viewMonth = initDate.getMonth();
                }
            }
        } else {
            // URL mode: read initial values from URL
            var params = new URLSearchParams(window.location.search);
            var initStart = params.get('start');
            var initEnd = params.get('end');
            if (initStart && initEnd && initStart === initEnd) {
                state.mode = 'single';
                state.selected = parseDate(initStart);
                if (state.selected) {
                    state.viewYear = state.selected.getFullYear();
                    state.viewMonth = state.selected.getMonth();
                }
            } else if (initStart && initEnd) {
                state.mode = 'range';
                state.rangeStart = parseDate(initStart);
                state.rangeEnd = parseDate(initEnd);
                if (state.rangeStart) {
                    state.viewYear = state.rangeStart.getFullYear();
                    state.viewMonth = state.rangeStart.getMonth();
                }
            } else if (initStart) {
                state.mode = 'single';
                state.selected = parseDate(initStart);
                if (state.selected) {
                    state.viewYear = state.selected.getFullYear();
                    state.viewMonth = state.selected.getMonth();
                }
            }
        }

        // Add aria-live to selected-dates so screen readers announce date changes
        var selectedDatesEl = dropdown.querySelector('.selected-dates');
        if (selectedDatesEl) selectedDatesEl.setAttribute('aria-live', 'polite');

        function openDropdown() {
            isOpen = true;
            dropdown.classList.add('open');
            btn.setAttribute('aria-expanded', 'true');
            render();
            // Move focus into the calendar
            var grid = dropdown.querySelector('.calendar-grid');
            var toFocus = grid.querySelector('.day.selected') || grid.querySelector('.day:not(.other-month)');
            if (toFocus) toFocus.focus();
        }

        function closeDropdown() {
            isOpen = false;
            dropdown.classList.remove('open');
            btn.setAttribute('aria-expanded', 'false');
        }

        // Toggle dropdown on button click
        btn.addEventListener('click', function (e) {
            e.stopPropagation();
            if (isOpen) closeDropdown();
            else openDropdown();
        });

        // Stop ALL clicks inside dropdown from bubbling to document
        dropdown.addEventListener('click', function (e) {
            e.stopPropagation();
        });

        // Close on outside click
        document.addEventListener('click', function () {
            if (isOpen) closeDropdown();
        });

        // Mode tabs (only if present)
        if (hasModeToggle) {
            dropdown.querySelectorAll('.mode-tab').forEach(function (tab) {
                tab.addEventListener('click', function () {
                    state.mode = tab.dataset.mode;
                    state.selected = null;
                    state.rangeStart = null;
                    state.rangeEnd = null;
                    render();
                });
            });
        }

        // Navigation arrows
        dropdown.querySelector('.prev-month').addEventListener('click', function () {
            state.viewMonth--;
            if (state.viewMonth < 0) { state.viewMonth = 11; state.viewYear--; }
            render();
        });
        dropdown.querySelector('.next-month').addEventListener('click', function () {
            state.viewMonth++;
            if (state.viewMonth > 11) { state.viewMonth = 0; state.viewYear++; }
            render();
        });

        // Clear button
        dropdown.querySelector('.clear-btn').addEventListener('click', function () {
            if (targetInput) {
                state.selected = null;
                targetInput.value = '';
                render();
                closeDropdown();
            } else {
                applyFilter(null, null);
            }
        });

        function applyFilter(startDate, endDate) {
            var p = new URLSearchParams(window.location.search);
            if (startDate) p.set('start', formatDate(startDate));
            else p.delete('start');
            if (endDate) p.set('end', formatDate(endDate));
            else p.delete('end');
            window.location.search = p.toString();
        }

        function render() {
            // Update mode tabs if present
            if (hasModeToggle) {
                dropdown.querySelectorAll('.mode-tab').forEach(function (tab) {
                    tab.classList.toggle('active', tab.dataset.mode === state.mode);
                });
            }

            // Update month label
            var months = [
                T.month_1, T.month_2, T.month_3, T.month_4, T.month_5, T.month_6,
                T.month_7, T.month_8, T.month_9, T.month_10, T.month_11, T.month_12
            ];
            dropdown.querySelector('.month-label').textContent =
                months[state.viewMonth] + ' ' + state.viewYear;

            // Build calendar grid
            var grid = dropdown.querySelector('.calendar-grid');
            grid.querySelectorAll('.day').forEach(function (el) { el.remove(); });

            var firstDay = new Date(state.viewYear, state.viewMonth, 1);
            var lastDay = new Date(state.viewYear, state.viewMonth + 1, 0);
            var startDow = firstDay.getDay(); // Sunday = 0

            var today = new Date();
            today.setHours(0, 0, 0, 0);

            // Previous month padding
            var prevLast = new Date(state.viewYear, state.viewMonth, 0);
            for (var i = startDow - 1; i >= 0; i--) {
                grid.appendChild(makeDayCell(
                    new Date(state.viewYear, state.viewMonth - 1, prevLast.getDate() - i), true, today));
            }

            // Current month days
            for (var day = 1; day <= lastDay.getDate(); day++) {
                grid.appendChild(makeDayCell(
                    new Date(state.viewYear, state.viewMonth, day), false, today));
            }

            // Fill remaining cells to complete 6 rows
            var cellCount = grid.querySelectorAll('.day').length;
            var target = cellCount <= 35 ? 35 : 42;
            for (var i = 1; cellCount < target; i++, cellCount++) {
                grid.appendChild(makeDayCell(
                    new Date(state.viewYear, state.viewMonth + 1, i), true, today));
            }

            // Update display text
            var display = dropdown.querySelector('.selected-dates');
            if (state.mode === 'single' && state.selected) {
                display.textContent = formatDate(state.selected);
            } else if (state.mode === 'range' && state.rangeStart) {
                var text = formatDate(state.rangeStart);
                if (state.rangeEnd) text += '  ←  ' + formatDate(state.rangeEnd);
                else text += '  ←  ...';
                display.textContent = text;
            } else {
                display.textContent = T.no_date_selected;
            }

            updateButtonLabel();
        }

        function makeDayCell(date, isOtherMonth, today) {
            var cell = document.createElement('div');
            cell.className = 'day';
            cell.textContent = date.getDate();
            if (isOtherMonth) {
                cell.classList.add('other-month');
                cell.setAttribute('aria-hidden', 'true');
                cell.setAttribute('tabindex', '-1');
            } else {
                var months = [
                    T.month_1, T.month_2, T.month_3, T.month_4, T.month_5, T.month_6,
                    T.month_7, T.month_8, T.month_9, T.month_10, T.month_11, T.month_12
                ];
                cell.setAttribute('tabindex', '0');
                cell.setAttribute('role', 'button');
                cell.setAttribute('aria-label', date.getDate() + ' ' + months[date.getMonth()] + ' ' + date.getFullYear());

                var isSelected = (state.mode === 'single' && state.selected && sameDay(date, state.selected))
                    || (state.mode === 'range' && ((state.rangeStart && sameDay(date, state.rangeStart))
                                                 || (state.rangeEnd && sameDay(date, state.rangeEnd))));
                cell.setAttribute('aria-pressed', isSelected ? 'true' : 'false');

                cell.addEventListener('keydown', function (e) {
                    if (e.key === 'Enter' || e.key === ' ') {
                        e.preventDefault();
                        onDayClick(date);
                    } else if (e.key === 'ArrowLeft' || e.key === 'ArrowRight' ||
                               e.key === 'ArrowUp'   || e.key === 'ArrowDown') {
                        e.preventDefault();
                        var delta = { ArrowLeft: -1, ArrowRight: 1, ArrowUp: -7, ArrowDown: 7 }[e.key];
                        var newDate = new Date(date);
                        newDate.setDate(date.getDate() + delta);
                        if (newDate.getMonth() !== state.viewMonth || newDate.getFullYear() !== state.viewYear) {
                            state.viewMonth = newDate.getMonth();
                            state.viewYear  = newDate.getFullYear();
                            render();
                        }
                        var newDay = newDate.getDate();
                        var grid = dropdown.querySelector('.calendar-grid');
                        grid.querySelectorAll('.day:not(.other-month)').forEach(function (c) {
                            if (parseInt(c.textContent) === newDay) c.focus();
                        });
                    } else if (e.key === 'Escape') {
                        closeDropdown();
                        btn.focus();
                    }
                });
            }

            if (sameDay(date, today)) cell.classList.add('today');

            // Highlight
            if (state.mode === 'single' && state.selected && sameDay(date, state.selected)) {
                cell.classList.add('selected');
            } else if (state.mode === 'range') {
                var rs = state.rangeStart, re = state.rangeEnd;
                if (rs && sameDay(date, rs)) cell.classList.add('selected');
                if (re && sameDay(date, re)) cell.classList.add('selected');
                if (rs && re && date.getTime() > rs.getTime() && date.getTime() < re.getTime()) {
                    cell.classList.add('in-range');
                }
            }

            cell.addEventListener('click', function () {
                onDayClick(date);
            });

            return cell;
        }

        function onDayClick(date) {
            if (state.mode === 'single') {
                state.selected = date;
                if (targetInput) {
                    targetInput.value = formatDate(date);
                    render();
                    closeDropdown();
                } else {
                    render();
                    applyFilter(date, date);
                }
            } else {
                // Range mode
                if (!state.rangeStart || state.rangeEnd) {
                    // First click or resetting
                    state.rangeStart = date;
                    state.rangeEnd = null;
                    render();
                } else {
                    // Second click - set end
                    if (date.getTime() < state.rangeStart.getTime()) {
                        state.rangeEnd = state.rangeStart;
                        state.rangeStart = date;
                    } else {
                        state.rangeEnd = date;
                    }
                    render();
                    // Auto-apply: navigate with both dates
                    applyFilter(state.rangeStart, state.rangeEnd);
                }
            }
        }

        function updateButtonLabel() {
            if (state.mode === 'single' && state.selected) {
                btn.textContent = formatDate(state.selected);
            } else if (state.mode === 'range' && state.rangeStart && state.rangeEnd) {
                btn.textContent = formatDate(state.rangeStart) + ' - ' + formatDate(state.rangeEnd);
            } else if (state.mode === 'range' && state.rangeStart) {
                btn.textContent = formatDate(state.rangeStart) + ' - ...';
            } else {
                btn.textContent = T.pick_date;
            }
        }

        updateButtonLabel();
    });
}

function parseDate(str) {
    if (!str) return null;
    var parts = str.split('-');
    if (parts.length !== 3) return null;
    return new Date(parseInt(parts[0]), parseInt(parts[1]) - 1, parseInt(parts[2]));
}

function formatDate(d) {
    if (!d) return '';
    var y = d.getFullYear();
    var m = String(d.getMonth() + 1).padStart(2, '0');
    var day = String(d.getDate()).padStart(2, '0');
    return y + '-' + m + '-' + day;
}

function sameDay(a, b) {
    return a.getFullYear() === b.getFullYear() &&
           a.getMonth() === b.getMonth() &&
           a.getDate() === b.getDate();
}

// ── Settings Dropdown ──
(function() {
    var settingsBtn = document.getElementById('settings-toggle');
    var settingsDropdown = document.getElementById('settings-dropdown');

    if (!settingsBtn || !settingsDropdown) return;

    var isOpen = false;

    // Check if dropdown should be reopened after reload
    if (sessionStorage.getItem('settingsOpen') === 'true') {
        isOpen = true;
        settingsDropdown.classList.add('open');
        settingsBtn.setAttribute('aria-expanded', 'true');
        sessionStorage.removeItem('settingsOpen');
    }

    // Toggle dropdown
    settingsBtn.addEventListener('click', function(e) {
        e.stopPropagation();
        isOpen = !isOpen;
        settingsDropdown.classList.toggle('open', isOpen);
        settingsBtn.setAttribute('aria-expanded', isOpen ? 'true' : 'false');
    });

    // Close on outside click
    document.addEventListener('click', function(e) {
        if (!settingsDropdown.contains(e.target) && e.target !== settingsBtn) {
            isOpen = false;
            settingsDropdown.classList.remove('open');
            settingsBtn.setAttribute('aria-expanded', 'false');
        }
    });

    // Close on ESC key
    document.addEventListener('keydown', function(e) {
        if (e.key === 'Escape' && isOpen) {
            isOpen = false;
            settingsDropdown.classList.remove('open');
            settingsBtn.setAttribute('aria-expanded', 'false');
        }
    });

    // Stop dropdown clicks from closing
    settingsDropdown.addEventListener('click', function(e) {
        e.stopPropagation();
    });

    // Language switching (reload page with new cookie)
    document.querySelectorAll('.lang-option').forEach(function(btn) {
        btn.addEventListener('click', function() {
            var lang = btn.dataset.lang;
            if (!lang) return; // ignore non-language buttons (e.g. chart toggles)

            // Update cookie
            document.cookie = 'lang=' + lang + '; path=/; max-age=' + (365 * 24 * 3600);

            // Remember dropdown was open
            sessionStorage.setItem('settingsOpen', 'true');

            // Reload page to apply translations
            window.location.reload();
        });
    });

    // Theme switching (CSS variables, no reload)
    function getCookie(name) {
        var value = '; ' + document.cookie;
        var parts = value.split('; ' + name + '=');
        if (parts.length === 2) return parts.pop().split(';').shift();
        return null;
    }

    var currentTheme = getCookie('theme') || 'default';

    // Apply saved theme on load
    if (currentTheme !== 'default') {
        document.documentElement.setAttribute('data-theme', currentTheme);
    }

    // Set initial radio state
    var savedRadio = document.querySelector('input[name="theme"][value="' + currentTheme + '"]');
    if (savedRadio) savedRadio.checked = true;

    // Theme change handler
    document.querySelectorAll('input[name="theme"]').forEach(function(radio) {
        radio.addEventListener('change', function() {
            var theme = radio.value;

            // Update data-theme attribute
            if (theme === 'default') {
                document.documentElement.removeAttribute('data-theme');
            } else {
                document.documentElement.setAttribute('data-theme', theme);
            }

            // Save to cookie
            document.cookie = 'theme=' + theme + '; path=/; max-age=' + (365 * 24 * 3600);
        });
    });
})();
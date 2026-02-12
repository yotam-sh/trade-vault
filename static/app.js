/* my-stocks - Table sorting, filtering, and calendar date picker */

document.addEventListener('DOMContentLoaded', function () {

    // ─── Table sorting ───
    document.querySelectorAll('table.sortable thead th').forEach(function (th) {
        th.addEventListener('click', function () {
            var table = th.closest('table');
            var tbody = table.querySelector('tbody');
            var colIdx = Array.from(th.parentNode.children).indexOf(th);
            var rows = Array.from(tbody.querySelectorAll('tr:not(.subtotal):not(.grand-total):not(.group-header)'));

            var isAsc = th.classList.contains('sorted-asc');
            table.querySelectorAll('th').forEach(function (h) {
                h.classList.remove('sorted-asc', 'sorted-desc');
            });
            th.classList.add(isAsc ? 'sorted-desc' : 'sorted-asc');
            var direction = isAsc ? -1 : 1;

            rows.sort(function (a, b) {
                var aVal = a.children[colIdx] ? a.children[colIdx].textContent.trim() : '';
                var bVal = b.children[colIdx] ? b.children[colIdx].textContent.trim() : '';
                var aNum = parseFloat(aVal.replace(/[,%₪]/g, ''));
                var bNum = parseFloat(bVal.replace(/[,%₪]/g, ''));
                if (!isNaN(aNum) && !isNaN(bNum)) return (aNum - bNum) * direction;
                return aVal.localeCompare(bVal, 'he') * direction;
            });
            rows.forEach(function (row) { tbody.appendChild(row); });
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

        function openDropdown() {
            isOpen = true;
            dropdown.classList.add('open');
            render();
        }

        function closeDropdown() {
            isOpen = false;
            dropdown.classList.remove('open');
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
            var months = ['ינואר', 'פברואר', 'מרץ', 'אפריל', 'מאי', 'יוני',
                          'יולי', 'אוגוסט', 'ספטמבר', 'אוקטובר', 'נובמבר', 'דצמבר'];
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
                display.textContent = 'לא נבחר תאריך';
            }

            updateButtonLabel();
        }

        function makeDayCell(date, isOtherMonth, today) {
            var cell = document.createElement('div');
            cell.className = 'day';
            cell.textContent = date.getDate();
            if (isOtherMonth) cell.classList.add('other-month');
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
                btn.textContent = 'בחר תאריך';
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

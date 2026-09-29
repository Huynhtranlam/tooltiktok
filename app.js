(() => {
  'use strict';

  const $ = (selector, root = document) => root.querySelector(selector);
  const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];
  const escape = value => String(value ?? '').replace(/[&<>"']/g, char => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
  const clone = value => JSON.parse(JSON.stringify(value));
  const money = value => `${new Intl.NumberFormat('vi-VN', {maximumFractionDigits: 0}).format(value || 0)} ₫`;
  const count = value => new Intl.NumberFormat('vi-VN', {maximumFractionDigits: 2}).format(value || 0);
  const dateText = value => value ? `${value.slice(8,10)}/${value.slice(5,7)}/${value.slice(0,4)}` : '—';
  const today = () => { const d = new Date(); return `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}-${String(d.getDate()).padStart(2,'0')}`; };
  const weekdays = ['CN', 'T2', 'T3', 'T4', 'T5', 'T6', 'T7'];
  const state = {user:null, csrf:'', data:null, report:null, chartExpanded:false, periodDraft:[], activePeriod:0, overrideDraft:[], overrideEditing:false, csvFile:null, csvHash:'', portableFile:null, portableHash:'', legacyFile:null, legacyHash:'', activeOrder:null, draftTimer:null};
  const isAdmin = () => state.user?.role === 'admin';

  async function api(path, options = {}) {
    const headers = {...options.headers};
    if (!(options.body instanceof FormData) && options.body !== undefined) headers['Content-Type'] = 'application/json';
    if (options.method && options.method !== 'GET') headers['X-CSRF-Token'] = state.csrf;
    const response = await fetch(path, {credentials:'same-origin', ...options, headers});
    let data;
    try { data = await response.json(); } catch { data = {}; }
    if (!response.ok) { const error = new Error(data.error || `Lỗi ${response.status}`); error.fields = data.fields; error.rows = data.rows; error.status = response.status; throw error; }
    return data;
  }
  const json = value => JSON.stringify(value);
  function notice(message, bad = false) {
    const el = $('#notice'); el.textContent = message; el.classList.remove('hide'); el.classList.toggle('error', bad);
    if (bad) el.focus();
  }
  const fail = error => notice(error?.message || 'Có lỗi xảy ra. Hãy thử lại.', true);
  function clearNotice() { $('#notice').classList.add('hide'); }
  function showScreen(name) {
    $$('.screen').forEach(el => el.classList.toggle('active', el.id === name));
    $$('.nav-button').forEach(el => el.classList.toggle('active', el.dataset.screen === name));
    $('.sidebar').classList.remove('open'); clearNotice();
    if (name === 'settings' && isAdmin()) loadAdminPanels();
  }
  function adminDisabled() { return isAdmin() ? '' : 'disabled'; }

  async function boot() {
    const now = today();
    $('#reportFrom').value = now.slice(0,7) + '-01'; $('#reportTo').value = now;
    $('#payrollFrom').value = $('#reportFrom').value; $('#payrollTo').value = now;
    $('#overrideDate').value = now;
    let me;
    try { me = await api('/api/me'); }
    catch (error) {
      $('#loginError').textContent = location.protocol === 'file:' || error.status === 404
        ? 'Hãy chạy start-local.cmd trên máy này và dùng cửa sổ ứng dụng tự mở. Không mở index.html hoặc GitHub Pages trực tiếp.'
        : `Không kết nối được ứng dụng trên máy này: ${error.message}`;
      $('#loginView').classList.remove('hide'); $('#appView').classList.add('hide');
      return;
    }
    try {
      state.user = me.user; state.csrf = me.csrf;
      $('#loginView').classList.add('hide'); $('#appView').classList.remove('hide');
      await loadState(); await loadReport();
    } catch (error) { fail(error); }
  }
  async function loadState() {
    state.data = await api('/api/state');
    state.periodDraft = clone(state.data.schedule.periods);
    state.activePeriod = Math.min(state.activePeriod, state.periodDraft.length - 1);
    $('#scheduleSaved').textContent = `Đã lưu · phiên bản ${state.data.schedule.version}`;
    const draft = state.data.draft;
    $('#draftBanner').classList.toggle('hide', !isAdmin() || !draft);
    if (draft && draft.baseVersion !== state.data.schedule.version) $('#draftBanner span').textContent = 'Bản nháp được tạo trước khi lịch thay đổi trên máy khác. Hãy kiểm tra kỹ trước khi lưu.';
    renderSchedule(); renderOverride(); renderRates(); renderStaff(); renderClosures();
    $('#lastImport').textContent = state.data.lastImport ? `Lần nhập gần nhất: ${new Date(state.data.lastImport.created_at).toLocaleString('vi-VN')} · ${state.data.lastImport.order_count} đơn (${state.data.lastImport.inserted} mới, ${state.data.lastImport.updated} cập nhật).` : state.data.orderCount ? `Máy này có ${state.data.orderCount} đơn từ dữ liệu đã chuyển; chưa có lượt nhập CSV trực tiếp.` : 'Chưa nhập file CSV trên máy này.';
    $('#addStaffForm').classList.toggle('hide', !isAdmin());
    ['downloadBackup','serverBackup','previewPortable','previewLegacy','closePayroll'].forEach(id => { $('#' + id).disabled = !isAdmin() || (id === 'previewPortable' && !state.portableFile) || (id === 'previewLegacy' && !state.legacyFile); });
  }
  async function loadReport() {
    const from = $('#reportFrom').value, to = $('#reportTo').value;
    if (!from || !to || from > to) { notice('Chọn khoảng ngày hợp lệ: ngày bắt đầu không sau ngày kết thúc.', true); return; }
    state.report = await api(`/api/report?from=${encodeURIComponent(from)}&to=${encodeURIComponent(to)}`);
    renderDashboard(); renderOrders();
  }

  function renderDashboard() {
    const report = state.report; if (!report) return;
    $('#metricOrders').textContent = count(report.totals.orders); $('#metricQty').textContent = count(report.totals.qty);
    $('#metricRevenue').textContent = money(report.totals.revenue); $('#metricCommission').textContent = money(report.totals.commission);
    $('#metricReview').textContent = count(report.totals.review);
    $('#staffTable').innerHTML = report.staff.map(row => `<tr><td><strong>${escape(row.staff)}</strong></td><td>${count(row.orders)}</td><td>${count(row.qty)}</td><td>${money(row.revenue)}</td><td><strong>${money(row.commission)}</strong></td></tr>`).join('') || '<tr><td colspan="5" class="empty-cell">Chưa có đơn được gán trong khoảng ngày này.</td></tr>';
    const groups = new Map();
    for (const product of report.products) { if (!groups.has(product.staff)) groups.set(product.staff, []); groups.get(product.staff).push(product); }
    const metric = $('#chartMetric').value; const max = Math.max(1, ...report.products.map(row => row[metric]));
    $('#productChart').innerHTML = [...groups].map(([staff, rows]) => `<div class="product-card"><h3>${escape(staff)} <small>${rows.length} sản phẩm</small></h3>${(state.chartExpanded ? rows : rows.slice(0,8)).map(row => `<div class="bar-item"><div class="bar-caption"><span title="${escape(row.product)}">${escape(row.product)}</span><strong>${metric === 'qty' ? count(row.qty) + ' SP' : money(row.revenue)}</strong></div><div class="bar-track"><div class="bar-fill" style="width:${Math.max(1,row[metric]/max*100)}%"></div></div></div>`).join('')}${!state.chartExpanded && rows.length > 8 ? `<p class="muted small-text">Còn ${rows.length - 8} sản phẩm.</p>` : ''}</div>`).join('') || '<p class="muted">Chưa có sản phẩm trong khoảng ngày đã chọn.</p>';
    $('#toggleProducts').classList.toggle('hide', !report.products.some(row => groups.get(row.staff).length > 8));
    $('#toggleProducts').textContent = state.chartExpanded ? 'Thu gọn sản phẩm' : 'Xem tất cả sản phẩm';
  }

  function staffName(id) { return state.data?.staff.find(row => row.id === Number(id))?.name || 'Chọn nhân viên'; }
  function staffOptions(selected) { return '<option value="">Chọn nhân viên</option>' + state.data.staff.filter(row => row.active || row.id === Number(selected)).map(row => `<option value="${row.id}" ${row.id === Number(selected) ? 'selected' : ''}>${escape(row.name)}</option>`).join(''); }
  function dayOf(iso) { return new Date(`${iso}T00:00:00Z`).getUTCDay(); }
  function slotsOn(day) {
    if (Object.prototype.hasOwnProperty.call(state.data.schedule.overrides, day)) return clone(state.data.schedule.overrides[day]);
    const period = state.data.schedule.periods.find(row => row.start <= day && day <= row.end);
    return clone((period?.shifts || []).filter(shift => shift.days.includes(dayOf(day))));
  }
  function newShift(weekly = true) { return {id:crypto.randomUUID(),staffId:null,start:'10:00',end:'11:00',endDay:0,...(weekly ? {days:[0,1,2,3,4,5,6]} : {})}; }
  function timePicker(value, field, disabled) {
    const [hour, minute] = String(value || '00:00').split(':');
    return `<div class="time-picker"><select data-field="${field}Hour" aria-label="${field === 'start' ? 'Giờ bắt đầu' : 'Giờ kết thúc'}" ${disabled}>${Array.from({length:24},(_,i) => String(i).padStart(2,'0')).map(item => `<option value="${item}" ${item === hour ? 'selected' : ''}>${item}</option>`).join('')}</select><span>:</span><select data-field="${field}Minute" aria-label="${field === 'start' ? 'Phút bắt đầu' : 'Phút kết thúc'}" ${disabled}>${Array.from({length:60},(_,i) => String(i).padStart(2,'0')).map(item => `<option value="${item}" ${item === minute ? 'selected' : ''}>${item}</option>`).join('')}</select></div>`;
  }
  function shiftMarkup(shift, index, weekly = true, readOnly = false) {
    const disabled = readOnly || !isAdmin() ? 'disabled' : '';
    return `<div class="shift-row" data-shift="${escape(shift.id)}"><div class="shift-fields"><label>Nhân viên<select data-field="staffId" ${disabled}>${staffOptions(shift.staffId)}</select></label><label>Bắt đầu (24 giờ)${timePicker(shift.start,'start',disabled)}</label><label>Kết thúc (24 giờ)${timePicker(shift.end,'end',disabled)}</label><label>Ngày kết thúc<select data-field="endDay" ${disabled}><option value="0" ${shift.endDay === 0 ? 'selected' : ''}>Hôm nay</option><option value="1" ${shift.endDay === 1 ? 'selected' : ''}>Hôm sau</option></select></label>${readOnly ? '' : `<button class="button danger small" data-remove-shift="${index}" ${disabled} aria-label="Xóa ca ${index + 1}">Xóa ca</button>`}</div>${weekly ? `<fieldset class="day-picker"><legend>Ngày áp dụng</legend>${weekdays.map((day, number) => `<label class="day-pill"><input type="checkbox" data-day="${number}" ${shift.days?.includes(number) ? 'checked' : ''} ${disabled}>${day}</label>`).join('')}</fieldset>` : ''}</div>`;
  }
  function readShifts(container, weekly) {
    return $$('[data-shift]', container).map(row => ({id:row.dataset.shift,
      staffId:row.querySelector('[data-field="staffId"]').value ? Number(row.querySelector('[data-field="staffId"]').value) : null,
      start:row.querySelector('[data-field="startHour"]').value + ':' + row.querySelector('[data-field="startMinute"]').value,
      end:row.querySelector('[data-field="endHour"]').value + ':' + row.querySelector('[data-field="endMinute"]').value,
      endDay:Number(row.querySelector('[data-field="endDay"]').value),
      ...(weekly ? {days:$$('[data-day]:checked', row).map(el => Number(el.dataset.day))} : {})
    }));
  }
  function syncPeriod() {
    const period = state.periodDraft[state.activePeriod]; if (!period) return;
    period.start = $('#periodStart').value; period.end = $('#periodEnd').value;
    period.shifts = readShifts($('#shiftEditor'), true);
    $('#draftStatus').textContent = 'Đang lưu bản nháp trên máy này…';
    $('#scheduleSaved').textContent = 'Có thay đổi chưa lưu';
    renderWeekPreview(); renderPeriodNav();
    clearTimeout(state.draftTimer);
    state.draftTimer = setTimeout(async () => {
      try { const result = await api('/api/schedule/draft', {method:'PUT', body:json({baseVersion:state.data.schedule.version, periods:state.periodDraft})}); $('#draftStatus').textContent = `Đã lưu bản nháp · ${new Date(result.savedAt).toLocaleTimeString('vi-VN')}`; }
      catch (error) { $('#draftStatus').textContent = 'Chưa lưu được bản nháp'; fail(error); }
    }, 700);
  }
  function renderPeriodNav() {
    $('#periodNav').innerHTML = state.periodDraft.map((period, index) => `<button class="period-item ${index === state.activePeriod ? 'active' : ''}" data-period-index="${index}"><strong>Khoảng ${index + 1}</strong><small>${dateText(period.start)} – ${dateText(period.end)} · ${period.shifts.length} ca</small></button>`).join('');
  }
  function renderWeekPreview() {
    const period = state.periodDraft[state.activePeriod];
    $('#weekPreview').innerHTML = weekdays.map((day, number) => {
      const slots = (period?.shifts || []).filter(shift => shift.days?.includes(number)).sort((a,b) => a.start.localeCompare(b.start));
      return `<div class="week-day"><b>${day}</b>${slots.length ? slots.map(shift => `<div class="week-shift"><strong>${escape(staffName(shift.staffId))}</strong><br>${escape(shift.start)} → ${escape(shift.end)}${shift.endDay ? ' hôm sau' : ''}</div>`).join('') : '<small>Không có ca</small>'}</div>`;
    }).join('');
  }
  function renderSchedule() {
    renderPeriodNav();
    const period = state.periodDraft[state.activePeriod];
    $('#periodHeading').textContent = period ? `Khoảng lịch ${state.activePeriod + 1}` : 'Chưa có khoảng lịch';
    $('#periodStart').value = period?.start || ''; $('#periodEnd').value = period?.end || '';
    $('#shiftEditor').innerHTML = period?.shifts.map((shift,index) => shiftMarkup(shift,index)).join('') || '<p class="muted">Chưa có ca. Chọn “Thêm ca”.</p>';
    ['periodStart','periodEnd','addShift','removePeriod','addPeriod','saveSchedule'].forEach(id => $('#' + id).disabled = !isAdmin() || (!period && id !== 'addPeriod'));
    $('#removePeriod').disabled = !isAdmin() || state.periodDraft.length <= 1;
    renderWeekPreview();
  }
  function showScheduleErrors(fields) {
    const box = $('#scheduleErrors'); box.classList.remove('hide');
    box.innerHTML = `<strong>Kiểm tra lịch trước khi lưu</strong><ul>${fields.map(field => `<li>${escape(field.message)}</li>`).join('')}</ul>`;
    const first = fields[0]?.path?.match(/^periods\.(\d+)/);
    if (first && Number(first[1]) !== state.activePeriod) { state.activePeriod = Number(first[1]); renderSchedule(); }
    const path = fields[0]?.path || '';
    let target = null;
    if (path.endsWith('.start') && path.includes('.shifts.')) target = $$('[data-shift]', $('#shiftEditor'))[Number(path.split('.shifts.')[1].split('.')[0])]?.querySelector('[data-field="startHour"]');
    else if (path.endsWith('.end') && path.includes('.shifts.')) target = $$('[data-shift]', $('#shiftEditor'))[Number(path.split('.shifts.')[1].split('.')[0])]?.querySelector('[data-field="endHour"]');
    else if (path.endsWith('.staffId')) target = $$('[data-shift]', $('#shiftEditor'))[Number(path.split('.shifts.')[1].split('.')[0])]?.querySelector('[data-field="staffId"]');
    else if (path.endsWith('.dates')) target = $('#periodStart');
    if (target) { target.classList.add('field-invalid'); target.focus(); target.scrollIntoView({block:'center',behavior:'smooth'}); }
    else { box.focus(); box.scrollIntoView({block:'center',behavior:'smooth'}); }
  }
  async function saveSchedule() {
    syncPeriod(); clearTimeout(state.draftTimer);
    try {
      await api('/api/schedule', {method:'PUT', body:json({baseVersion:state.data.schedule.version, periods:state.periodDraft})});
      $('#scheduleErrors').classList.add('hide'); notice('Đã lưu lịch trên máy này. Đơn chưa chốt được tính lại theo lịch mới.');
      await loadState(); await loadReport();
    } catch (error) { if (error.fields) showScheduleErrors(error.fields); else fail(error); }
  }
  function renderOverride() {
    const day = $('#overrideDate').value || today();
    const hasOwn = Object.prototype.hasOwnProperty.call(state.data.schedule.overrides, day);
    $('#overrideMode').textContent = hasOwn ? 'Lịch riêng đang áp dụng' : 'Theo lịch cố định';
    $('#overrideMode').classList.toggle('warn', hasOwn);
    if (!state.overrideEditing) state.overrideDraft = slotsOn(day);
    $('#overrideShifts').innerHTML = state.overrideDraft.map((shift,index) => shiftMarkup(shift,index,false,!state.overrideEditing)).join('') || '<p class="muted">Ngày này chưa có ca.</p>';
    $('#editOverride').classList.toggle('hide', state.overrideEditing || !isAdmin());
    $('#addOverrideShift').classList.toggle('hide', !state.overrideEditing);
    $('#saveOverride').classList.toggle('hide', !state.overrideEditing);
    $('#resetOverride').classList.toggle('hide', !hasOwn || !isAdmin());
    $('#overrideDate').disabled = false;
  }
  async function saveOverride() {
    const day = $('#overrideDate').value;
    try {
      await api(`/api/overrides/${day}`, {method:'PUT', body:json({shifts:readShifts($('#overrideShifts'),false)})});
      state.overrideEditing = false; $('#overrideErrors').classList.add('hide'); notice(`Đã lưu lịch riêng ngày ${dateText(day)}.`);
      await loadState(); await loadReport();
    } catch (error) {
      if (error.fields) { $('#overrideErrors').innerHTML = `<strong>Kiểm tra lịch ngày</strong><ul>${error.fields.map(x => `<li>${escape(x.message)}</li>`).join('')}</ul>`; $('#overrideErrors').classList.remove('hide'); $('#overrideErrors').focus(); }
      else fail(error);
    }
  }

  function orderStatusText(order) { const item = order.assignment; return `<span class="status-chip ${item.kind}">${escape(item.kind === 'assigned' ? 'Đã gán' : item.kind === 'review' ? 'Cần xử lý' : 'Không tính')}</span>`; }
  function renderOrders() {
    if (!state.report) return;
    const filter = $('#orderStatus').value, query = $('#orderSearch').value.trim().toLocaleLowerCase('vi');
    const rows = state.report.orders.filter(order => (filter === 'all' || order.assignment.kind === filter) && (!query || order.id.toLocaleLowerCase('vi').includes(query) || order.lines.some(line => String(line.product || '').toLocaleLowerCase('vi').includes(query))));
    $('#orderResultCount').textContent = `${count(rows.length)} đơn`;
    $('#orderLimit').textContent = rows.length > 200 ? `Đang hiển thị 200/${rows.length} đơn. Dùng ô tìm kiếm để thu hẹp.` : '';
    $('#orderTable').innerHTML = rows.slice(0,200).map(order => `<tr><td>${escape((order.createdAt || '').replace('T',' ').slice(0,16))}</td><td><strong>${escape(order.id)}</strong></td><td>${count(order.lines.reduce((total,line) => total + line.qty,0))} SP · ${escape(order.lines[0]?.product || '—')}${order.lines.length > 1 ? ` +${order.lines.length - 1}` : ''}</td><td>${escape(order.channel || 'Trống')}</td><td>${escape(order.assignment.staffId ? staffName(order.assignment.staffId) : '—')}</td><td>${orderStatusText(order)} <small class="muted">${escape(order.assignment.reason)}</small></td><td>${isAdmin() && order.assignment.kind !== 'excluded' ? `<button class="button small" data-adjust="${escape(order.id)}">Điều chỉnh</button>` : ''}</td></tr>`).join('') || '<tr><td colspan="7" class="empty-cell">Không có đơn phù hợp.</td></tr>';
  }
  function openAssignment(orderId) {
    const order = state.report.orders.find(row => row.id === orderId); if (!order) return;
    state.activeOrder = order;
    $('#assignmentPanel').classList.remove('hide'); $('#assignmentOrderId').textContent = order.id;
    $('#assignmentContext').textContent = `Giờ tạo: ${(order.createdAt || '').replace('T',' ')} · ${order.assignment.reason} · ${order.lines.map(line => line.product).join(', ')}`;
    $('#assignmentStaff').innerHTML = staffOptions(order.assignment.staffId);
    $('#assignmentReason').value = '';
    $('#clearAssignment').classList.toggle('hide', order.assignment.reason !== 'Gán thủ công');
    $('#assignmentPanel').scrollIntoView({block:'center',behavior:'smooth'});
  }
  function safeCsvCell(value) { let text = String(value ?? ''); if (/^[\s]*[=+\-@]/.test(text)) text = "'" + text; return `"${text.replace(/"/g,'""')}"`; }
  function downloadCsv(filename, headers, rows) {
    const content = '\ufeff' + [headers,...rows].map(row => row.map(safeCsvCell).join(',')).join('\r\n');
    const url = URL.createObjectURL(new Blob([content], {type:'text/csv;charset=utf-8'}));
    const link = document.createElement('a'); link.href = url; link.download = filename; link.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);
  }

  function renderRates() {
    const rates = state.data.rates;
    $('#rateList').innerHTML = state.data.staff.map(person => { const history = rates[person.id] || []; const current = history.at(-1);
      return `<div class="rate-row" data-rate-staff="${person.id}"><strong>${escape(person.name)}</strong><label>Tỷ lệ (%)<input type="number" min="0" max="100" step="0.01" value="${escape(current?.rate ?? 0)}" ${adminDisabled()}></label><label>Hiệu lực từ<input type="date" value="${today()}" ${adminDisabled()}></label><button class="button small" data-save-rate="${person.id}" ${adminDisabled()}>Lưu tỷ lệ</button><div class="rate-history">${history.map(item => `${dateText(item.effectiveFrom)}: ${item.rate}%`).join(' · ')}</div></div>`;
    }).join('');
  }
  function renderClosures() {
    $('#payrollClosures').innerHTML = '<h3>Các kỳ đã chốt</h3>' + (state.data.closures.map(item => `<div class="closure-item"><span><strong>${dateText(item.start_day)} – ${dateText(item.end_day)}</strong><small>${item.reopened_at ? 'Đã mở lại' : 'Đã chốt'}</small></span><button class="button small" data-view-closure="${item.id}">Xem</button></div>`).join('') || '<p class="muted small-text">Chưa có kỳ đã chốt.</p>');
  }
  function renderStaff() { $('#staffList').innerHTML = state.data.staff.map(person => `<span class="tag">${escape(person.name)}</span>`).join(''); }
  async function loadAdminPanels() {
    if (!isAdmin()) return;
    try {
      const audit = await api('/api/audit');
      $('#auditList').innerHTML = audit.map(item => `<div class="audit-row"><strong>Máy này</strong> · ${escape(item.action)} ${escape(item.object_type)} ${escape(item.object_id)}<br><small>${new Date(item.at).toLocaleString('vi-VN')}</small></div>`).join('') || '<p class="muted">Chưa có thay đổi.</p>';
    } catch (error) { fail(error); }
  }
  function previewBox(target, html) { const box = $(target); box.innerHTML = html; box.classList.remove('hide'); }
  function downloadBackup() {
    const link = document.createElement('a');
    link.href = '/api/backup'; link.download = `liveledger-data-${today()}.json`;
    document.body.appendChild(link); link.click(); link.remove();
  }

  $('#mobileMenu').addEventListener('click', () => $('.sidebar').classList.toggle('open'));
  $$('.nav-button').forEach(button => button.addEventListener('click', () => showScreen(button.dataset.screen)));
  $$('[data-go]').forEach(button => button.addEventListener('click', () => showScreen(button.dataset.go)));
  $('#applyReport').addEventListener('click', async () => { try { await loadReport(); } catch (error) { fail(error); } });
  $('#chartMetric').addEventListener('change', renderDashboard);
  $('#toggleProducts').addEventListener('click', () => { state.chartExpanded = !state.chartExpanded; renderDashboard(); });

  $('#csvFile').addEventListener('change', event => { state.csvFile = event.target.files[0] || null; state.csvHash = ''; $('#previewCsv').disabled = !state.csvFile || !isAdmin(); $('#csvFileName').textContent = state.csvFile?.name || 'Chưa chọn file'; $('#csvPreview').classList.add('hide'); });
  $('#previewCsv').addEventListener('click', async () => {
    if (!state.csvFile) return;
    const form = new FormData(); form.append('file',state.csvFile);
    try {
      const result = await api('/api/import/preview',{method:'POST',body:form}); state.csvHash = result.sha256;
      previewBox('#csvPreview', `<strong>Xem trước file ${escape(state.csvFile.name)}</strong><div class="preview-stats"><span><b>${count(result.rows)}</b>dòng sản phẩm</span><span><b>${count(result.orders)}</b>mã đơn</span><span><b>${count(result.inserted)}</b>đơn mới</span><span><b>${count(result.updated)}</b>đơn cập nhật</span></div><p>Kênh đơn: ${Object.entries(result.channels).map(([key,value]) => `${escape(key)} ${count(value)}`).join(', ')}.</p>${result.closedOrders ? `<p class="field-error">${result.closedOrders} đơn thuộc kỳ đã chốt; cần mở lại kỳ trước khi nhập.</p>` : ''}${result.errors.length ? `<div class="error-list"><strong>${result.errors.length} dòng cần sửa, chưa thể nhập:</strong><ul>${result.errors.slice(0,12).map(message => `<li>${escape(message)}</li>`).join('')}</ul></div>` : `<button id="commitCsv" class="button primary" ${result.closedOrders ? 'disabled' : ''}>Xác nhận nhập ${count(result.orders)} đơn</button>`}`);
    } catch (error) { fail(error); }
  });
  $('#csvPreview').addEventListener('click', async event => {
    if (event.target.id !== 'commitCsv' || !state.csvFile) return;
    const form = new FormData(); form.append('file',state.csvFile); form.append('sha256',state.csvHash);
    event.target.disabled = true;
    try { const result = await api('/api/import/commit',{method:'POST',body:form}); $('#csvPreview').classList.add('hide'); $('#csvFile').value = ''; state.csvFile = null; $('#previewCsv').disabled = true; $('#csvFileName').textContent = 'Chưa chọn file'; notice(`Đã nhập ${result.inserted} đơn mới, cập nhật ${result.updated} đơn.`); await loadState(); await loadReport(); }
    catch (error) { event.target.disabled = false; fail(error); }
  });

  $('#periodNav').addEventListener('click', event => { const button = event.target.closest('[data-period-index]'); if (!button) return; if (isAdmin()) syncPeriod(); state.activePeriod = Number(button.dataset.periodIndex); $('#scheduleErrors').classList.add('hide'); renderSchedule(); });
  $('#restoreDraft').addEventListener('click', () => { const draft = state.data.draft; if (!draft) return; state.periodDraft = clone(draft.periods); state.activePeriod = 0; $('#draftBanner').classList.add('hide'); $('#draftStatus').textContent = draft.baseVersion === state.data.schedule.version ? 'Bản nháp đã được mở; hãy kiểm tra và lưu.' : 'Bản nháp cũ; hãy kiểm tra mọi khoảng trước khi lưu.'; renderSchedule(); });
  ['periodStart','periodEnd'].forEach(id => $('#' + id).addEventListener('change', syncPeriod));
  $('#shiftEditor').addEventListener('input', syncPeriod);
  $('#shiftEditor').addEventListener('change', syncPeriod);
  $('#shiftEditor').addEventListener('click', event => { const button = event.target.closest('[data-remove-shift]'); if (!button) return; syncPeriod(); state.periodDraft[state.activePeriod].shifts.splice(Number(button.dataset.removeShift),1); renderSchedule(); syncPeriod(); });
  $('#addShift').addEventListener('click', () => { syncPeriod(); state.periodDraft[state.activePeriod].shifts.push(newShift(true)); renderSchedule(); syncPeriod(); });
  $('#addPeriod').addEventListener('click', () => { if (state.periodDraft.length) syncPeriod(); const last = [...state.periodDraft].sort((a,b) => a.end.localeCompare(b.end)).at(-1); const next = last?.end ? new Date(`${last.end}T00:00:00Z`) : new Date(); if (last?.end) next.setUTCDate(next.getUTCDate()+1); const start = next.toISOString().slice(0,10); state.periodDraft.push({id:crypto.randomUUID(),start,end:start,shifts:[]}); state.activePeriod = state.periodDraft.length - 1; renderSchedule(); syncPeriod(); });
  $('#removePeriod').addEventListener('click', () => { if (state.periodDraft.length <= 1) return; state.periodDraft.splice(state.activePeriod,1); state.activePeriod = Math.max(0,state.activePeriod-1); renderSchedule(); syncPeriod(); });
  $('#saveSchedule').addEventListener('click', saveSchedule);
  $('#overrideDate').addEventListener('change', () => { if (state.overrideEditing && !confirm('Bỏ các thay đổi chưa lưu của ngày đang sửa?')) { $('#overrideDate').value = $('#overrideDate').dataset.previous || today(); return; } $('#overrideDate').dataset.previous = $('#overrideDate').value; state.overrideEditing = false; $('#overrideErrors').classList.add('hide'); renderOverride(); });
  $('#editOverride').addEventListener('click', () => { state.overrideEditing = true; renderOverride(); });
  $('#addOverrideShift').addEventListener('click', () => { state.overrideDraft = readShifts($('#overrideShifts'),false); state.overrideDraft.push(newShift(false)); renderOverride(); });
  $('#overrideShifts').addEventListener('click', event => { const button = event.target.closest('[data-remove-shift]'); if (!button || !state.overrideEditing) return; state.overrideDraft = readShifts($('#overrideShifts'),false); state.overrideDraft.splice(Number(button.dataset.removeShift),1); renderOverride(); });
  $('#saveOverride').addEventListener('click', saveOverride);
  $('#resetOverride').addEventListener('click', async () => { if (!confirm('Bỏ lịch riêng của ngày này và dùng lại lịch cố định?')) return; try { await api(`/api/overrides/${$('#overrideDate').value}`,{method:'DELETE'}); state.overrideEditing = false; await loadState(); await loadReport(); notice('Đã dùng lại lịch cố định.'); } catch (error) { fail(error); } });

  $('#orderStatus').addEventListener('change', renderOrders); $('#orderSearch').addEventListener('input', renderOrders);
  $('#orderTable').addEventListener('click', event => { const button = event.target.closest('[data-adjust]'); if (button) openAssignment(button.dataset.adjust); });
  $('#closeAssignment').addEventListener('click', () => $('#assignmentPanel').classList.add('hide'));
  $('#saveAssignment').addEventListener('click', async () => {
    if (!state.activeOrder) return;
    try { await api(`/api/manual/${encodeURIComponent(state.activeOrder.id)}`,{method:'PUT',body:json({staffId:Number($('#assignmentStaff').value),reason:$('#assignmentReason').value})}); $('#assignmentPanel').classList.add('hide'); notice(`Đã điều chỉnh đơn ${state.activeOrder.id}.`); await loadReport(); }
    catch (error) { fail(error); }
  });
  $('#clearAssignment').addEventListener('click', async () => { if (!state.activeOrder) return; try { await api(`/api/manual/${encodeURIComponent(state.activeOrder.id)}`,{method:'DELETE'}); $('#assignmentPanel').classList.add('hide'); notice('Đã trở về gán theo lịch.'); await loadReport(); } catch (error) { fail(error); } });
  $('#exportOrders').addEventListener('click', () => { if (!state.report) return; downloadCsv('don-live.csv',['Mã đơn','Giờ tạo','Kênh','Trạng thái gán','Nhân viên','Lý do','Sản phẩm','Số lượng','Doanh số'],state.report.orders.flatMap(order => order.lines.map(line => [order.id,order.createdAt,order.channel,order.assignment.kind,order.assignment.staffId ? staffName(order.assignment.staffId) : '',order.assignment.reason,line.product,line.qty,line.revenue]))); });

  $('#rateList').addEventListener('click', async event => { const button = event.target.closest('[data-save-rate]'); if (!button) return; const row = button.closest('[data-rate-staff]'); const inputs = $$('input',row); try { await api('/api/rates',{method:'POST',body:json({staffId:Number(button.dataset.saveRate),rate:Number(inputs[0].value),effectiveFrom:inputs[1].value})}); notice('Đã lưu tỷ lệ và ngày hiệu lực. Kỳ đã chốt không đổi.'); await loadState(); await loadReport(); } catch (error) { fail(error); } });
  $('#closePayroll').addEventListener('click', async () => { const from = $('#payrollFrom').value, to = $('#payrollTo').value; if (!confirm(`Chốt hoa hồng từ ${dateText(from)} đến ${dateText(to)}? Kết quả sẽ được giữ cố định.`)) return; try { const result = await api('/api/payroll/close',{method:'POST',body:json({from,to})}); notice(`Đã chốt kỳ #${result.id}: ${money(result.totals.commission)} hoa hồng.`); await loadState(); } catch (error) { fail(error); } });
  $('#payrollClosures').addEventListener('click', async event => { const button = event.target.closest('[data-view-closure]'); if (!button) return; try { const result = await api(`/api/payroll/${button.dataset.viewClosure}`); $('#snapshotPanel').classList.remove('hide'); $('#snapshotHeading').textContent = `Kỳ #${result.id} · ${dateText(result.from)} – ${dateText(result.to)}`; $('#snapshotContent').innerHTML = `<p>Chốt lúc ${new Date(result.closedAt).toLocaleString('vi-VN')}${result.reopenedAt ? ' · Đã mở lại' : ''}. Hoa hồng: <strong>${money(result.snapshot.totals.commission)}</strong></p><div class="table-scroll"><table><thead><tr><th>Nhân viên</th><th>Đơn</th><th>Doanh số</th><th>Hoa hồng</th></tr></thead><tbody>${result.snapshot.staff.map(row => `<tr><td>${escape(row.staff)}</td><td>${count(row.orders)}</td><td>${money(row.revenue)}</td><td>${money(row.commission)}</td></tr>`).join('')}</tbody></table></div>${isAdmin() && !result.reopenedAt ? `<div class="form-row"><label class="grow">Lý do mở lại kỳ<input id="reopenReason" placeholder="Ví dụ: cần nhập bổ sung đơn thiếu"></label><button id="reopenPayroll" class="button danger" data-id="${result.id}">Mở lại kỳ</button></div>` : ''}`; $('#snapshotPanel').scrollIntoView({behavior:'smooth'}); } catch (error) { fail(error); } });
  $('#snapshotContent').addEventListener('click', async event => { const button = event.target.closest('#reopenPayroll'); if (!button) return; try { await api(`/api/payroll/${button.dataset.id}/reopen`,{method:'POST',body:json({reason:$('#reopenReason').value})}); notice('Đã mở lại kỳ; có thể sửa và chốt lại.'); $('#snapshotPanel').classList.add('hide'); await loadState(); } catch (error) { fail(error); } });
  $('#closeSnapshot').addEventListener('click', () => $('#snapshotPanel').classList.add('hide'));
  $('#exportPayroll').addEventListener('click', () => { if (!state.report) return; downloadCsv('hoa-hong-tam-tinh.csv',['Nhân viên','Số đơn','Số lượng','Doanh số','Hoa hồng tạm tính'],state.report.staff.map(row => [row.staff,row.orders,row.qty,row.revenue,row.commission])); });

  $('#addStaffForm').addEventListener('submit', async event => { event.preventDefault(); const name = new FormData(event.currentTarget).get('name'); try { await api('/api/staff',{method:'POST',body:json({name})}); event.currentTarget.reset(); notice('Đã thêm nhân viên.'); await loadState(); } catch (error) { fail(error); } });
  $('#downloadBackup').addEventListener('click', () => { downloadBackup(); notice('Đang tải dữ liệu của máy này. Hãy giữ file ở nơi an toàn.'); });
  $('#serverBackup').addEventListener('click', async () => { try { const result = await api('/api/backup/server',{method:'POST'}); notice(`Đã tạo bản sao lưu ${result.file} trong thư mục data/backups của máy này.`); } catch (error) { fail(error); } });
  $('#portableFile').addEventListener('change', event => { state.portableFile = event.target.files[0] || null; state.portableHash = ''; $('#previewPortable').disabled = !state.portableFile || !isAdmin(); $('#portablePreview').classList.add('hide'); });
  $('#previewPortable').addEventListener('click', async () => {
    if (!state.portableFile) return;
    const form = new FormData(); form.append('file',state.portableFile);
    try {
      const result = await api('/api/backup/preview',{method:'POST',body:form}); state.portableHash = result.sha256;
      previewBox('#portablePreview', `<strong>Dữ liệu từ ${escape(state.portableFile.name)}</strong><div class="preview-stats"><span><b>${count(result.staff)}</b>nhân viên</span><span><b>${count(result.periods)}</b>khoảng lịch</span><span><b>${count(result.orders)}</b>đơn</span><span><b>${count(result.manual)}</b>đơn chỉnh tay</span><span><b>${count(result.closures)}</b>kỳ đã chốt</span></div><p>Máy này hiện có ${count(result.currentOrders)} đơn. Sau khi nhập, toàn bộ dữ liệu nghiệp vụ hiện tại sẽ được thay bằng file này.</p><button id="commitPortable" class="button danger">Thay dữ liệu trên máy này</button>`);
    } catch (error) { fail(error); }
  });
  $('#portablePreview').addEventListener('click', async event => {
    if (event.target.id !== 'commitPortable' || !state.portableFile) return;
    if (!confirm('Thay toàn bộ lịch, đơn và hoa hồng trên máy này bằng file đã xem trước? Ứng dụng sẽ sao lưu SQLite hiện tại trước khi thay.')) return;
    const form = new FormData(); form.append('file',state.portableFile); form.append('sha256',state.portableHash);
    event.target.disabled = true;
    try {
      const result = await api('/api/backup/commit',{method:'POST',body:form});
      $('#portablePreview').classList.add('hide'); $('#portableFile').value = ''; state.portableFile = null; state.portableHash = ''; $('#previewPortable').disabled = true;
      state.activePeriod = 0; state.overrideEditing = false; $('#snapshotPanel').classList.add('hide');
      await loadState(); await loadReport(); await loadAdminPanels();
      notice(`Đã nhập ${result.orders} đơn và ${result.periods} khoảng lịch trên máy này.`);
    } catch (error) { event.target.disabled = false; fail(error); }
  });
  $('#legacyFile').addEventListener('change', event => { state.legacyFile = event.target.files[0] || null; state.legacyHash = ''; $('#previewLegacy').disabled = !state.legacyFile || !isAdmin(); $('#legacyPreview').classList.add('hide'); });
  $('#previewLegacy').addEventListener('click', async () => { if (!state.legacyFile) return; const form = new FormData(); form.append('file',state.legacyFile); try { const result = await api('/api/legacy/preview',{method:'POST',body:form}); state.legacyHash = result.sha256; previewBox('#legacyPreview', `<strong>Bản sao lưu: ${escape(state.legacyFile.name)}</strong><div class="preview-stats"><span><b>${count(result.orders)}</b>đơn</span><span><b>${count(result.existingOrders)}</b>đơn trùng mã</span><span><b>${count(result.periods)}</b>khoảng lịch</span></div><p>Nhân viên: ${result.staff.map(escape).join(', ') || 'Không có'}.</p><label class="day-pill"><input id="replaceLegacySchedule" type="checkbox"> Thay lịch, lịch riêng và tỷ lệ hiện tại bằng dữ liệu trong bản sao lưu</label><p class="muted small-text">Đơn trùng mã sẽ được cập nhật. Nếu không đánh dấu, giữ lịch và tỷ lệ trên máy này.</p><button id="commitLegacy" class="button primary">Nhập dữ liệu cũ trên máy này</button>`); } catch (error) { fail(error); } });
  $('#legacyPreview').addEventListener('click', async event => { if (event.target.id !== 'commitLegacy' || !state.legacyFile) return; const replaceSchedule = $('#replaceLegacySchedule').checked; if (!confirm(`Nhập ${state.legacyFile.name} trên máy này? ${replaceSchedule ? 'Lịch và tỷ lệ hiện tại sẽ được thay.' : 'Lịch hiện tại được giữ.'}`)) return; const form = new FormData(); form.append('file',state.legacyFile); form.append('sha256',state.legacyHash); form.append('replaceSchedule',String(replaceSchedule)); event.target.disabled = true; try { const result = await api('/api/legacy/commit',{method:'POST',body:form}); $('#legacyPreview').classList.add('hide'); $('#legacyFile').value = ''; state.legacyFile = null; $('#previewLegacy').disabled = true; notice(`Đã chuyển ${result.orders} đơn từ công cụ cũ.${result.replacedSchedule ? ' Đã thay lịch theo file sao lưu.' : ''}`); await loadState(); await loadReport(); await loadAdminPanels(); } catch (error) { event.target.disabled = false; fail(error); } });

  boot();
})();

/* ════════════════════════════════════════════════════════════
   Claude Bot — Dashboard istemcisi
   ════════════════════════════════════════════════════════════ */
(() => {
  'use strict';

  // ── Yardımcılar ────────────────────────────────────────────
  const $  = (sel, root = document) => root.querySelector(sel);
  const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];

  const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => (
    { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]
  ));
  const icon = (name, cls = 'sm') => `<svg class="i ${cls}"><use href="#i-${name}"/></svg>`;
  const pad  = (n) => String(n).padStart(2, '0');
  const lower = (s) => String(s || '').toLocaleLowerCase('tr');
  const enc = encodeURIComponent;

  const storage = {
    get(k, d) { try { return localStorage.getItem(k) ?? d; } catch { return d; } },
    set(k, v) { try { localStorage.setItem(k, v); } catch {} },
  };

  async function api(url, opts = {}) {
    if (opts.json !== undefined) {
      opts = { ...opts, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(opts.json) };
      delete opts.json;
    }
    const res = await fetch(url, opts);
    let data = {};
    try { data = await res.json(); } catch {}
    if (!res.ok) {
      const detail = Array.isArray(data.detail) ? data.detail.map((d) => d.msg).join(', ') : data.detail;
      throw new Error(detail || `HTTP ${res.status}`);
    }
    return data;
  }
  const errText = (err) => (err.message === 'Failed to fetch' ? 'Sunucuya bağlanılamadı' : err.message);

  async function copyText(text, what = 'Kopyalandı') {
    try { await navigator.clipboard.writeText(text); toast(what, 'success', 2000); }
    catch { toast('Panoya kopyalanamadı', 'error'); }
  }

  // ── Zaman biçimleri ────────────────────────────────────────
  const MIN = 60e3, HOUR = 60 * MIN, DAY = 24 * HOUR;

  function startOfDay(d) { const x = new Date(d); x.setHours(0, 0, 0, 0); return x; }

  function dayLabel(date) {
    const diff = Math.round((startOfDay(date) - startOfDay(new Date())) / DAY);
    if (diff === 0)  return 'Bugün';
    if (diff === 1)  return 'Yarın';
    if (diff === -1) return 'Dün';
    return date.toLocaleDateString('tr-TR', { weekday: 'short', day: 'numeric', month: 'short' });
  }

  const hhmm = (d) => `${pad(d.getHours())}:${pad(d.getMinutes())}`;
  const whenLabel = (d) => `${dayLabel(d)} ${hhmm(d)}`;

  function relSpan(ms) {
    ms = Math.abs(ms);
    if (ms < MIN) return 'birkaç saniye';
    const d = Math.floor(ms / DAY), h = Math.floor((ms % DAY) / HOUR), m = Math.floor((ms % HOUR) / MIN);
    if (d) return h ? `${d} gün ${h} sa` : `${d} gün`;
    if (h) return m ? `${h} sa ${m} dk` : `${h} sa`;
    return `${m} dk`;
  }
  const rel = (date) => {
    const diff = date - Date.now();
    return `${relSpan(diff)} ${diff >= 0 ? 'sonra' : 'önce'}`;
  };

  function duration(sec) {
    if (sec == null) return '—';
    if (sec < 60) return `${Math.round(sec)} sn`;
    const m = Math.floor(sec / 60), s = Math.round(sec % 60);
    return s ? `${m} dk ${s} sn` : `${m} dk`;
  }

  // <input type="datetime-local"> değeri (yerel saat)
  const toLocalInput = (d) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;

  // ── Cron ↔ { time, days } ──────────────────────────────────
  const DAYS = [
    { label: 'Pzt', long: 'Pazartesi', value: 1 },
    { label: 'Sal', long: 'Salı',      value: 2 },
    { label: 'Çar', long: 'Çarşamba',  value: 3 },
    { label: 'Per', long: 'Perşembe',  value: 4 },
    { label: 'Cum', long: 'Cuma',      value: 5 },
    { label: 'Cmt', long: 'Cumartesi', value: 6 },
    { label: 'Paz', long: 'Pazar',     value: 0 },
  ];
  const ALL_DAYS = [0, 1, 2, 3, 4, 5, 6];

  // "30 9 * * 1-5" → { time: "09:30", days: [1..5], custom: false }
  // Panelin ifade edemediği cron'lar (*/5, belirli ay günü vb.) custom=true döner.
  function cronToSimple(cron) {
    const parts = String(cron || '').trim().split(/\s+/);
    const fallback = { time: '09:00', days: [...ALL_DAYS], custom: !!cron };
    if (parts.length !== 5) return fallback;
    const [min, hour, dom, mon, dow] = parts;
    if (!/^\d+$/.test(min) || !/^\d+$/.test(hour) || dom !== '*' || mon !== '*') return fallback;

    const time = `${pad(+hour)}:${pad(+min)}`;
    if (dow === '*') return { time, days: [...ALL_DAYS], custom: false };

    const days = new Set();
    for (const item of dow.split(',')) {
      const range = item.match(/^(\d)-(\d)$/);
      if (range) { for (let i = +range[1]; i <= +range[2]; i++) days.add(i % 7); }
      else if (/^\d$/.test(item)) days.add(+item % 7);
      else return { ...fallback, time };
    }
    return { time, days: [...days], custom: false };
  }

  // { time: "09:30", days: [1..5] } → "30 9 * * 1-5"
  function simpleToCron(time, days) {
    const [h, m] = (time || '09:00').split(':').map(Number);
    const set = new Set(days.length ? days : ALL_DAYS);
    let dow;
    if (set.size === 7) dow = '*';
    else if (set.size === 5 && [1, 2, 3, 4, 5].every((d) => set.has(d))) dow = '1-5';
    else if (set.size === 2 && set.has(0) && set.has(6)) dow = '0,6';
    else dow = [...set].sort((a, b) => a - b).join(',');
    return `${m} ${h} * * ${dow}`;
  }

  function presetOf(days) {
    const set = new Set(days);
    if (set.size === 7 || set.size === 0) return 'all';
    if (set.size === 5 && [1, 2, 3, 4, 5].every((d) => set.has(d))) return 'weekdays';
    if (set.size === 2 && set.has(0) && set.has(6)) return 'weekend';
    return null;
  }

  function daysLabel(days) {
    const p = presetOf(days);
    if (p === 'all') return 'Her gün';
    if (p === 'weekdays') return 'Hafta içi';
    if (p === 'weekend') return 'Hafta sonu';
    const picked = DAYS.filter((d) => days.includes(d.value));
    return picked.length === 1 ? `Her ${picked[0].long}` : picked.map((d) => d.label).join(', ');
  }

  function humanCron(cron) {
    const s = cronToSimple(cron);
    return s.custom ? `Özel: ${cron}` : `${daysLabel(s.days)} · ${s.time}`;
  }

  // ── Durum ──────────────────────────────────────────────────
  const state = {
    status: 'idle',
    data: null,
    jobs: [],
    upcoming: [],
    paused: false,
    shots: [],
    view: 'overview',
  };

  const STATUS = {
    idle:       { pill: 'Bekliyor',    title: 'Şu an <em>bekliyor</em>',    icon: 'moon-z' },
    running:    { pill: 'Çalışıyor',   title: 'Şu an <em>çalışıyor</em>',   icon: 'bolt' },
    success:    { pill: 'Başarılı',    title: 'Son görev <em>başarılı</em>', icon: 'check' },
    error:      { pill: 'Hata',        title: 'Son görev <em>hatalı</em>',   icon: 'alert' },
    no_session: { pill: 'Oturum yok',  title: 'Oturum <em>bulunamadı</em>',  icon: 'key' },
  };

  // Geçmişteki çalışma durumları ve tetikleyiciler
  const RUN = {
    success: { label: 'Başarılı', cls: 'ok',   icon: 'check' },
    error:   { label: 'Hata',     cls: 'err',  icon: 'alert' },
    session: { label: 'Oturum',   cls: 'warn', icon: 'key' },
    skipped: { label: 'Atlandı',  cls: 'off',  icon: 'skip' },
    running: { label: 'Sürüyor',  cls: 'acc',  icon: 'bolt' },
  };
  const TRIGGERS = { scheduled: 'Zamanlı', manual: 'Manuel', retry: 'Tekrar', once: 'Tek seferlik', cli: 'Terminal' };

  // ── Tema ───────────────────────────────────────────────────
  const media = matchMedia('(prefers-color-scheme: light)');

  function applyTheme(pref) {
    const dark = pref === 'dark' || (pref === 'system' && !media.matches);
    const root = document.documentElement;
    root.dataset.theme = dark ? 'dark' : 'light';
    root.dataset.themePref = pref;
    $('meta[name="theme-color"]').content = dark ? '#0d0c0b' : '#f4f1eb';
    $$('[data-theme-set]').forEach((b) => b.setAttribute('aria-pressed', String(b.dataset.themeSet === pref)));
  }
  function setTheme(pref) { storage.set('cb-theme', pref); applyTheme(pref); }

  media.addEventListener('change', () => {
    if (document.documentElement.dataset.themePref === 'system') applyTheme('system');
  });
  $$('[data-theme-set]').forEach((b) => b.addEventListener('click', () => setTheme(b.dataset.themeSet)));
  applyTheme(document.documentElement.dataset.themePref || 'system');

  // ── Toast ──────────────────────────────────────────────────
  function toast(msg, type = 'info', duration = 3800) {
    const icons = { success: 'check', error: 'alert', info: 'info' };
    const el = document.createElement('div');
    el.className = `toast ${type}`;
    el.innerHTML = `<span class="toast-icon">${icon(icons[type] || 'info')}</span><span>${esc(msg)}</span>`;
    $('#toasts').appendChild(el);
    setTimeout(() => { el.classList.add('out'); el.addEventListener('animationend', () => el.remove()); }, duration);
  }

  // ── Yönlendirme ────────────────────────────────────────────
  const VIEWS = {
    overview: { title: 'Genel <em>Bakış</em>',      sub: 'Botun nabzı, tek bakışta',             doc: 'Genel Bakış' },
    history:  { title: 'Çalışma <em>Geçmişi</em>',  sub: 'Her çalışma, Claude\'un her yanıtı',    doc: 'Geçmiş' },
    logs:     { title: 'Canlı <em>Loglar</em>',     sub: 'Botun her adımı, gerçek zamanlı',      doc: 'Loglar' },
    config:   { title: 'Görev <em>Planı</em>',      sub: 'Ne zaman, nereye, ne yazılacak',        doc: 'Görevler' },
    gallery:  { title: 'Ekran <em>Galerisi</em>',   sub: 'Her çalışmadan kalan kareler',          doc: 'Galeri' },
  };
  const VIEW_KEYS = { 1: 'overview', 2: 'history', 3: 'logs', 4: 'config', 5: 'gallery' };

  function navigate(view, { push = true } = {}) {
    if (!VIEWS[view]) view = 'overview';
    state.view = view;
    closeMenu();
    if (drawer.classList.contains('open')) closeDrawer();
    if (oneoff.classList.contains('open')) closeOneOff();
    closeLightbox();
    $$('.view').forEach((v) => v.classList.toggle('active', v.id === `view-${view}`));
    $$('.nav-item').forEach((n) => n.classList.toggle('active', n.dataset.view === view));
    $('#page-title').innerHTML = VIEWS[view].title;
    $('#page-sub').textContent = VIEWS[view].sub;
    document.title = `${VIEWS[view].doc} · Claude Bot`;
    if (push && location.hash !== `#${view}`) history.replaceState(null, '', `#${view}`);
    window.scrollTo({ top: 0 });

    if (view === 'overview') { loadHeatmap(); loadSession(); }
    if (view === 'history')  loadRuns(true);
    if (view === 'logs')     startLogStream();
    if (view === 'gallery')  loadShots();
    if (view === 'config' && !config.dirty) loadConfig();
  }

  window.addEventListener('hashchange', () => navigate(location.hash.slice(1), { push: false }));
  window.addEventListener('scroll', () => {
    $('#topbar').classList.toggle('scrolled', window.scrollY > 4);
    closeMenu();
  }, { passive: true });

  // ── Saat ───────────────────────────────────────────────────
  function tickClock() { $('#clock').textContent = new Date().toLocaleTimeString('tr-TR'); }

  // ══════════════════════════════════════════════════════════
  //  GENEL BAKIŞ
  // ══════════════════════════════════════════════════════════
  async function refreshStatus() {
    try {
      const [data, jobs] = await Promise.all([api('/api/status'), api('/api/jobs').catch(() => null)]);
      const prev = state.status;
      state.data = data;
      state.status = STATUS[data.status] ? data.status : 'idle';
      state.paused = !!data.paused;
      if (jobs) {
        state.jobs = jobs.jobs || [];
        state.upcoming = jobs.upcoming || [];
        state.schedulerRunning = jobs.running;
      }

      renderStatus();
      renderJobRows();
      renderUpcoming();
      renderTimeline();
      renderLastRun();
      tickCountdown();
      syncHistoryJobs();

      if (prev === 'running' && state.status !== 'running') {
        if (state.status === 'success') toast('Görev başarıyla tamamlandı', 'success');
        if (state.status === 'error')   toast('Görev hata ile sonuçlandı', 'error');
        loadHeatmap();
        loadSession();
        if (state.view === 'history') loadRuns(true);
        if (state.view === 'gallery') loadShots();
      }
    } catch (err) {
      console.error('Durum alınamadı:', err);
    }
  }

  let pollTimer;
  async function poll() {
    clearTimeout(pollTimer);
    await refreshStatus();
    pollTimer = setTimeout(poll, state.status === 'running' ? 2000 : 8000);
  }

  function renderStatus() {
    const d = state.data || {};
    const running = state.status === 'running';
    const pausedView = state.paused && !running;
    const s = STATUS[state.status];
    document.body.dataset.status = state.status;
    document.body.dataset.paused = String(pausedView);

    const pill = $('#rail-pill');
    pill.dataset.s = state.status;
    pill.innerHTML = `<span class="dot"></span>${s.pill}`;

    const active = state.jobs.filter((j) => j.enabled).length;
    $('#rail-sched').textContent = state.paused ? 'Duraklatıldı'
      : state.schedulerRunning === false ? 'Durdu' : `${active} aktif görev`;

    $('#hero-title').innerHTML = pausedView ? 'Zamanlayıcı <em>duraklatıldı</em>' : s.title;
    $('#orb-icon').setAttribute('href', `#i-${pausedView ? 'pause' : s.icon}`);

    const last = d.last_run ? new Date(d.last_run) : null;
    let desc;
    if (running)                            desc = 'Claude\'a mesaj gönderiliyor — her adımı Loglar\'dan canlı izleyebilirsiniz.';
    else if (state.status === 'no_session') desc = 'Kayıtlı oturum yok. Terminalde python main.py --save-session ile giriş yapın.';
    else if (pausedView)                    desc = 'Zamanlanmış çalışmalar durdu. Elle çalıştırma yine de mümkün.';
    else if (last)                          desc = `Son çalışma ${rel(last)} · ${whenLabel(last)}`;
    else                                    desc = 'Henüz hiç çalıştırılmadı.';
    $('#hero-desc').textContent = desc;

    // Performans halkası (tüm zamanlar)
    const total = d.stats?.total ?? 0, ok = d.stats?.success ?? 0, bad = d.stats?.error ?? 0;
    $('#stat-total').textContent = total;
    $('#stat-success').textContent = ok;
    $('#stat-error').textContent = bad;
    const C = 2 * Math.PI * 42;
    const okLen = total ? (ok / total) * C : 0;
    const errLen = total ? (bad / total) * C : 0;
    $('#ring-ok').setAttribute('stroke-dasharray', `${okLen} ${C}`);
    $('#ring-err').setAttribute('stroke-dasharray', `${errLen} ${C}`);
    $('#ring-err').setAttribute('stroke-dashoffset', `${-okLen}`);
    // Sıfır uzunluklu yay, yuvarlak ucu yüzünden nokta olarak çizilir — gizle
    $('#ring-ok').style.opacity = okLen ? 1 : 0;
    $('#ring-err').style.opacity = errLen ? 1 : 0;
    $('#ring-rate').textContent = total ? `%${Math.round((ok / total) * 100)}` : '—';

    // Butonlar
    const btn = $('#btn-run-now');
    btn.disabled = running;
    btn.innerHTML = running
      ? '<span class="spinner"></span><span>Çalışıyor…</span>'
      : `${icon('play')}<span>Şimdi Çalıştır</span>`;
    $$('[data-run-job]').forEach((b) => { b.disabled = running; });

    const pauseBtn = $('#btn-pause-all');
    pauseBtn.classList.toggle('on', state.paused);
    pauseBtn.innerHTML = state.paused ? `${icon('play')}<span>Sürdür</span>` : `${icon('pause')}<span>Duraklat</span>`;
    pauseBtn.title = state.paused ? 'Zamanlanmış çalışmaları sürdür' : 'Tüm zamanlanmış çalışmaları duraklat';

    const first = state.jobs.find((j) => j.enabled);
    $('#run-hint').textContent = first ? `Varsayılan: ilk aktif görev “${first.id}”` : 'Aktif görev yok';

    // Uyarı
    const slot = $('#alert-slot');
    if (d.last_error) {
      slot.hidden = false;
      slot.innerHTML = `
        <div class="alert">
          <div class="alert-icon">${icon('alert')}</div>
          <div class="alert-body">
            <div class="alert-title">Son hata</div>
            <pre>${esc(d.last_error)}</pre>
          </div>
          <a class="btn btn-ghost sm" href="#logs">${icon('terminal')}Loglar</a>
        </div>`;
    } else if (state.status === 'no_session') {
      slot.hidden = false;
      slot.innerHTML = `
        <div class="alert warn">
          <div class="alert-icon">${icon('key')}</div>
          <div class="alert-body">
            <div class="alert-title">Oturum gerekli</div>
            <pre>python main.py --save-session</pre>
          </div>
        </div>`;
    } else {
      slot.hidden = true;
      slot.innerHTML = '';
    }
  }

  // Planlanmış tüm çalışmalar: cron görevleri, tek seferlikler, tekrar denemeleri ve atlananlar
  function plannedRuns() {
    const items = [];
    for (const j of state.jobs) {
      if (!j.enabled) continue;
      if (j.next_run)    items.push({ at: new Date(j.next_run), job: j.id, kind: 'cron' });
      if (j.skipped_run) items.push({ at: new Date(j.skipped_run), job: j.id, kind: 'skip' });
    }
    for (const u of state.upcoming) {
      if (!u.paused) items.push({ at: new Date(u.run_at), job: u.job_id, kind: u.kind });
    }
    return items.sort((a, b) => a.at - b.at);
  }

  function nextRun() {
    const now = Date.now() - 5000;
    return plannedRuns().find((p) => p.kind !== 'skip' && p.at >= now) || null;
  }

  let zeroRefreshAt = 0;
  function tickCountdown() {
    const n = state.paused ? null : nextRun();
    const val = $('#cd-value');
    if (!n) {
      $('#cd-label').textContent = 'Sonraki çalışma';
      val.innerHTML = '--<span class="sep">:</span>--<span class="sep">:</span>--';
      $('#cd-at').innerHTML = state.paused
        ? `<span class="paused-note">${icon('pause')}Duraklatıldı</span>`
        : 'Zamanlanmış görev yok';
      return;
    }
    const kind = { once: ' · tek seferlik', retry: ' · tekrar' }[n.kind] || '';
    $('#cd-label').innerHTML = `Sonraki çalışma · <b>${esc(n.job)}</b>${kind}`;
    $('#cd-at').textContent = whenLabel(n.at);

    let ms = n.at - Date.now();
    if (ms <= 0) {
      val.textContent = 'Şimdi';
      if (Date.now() - zeroRefreshAt > 5000) { zeroRefreshAt = Date.now(); setTimeout(poll, 1500); }
      return;
    }
    const d = Math.floor(ms / DAY); ms %= DAY;
    const h = Math.floor(ms / HOUR); ms %= HOUR;
    const m = Math.floor(ms / MIN);
    const s = Math.floor((ms % MIN) / 1000);
    const sep = '<span class="sep">:</span>';
    val.innerHTML = `${d ? `${d}<span class="sep">g </span>` : ''}${pad(h)}${sep}${pad(m)}${sep}${pad(s)}`;
  }

  // Önümüzdeki 24 saati kaydırmalı bir cetvel olarak çizer
  function renderTimeline() {
    const track = $('#track');
    const now = Date.now(), end = now + DAY;
    const pos = (t) => ((t - now) / DAY) * 100;
    let html = '<div class="track-bar"></div><div class="track-now" data-label="şimdi"></div>';

    const t0 = new Date(now); t0.setMinutes(0, 0, 0); t0.setHours(t0.getHours() + 1);
    for (let t = t0.getTime(); t < end; t += HOUR) {
      const h = new Date(t).getHours();
      if (h % 3) continue;
      const p = pos(t);
      html += `<div class="track-tick" style="left:${p}%"></div>`;
      if (p > 7 && p < 95) html += `<div class="track-label" style="left:${p}%">${pad(h)}:00</div>`;
    }

    // Aynı dakikaya ve türe düşen çalışmaları birleştir
    const groups = new Map();
    if (!state.paused) {
      for (const p of plannedRuns()) {
        const t = p.at.getTime();
        if (t < now || t > end) continue;
        const key = `${Math.floor(t / MIN)}:${p.kind}`;
        if (!groups.has(key)) groups.set(key, { t, kind: p.kind, ids: [] });
        groups.get(key).ids.push(p.job);
      }
    }
    const marks = [...groups.values()].sort((a, b) => a.t - b.t);
    const firstReal = marks.find((g) => g.kind !== 'skip');
    const prefix = { skip: 'atla · ', once: 'bir kez · ', retry: 'tekrar · ' };
    marks.forEach((g) => {
      const label = `${hhmm(new Date(g.t))} · ${prefix[g.kind] || ''}${g.ids.join(', ')}`;
      const cls = [g === firstReal ? 'next' : '', g.kind === 'cron' ? '' : g.kind].join(' ');
      html += `<div class="track-mark ${cls}" style="left:${Math.min(Math.max(pos(g.t), 4), 96)}%" title="${esc(label)}">
        <span class="flag">${esc(label)}</span><span class="stem"></span></div>`;
    });
    if (!marks.length) {
      html += `<div class="track-empty">${state.paused ? 'Zamanlayıcı duraklatıldı' : 'Bu aralıkta planlı çalışma yok'}</div>`;
    }

    track.innerHTML = html;
    const total = marks.filter((g) => g.kind !== 'skip').reduce((n, g) => n + g.ids.length, 0);
    $('#tl-count').textContent = total ? `${total} çalışma planlandı` : '';
  }

  function renderJobRows() {
    const el = $('#job-rows');
    if (!state.jobs.length) {
      el.innerHTML = `
        <div class="empty">
          <div class="empty-icon">${icon('calendar', 'lg')}</div>
          <div><b>Henüz görev yok</b>İlk görevinizi oluşturarak başlayın.</div>
          <a class="btn btn-primary sm" href="#config">${icon('plus')}Görev oluştur</a>
        </div>`;
      return;
    }
    const running = state.status === 'running';
    el.innerHTML = state.jobs.map((j) => {
      const s = cronToSimple(j.cron);
      const next = j.enabled && j.next_run && !state.paused ? new Date(j.next_run) : null;
      const chat = j.chat_id ? `${esc(j.chat_id.slice(0, 8))}…` : 'Global sohbet';
      const st = j.stats || { total: 0, success: 0 };
      const rate = st.total ? Math.round((st.success / st.total) * 100) : null;
      const rc = rate == null ? '' : rate >= 90 ? 'var(--ok)' : rate >= 60 ? 'var(--warn)' : 'var(--err)';
      const tags = [
        j.enabled ? '<span class="tag ok">Aktif</span>' : '<span class="tag off">Pasif</span>',
        j.skipped_run ? '<span class="tag warn">Sıradaki atlanacak</span>' : '',
        j.retries ? `<span class="tag" title="Hata olursa ${j.retries} kez tekrar denenir">${icon('retry')}${j.retries}</span>` : '',
      ].join(' ');
      let nextHtml;
      if (state.paused && j.enabled) nextHtml = 'Duraklatıldı';
      else if (next) nextHtml = `<b>${relSpan(next - Date.now())}</b>${j.skipped_run ? `<s>${hhmm(new Date(j.skipped_run))}</s> atlanıyor` : 'sonra'}`;
      else nextHtml = j.enabled ? 'Bekleniyor' : 'Çalışmayacak';
      return `
        <div class="job-row ${j.enabled ? '' : 'off'}">
          <div class="job-time"><b>${s.custom ? '••:••' : s.time}</b><small>${esc(s.custom ? 'özel' : daysLabel(s.days))}</small></div>
          <div class="job-main">
            <div class="job-name">${esc(j.id)} ${tags}</div>
            <div class="job-meta">
              <span>${icon('message')}<span class="mono">${chat}</span></span>
              <span>${icon('calendar')}${esc(humanCron(j.cron))}</span>
              ${rate == null ? '' : `<span class="job-rate" style="--rc:${rc}" title="${st.success}/${st.total} başarılı"><i></i>%${rate} · ${st.total} çalışma</span>`}
            </div>
            <div class="job-prompt" title="${esc(j.prompt_preview)}">${j.prompt_preview ? `“${esc(j.prompt_preview)}”` : '<span class="faint">Global prompt kullanılır</span>'}</div>
          </div>
          <div class="job-next">${nextHtml}</div>
          <div class="job-actions">
            <button type="button" class="btn btn-ghost sm icon" data-run-job="${esc(j.id)}" title="“${esc(j.id)}” görevini şimdi çalıştır" ${running ? 'disabled' : ''}>${icon('play')}</button>
            <button type="button" class="btn btn-quiet sm icon" data-job-menu="${esc(j.id)}" title="Diğer eylemler" aria-haspopup="menu">${icon('more')}</button>
          </div>
        </div>`;
    }).join('');
  }

  function renderUpcoming() {
    const el = $('#upcoming');
    if (!state.upcoming.length) { el.hidden = true; el.innerHTML = ''; return; }
    el.hidden = false;
    el.innerHTML = `<div class="upcoming-title">Ek planlar</div>` + state.upcoming.map((u) => {
      const at = new Date(u.run_at);
      const tag = u.kind === 'once' ? `<span class="tag acc">${icon('calendar')}Bir kez</span>` : `<span class="tag warn">${icon('retry')}Tekrar</span>`;
      return `
        <div class="upcoming-item">
          ${tag}<b>${esc(u.job_id)}</b>
          <span class="when">${whenLabel(at)}${u.paused ? ' · duraklatıldı' : ` · ${rel(at)}`}</span>
          <span class="spacer"></span>
          ${u.kind === 'once' ? `<button type="button" class="btn btn-quiet sm icon btn-danger" data-cancel-once="${u.id}" title="Planı iptal et">${icon('x')}</button>` : ''}
        </div>`;
    }).join('');
  }

  function renderLastRun() {
    const el = $('#last-run');
    const r = state.data?.last_run_record;
    if (!r) {
      el.innerHTML = `<div class="empty"><div class="empty-icon">${icon('sparkle', 'lg')}</div><div><b>Henüz çalışma yok</b>İlk çalışmadan sonra Claude'un yanıtı burada görünecek.</div></div>`;
      return;
    }
    const st = RUN[r.status] || RUN.error;
    const at = new Date(r.started_at);
    const body = r.status === 'success'
      ? (r.response_preview
          ? `<div class="reply-label">${icon('sparkle')}Claude'un yanıtı</div><div class="reply clamp">${esc(r.response_preview)}</div>`
          : '<div class="reply muted">Mesaj gönderildi; yanıt metni okunamadı.</div>')
      : `<div class="reply error">${esc(r.error || 'Bilinmeyen hata')}</div>`;
    el.innerHTML = `
      <div class="last-head">
        <span class="tag ${st.cls}">${icon(st.icon)}${st.label}</span>
        <b>${esc(r.job_id)}</b><span>· ${TRIGGERS[r.trigger] || r.trigger}</span>
        <span>· ${rel(at)}</span>
      </div>
      ${body}
      <div class="last-foot">
        ${r.screenshot ? `<button type="button" class="thumb" data-last-shot><img src="/screenshots/${esc(r.screenshot)}" alt="" loading="lazy" onerror="this.parentElement.remove()" /></button>` : ''}
        <span class="faint" style="font-size:12px">${whenLabel(at)} · ${duration(r.duration)}</span>
        <span class="spacer"></span>
        <button type="button" class="btn btn-ghost sm" data-open-run="${r.id}">Ayrıntılar${icon('chev-r')}</button>
      </div>`;
  }

  $('#last-run').addEventListener('click', (e) => {
    const r = state.data?.last_run_record;
    if (e.target.closest('[data-last-shot]') && r) openLightbox([shotFromRun(r)], 0);
    const open = e.target.closest('[data-open-run]');
    if (open) openRun(+open.dataset.openRun);
  });

  async function runNow(jobId = '') {
    if (state.status === 'running') return;
    const btn = $('#btn-run-now');
    btn.disabled = true;
    btn.innerHTML = '<span class="spinner"></span><span>Başlatılıyor…</span>';
    try {
      const data = await api(jobId ? `/api/run-now?job_id=${enc(jobId)}` : '/api/run-now', { method: 'POST' });
      toast(data.message || 'Görev başlatıldı', 'success');
      state.status = 'running';
      renderStatus();
      setTimeout(poll, 1200);
    } catch (err) {
      toast(errText(err), 'error');
      renderStatus();
    }
  }

  async function togglePause() {
    const paused = !state.paused;
    try {
      await api('/api/scheduler/pause', { method: 'POST', json: { paused } });
      toast(paused ? 'Zamanlanmış çalışmalar duraklatıldı' : 'Zamanlayıcı sürdürüldü', 'success');
      await poll();
    } catch (err) { toast(errText(err), 'error'); }
  }

  async function setSkip(jobId, skip) {
    try {
      await api(`/api/jobs/${enc(jobId)}/skip`, { method: skip ? 'POST' : 'DELETE' });
      toast(skip ? `“${jobId}” görevinin sıradaki çalışması atlanacak` : 'Atlama geri alındı', 'success');
      await poll();
    } catch (err) { toast(errText(err), 'error'); }
  }

  async function cancelOneOff(id) {
    try {
      await api(`/api/one-offs/${id}`, { method: 'DELETE' });
      toast('Plan iptal edildi', 'success');
      await poll();
    } catch (err) { toast(errText(err), 'error'); }
  }

  $('#btn-run-now').addEventListener('click', () => runNow());
  $('#btn-pause-all').addEventListener('click', togglePause);
  $('#btn-oneoff').addEventListener('click', () => openOneOff());
  $('#btn-refresh').addEventListener('click', async () => {
    const b = $('#btn-refresh');
    b.disabled = true;
    await Promise.all([poll(), loadHeatmap(), loadSession()]);
    b.disabled = false;
  });
  $('#job-rows').addEventListener('click', (e) => {
    const run = e.target.closest('[data-run-job]');
    if (run) return runNow(run.dataset.runJob);
    const more = e.target.closest('[data-job-menu]');
    if (more) openJobMenu(more, more.dataset.jobMenu);
  });
  $('#upcoming').addEventListener('click', (e) => {
    const b = e.target.closest('[data-cancel-once]');
    if (b) cancelOneOff(+b.dataset.cancelOnce);
  });

  // ── Görev eylem menüsü ─────────────────────────────────────
  const menu = $('#job-menu');

  function openJobMenu(anchor, jobId) {
    const j = state.jobs.find((x) => x.id === jobId);
    if (!j) return;
    if (!menu.hidden && menu.dataset.job === jobId) return closeMenu();
    const items = [
      ['play', 'Şimdi çalıştır', () => runNow(jobId), state.status === 'running'],
      ['calendar', 'Bir kez planla…', () => openOneOff(jobId)],
      j.skipped_run
        ? ['undo', 'Atlamayı geri al', () => setSkip(jobId, false)]
        : ['skip', 'Sıradakini atla', () => setSkip(jobId, true), !(j.enabled && j.next_run) || state.paused],
      null,
      ['history', 'Geçmişini gör', () => { historyState.job = jobId; navigate('history'); }],
      ['sliders', 'Düzenle', () => navigate('config')],
    ];
    menu.dataset.job = jobId;
    menu.innerHTML = items.map((it, i) => it
      ? `<button type="button" role="menuitem" data-i="${i}" ${it[3] ? 'disabled style="opacity:.45"' : ''}>${icon(it[0])}${it[1]}</button>`
      : '<hr />').join('');
    menu._items = items;
    menu.hidden = false;
    const r = anchor.getBoundingClientRect();
    const w = menu.offsetWidth, h = menu.offsetHeight;
    menu.style.left = `${Math.max(8, Math.min(r.right - w, innerWidth - w - 8))}px`;
    const top = r.bottom + 6 + h > innerHeight ? r.top - h - 6 : r.bottom + 6;
    menu.style.top = `${Math.max(8, Math.min(top, innerHeight - h - 8))}px`;
    $('button:not([disabled])', menu)?.focus();
  }
  function closeMenu() { menu.hidden = true; menu.dataset.job = ''; }

  menu.addEventListener('click', (e) => {
    const b = e.target.closest('button[data-i]');
    if (!b || b.disabled) return;
    const fn = menu._items[+b.dataset.i][2];
    closeMenu();
    fn();
  });
  document.addEventListener('click', (e) => {
    if (!menu.hidden && !menu.contains(e.target) && !e.target.closest('[data-job-menu]')) closeMenu();
  });

  // ── Tek seferlik planlama ──────────────────────────────────
  const oneoff = $('#oneoff-modal');

  function openOneOff(jobId) {
    if (!state.jobs.length) return toast('Önce bir görev oluşturun', 'info');
    const sel = $('#oneoff-job');
    sel.innerHTML = state.jobs.map((j) => `<option value="${esc(j.id)}">${esc(j.id)}${j.enabled ? '' : ' (pasif)'}</option>`).join('');
    sel.value = jobId || (state.jobs.find((j) => j.enabled) || state.jobs[0]).id;
    setQuickTime('1h');
    $('#oneoff-at').min = toLocalInput(new Date());
    oneoff.classList.add('open');
    $('#oneoff-at').focus();
  }
  function closeOneOff() { oneoff.classList.remove('open'); }

  function setQuickTime(kind) {
    const d = new Date();
    if (kind === '30m') d.setMinutes(d.getMinutes() + 30);
    if (kind === '1h') d.setHours(d.getHours() + 1);
    if (kind === 'tonight') { d.setHours(20, 0, 0, 0); if (d <= new Date()) d.setDate(d.getDate() + 1); }
    if (kind === 'tomorrow') { d.setDate(d.getDate() + 1); d.setHours(9, 0, 0, 0); }
    if (kind === '30m' || kind === '1h') d.setMinutes(Math.ceil(d.getMinutes() / 5) * 5, 0, 0);
    $('#oneoff-at').value = toLocalInput(d);
    $$('[data-quick]', oneoff).forEach((b) => b.classList.toggle('on', b.dataset.quick === kind));
  }

  $('#quick-times').addEventListener('click', (e) => { const b = e.target.closest('[data-quick]'); if (b) setQuickTime(b.dataset.quick); });
  $('#oneoff-at').addEventListener('input', () => $$('[data-quick]', oneoff).forEach((b) => b.classList.remove('on')));
  oneoff.addEventListener('click', (e) => { if (e.target === oneoff || e.target.closest('[data-close]')) closeOneOff(); });
  $('#oneoff-form').addEventListener('submit', async (e) => {
    e.preventDefault();
    const at = new Date($('#oneoff-at').value);
    if (isNaN(at) || at <= new Date()) return toast('Gelecekte bir zaman seçin', 'error');
    try {
      await api('/api/one-offs', { method: 'POST', json: { job_id: $('#oneoff-job').value, run_at: at.toISOString() } });
      closeOneOff();
      toast(`Planlandı: ${whenLabel(at)}`, 'success');
      await poll();
    } catch (err) { toast(errText(err), 'error'); }
  });

  // ── Çalışma takvimi ────────────────────────────────────────
  async function loadHeatmap() {
    try {
      const { days } = await api('/api/runs/heatmap?days=182');
      renderHeatmap(days);
    } catch (err) { console.error('Takvim alınamadı:', err); }
  }

  function renderHeatmap(days) {
    const fmt = (d) => d.toLocaleDateString('tr-TR', { day: 'numeric', month: 'short', weekday: 'short' });
    const first = new Date(`${days[0].date}T00:00`);
    const offset = (first.getDay() + 6) % 7;   // Pazartesi = 0
    const cells = [...Array(offset).fill(null), ...days];
    const cols = Math.ceil(cells.length / 7);

    const months = [];
    let lastMonth = -1;
    for (let c = 0; c < cols; c++) {
      const day = cells.slice(c * 7, c * 7 + 7).find(Boolean);
      const m = day ? new Date(`${day.date}T00:00`).getMonth() : lastMonth;
      months.push(m !== lastMonth && day ? new Date(`${day.date}T00:00`).toLocaleDateString('tr-TR', { month: 'short' }) : '');
      lastMonth = m;
    }

    const today = days[days.length - 1].date;
    const cellHtml = cells.map((d) => {
      if (!d) return '<span class="heat-cell pad"></span>';
      const n = d.success + d.error;
      let cls = '';
      if (d.error && d.success) cls = 'mix';
      else if (d.error) cls = 'err';
      else if (d.success) cls = `ok${Math.min(d.success, 3)}`;
      const title = `${fmt(new Date(`${d.date}T00:00`))} — ${n ? `${d.success} başarılı, ${d.error} hatalı` : 'çalışma yok'}`;
      return `<span class="heat-cell ${cls} ${d.date === today ? 'today' : ''}" title="${title}"></span>`;
    }).join('');

    // Seri: bugün (ya da henüz çalışmadıysa dün) geriye doğru kesintisiz başarılı günler
    let streak = 0;
    let i = days.length - 1;
    if (!days[i].success && !days[i].error) i--;
    for (; i >= 0 && days[i].success && !days[i].error; i--) streak++;

    const total = days.reduce((n, d) => n + d.success + d.error, 0);
    const ok = days.reduce((n, d) => n + d.success, 0);
    $('#heat-summary').textContent = total ? `Son 26 haftada ${total} çalışma · %${Math.round((ok / total) * 100)} başarı` : 'Son 26 hafta';

    $('#heatmap').innerHTML = `
      <div class="heat-days"><span>Pzt</span><span></span><span>Çar</span><span></span><span>Cum</span><span></span><span>Paz</span></div>
      <div class="heat-main">
        <div class="heat-months">${months.map((m) => `<span>${m}</span>`).join('')}</div>
        <div class="heat-grid">${cellHtml}</div>
      </div>
      <div class="heat-foot">
        <span class="lg"><i style="background:var(--surface-3)"></i>Yok</span>
        <span class="lg"><i class="heat-cell ok2"></i>Başarılı</span>
        <span class="lg"><i class="heat-cell mix"></i>Karışık</span>
        <span class="lg"><i class="heat-cell err"></i>Hatalı</span>
        <span class="spacer"></span>
        ${streak >= 2 ? `<span class="streak">${icon('bolt')}<b>${streak}</b> gündür kesintisiz</span>` : ''}
      </div>`;
    const main = $('.heat-main');
    main.scrollLeft = main.scrollWidth;  // dar ekranda en yeni haftalar görünsün
  }

  // ── Oturum sağlığı ─────────────────────────────────────────
  async function loadSession() {
    try { renderSession(await api('/api/session')); }
    catch (err) { console.error('Oturum bilgisi alınamadı:', err); }
  }

  function renderSession(s) {
    const card = $('#session-card');
    const cmd = 'python main.py --save-session';
    const cmdHint = `<div class="cmd-hint"><code>${cmd}</code><button type="button" class="btn btn-quiet sm icon" data-copy="${cmd}" title="Kopyala">${icon('copy')}</button></div>`;

    if (!s.exists || state.status === 'no_session') {
      card.dataset.health = 'err';
      $('#session-body').innerHTML = `
        <div class="session-state"><div class="session-badge">${icon('key', 'lg')}</div>
          <div><b>Oturum yok</b><small>Bot giriş yapamaz; önce oturum kaydedin.</small></div></div>${cmdHint}`;
      return;
    }
    const exp = s.expires_at ? new Date(s.expires_at) : null;
    const daysLeft = exp ? (exp - Date.now()) / DAY : null;
    const health = daysLeft == null ? 'warn' : daysLeft < 3 ? 'err' : daysLeft < 7 ? 'warn' : 'ok';
    card.dataset.health = health;
    const title = { ok: 'Sağlıklı', warn: daysLeft == null ? 'Süresi bilinmiyor' : 'Yakında yenilenmeli', err: daysLeft <= 0 ? 'Süresi doldu' : 'Süresi dolmak üzere' }[health];
    const pct = daysLeft == null ? 0 : Math.max(0, Math.min(daysLeft / 30, 1)) * 100;

    $('#session-body').innerHTML = `
      <div class="session-state"><div class="session-badge">${icon(health === 'ok' ? 'shield' : 'alert', 'lg')}</div>
        <div><b>${title}</b><small>${exp ? `${daysLeft > 0 ? `${Math.floor(daysLeft)} gün kaldı` : 'Yeniden giriş gerekli'}` : 'sessionKey çerezi bulunamadı'}</small></div></div>
      ${exp ? `<div class="life"><div class="life-top"><span>Oturum ömrü</span><b>${exp.toLocaleDateString('tr-TR', { day: 'numeric', month: 'long' })}</b></div><div class="life-bar"><i style="width:${pct}%"></i></div></div>` : ''}
      <div class="session-meta">
        <span><em>Son kayıt</em>${s.saved_at ? rel(new Date(s.saved_at)) : '—'}</span>
        <span><em>Çerez sayısı</em>${s.cookie_count}</span>
      </div>
      ${health === 'ok' ? '' : cmdHint}`;
  }

  $('#session-card').addEventListener('click', (e) => {
    const b = e.target.closest('[data-copy]');
    if (b) copyText(b.dataset.copy, 'Komut kopyalandı');
  });

  // ══════════════════════════════════════════════════════════
  //  GEÇMİŞ
  // ══════════════════════════════════════════════════════════
  const historyState = { job: '', status: '', runs: [], more: false, loading: false };
  const runList = $('#run-list');

  function syncHistoryJobs() {
    const sel = $('#history-job');
    const ids = state.jobs.map((j) => j.id);
    if (historyState.job && !ids.includes(historyState.job)) ids.push(historyState.job);
    const html = '<option value="">Tüm görevler</option>' + ids.map((id) => `<option value="${esc(id)}">${esc(id)}</option>`).join('');
    if (sel.innerHTML !== html) sel.innerHTML = html;
    sel.value = historyState.job;
  }

  async function loadRuns(reset = false) {
    if (historyState.loading) return;
    historyState.loading = true;
    syncHistoryJobs();
    if (reset) {
      historyState.runs = [];
      runList.innerHTML = Array(4).fill('<div class="skel" style="height:54px;margin:8px"></div>').join('');
    }
    const params = new URLSearchParams({ limit: '40' });
    if (historyState.job) params.set('job_id', historyState.job);
    if (historyState.status) params.set('status', historyState.status);
    const last = historyState.runs[historyState.runs.length - 1];
    if (!reset && last) params.set('before_id', last.id);
    try {
      const data = await api(`/api/runs?${params}`);
      historyState.runs.push(...data.runs);
      historyState.more = data.more;
      const c = data.counts || {};
      $('#hn-all').textContent = c.all || 0;
      for (const k of ['success', 'error', 'session', 'skipped']) $(`#hn-${k}`).textContent = c[k] || 0;
      renderRuns();
    } catch (err) {
      runList.innerHTML = `<div class="empty"><div class="empty-icon">${icon('alert', 'lg')}</div><div><b>Geçmiş yüklenemedi</b>${esc(errText(err))}</div></div>`;
    } finally {
      historyState.loading = false;
    }
  }

  function renderRuns() {
    $('#run-more').hidden = !historyState.more;
    if (!historyState.runs.length) {
      const filtered = historyState.job || historyState.status;
      runList.innerHTML = `<div class="empty"><div class="empty-icon">${icon('history', 'lg')}</div><div><b>${filtered ? 'Bu filtrede çalışma yok' : 'Henüz çalışma yok'}</b>Bot her çalıştığında sonucu ve Claude'un yanıtı burada birikir.</div></div>`;
      return;
    }
    let html = '', lastDay = '';
    for (const r of historyState.runs) {
      const at = new Date(r.started_at);
      const day = dayLabel(at);
      if (day !== lastDay) { html += `<div class="run-day">${esc(day)}</div>`; lastDay = day; }
      const st = RUN[r.status] || RUN.error;
      const text = r.status === 'success'
        ? `<div class="run-text">${r.response_preview ? esc(r.response_preview) : '<span class="faint">Yanıt metni yok</span>'}</div>`
        : `<div class="run-text ${r.status === 'skipped' ? '' : 'err'}">${esc(r.error || '')}</div>`;
      html += `
        <button type="button" class="run-row" data-run="${r.id}">
          <span class="run-icon ${st.cls}" title="${st.label}">${icon(st.icon)}</span>
          <span class="run-job"><b>${esc(r.job_id)}</b><small>${TRIGGERS[r.trigger] || esc(r.trigger)}${r.attempt > 1 ? ` · ${r.attempt}. deneme` : ''}</small></span>
          ${text}
          <span class="run-when"><b>${hhmm(at)}</b>${r.status === 'skipped' ? 'atlandı' : duration(r.duration)}</span>
        </button>`;
    }
    runList.innerHTML = html;
  }

  runList.addEventListener('click', (e) => { const b = e.target.closest('[data-run]'); if (b) openRun(+b.dataset.run); });
  $('#btn-run-more').addEventListener('click', () => loadRuns(false));
  $('#btn-history-refresh').addEventListener('click', () => loadRuns(true));
  $('#history-job').addEventListener('change', (e) => { historyState.job = e.target.value; loadRuns(true); });
  $('#history-status').addEventListener('click', (e) => {
    const chip = e.target.closest('.chip');
    if (!chip) return;
    historyState.status = chip.dataset.status;
    $$('.chip', $('#history-status')).forEach((c) => c.classList.toggle('on', c === chip));
    loadRuns(true);
  });

  // ── Çalışma ayrıntısı ──────────────────────────────────────
  const drawer = $('#drawer');
  let drawerRun = null;

  function shotFromRun(r) {
    return shotInfo({ filename: r.screenshot, url: r.screenshot_url || `/screenshots/${r.screenshot}`, timestamp: new Date(r.started_at).getTime() / 1000 });
  }

  async function openRun(id) {
    drawer.classList.add('open');
    $('#drawer-head').innerHTML = `<h3>Çalışma #${id}</h3><span class="spacer"></span><button type="button" class="btn btn-quiet sm icon" data-close title="Kapat (Esc)">${icon('x')}</button>`;
    $('#drawer-body').innerHTML = '<div class="skel" style="height:80px"></div><div class="skel" style="height:160px"></div>';
    try {
      drawerRun = await api(`/api/runs/${id}`);
      renderDrawer(drawerRun);
    } catch (err) {
      $('#drawer-body').innerHTML = `<div class="empty"><b>Yüklenemedi</b>${esc(errText(err))}</div>`;
    }
  }
  function closeDrawer() { drawer.classList.remove('open'); drawerRun = null; }

  function renderDrawer(r) {
    const st = RUN[r.status] || RUN.error;
    const at = new Date(r.started_at);
    $('#drawer-head').innerHTML = `
      <span class="run-icon ${st.cls}">${icon(st.icon)}</span>
      <div><h3>${esc(r.job_id)}</h3><span class="faint" style="font-size:12px">Çalışma #${r.id} · ${st.label}</span></div>
      <span class="spacer"></span>
      ${r.job_exists ? `<button type="button" class="btn btn-ghost sm" data-rerun ${state.status === 'running' ? 'disabled' : ''}>${icon('play')}Tekrar çalıştır</button>` : ''}
      <button type="button" class="btn btn-quiet sm icon" data-close title="Kapat (Esc)">${icon('x')}</button>`;

    const chat = r.chat_id
      ? `<a href="https://claude.ai/chat/${enc(r.chat_id)}" target="_blank" rel="noopener">${esc(r.chat_id.slice(0, 8))}… ${icon('external')}</a>`
      : 'Global';
    let html = `
      <div class="meta-grid">
        <div><small>Başlangıç</small><b>${whenLabel(at)}</b></div>
        <div><small>Süre</small><b>${r.status === 'skipped' ? '—' : duration(r.duration)}</b></div>
        <div><small>Tetikleyici</small><b>${TRIGGERS[r.trigger] || esc(r.trigger)}${r.attempt > 1 ? ` · ${r.attempt}. deneme` : ''}</b></div>
        <div><small>Sohbet</small><b>${chat}</b></div>
        <div><small>Bitiş</small><b>${r.finished_at ? hhmm(new Date(r.finished_at)) : '—'}</b></div>
        <div><small>Durum</small><b>${st.label}</b></div>
      </div>`;

    if (r.status === 'success' || r.response) {
      html += `
        <section class="d-section">
          <h4>${icon('sparkle')}Claude'un yanıtı<span class="spacer"></span>${r.response ? `<button type="button" class="btn btn-quiet sm" data-copy-response>${icon('copy')}Kopyala</button>` : ''}</h4>
          ${r.response ? `<div class="reply">${esc(r.response)}</div>` : '<div class="reply muted">Yanıt metni okunamadı.</div>'}
        </section>`;
    }
    if (r.error) {
      html += `<section class="d-section"><h4>${icon('alert')}${r.status === 'skipped' ? 'Neden' : 'Hata'}</h4><div class="reply ${r.status === 'skipped' ? 'muted' : 'error'}">${esc(r.error)}</div></section>`;
    }
    if (r.prompt) {
      html += `<section class="d-section"><h4>${icon('message')}Gönderilen mesaj</h4><div class="reply muted" style="font-style:normal;color:var(--text-2)">${esc(r.prompt)}</div></section>`;
    }
    if (r.screenshot_url) {
      html += `<section class="d-section"><h4>${icon('image')}Ekran görüntüsü</h4><button type="button" class="d-shot" data-drawer-shot><img src="${esc(r.screenshot_url)}" alt="" /></button></section>`;
    }
    if (r.logs) {
      html += `<details class="d-logs"><summary>${icon('chev-d')}Bu çalışmanın logları (${r.logs.split('\n').length} satır)</summary><div class="log-viewer" id="drawer-logs"></div></details>`;
    }
    $('#drawer-body').innerHTML = html;
    if (r.logs) $('#drawer-logs').replaceChildren(...splitLogBlock(r.logs).map((e) => logNode(e, '')));
  }

  drawer.addEventListener('click', (e) => {
    if (e.target === drawer || e.target.closest('[data-close]')) return closeDrawer();
    if (!drawerRun) return;
    if (e.target.closest('[data-copy-response]')) copyText(drawerRun.response, 'Yanıt kopyalandı');
    if (e.target.closest('[data-drawer-shot]')) openLightbox([shotFromRun(drawerRun)], 0);
    if (e.target.closest('[data-rerun]')) { const id = drawerRun.job_id; closeDrawer(); runNow(id); }
  });

  // ══════════════════════════════════════════════════════════
  //  LOGLAR
  // ══════════════════════════════════════════════════════════
  const LOG_MAX = 1000;
  const LOG_RE = /^(\d{4}-\d{2}-\d{2}) (\d{2}:\d{2}:\d{2}) \| (\w+)\s*\| ([^|]*?) \| ([\s\S]*)$/;
  const LOG_START = /^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2} \| /;
  const LEVEL_TAGS = { INFO: 'INFO', DEBUG: 'DEBUG', WARNING: 'WARN', ERROR: 'ERROR', CRITICAL: 'CRIT' };
  const logs = { store: [], level: 'ALL', query: '', paused: false, follow: true, es: null };
  const viewer = $('#log-viewer');

  function parseLog(raw) {
    const m = raw.match(LOG_RE);
    if (!m) return { raw, lv: /Traceback|Error/.test(raw) ? 'ERROR' : 'INFO', time: '', mod: '', msg: raw, plain: true };
    return { raw, time: m[2], lv: m[3].toUpperCase(), mod: m[4].trim(), msg: m[5] };
  }

  // Kayıtlı log metnini (çok satırlı traceback'ler dahil) kayıtlara böler
  function splitLogBlock(text) {
    const records = [];
    for (const line of text.split('\n')) {
      if (LOG_START.test(line) || !records.length) records.push(line);
      else records[records.length - 1] += `\n${line}`;
    }
    return records.map(parseLog);
  }

  function levelBucket(lv) { return lv === 'CRITICAL' ? 'ERROR' : lv; }

  function logMatches(e) {
    if (logs.level !== 'ALL' && levelBucket(e.lv) !== logs.level) return false;
    return !logs.query || lower(e.raw).includes(logs.query);
  }

  function highlight(text, query) {
    const safe = esc(text);
    if (!query) return safe;
    const q = esc(query).replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
    return safe.replace(new RegExp(q, 'gi'), (m) => `<mark>${m}</mark>`);
  }

  function logNode(e, query = logs.query) {
    const div = document.createElement('div');
    div.className = `log-line ${e.lv}${e.plain ? ' raw' : ''}`;
    div.innerHTML = e.plain
      ? `<span class="x">${highlight(e.msg, query)}</span>`
      : `<span class="t">${e.time}</span><span class="lv">${esc(LEVEL_TAGS[e.lv] || e.lv.slice(0, 5))}</span><span class="m" title="${esc(e.mod)}">${esc(e.mod)}</span><span class="x">${highlight(e.msg, query)}</span>`;
    return div;
  }

  function nearBottom() { return viewer.scrollHeight - viewer.scrollTop - viewer.clientHeight < 48; }
  function toBottom() { viewer.scrollTop = viewer.scrollHeight; }

  function renderLogs() {
    const items = logs.store.filter(logMatches);
    viewer.replaceChildren(...items.map((e) => logNode(e)));
    if (!items.length) {
      viewer.innerHTML = `<div class="log-empty">${logs.store.length ? 'Filtreyle eşleşen satır yok' : 'Henüz log yok'}</div>`;
    }
    if (logs.follow) toBottom();
    updateLogCounts();
  }

  function updateLogCounts() {
    const c = { ALL: logs.store.length, INFO: 0, WARNING: 0, ERROR: 0 };
    for (const e of logs.store) { const b = levelBucket(e.lv); if (b in c) c[b]++; }
    for (const k in c) $(`#n-${k}`).textContent = c[k];
  }

  function pushLog(raw) {
    const e = parseLog(raw);
    logs.store.push(e);
    let trimmed = false;
    if (logs.store.length > LOG_MAX) { logs.store.splice(0, logs.store.length - LOG_MAX); trimmed = true; }
    if (logs.paused) return;
    if (trimmed && viewer.firstElementChild?.classList.contains('log-line')) viewer.firstElementChild.remove();
    if (!logMatches(e)) return;
    $('.log-empty', viewer)?.remove();
    const stick = logs.follow && nearBottom();
    viewer.appendChild(logNode(e));
    if (stick) toBottom();
  }

  let countsQueued = false;
  function queueCounts() {
    if (countsQueued) return;
    countsQueued = true;
    requestAnimationFrame(() => { countsQueued = false; updateLogCounts(); });
  }

  function setLive(mode) {
    const el = $('#live');
    el.className = `live ${mode}`;
    el.lastElementChild.textContent = { '': 'Canlı', off: 'Bağlantı kesildi', paused: 'Duraklatıldı' }[mode];
  }

  function startLogStream() {
    if (logs.es) return;
    logs.es = new EventSource('/api/logs/stream');
    // Sunucu her bağlantıda tamponun tamamını yeniden gönderir; yinelenmeyi önlemek için sıfırla
    logs.es.onopen = () => {
      logs.store = [];
      viewer.innerHTML = '<div class="log-empty">Henüz log yok</div>';
      updateLogCounts();
      setLive(logs.paused ? 'paused' : '');
    };
    logs.es.onmessage = (ev) => {
      if (!ev.data.trim()) return;
      pushLog(ev.data);
      queueCounts();
    };
    logs.es.onerror = () => setLive('off');
  }

  $('#log-levels').addEventListener('click', (e) => {
    const chip = e.target.closest('.chip');
    if (!chip) return;
    logs.level = chip.dataset.level;
    $$('.chip', $('#log-levels')).forEach((c) => c.classList.toggle('on', c === chip));
    renderLogs();
  });

  let searchTimer;
  $('#log-search').addEventListener('input', (e) => {
    clearTimeout(searchTimer);
    searchTimer = setTimeout(() => { logs.query = lower(e.target.value.trim()); renderLogs(); }, 120);
  });

  $('#btn-pause').addEventListener('click', () => {
    logs.paused = !logs.paused;
    $('#btn-pause').classList.toggle('on', logs.paused);
    $('#pause-icon').setAttribute('href', logs.paused ? '#i-play' : '#i-pause');
    $('#btn-pause').title = logs.paused ? 'Akışı sürdür' : 'Akışı duraklat';
    setLive(logs.paused ? 'paused' : (logs.es?.readyState === 2 ? 'off' : ''));
    if (!logs.paused) renderLogs();
  });

  $('#btn-autoscroll').addEventListener('click', () => {
    logs.follow = !logs.follow;
    $('#btn-autoscroll').classList.toggle('on', logs.follow);
    if (logs.follow) toBottom();
  });

  $('#btn-log-clear').addEventListener('click', () => { logs.store = []; renderLogs(); });

  $('#btn-log-download').addEventListener('click', () => {
    const lines = logs.store.filter(logMatches).map((e) => e.raw);
    const blob = new Blob([lines.join('\n')], { type: 'text/plain' });
    const a = document.createElement('a');
    const d = new Date();
    a.href = URL.createObjectURL(blob);
    a.download = `claude-bot-${d.getFullYear()}${pad(d.getMonth() + 1)}${pad(d.getDate())}-${pad(d.getHours())}${pad(d.getMinutes())}.log`;
    a.click();
    URL.revokeObjectURL(a.href);
  });

  viewer.addEventListener('scroll', () => $('#btn-jump').classList.toggle('show', !nearBottom()), { passive: true });
  $('#btn-jump').addEventListener('click', () => { toBottom(); logs.follow = true; $('#btn-autoscroll').classList.add('on'); });

  // ══════════════════════════════════════════════════════════
  //  GÖREVLER / KONFİGÜRASYON
  // ══════════════════════════════════════════════════════════
  const config = { baseline: '', dirty: false, loaded: false };
  const jobList = $('#job-list-config');
  const PROMPT_VARS = ['tarih', 'gün', 'saat', 'ay', 'yıl', 'dün', 'yarın'];
  const RETRY_DELAYS = [1, 2, 5, 10, 15, 30, 60];

  async function loadConfig() {
    try {
      const cfg = await api('/api/config');
      const tz = $('#input-timezone');
      const zone = cfg.timezone || 'Europe/Istanbul';
      if (![...tz.options].some((o) => o.value === zone)) tz.add(new Option(zone, zone));
      tz.value = zone;
      $('#input-headless').checked = cfg.headless ?? true;

      jobList.innerHTML = '';
      (cfg.jobs || []).forEach((j) => addJobCard(j, { collapsed: (cfg.jobs || []).length > 3 }));
      updateJobsMeta();
      config.baseline = JSON.stringify(collectConfig());
      config.loaded = true;
      checkDirty();
    } catch (err) {
      toast(`Konfigürasyon yüklenemedi: ${errText(err)}`, 'error');
    }
  }

  function addJobCard(job, { collapsed = false, focus = false } = {}) {
    const s = cronToSimple(job.cron || '0 9 * * *');
    const card = document.createElement('div');
    card.className = `card job-card${job.enabled === false ? ' off' : ''}${collapsed ? ' collapsed' : ''}`;
    if (s.custom) card.dataset.rawCron = job.cron;

    const dayBtns = DAYS.map((d) =>
      `<button type="button" class="day ${s.days.includes(d.value) ? 'on' : ''}" data-day="${d.value}" title="${d.long}">${d.label}</button>`
    ).join('');

    const retries = Math.max(0, Math.min(+job.retries || 0, 5));
    const delay = +job.retry_delay || 5;
    const delays = RETRY_DELAYS.includes(delay) ? RETRY_DELAYS : [...RETRY_DELAYS, delay].sort((a, b) => a - b);
    const retryOpts = [0, 1, 2, 3, 4, 5].map((n) =>
      `<option value="${n}" ${n === retries ? 'selected' : ''}>${n ? `${n} kez tekrar dene` : 'Tekrar deneme'}</option>`).join('');
    const delayOpts = delays.map((n) => `<option value="${n}" ${n === delay ? 'selected' : ''}>${n} dk arayla</option>`).join('');
    const varChips = PROMPT_VARS.map((v) => `<button type="button" class="var-chip" data-var="{${v}}" title="{${v}} ekle">{${v}}</button>`).join('')
      + '<button type="button" class="var-chip" data-var="{seçenek 1|seçenek 2}" title="Her çalışmada seçeneklerden biri rastgele seçilir">{a|b} rastgele</button>';

    card.innerHTML = `
      <div class="job-card-head">
        <span class="job-index"></span>
        <input type="text" class="job-id-input" value="${esc(job.id)}" placeholder="gorev_adi" aria-label="Görev adı" spellcheck="false" />
        <span class="job-summary"></span>
        <span class="spacer"></span>
        <label class="switch" title="Aktif / Pasif"><input type="checkbox" class="job-enabled" ${job.enabled !== false ? 'checked' : ''} /><span></span></label>
        <button type="button" class="btn btn-quiet sm icon btn-danger" data-act="delete" title="Görevi sil">${icon('trash')}</button>
        <button type="button" class="btn btn-quiet sm icon collapse-btn" data-act="collapse" title="Daralt / genişlet">${icon('chev-d')}</button>
      </div>
      <div class="job-card-body">
        <div class="field full">
          <label class="field-label"><span>Sohbet (Chat ID)</span></label>
          <div class="affix"><span>claude.ai/chat/</span><input type="text" class="input job-chat-id" value="${esc(job.chat_id)}" placeholder="xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx" spellcheck="false" /></div>
          <span class="field-hint">Boş bırakılırsa global sohbet kullanılır. Tam URL yapıştırırsanız ID otomatik ayıklanır.</span>
        </div>
        <div class="field">
          <label class="field-label"><span>Mesaj</span><span class="char-count"></span></label>
          <textarea class="textarea job-prompt-input" rows="6" placeholder="Bu görevde Claude'a gönderilecek mesaj…">${esc(job.prompt)}</textarea>
          <div class="var-chips">${varChips}</div>
          <div class="prompt-preview" hidden></div>
        </div>
        <div class="field">
          <label class="field-label"><span>Zamanlama</span></label>
          <div class="schedule">
            <div class="schedule-top">
              <input type="time" class="time-input job-time-input" value="${s.time}" />
              <div class="presets">
                <button type="button" class="preset" data-preset="all">Her gün</button>
                <button type="button" class="preset" data-preset="weekdays">Hafta içi</button>
                <button type="button" class="preset" data-preset="weekend">Hafta sonu</button>
              </div>
            </div>
            <div class="days">${dayBtns}</div>
            <div class="schedule-foot">
              <span class="schedule-human">${icon('clock')}<span class="human"></span></span>
              <code class="cron-code"></code>
            </div>
          </div>
        </div>
        <div class="full retry-row">
          ${icon('retry')}<span>Hata olursa</span>
          <select class="select job-retries" aria-label="Tekrar deneme sayısı">${retryOpts}</select>
          <select class="select job-retry-delay" aria-label="Denemeler arası bekleme" ${retries ? '' : 'disabled'}>${delayOpts}</select>
          <span class="faint" style="font-size:12px">Oturum hatalarında tekrar denenmez.</span>
        </div>
      </div>`;

    jobList.appendChild(card);
    syncCard(card);
    updatePromptPreview(card);
    if (focus) {
      card.scrollIntoView({ behavior: 'smooth', block: 'center' });
      setTimeout(() => $('.job-id-input', card).select(), 300);
    }
    return card;
  }

  function cardDays(card) { return $$('.day.on', card).map((b) => +b.dataset.day); }

  function cardCron(card) {
    return card.dataset.rawCron || simpleToCron($('.job-time-input', card).value, cardDays(card));
  }

  // Kart başlığı, özet, cron önizlemesi ve preset durumunu günceller
  function syncCard(card) {
    const days = cardDays(card);
    const cron = cardCron(card);
    const custom = !!card.dataset.rawCron;
    const human = custom ? 'Özel cron — saat/gün seçilince üzerine yazılır' : `${daysLabel(days.length ? days : ALL_DAYS)} · ${$('.job-time-input', card).value || '09:00'}`;
    $('.human', card).textContent = human;
    $('.cron-code', card).textContent = cron;
    $('.job-summary', card).textContent = custom ? cron : human;
    const p = presetOf(days.length ? days : ALL_DAYS);
    $$('.preset', card).forEach((b) => b.classList.toggle('on', !custom && b.dataset.preset === p));
    const prompt = $('.job-prompt-input', card).value;
    $('.char-count', card).textContent = `${prompt.length} karakter`;
    card.classList.toggle('off', !$('.job-enabled', card).checked);
    $('.job-retry-delay', card).disabled = $('.job-retries', card).value === '0';
  }

  // Değişken içeren mesajın doldurulmuş hâlini sunucudan alır
  const previewTimers = new WeakMap();
  function updatePromptPreview(card) {
    clearTimeout(previewTimers.get(card));
    const box = $('.prompt-preview', card);
    const prompt = $('.job-prompt-input', card).value;
    if (!/\{[^{}\n]+\}/.test(prompt)) { box.hidden = true; return; }
    previewTimers.set(card, setTimeout(async () => {
      try {
        const { rendered } = await api('/api/prompt/preview', { method: 'POST', json: { prompt } });
        if ($('.job-prompt-input', card).value !== prompt) return;
        box.hidden = false;
        box.innerHTML = `<b>${icon('sparkle')}Şimdi çalışsa gönderilecek mesaj</b>${esc(rendered)}`;
      } catch { box.hidden = true; }
    }, 350));
  }

  function insertAtCursor(textarea, text) {
    const { selectionStart: a, selectionEnd: b, value } = textarea;
    textarea.value = value.slice(0, a) + text + value.slice(b);
    textarea.focus();
    textarea.setSelectionRange(a + text.length, a + text.length);
    textarea.dispatchEvent(new Event('input', { bubbles: true }));
  }

  function updateJobsMeta() {
    const cards = $$('.job-card', jobList);
    cards.forEach((c, i) => { $('.job-index', c).textContent = pad(i + 1); });
    const active = cards.filter((c) => $('.job-enabled', c).checked).length;
    $('#jobs-count').textContent = cards.length ? `${cards.length} görev · ${active} aktif` : 'Henüz görev yok — aşağıdan ekleyin';
  }

  function collectConfig() {
    return {
      jobs: $$('.job-card', jobList).map((c) => ({
        id:          $('.job-id-input', c).value.trim() || 'gorev',
        chat_id:     $('.job-chat-id', c).value.trim(),
        prompt:      $('.job-prompt-input', c).value,
        cron:        cardCron(c),
        enabled:     $('.job-enabled', c).checked,
        retries:     +$('.job-retries', c).value,
        retry_delay: +$('.job-retry-delay', c).value,
      })),
      timezone: $('#input-timezone').value,
      headless: $('#input-headless').checked,
    };
  }

  function checkDirty() {
    if (!config.loaded) return;
    config.dirty = JSON.stringify(collectConfig()) !== config.baseline;
    $('#savebar').classList.toggle('show', config.dirty);
  }

  function newJobId() {
    const ids = new Set($$('.job-id-input', jobList).map((i) => i.value.trim()));
    let n = ids.size + 1;
    while (ids.has(`gorev_${n}`)) n++;
    return `gorev_${n}`;
  }

  function addJob() {
    if (state.view !== 'config') navigate('config');
    addJobCard({ id: newJobId(), cron: '0 9 * * *', enabled: true, chat_id: '', prompt: '' }, { focus: true });
    updateJobsMeta();
    checkDirty();
  }

  jobList.addEventListener('click', (e) => {
    const card = e.target.closest('.job-card');
    if (!card) return;
    const t = e.target.closest('button');
    if (!t) return;

    if (t.dataset.var) {
      insertAtCursor($('.job-prompt-input', card), t.dataset.var);
      return;
    } else if (t.classList.contains('day')) {
      t.classList.toggle('on');
      delete card.dataset.rawCron;
    } else if (t.dataset.preset) {
      $$('.day', card).forEach((b) => {
        const d = +b.dataset.day;
        const on = t.dataset.preset === 'all' || (t.dataset.preset === 'weekdays' ? d >= 1 && d <= 5 : d === 0 || d === 6);
        b.classList.toggle('on', on);
      });
      delete card.dataset.rawCron;
    } else if (t.dataset.act === 'collapse') {
      card.classList.toggle('collapsed');
      return;
    } else if (t.dataset.act === 'delete') {
      const name = $('.job-id-input', card).value || 'görev';
      card.remove();
      updateJobsMeta();
      checkDirty();
      toast(`“${name}” silindi — kaydedene kadar geri alabilirsiniz`, 'info');
      return;
    } else {
      return;
    }
    syncCard(card);
    checkDirty();
  });

  jobList.addEventListener('input', (e) => {
    const card = e.target.closest('.job-card');
    if (!card) return;
    if (e.target.classList.contains('job-chat-id')) {
      // Tam URL yapıştırıldıysa yalnızca ID'yi bırak
      const m = e.target.value.match(/chat\/([0-9a-f-]{8,})/i);
      if (m) e.target.value = m[1];
    }
    if (e.target.classList.contains('job-time-input')) delete card.dataset.rawCron;
    if (e.target.classList.contains('job-id-input')) e.target.classList.remove('invalid');
    if (e.target.classList.contains('job-prompt-input')) updatePromptPreview(card);
    syncCard(card);
    checkDirty();
  });
  jobList.addEventListener('change', (e) => {
    const card = e.target.closest('.job-card');
    if (!card) return;
    syncCard(card);
    if (e.target.classList.contains('job-enabled')) updateJobsMeta();
    checkDirty();
  });

  $('#input-timezone').addEventListener('change', checkDirty);
  $('#input-headless').addEventListener('change', checkDirty);
  $('#btn-add-job').addEventListener('click', addJob);
  $('#btn-add-job-top').addEventListener('click', addJob);
  $('#config-form').addEventListener('submit', (e) => { e.preventDefault(); saveConfig(); });

  function validate() {
    const inputs = $$('.job-id-input', jobList);
    inputs.forEach((i) => i.classList.remove('invalid'));
    const seen = new Map();
    let bad = null;
    inputs.forEach((inp) => {
      const id = inp.value.trim();
      if (!id) { inp.classList.add('invalid'); bad ??= 'Görev adı boş olamaz'; return; }
      if (seen.has(id)) { inp.classList.add('invalid'); seen.get(id).classList.add('invalid'); bad ??= `“${id}” adı birden fazla görevde kullanılıyor`; }
      seen.set(id, inp);
    });
    if (bad) {
      const first = $('.job-id-input.invalid', jobList);
      first?.closest('.job-card').classList.remove('collapsed');
      first?.focus();
    }
    return bad;
  }

  async function saveConfig() {
    const problem = validate();
    if (problem) { toast(problem, 'error'); return; }
    const payload = collectConfig();

    const btn = $('#btn-save');
    btn.disabled = true;
    btn.innerHTML = '<span class="spinner"></span><span>Kaydediliyor…</span>';
    try {
      await api('/api/config', { method: 'POST', json: payload });
      config.baseline = JSON.stringify(payload);
      checkDirty();
      toast('Kaydedildi — zamanlayıcı güncellendi', 'success');
      setTimeout(poll, 600);
    } catch (err) {
      toast(`Kaydedilemedi: ${errText(err)}`, 'error');
    } finally {
      btn.disabled = false;
      btn.innerHTML = `${icon('save')}<span>Kaydet ve uygula</span>`;
    }
  }

  $('#btn-save').addEventListener('click', saveConfig);
  $('#btn-revert').addEventListener('click', () => { config.dirty = false; loadConfig(); });

  window.addEventListener('beforeunload', (e) => {
    if (config.dirty) { e.preventDefault(); e.returnValue = ''; }
  });

  // ══════════════════════════════════════════════════════════
  //  GALERİ
  // ══════════════════════════════════════════════════════════
  const SHOT_LABELS = {
    success:                  ['ok',   'Başarılı'],
    login_required:           ['warn', 'Giriş gerekli'],
    critical_error:           ['err',  'Kritik hata'],
    text_insert_failed:       ['err',  'Metin eklenemedi'],
    send_message_error:       ['err',  'Gönderim hatası'],
    element_not_interactable: ['err',  'Etkileşim hatası'],
  };

  function shotInfo(s) {
    const key = s.filename.replace(/_\d{8}_\d{6}\.png$/i, '').replace(/\.png$/i, '');
    const [kind, label] = SHOT_LABELS[key] || ['err', key.replace(/_/g, ' ')];
    return { ...s, kind, label, date: new Date(s.timestamp * 1000) };
  }

  const gallery = { filter: 'all', list: [] };

  async function loadShots() {
    try {
      const data = await api('/api/screenshots/list');
      state.shots = (data.screenshots || []).map(shotInfo);
    } catch {
      $('#gallery').innerHTML = `<div class="empty" style="grid-column:1/-1"><div class="empty-icon">${icon('alert', 'lg')}</div><div><b>Yüklenemedi</b>Ekran görüntüleri alınamadı.</div></div>`;
      return;
    }
    renderGallery();
  }

  function renderGallery() {
    const counts = { all: state.shots.length, ok: 0, warn: 0, err: 0 };
    state.shots.forEach((s) => counts[s.kind]++);
    for (const k in counts) $(`#sn-${k}`).textContent = counts[k];

    gallery.list = state.shots.filter((s) => gallery.filter === 'all' || s.kind === gallery.filter);
    const el = $('#gallery');
    if (!gallery.list.length) {
      el.innerHTML = `<div class="empty" style="grid-column:1/-1"><div class="empty-icon">${icon('image', 'lg')}</div><div><b>${state.shots.length ? 'Bu filtrede kare yok' : 'Henüz ekran görüntüsü yok'}</b>Bot bir görev çalıştırdığında burada görünecek.</div></div>`;
      return;
    }
    let html = '', lastDay = '';
    gallery.list.forEach((s, i) => {
      const day = dayLabel(s.date);
      if (day !== lastDay) { html += `<div class="day-head">${esc(day)}</div>`; lastDay = day; }
      html += `
        <button type="button" class="shot" data-i="${i}">
          <div class="shot-img"><img src="${esc(s.url)}" alt="${esc(s.label)}" loading="lazy" /></div>
          <div class="shot-meta">
            <div class="shot-meta-top"><span class="tag ${s.kind}">${esc(s.label)}</span><span class="shot-date">${hhmm(s.date)}</span></div>
            <span class="shot-name">${esc(s.filename)}</span>
          </div>
        </button>`;
    });
    el.innerHTML = html;
  }

  $('#gallery').addEventListener('click', (e) => {
    const b = e.target.closest('.shot');
    if (b) openLightbox(gallery.list, +b.dataset.i);
  });
  $('#shot-filters').addEventListener('click', (e) => {
    const chip = e.target.closest('.chip');
    if (!chip) return;
    gallery.filter = chip.dataset.kind;
    $$('.chip', $('#shot-filters')).forEach((c) => c.classList.toggle('on', c === chip));
    renderGallery();
  });
  $('#btn-shots-refresh').addEventListener('click', loadShots);

  // Lightbox
  const lb = { list: [], i: 0 };
  function openLightbox(list, i) { lb.list = list; lb.i = i; showLightbox(); $('#lightbox').classList.add('open'); }
  function closeLightbox() { $('#lightbox').classList.remove('open'); }
  function stepLightbox(d) { if (lb.list.length) { lb.i = (lb.i + d + lb.list.length) % lb.list.length; showLightbox(); } }
  function showLightbox() {
    const s = lb.list[lb.i];
    if (!s) return;
    const img = $('#lb-img');
    img.style.animation = 'none'; void img.offsetWidth; img.style.animation = '';
    img.src = s.url;
    img.alt = s.label;
    $('#lb-tag').className = `tag ${s.kind}`;
    $('#lb-tag').textContent = s.label;
    $('#lb-title').textContent = s.filename;
    $('#lb-sub').textContent = s.size ? `${whenLabel(s.date)} · ${(s.size / 1024).toFixed(0)} KB` : whenLabel(s.date);
    $('#lb-open').href = s.url;
    $('#lb-count').textContent = `${lb.i + 1} / ${lb.list.length}`;
    const multi = lb.list.length > 1;
    $('#lb-prev').hidden = !multi;
    $('#lb-next').hidden = !multi;
  }
  $('#lb-close').addEventListener('click', closeLightbox);
  $('#lb-prev').addEventListener('click', () => stepLightbox(-1));
  $('#lb-next').addEventListener('click', () => stepLightbox(1));
  $('#lightbox').addEventListener('click', (e) => { if (e.target.classList.contains('lb-stage') || e.target.id === 'lightbox') closeLightbox(); });

  // ══════════════════════════════════════════════════════════
  //  KOMUT PALETİ
  // ══════════════════════════════════════════════════════════
  const palette = { items: [], sel: 0 };

  function paletteCommands() {
    return [
      { group: 'Git', icon: 'overview', label: 'Genel Bakış', hint: '1', run: () => navigate('overview') },
      { group: 'Git', icon: 'history',  label: 'Geçmiş',      hint: '2', run: () => navigate('history') },
      { group: 'Git', icon: 'terminal', label: 'Loglar',      hint: '3', run: () => navigate('logs') },
      { group: 'Git', icon: 'sliders',  label: 'Görevler',    hint: '4', run: () => navigate('config') },
      { group: 'Git', icon: 'image',    label: 'Galeri',      hint: '5', run: () => navigate('gallery') },
      { group: 'Eylem', icon: 'play',     label: 'Şimdi çalıştır (ilk aktif görev)', run: () => runNow() },
      ...state.jobs.map((j) => ({ group: 'Eylem', icon: 'play', label: `Çalıştır: ${j.id}`, hint: j.enabled ? '' : 'pasif', run: () => runNow(j.id) })),
      { group: 'Eylem', icon: 'calendar', label: 'Bir kez planla…', run: () => openOneOff() },
      { group: 'Eylem', icon: state.paused ? 'play' : 'pause', label: state.paused ? 'Zamanlayıcıyı sürdür' : 'Tüm çalışmaları duraklat', run: togglePause },
      { group: 'Eylem', icon: 'plus',     label: 'Yeni görev ekle', run: addJob },
      { group: 'Eylem', icon: 'refresh',  label: 'Durumu yenile',   run: () => { poll(); loadHeatmap(); loadSession(); } },
      { group: 'Tema', icon: 'sun',     label: 'Açık tema',     run: () => setTheme('light') },
      { group: 'Tema', icon: 'moon',    label: 'Koyu tema',     run: () => setTheme('dark') },
      { group: 'Tema', icon: 'monitor', label: 'Sistem teması', run: () => setTheme('system') },
    ];
  }

  function renderPalette() {
    const q = lower($('#palette-input').value.trim());
    palette.items = paletteCommands().filter((c) => !q || lower(`${c.group} ${c.label}`).includes(q));
    palette.sel = Math.min(palette.sel, Math.max(palette.items.length - 1, 0));
    let html = '', group = '';
    palette.items.forEach((c, i) => {
      if (c.group !== group) { html += `<div class="palette-group">${c.group}</div>`; group = c.group; }
      html += `<button type="button" class="palette-item ${i === palette.sel ? 'sel' : ''}" data-i="${i}">${icon(c.icon)}<span>${esc(c.label)}</span>${c.hint ? `<small>${esc(c.hint)}</small>` : ''}</button>`;
    });
    $('#palette-list').innerHTML = html || '<div class="empty">Eşleşen komut yok</div>';
    $('.palette-item.sel')?.scrollIntoView({ block: 'nearest' });
  }

  function openPalette() {
    closeMenu();
    $('#palette').classList.add('open');
    $('#palette-input').value = '';
    palette.sel = 0;
    renderPalette();
    $('#palette-input').focus();
  }
  function closePalette() { $('#palette').classList.remove('open'); }
  function runPalette(i) {
    const c = palette.items[i];
    if (!c) return;
    closePalette();
    c.run();
  }

  $('#cmd-trigger').addEventListener('click', openPalette);
  $('#palette-input').addEventListener('input', () => { palette.sel = 0; renderPalette(); });
  $('#palette-list').addEventListener('click', (e) => { const b = e.target.closest('.palette-item'); if (b) runPalette(+b.dataset.i); });
  $('#palette-list').addEventListener('mousemove', (e) => {
    const b = e.target.closest('.palette-item');
    if (b && +b.dataset.i !== palette.sel) { palette.sel = +b.dataset.i; $$('.palette-item').forEach((x) => x.classList.toggle('sel', x === b)); }
  });
  $('#palette').addEventListener('click', (e) => { if (e.target.id === 'palette') closePalette(); });
  $('#palette-input').addEventListener('keydown', (e) => {
    if (e.key === 'ArrowDown') { e.preventDefault(); palette.sel = (palette.sel + 1) % Math.max(palette.items.length, 1); renderPalette(); }
    if (e.key === 'ArrowUp')   { e.preventDefault(); palette.sel = (palette.sel - 1 + palette.items.length) % Math.max(palette.items.length, 1); renderPalette(); }
    if (e.key === 'Enter')     { e.preventDefault(); runPalette(palette.sel); }
  });

  // ── Klavye kısayolları ─────────────────────────────────────
  const isMac = /Mac|iPhone|iPad/.test(navigator.platform);
  $('#cmd-kbd').textContent = isMac ? '⌘K' : 'Ctrl K';

  const isOpen = (sel) => $(sel).classList.contains('open');

  document.addEventListener('keydown', (e) => {
    if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') {
      e.preventDefault();
      isOpen('#palette') ? closePalette() : openPalette();
      return;
    }
    if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 's' && state.view === 'config') {
      e.preventDefault();
      if (config.dirty) saveConfig();
      return;
    }
    if (e.key === 'Escape') {
      if (!menu.hidden) return closeMenu();
      if (isOpen('#palette')) return closePalette();
      if (isOpen('#lightbox')) return closeLightbox();
      if (isOpen('#oneoff-modal')) return closeOneOff();
      if (isOpen('#drawer')) return closeDrawer();
    }
    if (isOpen('#lightbox')) {
      if (e.key === 'ArrowLeft')  stepLightbox(-1);
      if (e.key === 'ArrowRight') stepLightbox(1);
      return;
    }
    const typing = /INPUT|TEXTAREA|SELECT/.test(document.activeElement?.tagName) || document.activeElement?.isContentEditable;
    const overlay = isOpen('#palette') || isOpen('#drawer') || isOpen('#oneoff-modal');
    if (typing || overlay || e.metaKey || e.ctrlKey || e.altKey) return;
    if (VIEW_KEYS[e.key]) navigate(VIEW_KEYS[e.key]);
    if (e.key === '/' && state.view === 'logs') { e.preventDefault(); $('#log-search').focus(); }
  });

  // ── Başlat ─────────────────────────────────────────────────
  tickClock();
  setInterval(() => { tickClock(); tickCountdown(); }, 1000);
  setInterval(() => {
    renderTimeline();
    if (state.view === 'overview') { renderJobRows(); renderUpcoming(); renderLastRun(); }
  }, 30e3);
  setInterval(() => { if (state.view === 'overview') { loadHeatmap(); loadSession(); } }, 5 * 60e3);
  navigate(location.hash.slice(1) || 'overview', { push: false });
  poll();
})();

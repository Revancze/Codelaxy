(function () {
  'use strict';
  /* Read-only roadmap viewer. Never evaluates workbook content as HTML or script; every string from
     the workbook is already escaped by the generator and is only ever inserted with textContent here.
     Translation never blocks reading: any failure falls back to the English text that is on the page. */
  var cfg = JSON.parse(document.getElementById('rv-config').textContent);
  var OPEN = '⟦', CLOSE = '⟧';
  var CODE_RE = /^[a-z]{2,3}(-[A-Za-z0-9]{2,8})*$/;
  function $(id) { return document.getElementById(id); }
  function fmt(s, v) { return String(s).replace(/\{(\w+)\}/g, function (_, k) { return v && v[k] != null ? v[k] : ''; }); }

  var UI = {
    en: {
      title: 'Codelaxy Roadmap Workbook - read-only view',
      source: 'Source: {file} · SHA-256 {sha} · git blob {blob}',
      ref: 'Reference state: commit {commit}, inventory {date}.',
      historical: 'This is a historical snapshot of the workbook, not the current project status. The ratified sources are docs/roadmap.md and docs/architecture.md in the repository.',
      unofficial: 'Translations are unofficial reading aids; the English text is authoritative.',
      language: 'Language', lang_en: 'English (original)', lang_other: 'Other language…', apply: 'Use',
      tip_pack: '{name} · unofficial translation', tip_api: 'Machine translation on this device · unofficial',
      tip_outdated: 'The English text changed after this cell was translated, so no translation is shown. The English text is authoritative.',
      tip_missing: 'No translation exists for this cell yet. The English text is authoritative.',
      tip_working: 'Translating…',
      tip_failed: 'This cell could not be translated safely. The English text is authoritative.',
      tip_hint: 'Hover, focus or tap a cell to see its translation. Esc closes.',
      status_off: 'Original English text.',
      status_loading: 'Loading language pack {code}…',
      status_pack_missing: 'Language pack "{code}" was not found next to this file. Showing English.',
      status_api_missing: 'This browser has no on-device translator. Showing English. (Chrome or Edge on a computer can translate into more languages.)',
      status_api_failed: 'The translator for "{code}" could not be started. Showing English.',
      status_bad_code: '"{code}" is not a valid language code. Showing English.',
      status_pair_unavailable: 'This browser cannot translate English into "{code}" on this device. Showing English.',
      status_download: 'The translation model for "{code}" must be downloaded once (then it works offline).',
      status_download_btn: 'Download model',
      status_downloading: 'Downloading the model for "{code}": {pct}%',
      status_ready: '{name} translation is on.',
      status_pack_stale: 'This language pack was made from a different version of the workbook; cells that changed show no translation.'
    },
    cs: {
      title: 'Sešit roadmapy Codelaxy - náhled jen ke čtení',
      source: 'Zdroj: {file} · SHA-256 {sha} · git blob {blob}',
      ref: 'Referenční stav: commit {commit}, inventura {date}.',
      historical: 'Je to historický stav sešitu, nikoli aktuální stav projektu. Ratifikované zdroje jsou docs/roadmap.md a docs/architecture.md v repozitáři.',
      unofficial: 'Překlady jsou neoficiální pomůcka pro čtení; závazný je anglický text.',
      language: 'Jazyk', lang_en: 'English (originál)', lang_other: 'Jiný jazyk…', apply: 'Použít',
      tip_pack: '{name} · neoficiální překlad', tip_api: 'Strojový překlad v tomto zařízení · neoficiální',
      tip_outdated: 'Anglický text se po překladu změnil, proto se překlad nezobrazuje. Závazný je anglický text.',
      tip_missing: 'Pro tuto buňku zatím překlad neexistuje. Závazný je anglický text.',
      tip_working: 'Překládám…',
      tip_failed: 'Tuto buňku se nepodařilo bezpečně přeložit. Závazný je anglický text.',
      tip_hint: 'Najeďte na buňku, vyberte ji klávesnicí nebo na ni klepněte. Esc zavře bublinu.',
      status_off: 'Původní anglický text.',
      status_loading: 'Načítám jazykový balíček {code}…',
      status_pack_missing: 'Jazykový balíček "{code}" nebyl nalezen vedle tohoto souboru. Zobrazuje se angličtina.',
      status_api_missing: 'Tento prohlížeč nemá překladač v zařízení. Zobrazuje se angličtina.',
      status_api_failed: 'Překladač pro "{code}" se nepodařilo spustit. Zobrazuje se angličtina.',
      status_bad_code: '"{code}" není platný kód jazyka. Zobrazuje se angličtina.',
      status_pair_unavailable: 'Tento prohlížeč nedokáže na tomto zařízení překládat z angličtiny do "{code}". Zobrazuje se angličtina.',
      status_download: 'Překladový model pro "{code}" je třeba jednou stáhnout (potom funguje i offline).',
      status_download_btn: 'Stáhnout model',
      status_downloading: 'Stahuji model pro "{code}": {pct} %',
      status_ready: 'Překlad {name} je zapnutý.',
      status_pack_stale: 'Tento jazykový balíček vznikl z jiné verze sešitu; změněné buňky se nepřekládají.'
    }
  };
  var ui = UI.en;
  var state = { lang: 'en', mode: 'none', pack: null, translator: null, cache: {}, token: 0, tipToken: 0,
                active: null, pinned: null, timer: null };
  var cells = Array.prototype.slice.call(document.querySelectorAll('td.tr'));

  function store(k, v) { try { if (v == null) localStorage.removeItem(k); else localStorage.setItem(k, v); } catch (e) { /* storage is optional */ } }
  function load(k) { try { return localStorage.getItem(k); } catch (e) { return null; } }
  function withTimeout(p, ms) {
    return new Promise(function (resolve, reject) {
      var t = setTimeout(function () { reject(new Error('timeout')); }, ms);
      Promise.resolve(p).then(function (v) { clearTimeout(t); resolve(v); }, function (e) { clearTimeout(t); reject(e); });
    });
  }

  /* ---- URL fragment: #lang=cs&sheet=MICROMAP ---- */
  function readHash() {
    var p = {};
    location.hash.replace(/^#/, '').split('&').forEach(function (kv) {
      var i = kv.indexOf('=');
      if (i > 0) { try { p[decodeURIComponent(kv.slice(0, i))] = decodeURIComponent(kv.slice(i + 1)); } catch (e) { /* ignore */ } }
    });
    return p;
  }
  function writeHash(p) {
    var s = Object.keys(p).filter(function (k) { return p[k]; })
      .map(function (k) { return encodeURIComponent(k) + '=' + encodeURIComponent(p[k]); }).join('&');
    try { history.replaceState(null, '', s ? '#' + s : location.pathname + location.search); } catch (e) { /* ignore */ }
  }

  /* ---- chrome text ---- */
  function setStatus(text, button) {
    var s = $('status');
    s.textContent = text || '';
    if (button) {
      var b = document.createElement('button');
      b.type = 'button'; b.textContent = button.label; b.addEventListener('click', button.onClick);
      s.appendChild(b);
    }
  }
  function applyChrome() {
    document.title = ui.title;
    $('t-title').textContent = ui.title;
    $('t-source').textContent = fmt(ui.source, { file: cfg.file, sha: cfg.sha256, blob: cfg.blob.slice(0, 8) });
    $('t-ref').textContent = fmt(ui.ref, { commit: cfg.reference.commit || '?', date: cfg.reference.date || '?' });
    $('t-hist').textContent = ui.historical;
    $('t-unofficial').textContent = ui.unofficial;
    $('t-language').textContent = ui.language;
    $('other-apply').textContent = ui.apply;
    var sel = $('lang');
    sel.options[0].textContent = ui.lang_en;
    sel.options[sel.options.length - 1].textContent = ui.lang_other;
  }
  function buildSelect() {
    var sel = $('lang');
    sel.textContent = '';
    function opt(v, t) { var o = document.createElement('option'); o.value = v; o.textContent = t; sel.appendChild(o); }
    opt('en', 'English');
    cfg.packs.forEach(function (p) { opt(p.code, p.name); });
    opt('other', '...');
    var dl = $('codes');
    [['ja', 'Japanese'], ['de', 'German'], ['fr', 'French'], ['es', 'Spanish'], ['it', 'Italian'], ['pl', 'Polish'],
     ['sk', 'Slovak'], ['ru', 'Russian'], ['uk', 'Ukrainian'], ['zh', 'Chinese'], ['ko', 'Korean'], ['pt', 'Portuguese'],
     ['nl', 'Dutch'], ['tr', 'Turkish'], ['ar', 'Arabic']].forEach(function (c) {
      var o = document.createElement('option'); o.value = c[0]; o.label = c[1]; dl.appendChild(o);
    });
  }
  function syncSelect(code) {
    var sel = $('lang'), known = false, i;
    for (i = 0; i < sel.options.length; i++) { if (sel.options[i].value === code) known = true; }
    sel.value = known ? code : 'other';
    $('other-box').hidden = known;
    if (!known) { $('other-code').value = code; }
  }

  /* ---- translation sources ---- */
  function loadPack(info) {
    return new Promise(function (resolve, reject) {
      var packs = window.__RV_PACKS = window.__RV_PACKS || {};
      if (packs[info.code]) { resolve(packs[info.code]); return; }
      var s = document.createElement('script');
      s.async = true; s.src = info.file;
      s.onload = function () { if (packs[info.code]) resolve(packs[info.code]); else reject(new Error('empty pack')); };
      s.onerror = function () { reject(new Error('pack not found')); };
      document.head.appendChild(s);
      setTimeout(function () { reject(new Error('timeout')); }, 15000);
    });
  }

  function extract(td) {
    var parts = [], tokens = [];
    Array.prototype.forEach.call(td.childNodes, function (n) {
      if (n.nodeType === 3) { parts.push({ t: n.nodeValue }); }
      else if (n.nodeType === 1) {
        if (n.classList.contains('np') || n.tagName === 'A') { parts.push({ p: tokens.length }); tokens.push(n.textContent); }
        else { parts.push({ t: n.textContent }); }
      }
    });
    return { parts: parts, tokens: tokens };
  }
  function hasLetters(s) { return /[^\W\d_]/.test(s); }

  function translateWhole(ex, tr) {
    var text = ex.parts.map(function (x) { return x.p != null ? OPEN + x.p + CLOSE : x.t; }).join('');
    return tr.translate(text).then(function (out) {
      var seen = {}, ok = true;
      out.replace(/⟦(\d+)⟧/g, function (m, i) { seen[i] = (seen[i] || 0) + 1; return m; });
      ex.tokens.forEach(function (_, i) { if (seen[i] !== 1) ok = false; });
      Object.keys(seen).forEach(function (i) { if (Number(i) >= ex.tokens.length) ok = false; });
      if (!ok) throw new Error('placeholders not preserved');
      return out.replace(/⟦(\d+)⟧/g, function (m, i) { return ex.tokens[Number(i)]; });
    });
  }
  function translateByParts(ex, tr) {
    return Promise.all(ex.parts.map(function (x) {
      if (x.p != null) return Promise.resolve(ex.tokens[x.p]);
      return hasLetters(x.t) ? tr.translate(x.t) : Promise.resolve(x.t);
    })).then(function (xs) { return xs.join(''); });
  }
  function translateCell(td) {
    // The language and translator are fixed when the request starts: a language switch
    // while it is pending must not store the result under the newly chosen language.
    var lang = state.lang, tr = state.translator, key = td.getAttribute('data-k');
    if (state.cache[lang + '|' + key]) return Promise.resolve(state.cache[lang + '|' + key]);
    var ex = extract(td);
    return withTimeout(translateWhole(ex, tr).catch(function () { return translateByParts(ex, tr); }), 30000).then(function (text) {
      var res = { kind: 'api', text: text };
      state.cache[lang + '|' + key] = res;
      return res;
    });
  }

  function tipContent(td) {
    var key = td.getAttribute('data-k'), h = td.getAttribute('data-h');
    if (state.mode === 'pack') {
      var e = state.pack.e[key];
      if (!e) return Promise.resolve({ kind: 'missing' });
      if (e[0] !== h) return Promise.resolve({ kind: 'outdated' });
      return Promise.resolve({ kind: 'pack', text: e[1] });
    }
    if (state.mode === 'api') return translateCell(td);
    return Promise.resolve(null);
  }

  /* ---- tooltip ---- */
  function position(td) {
    var tip = $('tip'), r = td.getBoundingClientRect(), vw = document.documentElement.clientWidth, vh = window.innerHeight;
    tip.style.left = '0px'; tip.style.top = '0px';
    var w = tip.offsetWidth, h = tip.offsetHeight;
    var left = Math.max(8, Math.min(r.left, vw - w - 8));
    var top = r.bottom + 6;
    if (top + h > vh - 8) top = Math.max(8, r.top - h - 6);
    tip.style.left = left + 'px'; tip.style.top = top + 'px';
  }
  function render(td, res) {
    var tip = $('tip');
    tip.textContent = ''; tip.classList.remove('bad');
    if (!res) { tip.hidden = true; return; }
    var head = document.createElement('div'); head.className = 'tt-head';
    var body = document.createElement('div');
    if (res.kind === 'pack') { head.textContent = fmt(ui.tip_pack, { name: state.packName }); body.textContent = res.text; }
    else if (res.kind === 'api') { head.textContent = ui.tip_api; body.textContent = res.text; }
    else if (res.kind === 'working') { body.textContent = ui.tip_working; }
    else {
      tip.classList.add('bad');
      body.textContent = res.kind === 'outdated' ? ui.tip_outdated : res.kind === 'missing' ? ui.tip_missing : ui.tip_failed;
    }
    if (head.textContent) tip.appendChild(head);
    tip.appendChild(body);
    tip.hidden = false;
    position(td);
  }
  function showTip(td) {
    if (state.mode === 'none') return;
    state.active = td;
    var token = ++state.tipToken;
    render(td, { kind: 'working' });
    tipContent(td).then(function (res) { if (token === state.tipToken && state.active === td) render(td, res); })
      .catch(function () { if (token === state.tipToken && state.active === td) render(td, { kind: 'failed' }); });
  }
  function hideTip() {
    clearTimeout(state.timer);
    state.tipToken++; state.active = null;
    $('tip').hidden = true;
  }
  function unpin() { if (state.pinned) { state.pinned.classList.remove('pinned'); state.pinned = null; } }
  function cellOf(node) { return node && node.closest ? node.closest('td.tr[tabindex]') : null; }

  document.addEventListener('mouseover', function (e) {
    var td = cellOf(e.target);
    if (td) {
      if (state.pinned && state.pinned !== td) return;
      clearTimeout(state.timer);
      state.timer = setTimeout(function () { showTip(td); }, 120);
    } else if (!state.pinned && !(e.target.closest && e.target.closest('#tip'))) { hideTip(); }
  });
  document.addEventListener('focusin', function (e) { var td = cellOf(e.target); if (td && !state.pinned) showTip(td); });
  document.addEventListener('focusout', function (e) { if (cellOf(e.target) && !state.pinned) hideTip(); });
  document.addEventListener('click', function (e) {
    var link = e.target.closest ? e.target.closest('a[data-goto]') : null;
    if (link) { e.preventDefault(); goTo(link.getAttribute('data-goto')); return; }
    if (e.target.closest && e.target.closest('a')) return;
    var td = cellOf(e.target);
    if (td) {
      if (state.pinned === td) { unpin(); hideTip(); } else { unpin(); state.pinned = td; td.classList.add('pinned'); showTip(td); }
    } else if (!(e.target.closest && e.target.closest('#tip'))) { unpin(); hideTip(); }
  });
  document.addEventListener('keydown', function (e) {
    if (e.key === 'Escape') { unpin(); hideTip(); return; }
    var td = e.target && e.target.matches && e.target.matches('td.tr[tabindex]') ? e.target : null;
    if (td && (e.key === 'Enter' || e.key === ' ')) {
      e.preventDefault();
      if (state.pinned === td) { unpin(); hideTip(); } else { unpin(); state.pinned = td; td.classList.add('pinned'); showTip(td); }
    }
  });
  window.addEventListener('scroll', function () { if (state.active && !state.pinned) hideTip(); }, true);
  window.addEventListener('resize', function () { if (state.active) position(state.active); });

  /* ---- sheets ---- */
  function showSheet(name) {
    if (cfg.sheets.indexOf(name) < 0) name = cfg.sheets[0];
    Array.prototype.forEach.call(document.querySelectorAll('.tab'), function (b) {
      b.setAttribute('aria-selected', b.getAttribute('data-sheet') === name ? 'true' : 'false');
    });
    Array.prototype.forEach.call(document.querySelectorAll('.sheet'), function (s) { s.hidden = s.id !== 'sheet-' + name; });
    hideTip(); unpin();
    var p = readHash(); p.sheet = name === cfg.sheets[0] ? '' : name; writeHash(p);
    return name;
  }
  function goTo(key) {
    var sheet = key.split('!')[0];
    showSheet(sheet);
    var td = document.querySelector('td[data-k="' + key + '"]');
    if (td) { td.scrollIntoView({ block: 'center', inline: 'nearest' }); td.classList.remove('flash'); void td.offsetWidth; td.classList.add('flash'); }
  }

  /* ---- language switching ---- */
  function setCells(on) { cells.forEach(function (td) { if (on) td.setAttribute('tabindex', '0'); else td.removeAttribute('tabindex'); }); }
  function offerDownload(code, mine) {
    setCells(false);
    setStatus(fmt(ui.status_download, { code: code }), { label: ui.status_download_btn, onClick: function () { makeTranslator(code, mine); } });
  }
  function makeTranslator(code, mine) {
    setStatus(fmt(ui.status_downloading, { code: code, pct: 0 }));
    var opts = { sourceLanguage: 'en', targetLanguage: code, monitor: function (m) {
      m.addEventListener('downloadprogress', function (e) { if (mine === state.token) setStatus(fmt(ui.status_downloading, { code: code, pct: Math.round(e.loaded * 100) })); });
    } };
    return withTimeout(Translator.create(opts), 180000).then(function (t) {
      if (mine !== state.token) { try { if (t.destroy) t.destroy(); } catch (e) { /* ignore */ } return; }
      state.translator = t; state.mode = 'api'; setCells(true);
      setStatus(fmt(ui.status_ready, { name: code }) + ' ' + ui.tip_hint);
    }).catch(function () { if (mine === state.token) { setCells(false); setStatus(fmt(ui.status_api_failed, { code: code })); } });
  }
  function startApi(code, mine) {
    if (!CODE_RE.test(code)) { setCells(false); setStatus(fmt(ui.status_bad_code, { code: code })); return Promise.resolve(); }
    if (typeof Translator === 'undefined') { setCells(false); setStatus(ui.status_api_missing); return Promise.resolve(); }
    return withTimeout(Translator.availability({ sourceLanguage: 'en', targetLanguage: code }), 6000).then(function (av) {
      if (mine !== state.token) return null;
      if (av === 'unavailable') { setCells(false); setStatus(fmt(ui.status_pair_unavailable, { code: code })); return null; }
      if (av === 'available') return makeTranslator(code, mine);
      offerDownload(code, mine);
      return null;
    }).catch(function () { if (mine === state.token) offerDownload(code, mine); });
  }
  function setLang(code, persist) {
    var mine = ++state.token;
    hideTip(); unpin();
    state.lang = code; state.mode = 'none'; state.pack = null; state.translator = null;
    document.documentElement.setAttribute('data-lang', code);
    if (persist) store('rv.lang', code);
    var p = readHash(); p.lang = code === 'en' ? '' : code; writeHash(p);
    syncSelect(code);
    var info = cfg.packs.filter(function (x) { return x.code === code; })[0];
    ui = UI[code] || UI.en;
    applyChrome();
    if (code === 'en') { setCells(false); setStatus(ui.status_off); return Promise.resolve(); }
    if (info) {
      setCells(false);
      setStatus(fmt(ui.status_loading, { code: code }));
      return loadPack(info).then(function (pack) {
        if (mine !== state.token) return;
        state.pack = pack; state.packName = info.name; state.mode = 'pack'; setCells(true);
        var stale = pack.meta && pack.meta.source_sha256 !== cfg.sha256;
        setStatus(fmt(ui.status_ready, { name: info.name }) + ' ' + ui.tip_hint + (stale ? ' ' + ui.status_pack_stale : ''));
      }).catch(function () {
        if (mine !== state.token) return;
        ui = UI.en; applyChrome(); setCells(false); setStatus(fmt(ui.status_pack_missing, { code: code }));
      });
    }
    return startApi(code, mine);
  }

  /* ---- start ---- */
  buildSelect();
  Array.prototype.forEach.call(document.querySelectorAll('.tab'), function (b) {
    b.addEventListener('click', function () { showSheet(b.getAttribute('data-sheet')); });
  });
  $('lang').addEventListener('change', function () {
    var v = $('lang').value;
    if (v === 'other') { $('other-box').hidden = false; $('other-code').focus(); return; }
    $('other-box').hidden = true;
    setLang(v, true);
  });
  function applyOther() { var c = $('other-code').value.trim().toLowerCase(); if (c) setLang(c, true); }
  $('other-apply').addEventListener('click', applyOther);
  $('other-code').addEventListener('keydown', function (e) { if (e.key === 'Enter') { e.preventDefault(); applyOther(); } });

  var h = readHash();
  showSheet(h.sheet || cfg.sheets[0]);
  var wanted = h.lang || load('rv.lang') || 'en';      /* URL fragment, then saved choice, then English */
  var ready = setLang(CODE_RE.test(wanted) ? wanted : 'en', false);

  window.__rv = { state: state, cfg: cfg, setLang: setLang, tipContent: tipContent, showSheet: showSheet, ready: ready };
  if (h.selftest === '1') {
    /* a test may run a scenario (for example a language switch while a translation is pending) before the result is read */
    ready.then(function () { return window.__rvSelftestHook ? window.__rvSelftestHook(window.__rv) : null; }).then(function () {
      var out = { lang: state.lang, mode: state.mode, translatable: cells.length, hasTranslator: typeof Translator !== 'undefined' };
      var first = cells[0];
      /* diagnostic: the page's Content-Security-Policy must refuse a network request (".invalid" never resolves anyway) */
      var violated = false;
      document.addEventListener('securitypolicyviolation', function () { violated = true; });
      try { fetch('https://rv-csp-probe.invalid/').catch(function () { /* expected */ }); } catch (e) { /* expected */ }
      return new Promise(function (done) { setTimeout(done, 200); }).then(function () {
        return first ? tipContent(first) : null;
      }).then(function (r) {
        out.cspBlocksNetwork = violated;
        out.firstKind = r ? r.kind : null; out.firstText = r && r.text ? r.text.slice(0, 80) : null;
        out.cache = Object.keys(state.cache).map(function (k) { return k + '=' + state.cache[k].text; });
        out.tabindexCells = document.querySelectorAll('td.tr[tabindex]').length;
        out.activeSheet = (document.querySelector('.tab[aria-selected=true]') || {}).textContent;
        out.hash = location.hash;
        var pre = document.createElement('script');
        pre.type = 'application/json'; pre.id = 'rv-selftest'; pre.textContent = JSON.stringify(out);
        document.body.appendChild(pre);
      });
    });
  }
}());

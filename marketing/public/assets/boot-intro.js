/* Drevalis marketing boot intro — cyberpunk CRT boot sequence.
 *
 * When it plays:
 *   • Initial visit to the site in a new tab / new window.
 *   • Any refresh (F5, Cmd-R, Ctrl-Shift-R).
 *   • Closing and reopening the browser (sessionStorage dies with the tab).
 *
 * When it does NOT play:
 *   • Navigating between pages via the nav (home → pricing → download, …).
 *     Those are full-page loads on a static site, so we gate on
 *     ``sessionStorage.drevalis_boot_seen`` which only persists within
 *     the current tab session — menu clicks therefore skip it after the
 *     first page view.
 *   • When the visitor has ``prefers-reduced-motion: reduce``.
 */
(function () {
  if (typeof window === 'undefined' || typeof document === 'undefined') return;

  try {
    if (window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
      return;
    }
  } catch (_) {}

  var KEY = 'drevalis_boot_seen';
  var isReload = false;
  try {
    var navEntries = performance.getEntriesByType('navigation');
    if (navEntries && navEntries[0] && navEntries[0].type === 'reload') isReload = true;
  } catch (_) {}
  // Legacy fallback (older Safari).
  if (!isReload && performance.navigation && performance.navigation.type === 1) {
    isReload = true;
  }

  var seen = false;
  try {
    seen = window.sessionStorage.getItem(KEY) === '1';
  } catch (_) {}

  if (seen && !isReload) return;

  var BOOT_DURATION_MS = 3400;
  var FADE_MS = 500;

  // Line schema: text, time-to-appear (ms), tone ('title' | 'info' | 'ok' | 'warn' | 'accent' | 'dim')
  var LINES = [
    { t: 'DREVALIS // CREATOR STUDIO', at: 0,    tone: 'title' },
    { t: '//  est. 2026 · Made in Switzerland · Self-hosted AI pipeline', at: 140, tone: 'dim' },
    { t: '',                                            at: 260,  tone: 'dim' },
    { t: '[BOOT] Initializing runtime ...............', at: 380,  tone: 'info' },
    { t: '[NET ] Handshake → drevalis.com ........... OK', at: 620, tone: 'ok' },
    { t: '[GPU ] Scene generator pool ............... OK', at: 860, tone: 'ok' },
    { t: '[LLM ] Script engine router ............... OK', at: 1100, tone: 'ok' },
    { t: '[TTS ] Voice engine stack .................. OK', at: 1340, tone: 'ok' },
    { t: '[CV  ] Video + captions pipeline ........... OK', at: 1580, tone: 'ok' },
    { t: '[SEC ] Encryption vault · OAuth vault ...... OK', at: 1820, tone: 'ok' },
    { t: '[LIC ] License service ..................... OK', at: 2060, tone: 'ok' },
    { t: '',                                            at: 2180, tone: 'dim' },
    { t: '> All systems nominal. Jacking in.',           at: 2320, tone: 'accent' },
    { t: '> Loading interface ...',                      at: 2620, tone: 'info' },
  ];

  var style = document.createElement('style');
  style.textContent =
    '#drev-boot{position:fixed;inset:0;z-index:10000;display:flex;align-items:center;justify-content:center;' +
    'background:radial-gradient(ellipse at 50% 40%,#0a0612 0%,#000 70%);color:#e6fbff;' +
    'font:14px/1.55 "JetBrains Mono",ui-monospace,SFMono-Regular,Menlo,monospace;' +
    'transition:opacity ' + FADE_MS + 'ms ease,filter ' + FADE_MS + 'ms ease;' +
    'animation:drev-crt-flicker 4.2s infinite;}' +
    '@keyframes drev-crt-flicker{' +
    '0%,97%,100%{filter:brightness(1)}' +
    '7%{filter:brightness(1.08) contrast(1.05)}' +
    '45%{filter:brightness(0.94) contrast(1.03)}' +
    '62%{filter:brightness(1.05)}' +
    '98%{filter:brightness(0.72)}}' +

    /* grid backdrop + horizon glow */
    '#drev-boot .grid{position:absolute;inset:0;pointer-events:none;' +
    'background-image:linear-gradient(rgba(255,43,214,0.08) 1px,transparent 1px),' +
    'linear-gradient(90deg,rgba(0,230,255,0.08) 1px,transparent 1px);' +
    'background-size:44px 44px;mask-image:radial-gradient(ellipse at 50% 100%,#000 0%,rgba(0,0,0,0.2) 70%);' +
    '-webkit-mask-image:radial-gradient(ellipse at 50% 100%,#000 0%,rgba(0,0,0,0.2) 70%);' +
    'transform:perspective(700px) rotateX(58deg) translateY(28%);opacity:0.55;}' +
    '#drev-boot .horizon{position:absolute;left:0;right:0;bottom:44%;height:1px;' +
    'background:linear-gradient(90deg,transparent,#ff2bd6,#00e6ff,transparent);' +
    'box-shadow:0 0 18px rgba(255,43,214,0.6),0 0 42px rgba(0,230,255,0.35);}' +

    /* CRT scanlines + vignette */
    '#drev-boot .scan{position:absolute;inset:0;pointer-events:none;' +
    'background:repeating-linear-gradient(0deg,rgba(0,0,0,0) 0,rgba(0,0,0,0) 2px,rgba(0,0,0,0.22) 2px,rgba(0,0,0,0.22) 3px);}' +
    '#drev-boot .vignette{position:absolute;inset:0;pointer-events:none;' +
    'background:radial-gradient(ellipse at center,rgba(0,0,0,0) 50%,rgba(0,0,0,0.85) 100%);}' +
    '#drev-boot .noise{position:absolute;inset:-10%;pointer-events:none;opacity:0.06;mix-blend-mode:overlay;' +
    'background-image:url("data:image/svg+xml;utf8,<svg xmlns=%22http://www.w3.org/2000/svg%22 width=%22120%22 height=%22120%22><filter id=%22n%22><feTurbulence baseFrequency=%220.9%22 numOctaves=%222%22 stitchTiles=%22stitch%22/></filter><rect width=%22100%25%22 height=%22100%25%22 filter=%22url(%23n)%22 opacity=%220.7%22/></svg>");}' +

    /* main column */
    '#drev-boot .wrap{position:relative;z-index:2;max-width:760px;width:92%;padding:36px 28px 28px;' +
    'border:1px solid rgba(0,230,255,0.25);border-radius:10px;' +
    'background:linear-gradient(180deg,rgba(10,6,18,0.78),rgba(0,0,0,0.82));' +
    'box-shadow:0 0 0 1px rgba(255,43,214,0.18) inset,' +
    '0 0 40px rgba(0,230,255,0.12),0 0 80px rgba(255,43,214,0.10);}' +
    '#drev-boot .chip{display:inline-flex;align-items:center;gap:8px;padding:3px 10px;border-radius:999px;' +
    'border:1px solid rgba(0,230,255,0.35);font-size:10px;letter-spacing:0.14em;text-transform:uppercase;' +
    'color:#00e6ff;background:rgba(0,230,255,0.06);margin-bottom:14px;}' +
    '#drev-boot .chip .dot{width:7px;height:7px;border-radius:50%;background:#7cff8a;' +
    'box-shadow:0 0 8px #7cff8a;animation:drev-pulse 1.2s ease-in-out infinite;}' +
    '@keyframes drev-pulse{0%,100%{opacity:1;transform:scale(1)}50%{opacity:0.45;transform:scale(0.85)}}' +

    /* title with chromatic split */
    '#drev-boot .title{position:relative;font:700 22px/1.1 "JetBrains Mono",ui-monospace,monospace;' +
    'letter-spacing:0.06em;color:#fff;text-shadow:0 0 12px rgba(255,255,255,0.35);margin-bottom:4px;' +
    'min-height:1.1em;white-space:pre;}' +
    '#drev-boot .title::before,#drev-boot .title::after{' +
    'content:attr(data-text);position:absolute;inset:0;pointer-events:none;mix-blend-mode:screen;}' +
    '#drev-boot .title::before{color:#ff2bd6;transform:translate(-2px,0);text-shadow:0 0 10px rgba(255,43,214,0.7);' +
    'animation:drev-shift-a 3s steps(24) infinite;}' +
    '#drev-boot .title::after{color:#00e6ff;transform:translate(2px,0);text-shadow:0 0 10px rgba(0,230,255,0.7);' +
    'animation:drev-shift-b 3s steps(24) infinite;}' +
    '@keyframes drev-shift-a{0%,92%,100%{transform:translate(-2px,0)}94%{transform:translate(-5px,1px)}96%{transform:translate(1px,-1px)}98%{transform:translate(-3px,0)}}' +
    '@keyframes drev-shift-b{0%,92%,100%{transform:translate(2px,0)}94%{transform:translate(5px,-1px)}96%{transform:translate(-1px,1px)}98%{transform:translate(3px,0)}}' +

    '#drev-boot .sub{font-size:11px;color:rgba(230,251,255,0.55);letter-spacing:0.14em;text-transform:uppercase;margin-bottom:18px;}' +

    /* output lines */
    '#drev-boot .out{min-height:260px;}' +
    '#drev-boot .line{animation:drev-in 220ms ease-out both;min-height:1.55em;white-space:pre;font-variant-numeric:tabular-nums;}' +
    '@keyframes drev-in{from{opacity:0;transform:translateX(-6px)}to{opacity:1;transform:translateX(0)}}' +
    '#drev-boot .line.tone-title{color:#fff;font-weight:600;}' +
    '#drev-boot .line.tone-info{color:#00e6ff;text-shadow:0 0 8px rgba(0,230,255,0.45);}' +
    '#drev-boot .line.tone-ok{color:#7cff8a;text-shadow:0 0 8px rgba(124,255,138,0.35);}' +
    '#drev-boot .line.tone-warn{color:#ffd166;text-shadow:0 0 8px rgba(255,209,102,0.35);}' +
    '#drev-boot .line.tone-accent{color:#ff2bd6;text-shadow:0 0 10px rgba(255,43,214,0.6);letter-spacing:0.04em;}' +
    '#drev-boot .line.tone-dim{color:rgba(230,251,255,0.38);}' +
    '#drev-boot .line .ok{color:#7cff8a;text-shadow:0 0 8px #7cff8a;}' +

    '#drev-boot .cur{display:inline-block;width:9px;height:1em;background:#00e6ff;vertical-align:-3px;margin-left:4px;' +
    'box-shadow:0 0 8px #00e6ff,0 0 18px rgba(0,230,255,0.6);animation:drev-blink 780ms steps(2) infinite;}' +
    '@keyframes drev-blink{to{opacity:0}}' +

    /* progress bar */
    '#drev-boot .bar{height:4px;margin-top:22px;border-radius:2px;background:rgba(0,230,255,0.12);position:relative;overflow:hidden;}' +
    '#drev-boot .bar::before{content:"";position:absolute;inset:0;width:var(--p,0%);border-radius:2px;' +
    'background:linear-gradient(90deg,#00e6ff,#ff2bd6);box-shadow:0 0 14px rgba(255,43,214,0.55);' +
    'transition:width 120ms linear;}' +
    '#drev-boot .bar::after{content:"";position:absolute;top:0;bottom:0;width:20%;background:linear-gradient(90deg,transparent,rgba(255,255,255,0.35),transparent);' +
    'animation:drev-sweep 1.4s linear infinite;}' +
    '@keyframes drev-sweep{0%{transform:translateX(-100%)}100%{transform:translateX(520%)}}' +
    '#drev-boot .meta{display:flex;justify-content:space-between;font-size:11px;color:rgba(230,251,255,0.45);letter-spacing:0.08em;margin-top:8px;}' +

    /* skip button */
    '#drev-boot .skip{position:fixed;bottom:18px;right:18px;z-index:3;background:transparent;' +
    'border:1px solid rgba(0,230,255,0.3);color:rgba(230,251,255,0.7);font:500 11px/1 "JetBrains Mono",monospace;' +
    'letter-spacing:0.14em;text-transform:uppercase;padding:8px 12px;border-radius:6px;cursor:pointer;' +
    'transition:color 120ms,border-color 120ms,background 120ms;}' +
    '#drev-boot .skip:hover{color:#fff;border-color:#ff2bd6;background:rgba(255,43,214,0.08);}' +

    /* ── Matrix-rain sidebar columns ───────────────────────────── */
    '#drev-boot .rain{position:absolute;inset:0;pointer-events:none;overflow:hidden;' +
    'mask-image:linear-gradient(90deg,#000 0%,rgba(0,0,0,0.25) 12%,transparent 22%,transparent 78%,rgba(0,0,0,0.25) 88%,#000 100%);' +
    '-webkit-mask-image:linear-gradient(90deg,#000 0%,rgba(0,0,0,0.25) 12%,transparent 22%,transparent 78%,rgba(0,0,0,0.25) 88%,#000 100%);' +
    'font-family:"JetBrains Mono",monospace;font-size:13px;line-height:1.12;color:#00e6ff;opacity:0.55;}' +
    '#drev-boot .rain .col{position:absolute;top:-40%;white-space:pre;text-shadow:0 0 6px rgba(0,230,255,0.75);' +
    'animation:drev-rain 5.5s linear infinite;}' +
    '#drev-boot .rain .col:nth-child(odd){color:#ff2bd6;text-shadow:0 0 6px rgba(255,43,214,0.75);}' +
    '@keyframes drev-rain{0%{transform:translateY(-20%)}100%{transform:translateY(140%)}}' +

    /* ── VHS / RGB shear glitch bar — fires every ~1.3s ────────── */
    '#drev-boot .glitch-bar{position:absolute;left:0;right:0;height:14px;pointer-events:none;z-index:3;' +
    'background:linear-gradient(90deg,transparent,rgba(255,43,214,0.75),rgba(0,230,255,0.75),transparent);' +
    'mix-blend-mode:screen;animation:drev-glitch 5.2s steps(1) infinite;top:30%;}' +
    '#drev-boot .glitch-bar.b2{animation-delay:1.6s;background:linear-gradient(90deg,transparent,rgba(0,230,255,0.55),transparent);height:3px;top:62%;}' +
    '#drev-boot .glitch-bar.b3{animation-delay:3.1s;background:linear-gradient(90deg,transparent,rgba(255,255,255,0.35),transparent);height:1px;top:18%;}' +
    '@keyframes drev-glitch{' +
    '0%,6%,100%{opacity:0;transform:translateX(0)}' +
    '3%{opacity:1;transform:translateX(-8px)}' +
    '4%{opacity:0.7;transform:translateX(12px)}' +
    '5%{opacity:0.35;transform:translateX(-4px)}}' +

    /* ── Scrambled title — per-character cycling characters ────── */
    '#drev-boot .title .ch{display:inline-block;min-width:0.55em;text-align:center;}' +
    '#drev-boot .title .ch.settling{color:#00e6ff;text-shadow:0 0 6px rgba(0,230,255,0.8);}' +

    /* reduce size on narrow screens */
    '@media (max-width:520px){#drev-boot .wrap{padding:24px 18px;}#drev-boot .title{font-size:17px;}#drev-boot .out{min-height:220px;}#drev-boot .rain{display:none;}}' +
    '';
  document.head.appendChild(style);

  var host = document.createElement('div');
  host.id = 'drev-boot';
  host.innerHTML =
    '<div class="grid"></div>' +
    '<div class="horizon"></div>' +
    '<div class="rain" data-rain></div>' +
    '<div class="noise"></div>' +
    '<div class="glitch-bar"></div><div class="glitch-bar b2"></div><div class="glitch-bar b3"></div>' +
    '<div class="wrap">' +
      '<span class="chip"><span class="dot"></span>System boot</span>' +
      '<div class="title" data-text="DREVALIS // CREATOR STUDIO" data-title></div>' +
      '<div class="sub">Neural-assisted content pipeline · secure-by-default</div>' +
      '<div class="out" data-out></div>' +
      '<div class="bar" data-bar></div>' +
      '<div class="meta"><span>0x00 — checksum verified</span><span data-pct>0%</span></div>' +
    '</div>' +
    '<div class="scan"></div>' +
    '<div class="vignette"></div>' +
    '<button type="button" class="skip" aria-label="Skip intro">skip [esc]</button>';
  (document.body || document.documentElement).appendChild(host);

  // ── Matrix-rain columns ────────────────────────────────────────
  var rain = host.querySelector('[data-rain]');
  var RAIN_CHARS = 'ｦｱｳｴｵｶｷｸｹｺｻｼｽｾｿﾀﾁﾂﾃﾄﾅﾆﾇﾈﾉﾊﾋﾌﾍﾎ0123456789Dr3v@lı$<>#+*';
  for (var rc = 0; rc < 14; rc++) {
    var col = document.createElement('div');
    col.className = 'col';
    col.style.left = (rc * 7.6).toFixed(1) + '%';
    col.style.animationDelay = (-Math.random() * 5).toFixed(2) + 's';
    col.style.animationDuration = (4 + Math.random() * 3).toFixed(2) + 's';
    var buf = '';
    for (var ri = 0; ri < 36; ri++) {
      buf += RAIN_CHARS.charAt(Math.floor(Math.random() * RAIN_CHARS.length)) + '\n';
    }
    col.textContent = buf;
    rain.appendChild(col);
  }
  // Mirror column on the right half
  for (var rcR = 0; rcR < 14; rcR++) {
    var col2 = document.createElement('div');
    col2.className = 'col';
    col2.style.right = (rcR * 7.6).toFixed(1) + '%';
    col2.style.animationDelay = (-Math.random() * 5).toFixed(2) + 's';
    col2.style.animationDuration = (4 + Math.random() * 3).toFixed(2) + 's';
    var buf2 = '';
    for (var ri2 = 0; ri2 < 36; ri2++) {
      buf2 += RAIN_CHARS.charAt(Math.floor(Math.random() * RAIN_CHARS.length)) + '\n';
    }
    col2.textContent = buf2;
    rain.appendChild(col2);
  }

  // ── Title scramble ─────────────────────────────────────────────
  var titleEl = host.querySelector('[data-title]');
  (function scrambleTitle() {
    var target = 'DREVALIS // CREATOR STUDIO';
    var chars = '!<>-_\\/[]{}—=+*^?#01ABDEFGH';
    var spans = [];
    titleEl.textContent = '';
    for (var i = 0; i < target.length; i++) {
      var s = document.createElement('span');
      s.className = 'ch settling';
      s.textContent = target[i] === ' ' ? '\u00A0' : target[i];
      titleEl.appendChild(s);
      spans.push({ el: s, target: target[i], settled: target[i] === ' ' });
    }
    var settled = 0;
    var startTs = performance.now();
    var revealDurationMs = 850;
    function step() {
      var t = (performance.now() - startTs) / revealDurationMs;
      for (var j = 0; j < spans.length; j++) {
        var sp = spans[j];
        if (sp.settled) continue;
        var threshold = j / spans.length; // left-to-right cascade
        if (t >= threshold) {
          sp.el.textContent = sp.target === ' ' ? '\u00A0' : sp.target;
          sp.el.classList.remove('settling');
          sp.settled = true;
          settled++;
        } else {
          sp.el.textContent = chars.charAt(Math.floor(Math.random() * chars.length));
        }
      }
      if (settled < spans.length) requestAnimationFrame(step);
    }
    requestAnimationFrame(step);
  })();

  var out = host.querySelector('[data-out]');
  var bar = host.querySelector('[data-bar]');
  var pctLabel = host.querySelector('[data-pct]');
  var skipBtn = host.querySelector('.skip');
  var lockedScroll = document.body ? document.body.style.overflow : '';
  if (document.body) document.body.style.overflow = 'hidden';

  var start = performance.now();
  var rendered = 0;
  var fading = false;
  var rafId = 0;

  function finish() {
    if (fading) return;
    fading = true;
    try { window.sessionStorage.setItem(KEY, '1'); } catch (_) {}
    host.style.opacity = '0';
    host.style.filter = 'blur(6px)';
    setTimeout(function () {
      if (rafId) cancelAnimationFrame(rafId);
      if (host.parentNode) host.parentNode.removeChild(host);
      if (style.parentNode) style.parentNode.removeChild(style);
      if (document.body) document.body.style.overflow = lockedScroll;
      document.removeEventListener('keydown', onKey);
    }, FADE_MS);
  }

  function onKey(e) {
    if (e.key === 'Escape' || e.key === 'Enter' || e.key === ' ') {
      e.preventDefault();
      finish();
    }
  }
  document.addEventListener('keydown', onKey);
  skipBtn.addEventListener('click', finish);

  function tick() {
    var elapsed = performance.now() - start;
    var pct = Math.min(100, Math.round((elapsed / BOOT_DURATION_MS) * 100));
    bar.style.setProperty('--p', pct + '%');
    if (pctLabel) pctLabel.textContent = pct + '%';

    while (rendered < LINES.length && LINES[rendered].at <= elapsed) {
      var L = LINES[rendered];
      var div = document.createElement('div');
      div.className = 'line tone-' + (L.tone || 'info');
      var txt = L.t;
      if (txt === '') {
        div.innerHTML = '&nbsp;';
      } else if (L.tone === 'ok' && / OK$/.test(txt)) {
        // Highlight the trailing "OK" in neon green regardless of base tone.
        div.innerHTML = escapeHtml(txt.slice(0, -2)) + '<span class="ok">OK</span>';
      } else {
        div.textContent = txt;
      }
      out.appendChild(div);
      rendered++;
    }

    // Blinking cursor appears once all lines are out.
    if (rendered >= LINES.length && !out.querySelector('.cur-row')) {
      var curRow = document.createElement('div');
      curRow.className = 'line tone-info cur-row';
      curRow.innerHTML = '> <span class="cur"></span>';
      out.appendChild(curRow);
    }

    if (elapsed >= BOOT_DURATION_MS) {
      finish();
      return;
    }
    rafId = requestAnimationFrame(tick);
  }

  function escapeHtml(s) {
    return s
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;');
  }

  rafId = requestAnimationFrame(tick);
})();

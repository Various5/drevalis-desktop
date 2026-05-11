/* Drevalis cookie-consent banner — FADP / GDPR-compliant gate for GA4.
 *
 * How it works:
 *   • Before this script runs, each page hard-codes the gtag.js loader
 *     AND sets Consent Mode v2 defaults to "denied" via gtag('consent',
 *     'default', ...). That means gtag.js is loaded but GA fires no
 *     cookies and no hits until we flip the switches to "granted".
 *   • This script checks ``localStorage.drevalis_consent`` on load:
 *       "granted" → call gtag('consent', 'update', {...: 'granted'}).
 *       "denied"  → do nothing (stays denied).
 *       unset     → render the banner.
 *   • Accept / Decline both persist the choice + reveal the outcome via
 *     a gtag consent update call. A "Revoke" link in the footer of
 *     privacy.html lets users flip their choice later.
 *
 * The banner has zero external dependencies so it works even if the
 * Tailwind CDN is blocked.
 */
(function () {
  if (typeof window === 'undefined' || typeof document === 'undefined') return;

  var KEY = 'drevalis_consent';
  var value = null;
  try {
    value = window.localStorage.getItem(KEY);
  } catch (_) {
    // private mode or storage disabled — treat as unset, but skip persist.
  }

  function updateConsent(granted) {
    if (typeof window.gtag !== 'function') return;
    var state = granted ? 'granted' : 'denied';
    window.gtag('consent', 'update', {
      ad_storage: state,
      analytics_storage: state,
      ad_user_data: state,
      ad_personalization: state,
    });
  }

  function persist(choice) {
    try {
      window.localStorage.setItem(KEY, choice);
    } catch (_) {
      /* ignore */
    }
  }

  function applyStoredChoice() {
    if (value === 'granted') {
      updateConsent(true);
      return true;
    }
    if (value === 'denied') {
      updateConsent(false);
      return true;
    }
    return false;
  }

  function renderBanner() {
    if (document.getElementById('drevalis-consent-banner')) return;

    var style = document.createElement('style');
    style.textContent =
      '#drevalis-consent-banner{position:fixed;left:16px;right:16px;bottom:16px;z-index:9990;' +
      'max-width:520px;margin-left:auto;padding:18px 20px;border-radius:14px;' +
      'background:rgba(20,22,27,0.96);border:1px solid rgba(255,255,255,0.08);' +
      'box-shadow:0 20px 60px rgba(0,0,0,0.55);color:#E6E8EE;' +
      'font:14px/1.5 "DM Sans",system-ui,-apple-system,Segoe UI,Roboto,sans-serif;' +
      'backdrop-filter:blur(14px);-webkit-backdrop-filter:blur(14px);}' +
      '#drevalis-consent-banner h3{margin:0 0 6px;font:600 15px/1.3 "Outfit",system-ui,sans-serif;}' +
      '#drevalis-consent-banner p{margin:0 0 14px;color:#B4B8C1;font-size:13px;}' +
      '#drevalis-consent-banner a{color:#7cff8a;text-decoration:underline;}' +
      '#drevalis-consent-banner .cb-row{display:flex;gap:8px;flex-wrap:wrap;}' +
      '#drevalis-consent-banner button{cursor:pointer;padding:8px 14px;border-radius:8px;' +
      'font:500 13px/1 "DM Sans",system-ui,sans-serif;border:1px solid transparent;' +
      'transition:background 120ms,border-color 120ms;}' +
      '#drevalis-consent-banner .cb-accept{background:#7cff8a;color:#0A0B0E;}' +
      '#drevalis-consent-banner .cb-accept:hover{background:#5eea70;}' +
      '#drevalis-consent-banner .cb-decline{background:transparent;color:#E6E8EE;border-color:rgba(255,255,255,0.18);}' +
      '#drevalis-consent-banner .cb-decline:hover{background:rgba(255,255,255,0.06);}' +
      '@media (max-width:480px){#drevalis-consent-banner{left:8px;right:8px;bottom:8px;padding:14px 16px;}}';
    document.head.appendChild(style);

    var el = document.createElement('div');
    el.id = 'drevalis-consent-banner';
    el.setAttribute('role', 'dialog');
    el.setAttribute('aria-label', 'Cookie consent');
    el.innerHTML =
      '<h3>We use cookies for analytics</h3>' +
      '<p>We use Google Analytics to count visits and understand which pages are useful. ' +
      'No ads, no cross-site tracking. Read our <a href="/privacy">Privacy Policy</a>. ' +
      'You can change your mind any time via the link at the bottom of the privacy page.</p>' +
      '<div class="cb-row">' +
      '<button type="button" class="cb-accept">Accept analytics</button>' +
      '<button type="button" class="cb-decline">Decline</button>' +
      '</div>';

    el.querySelector('.cb-accept').addEventListener('click', function () {
      persist('granted');
      updateConsent(true);
      el.remove();
    });
    el.querySelector('.cb-decline').addEventListener('click', function () {
      persist('denied');
      updateConsent(false);
      el.remove();
    });

    var place = function () {
      (document.body || document.documentElement).appendChild(el);
    };
    if (document.readyState === 'loading') {
      document.addEventListener('DOMContentLoaded', place, { once: true });
    } else {
      place();
    }
  }

  // Public API: called from the revoke link in privacy.html.
  window.drevalisConsent = {
    revoke: function () {
      try {
        window.localStorage.removeItem(KEY);
      } catch (_) {
        /* ignore */
      }
      updateConsent(false);
      value = null;
      renderBanner();
    },
    accept: function () {
      persist('granted');
      updateConsent(true);
      var b = document.getElementById('drevalis-consent-banner');
      if (b) b.remove();
    },
    decline: function () {
      persist('denied');
      updateConsent(false);
      var b = document.getElementById('drevalis-consent-banner');
      if (b) b.remove();
    },
  };

  if (!applyStoredChoice()) {
    renderBanner();
  }

  // Wire any ``<a data-consent-revoke>`` links on the page so the
  // privacy policy can offer a CSP-safe revoke action without inline
  // ``onclick``. Uses delegation to survive late DOM insertions.
  function handleRevokeClick(ev) {
    var t = ev.target;
    while (t && t !== document) {
      if (t.hasAttribute && t.hasAttribute('data-consent-revoke')) {
        ev.preventDefault();
        if (window.drevalisConsent) window.drevalisConsent.revoke();
        return;
      }
      t = t.parentNode;
    }
  }
  document.addEventListener('click', handleRevokeClick);
})();

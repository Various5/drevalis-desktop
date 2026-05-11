/* Google gtag + Consent Mode v2 bootstrap, kept out of inline <script>
 * blocks so marketing pages can ship a strict CSP that drops
 * 'unsafe-inline' from script-src.
 *
 * Loaded before /assets/consent.js on every page; consent.js then
 * flips the default-denied flags to 'granted' when the visitor
 * accepts the banner.
 */
(function () {
  if (typeof window === 'undefined') return;
  window.dataLayer = window.dataLayer || [];
  function gtag() { window.dataLayer.push(arguments); }
  window.gtag = window.gtag || gtag;

  gtag('consent', 'default', {
    ad_storage: 'denied',
    analytics_storage: 'denied',
    ad_user_data: 'denied',
    ad_personalization: 'denied',
    wait_for_update: 500,
  });
  gtag('js', new Date());
  gtag('config', 'G-FJ3ZBMTLCF', { anonymize_ip: true });
})();

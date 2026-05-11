/* Tailwind CDN runtime config — pulled out of inline <script> to keep
 * the Content-Security-Policy free of 'unsafe-inline'. The CDN script
 * reads ``window.tailwind.config`` automatically.
 */
(function () {
  if (typeof window !== 'undefined' && window.tailwind) {
    window.tailwind.config = { darkMode: 'class' };
  }
})();

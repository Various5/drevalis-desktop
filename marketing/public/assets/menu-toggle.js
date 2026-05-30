/* Hamburger menu toggle — promoted from an inline ``onclick`` attribute
 * so a strict CSP without ``'unsafe-inline'`` can still drive the nav.
 *
 * Every page renders ``<button class="site-menu-btn">``; this script
 * wires a single click handler that flips ``html.nav-open``.
 */
(function () {
  if (typeof document === 'undefined') return;
  function bind() {
    document.querySelectorAll('.site-menu-btn').forEach(function (btn) {
      if (btn.dataset.bound === '1') return;
      btn.dataset.bound = '1';
      btn.setAttribute('aria-expanded', 'false');
      // Point aria-controls at the nav drawer (giving it an id if it lacks
      // one) so assistive tech announces what the button opens.
      var links = document.querySelector('.site-nav-links');
      if (links) {
        if (!links.id) links.id = 'site-nav';
        btn.setAttribute('aria-controls', links.id);
      }
      btn.addEventListener('click', function () {
        var open = document.documentElement.classList.toggle('nav-open');
        btn.setAttribute('aria-expanded', String(open));
      });
    });
    // Close the menu when a nav link inside the drawer is clicked so
    // returning to the page with an anchor link doesn't leave the
    // drawer hanging open.
    document.querySelectorAll('.site-nav-links a').forEach(function (a) {
      if (a.dataset.bound === '1') return;
      a.dataset.bound = '1';
      a.addEventListener('click', function () {
        document.documentElement.classList.remove('nav-open');
        var btn = document.querySelector('.site-menu-btn');
        if (btn) btn.setAttribute('aria-expanded', 'false');
      });
    });
  }
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', bind, { once: true });
  } else {
    bind();
  }
})();

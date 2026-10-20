// The house style for a landing page.
//
// Two behaviours, and both of them are opt-out rather than opt-in:
// the page remembers that the reader asked for reduced motion, and the
// copy button on a command line tells you it worked.
//
// Everything here respects prefers-reduced-motion. The standard bans
// motion that cannot be turned off.

(function () {
  'use strict';

  // The copy button. A command line that is hard to copy is a command line
  // nobody runs.
  function setUpCopyButtons() {
    var buttons = document.querySelectorAll('[data-copy]');
    Array.prototype.forEach.call(buttons, function (button) {
      button.addEventListener('click', function () {
        var text = button.getAttribute('data-copy');
        var done = function () {
          var label = button.textContent;
          button.textContent = 'Copied';
          button.setAttribute('aria-live', 'polite');
          window.setTimeout(function () {
            button.textContent = label;
          }, 1400);
        };

        if (navigator.clipboard && navigator.clipboard.writeText) {
          navigator.clipboard.writeText(text).then(done, function () {});
          return;
        }

        // A page served over plain HTTP has no clipboard API. The old way
        // still works.
        var area = document.createElement('textarea');
        area.value = text;
        area.setAttribute('readonly', '');
        area.style.position = 'absolute';
        area.style.left = '-9999px';
        document.body.appendChild(area);
        area.select();
        try {
          document.execCommand('copy');
          done();
        } catch (error) {
          // Nothing to do: the text is on screen either way.
        }
        document.body.removeChild(area);
      });
    });
  }

  // The platform-specific download button. A page that shows a Linux
  // button to a Windows reader is a page that has not been looked at.
  function setUpPlatformButtons() {
    var buttons = document.querySelectorAll('[data-os]');
    if (!buttons.length) {
      return;
    }

    var platform = 'unknown';
    var agent = navigator.userAgent.toLowerCase();
    if (agent.indexOf('win') !== -1) {
      platform = 'windows';
    } else if (agent.indexOf('mac') !== -1 || agent.indexOf('darwin') !== -1) {
      platform = 'macos';
    } else if (agent.indexOf('linux') !== -1 || agent.indexOf('x11') !== -1) {
      platform = 'linux';
    }

    Array.prototype.forEach.call(buttons, function (button) {
      var wanted = button.getAttribute('data-os');
      if (wanted === platform) {
        button.removeAttribute('hidden');
      } else {
        button.setAttribute('hidden', 'hidden');
      }
    });
  }

  // Sections that come in when they scroll into view. With reduced motion
  // they are simply there from the start.
  function setUpReveal() {
    var items = document.querySelectorAll('.reveal');
    if (!items.length) {
      return;
    }

    var reduced = window.matchMedia('(prefers-reduced-motion: reduce)');
    if (reduced.matches || !('IntersectionObserver' in window)) {
      Array.prototype.forEach.call(items, function (item) {
        item.classList.add('is-visible');
      });
      return;
    }

    var observer = new IntersectionObserver(function (entries) {
      entries.forEach(function (entry) {
        if (entry.isIntersecting) {
          entry.target.classList.add('is-visible');
          observer.unobserve(entry.target);
        }
      });
    }, { rootMargin: '0px 0px -10% 0px' });

    Array.prototype.forEach.call(items, function (item) {
      observer.observe(item);
    });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', function () {
      setUpCopyButtons();
      setUpPlatformButtons();
      setUpReveal();
    });
  } else {
    setUpCopyButtons();
    setUpPlatformButtons();
    setUpReveal();
  }
})();

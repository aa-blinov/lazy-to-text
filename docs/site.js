// Lazy to Text landing page. Small by design: no framework, no network calls.
(() => {
  const root = document.documentElement;
  root.classList.add("js");

  const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  // The download button for the visitor's own system is the primary one.
  const platform = (navigator.userAgentData && navigator.userAgentData.platform) || navigator.platform || "";
  const onMac = /Mac|iPhone|iPad/.test(platform);
  document.querySelectorAll("[data-os]").forEach((link) => {
    link.classList.toggle("is-primary", (link.dataset.os === "macos") === onMac);
  });

  // Sections reveal once as they scroll into view.
  const revealables = document.querySelectorAll(".reveal");
  if (reduceMotion || !("IntersectionObserver" in window)) {
    revealables.forEach((el) => el.classList.add("is-visible"));
  } else {
    const reveal = new IntersectionObserver(
      (entries) => {
        entries.forEach((entry) => {
          if (entry.isIntersecting) {
            entry.target.classList.add("is-visible");
            reveal.unobserve(entry.target);
          }
        });
      },
      { threshold: 0.15 }
    );
    revealables.forEach((el) => reveal.observe(el));
  }

  // The hero dictation plays once, the first time it is on screen.
  // Without motion, or without JavaScript, the finished sentence is shown.
  const typed = document.querySelector("[data-typed]");
  const wave = document.querySelector(".wave");
  if (!typed || !wave || reduceMotion) return;

  const sentence = Array.from(typed.textContent.trim());
  typed.textContent = "";

  const play = () => {
    wave.classList.add("is-speaking");
    typed.classList.add("is-typing");
    let index = 0;
    const timer = window.setInterval(() => {
      index += 1;
      typed.textContent = sentence.slice(0, index).join("");
      if (index >= sentence.length) {
        window.clearInterval(timer);
        wave.classList.remove("is-speaking");
        typed.classList.remove("is-typing");
      }
    }, 46);
  };

  const demo = typed.closest(".demo");
  if ("IntersectionObserver" in window && demo) {
    const once = new IntersectionObserver(
      (entries) => {
        if (entries.some((entry) => entry.isIntersecting)) {
          once.disconnect();
          window.setTimeout(play, 400);
        }
      },
      { threshold: 0.5 }
    );
    once.observe(demo);
  } else {
    window.setTimeout(play, 400);
  }
})();

// The intro shown on first visit: who the user plays (customer, then approver) and what to watch.
// Self-contained; it only touches the #intro dialog, the help button, the demo picker and the
// user's name (via window.setUserName in app.js).
"use strict";

(() => {
  const SEEN = "intro-seen-v1";
  const dlg = document.getElementById("intro");
  const slides = [...dlg.querySelectorAll(".slide")];
  const dotsBox = dlg.querySelector(".intro-dots");
  const back = dlg.querySelector("[data-go=back]");
  const next = dlg.querySelector("[data-go=next]");
  const still = matchMedia("(prefers-reduced-motion: reduce)");
  const nameInput = document.getElementById("user-name");
  let at = 0;

  // --- the character and its hats (inline SVG, coloured by CSS tokens) ----------------------

  const cap = `
    <path d="M32 62 Q60 24 88 62 Z" class="cap"/>
    <path d="M60 58 H100 Q106 58 103 64 H58 Z" class="cap-bill"/>
    <circle cx="60" cy="40" r="3" class="cap-bill"/>`;
  const topHat = `
    <rect x="40" y="16" width="40" height="42" rx="3" class="tophat"/>
    <rect x="40" y="46" width="40" height="8" class="tophat-band"/>
    <ellipse cx="60" cy="59" rx="32" ry="6" class="tophat"/>`;
  const hat = (svg, cls, pos = "translate(0 0)") =>
    `<g transform="${pos}"><g class="${cls}">${svg}</g></g>`;

  function figure(kind) {
    const hats = {
      juggle: hat(cap, "bob", "translate(-70 -5) scale(.8)") + hat(topHat, "bob late", "translate(120 -5) scale(.8)"),
      customer: hat(cap, "wiggle"),
      swap: hat(cap, "fly-off") + hat(topHat, "drop-in"),
      stack: hat(topHat, "") + hat(cap, "teeter", "translate(0 -40)"),
    }[kind];
    const wide = kind === "juggle";
    return `
      <svg viewBox="${wide ? "-80 -20 280 170" : "0 -45 120 190"}" class="figure ${kind}" aria-hidden="true">
        <g class="${kind === "swap" ? "squish" : "breathe"}">
          <ellipse cx="60" cy="100" rx="40" ry="38" class="blob"/>
          <circle cx="40" cy="106" r="6" class="cheek"/><circle cx="80" cy="106" r="6" class="cheek"/>
          <g class="eyes"><circle cx="47" cy="92" r="4.5" class="eye"/><circle cx="73" cy="92" r="4.5" class="eye"/></g>
          <path d="M50 108 Q60 117 70 108" class="smile"/>
        </g>
        ${hats}
      </svg>`;
  }
  for (const s of dlg.querySelectorAll("[data-figure]")) s.insertAdjacentHTML("afterbegin", figure(s.dataset.figure));

  // --- paging -----------------------------------------------------------------------------

  const dots = slides.map((_, i) => {
    const d = document.createElement("button");
    d.type = "button";
    d.setAttribute("aria-label", `Card ${i + 1} of ${slides.length}`);
    d.onclick = () => show(i);
    dotsBox.append(d);
    return d;
  });

  function show(i) {
    const dir = i < at ? "from-left" : "from-right";
    at = Math.max(0, Math.min(slides.length - 1, i));
    slides.forEach((s, j) => {
      s.hidden = j !== at;
      s.classList.remove("from-left", "from-right");
      if (j === at) { void s.offsetWidth; s.classList.add(dir); }
    });
    dots.forEach((d, j) => d.setAttribute("aria-current", String(j === at)));
    back.style.visibility = at === 0 ? "hidden" : "visible";
    next.textContent = slides[at].dataset.next;
  }

  function open() {
    nameInput.value = window.userName?.() || "";
    show(0);
    if (!dlg.open) dlg.showModal();
    next.focus();
  }

  function finish() {
    window.setUserName?.(nameInput.value);
    if (!still.matches) confetti(next);
    dlg.close();
    const demo = document.getElementById("demo");
    demo.open = true;
    demo.scrollIntoView({ behavior: "smooth", block: "start" });
    document.querySelector("#demo-cases button")?.focus({ preventScroll: true });
  }

  next.onclick = () => (at === slides.length - 1 ? finish() : show(at + 1));
  back.onclick = () => show(at - 1);
  dlg.querySelector("[data-go=skip]").onclick = () => dlg.close();
  dlg.addEventListener("click", (e) => {
    const r = dlg.getBoundingClientRect();
    const outside = e.clientX < r.left || e.clientX > r.right || e.clientY < r.top || e.clientY > r.bottom;
    if (e.target === dlg && outside) dlg.close();
  });
  dlg.addEventListener("keydown", (e) => {
    if (e.target === nameInput) {
      if (e.key === "Enter") { e.preventDefault(); finish(); }
      return;  // arrow keys move the caret, not the cards
    }
    if (e.target.tagName === "BUTTON" && (e.key === "Enter" || e.key === " ")) return;
    if (e.key === "ArrowRight") show(at + 1);
    if (e.key === "ArrowLeft") show(at - 1);
  });
  dlg.addEventListener("close", () => {
    try { localStorage.setItem(SEEN, "1"); } catch { /* storage blocked: show again next time */ }
  });
  document.getElementById("how-it-works").onclick = open;

  // A small burst of hats and dots from the button that closes the intro.
  function confetti(from) {
    const r = from.getBoundingClientRect();
    const glyphs = ["🎩", "🧢", "●", "■", "▲"];
    for (let i = 0; i < 18; i++) {
      const p = document.createElement("span");
      p.className = `confetti c${i % 4}`;
      p.textContent = glyphs[i % glyphs.length];
      const angle = (Math.PI * 2 * i) / 18 + Math.random() * 0.4;
      const dist = 80 + Math.random() * 120;
      p.style.left = `${r.left + r.width / 2}px`;
      p.style.top = `${r.top + r.height / 2}px`;
      p.style.setProperty("--dx", `${Math.cos(angle) * dist}px`);
      p.style.setProperty("--dy", `${Math.sin(angle) * dist - 60}px`);
      p.style.setProperty("--spin", `${(Math.random() - 0.5) * 720}deg`);
      document.body.append(p);
      setTimeout(() => p.remove(), 1000);  // animationend is unreliable in background windows
    }
  }

  let seen = false;
  try { seen = localStorage.getItem(SEEN) === "1"; } catch { /* storage blocked */ }
  if (!seen || new URLSearchParams(location.search).has("intro")) open();
})();

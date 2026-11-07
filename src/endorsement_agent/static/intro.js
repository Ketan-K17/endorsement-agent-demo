// The card decks: the intro shown on first visit (who the user plays, customer then approver,
// and what to watch), and the celebration shown once a case reaches the insurer (how to read
// what just happened). Self-contained; it only touches the two dialogs, the help button, the
// demo picker, the tabs (via window.selectTab) and the user's name (via window.setUserName).
"use strict";

(() => {
  const SEEN = "intro-seen-v1";
  const still = matchMedia("(prefers-reduced-motion: reduce)");

  // --- the character and its hats (inline SVG, coloured by CSS tokens) ----------------------

  const cap = `
    <path d="M32 62 Q60 24 88 62 Z" class="cap"/>
    <path d="M60 58 H100 Q106 58 103 64 H58 Z" class="cap-bill"/>
    <circle cx="60" cy="40" r="3" class="cap-bill"/>`;
  const topHat = `
    <rect x="40" y="16" width="40" height="42" rx="3" class="tophat"/>
    <rect x="40" y="46" width="40" height="8" class="tophat-band"/>
    <ellipse cx="60" cy="59" rx="32" ry="6" class="tophat"/>`;
  const envelope = `
    <rect x="84" y="62" width="34" height="24" rx="3" class="envelope"/>
    <path d="M86 65 L101 76 L116 65" class="envelope-flap"/>`;
  const hat = (svg, cls, pos = "translate(0 0)") =>
    `<g transform="${pos}"><g class="${cls}">${svg}</g></g>`;

  function figure(kind) {
    const hats = {
      juggle: hat(cap, "bob", "translate(-70 -5) scale(.8)") + hat(topHat, "bob late", "translate(120 -5) scale(.8)"),
      customer: hat(cap, "wiggle"),
      swap: hat(cap, "fly-off") + hat(topHat, "drop-in"),
      stack: hat(topHat, "") + hat(cap, "teeter", "translate(0 -40)"),
      cheer: hat(topHat, "bob") + hat(envelope, "send-off"),
      tip: hat(topHat, "tip"),
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
  for (const s of document.querySelectorAll("[data-figure]")) s.insertAdjacentHTML("afterbegin", figure(s.dataset.figure));

  // --- paging, shared by both decks -------------------------------------------------------

  function deck(dlg, finish) {
    const slides = [...dlg.querySelectorAll(".slide")];
    const back = dlg.querySelector("[data-go=back]");
    const next = dlg.querySelector("[data-go=next]");
    let at = 0;

    const dots = slides.map((_, i) => {
      const d = document.createElement("button");
      d.type = "button";
      d.setAttribute("aria-label", `Card ${i + 1} of ${slides.length}`);
      d.onclick = () => show(i);
      dlg.querySelector(".intro-dots").append(d);
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

    next.onclick = () => (at === slides.length - 1 ? finish() : show(at + 1));
    back.onclick = () => show(at - 1);
    dlg.querySelector("[data-go=skip]").onclick = () => dlg.close();
    dlg.addEventListener("click", (e) => {
      const r = dlg.getBoundingClientRect();
      const outside = e.clientX < r.left || e.clientX > r.right || e.clientY < r.top || e.clientY > r.bottom;
      if (e.target === dlg && outside) dlg.close();
    });
    dlg.addEventListener("keydown", (e) => {
      if (e.target.tagName === "INPUT") {
        if (e.key === "Enter") { e.preventDefault(); finish(); }
        return;  // arrow keys move the caret, not the cards
      }
      if (e.target.tagName === "BUTTON" && (e.key === "Enter" || e.key === " ")) return;
      if (e.key === "ArrowRight") show(at + 1);
      if (e.key === "ArrowLeft") show(at - 1);
    });

    return {
      next,
      open() {
        show(0);
        if (!dlg.open) dlg.showModal();
        next.focus();
      },
    };
  }

  // A small burst of glyphs from `from`: over the page, or inside `host` (a dialog's scene,
  // since the page sits under an open modal's top layer).
  function confetti(from, glyphs, host = document.body) {
    if (still.matches) return;
    const r = from.getBoundingClientRect();
    const h = host === document.body ? { left: 0, top: 0 } : host.getBoundingClientRect();
    for (let i = 0; i < 18; i++) {
      const p = document.createElement("span");
      p.className = `confetti c${i % 4}`;
      p.textContent = glyphs[i % glyphs.length];
      const angle = (Math.PI * 2 * i) / 18 + Math.random() * 0.4;
      const dist = 80 + Math.random() * 120;
      p.style.left = `${r.left + r.width / 2 - h.left}px`;
      p.style.top = `${r.top + r.height / 2 - h.top}px`;
      p.style.setProperty("--dx", `${Math.cos(angle) * dist}px`);
      p.style.setProperty("--dy", `${Math.sin(angle) * dist - 60}px`);
      p.style.setProperty("--spin", `${(Math.random() - 0.5) * 720}deg`);
      host.append(p);
      setTimeout(() => p.remove(), 1000);  // animationend is unreliable in background windows
    }
  }

  // --- the intro --------------------------------------------------------------------------

  const intro = document.getElementById("intro");
  const nameInput = document.getElementById("user-name");
  const introDeck = deck(intro, () => {
    window.setUserName?.(nameInput.value);
    confetti(introDeck.next, ["🎩", "🧢", "●", "■", "▲"]);
    intro.close();
    const demo = document.getElementById("demo");
    demo.open = true;
    demo.scrollIntoView({ behavior: "smooth", block: "start" });
    document.querySelector("#demo-cases button")?.focus({ preventScroll: true });
  });

  function openIntro() {
    nameInput.value = window.userName?.() || "";
    introDeck.open();
  }

  intro.addEventListener("close", () => {
    try { localStorage.setItem(SEEN, "1"); } catch { /* storage blocked: show again next time */ }
  });
  document.getElementById("how-it-works").onclick = openIntro;

  // --- the celebration, once the approved case is with the insurer --------------------------

  const hooray = document.getElementById("hooray");
  const hoorayDeck = deck(hooray, () => {
    confetti(hoorayDeck.next, ["🎉", "✉️", "●", "■", "▲"]);
    hooray.close();
    window.selectTab?.("context");
  });

  window.celebrateSubmission = ({ insurer, ref }) => {
    if (intro.open) intro.close();
    const you = window.userName?.() || "";
    for (const n of hooray.querySelectorAll("[data-fill=insurer]")) n.textContent = insurer || "the insurer";
    for (const n of hooray.querySelectorAll("[data-fill=ref]")) n.textContent = ref;
    for (const n of hooray.querySelectorAll("[data-fill=you]")) n.textContent = you ? `, ${you}` : "";
    hoorayDeck.open();
    const scene = hooray.querySelector(".scene");
    setTimeout(() => confetti(scene.querySelector(".figure"), ["🎉", "✨", "●", "■", "▲"], scene), 450);
  };

  let seen = false;
  try { seen = localStorage.getItem(SEEN) === "1"; } catch { /* storage blocked */ }
  if (!seen || new URLSearchParams(location.search).has("intro")) openIntro();
})();

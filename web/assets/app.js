/* 社内FAQ AI — shared client utilities: theme, toasts, confirm modal. */

const Theme = {
  KEY: "sfa-theme",
  init() {
    const saved = localStorage.getItem(this.KEY);
    if (saved) document.documentElement.setAttribute("data-theme", saved);
  },
  current() {
    const attr = document.documentElement.getAttribute("data-theme");
    if (attr) return attr;
    return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
  },
  toggle() {
    const next = this.current() === "dark" ? "light" : "dark";
    document.documentElement.setAttribute("data-theme", next);
    localStorage.setItem(this.KEY, next);
  },
  mountToggle(el) {
    el.addEventListener("click", () => this.toggle());
  },
};
Theme.init();

function el(tag, cls, text) {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (text !== undefined) e.textContent = text;
  return e;
}

const ICONS = {
  check: '<svg viewBox="0 0 20 20" fill="none"><path d="M4 10.5l3.5 3.5L16 6" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>',
  alert: '<svg viewBox="0 0 20 20" fill="none"><path d="M10 6.5v4.5M10 14h.01M17.5 10a7.5 7.5 0 11-15 0 7.5 7.5 0 0115 0z" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/></svg>',
};

let toastStack = null;
function ensureToastStack() {
  if (!toastStack) {
    toastStack = document.getElementById("toast-stack");
    if (!toastStack) {
      toastStack = el("div");
      toastStack.id = "toast-stack";
      document.body.appendChild(toastStack);
    }
  }
  return toastStack;
}

function toast(message, type = "success", duration = 3200) {
  const stack = ensureToastStack();
  const t = el("div", `toast toast-${type}`);
  t.innerHTML = (type === "error" ? ICONS.alert : ICONS.check) + `<span>${message}</span>`;
  stack.appendChild(t);
  setTimeout(() => {
    t.classList.add("leaving");
    setTimeout(() => t.remove(), 220);
  }, duration);
}

function confirmDialog({ title, body, confirmLabel = "削除", cancelLabel = "キャンセル", danger = true }) {
  return new Promise(resolve => {
    const backdrop = el("div", "modal-backdrop");
    const modal = el("div", "modal");
    modal.appendChild(el("h3", null, title));
    modal.appendChild(el("p", null, body));
    const actions = el("div", "modal-actions");
    const cancelBtn = el("button", "btn btn-ghost", cancelLabel);
    const okBtn = el("button", danger ? "btn btn-danger-ghost" : "btn btn-primary", confirmLabel);
    okBtn.style.background = danger ? "var(--danger)" : "";
    okBtn.style.color = danger ? "#fff" : "";
    okBtn.style.borderColor = danger ? "var(--danger)" : "";
    actions.appendChild(cancelBtn);
    actions.appendChild(okBtn);
    modal.appendChild(actions);
    backdrop.appendChild(modal);
    document.body.appendChild(backdrop);

    function close(result) {
      backdrop.remove();
      document.removeEventListener("keydown", onKey);
      resolve(result);
    }
    function onKey(e) { if (e.key === "Escape") close(false); }
    document.addEventListener("keydown", onKey);
    backdrop.addEventListener("click", e => { if (e.target === backdrop) close(false); });
    cancelBtn.addEventListener("click", () => close(false));
    okBtn.addEventListener("click", () => close(true));
    okBtn.focus();
  });
}

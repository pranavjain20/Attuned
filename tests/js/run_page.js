// Runs the page's inline script against a minimal stand-in for the browser DOM and
// prints what it rendered as JSON. Only the few DOM calls the page script makes exist.
// Usage: node run_page.js <page-script.js> <data.json>
"use strict";
const fs = require("fs");
const vm = require("vm");

const [scriptPath, dataPath] = process.argv.slice(2);
let chips = [];

function element(id) {
  const el = {
    id, textContent: "", disabled: false, listeners: {}, attrs: {}, html: "",
    addEventListener(type, fn) { (this.listeners[type] = this.listeners[type] || []).push(fn); },
    setAttribute(name, value) { this.attrs[name] = String(value); },
    getAttribute(name) { return name in this.attrs ? this.attrs[name] : null; },
    querySelectorAll() { return []; },
    closest() { return this; },
  };
  Object.defineProperty(el, "innerHTML", {
    get() { return this.html; },
    set(value) {
      this.html = String(value);
      if (this.id === "chips") {
        chips = [...this.html.matchAll(/<button class="chip" data-i="(\d+)">([^<]*)<\/button>/g)].map((m) => {
          const chip = element("chip");
          chip.setAttribute("data-i", m[1]);
          chip.label = m[2];
          return chip;
        });
      }
    },
  });
  return el;
}

const els = {};
for (const id of ["data", "main", "dow", "fulldate", "prev", "next", "chips"]) els[id] = element(id);
els.data.textContent = fs.readFileSync(dataPath, "utf8");

const context = {
  document: {
    getElementById: (id) => els[id] || null,
    querySelectorAll: (selector) => (selector === ".chip" ? chips : []),
    documentElement: { style: { setProperty() {} } },
    addEventListener() {},
  },
  requestAnimationFrame: (fn) => fn(),
  history: { replaceState() {} },
  location: { hash: "" },
};
vm.createContext(context);
vm.runInContext(fs.readFileSync(scriptPath, "utf8"), context);

function snapshot() {
  return {
    date: els.fulldate.textContent,
    main: els.main.innerHTML,
    prevDisabled: els.prev.disabled,
    nextDisabled: els.next.disabled,
    chips: chips.map((c) => ({ i: +c.getAttribute("data-i"), label: c.label, current: c.getAttribute("aria-current") })),
  };
}

const steps = [snapshot()];
els.prev.listeners.click.forEach((fn) => fn());
steps.push(snapshot());
els.chips.listeners.click.forEach((fn) => fn({ target: chips[chips.length - 1] }));
steps.push(snapshot());
process.stdout.write(JSON.stringify(steps));

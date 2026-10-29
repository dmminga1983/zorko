// Zorko page snapshot.
// Runs inside a frame. Walks the DOM (including open shadow roots), tags
// interactive elements with stable data-zorko-id numbers and returns a flat
// list of items in document order, plus hidden text for the injection guard.
(opts) => {
  const START = opts.startId;
  const MAX_TEXT = opts.maxText || 400;
  const SKIP = new Set(["SCRIPT", "STYLE", "NOSCRIPT", "TEMPLATE", "HEAD", "META", "LINK", "BR", "HR", "IFRAME", "FRAME", "OBJECT", "EMBED", "CANVAS", "VIDEO", "AUDIO", "PICTURE", "SOURCE", "TRACK", "MAP", "PATH"]);
  const INTERACTIVE_TAGS = new Set(["A", "BUTTON", "INPUT", "SELECT", "TEXTAREA", "SUMMARY", "DETAILS"]);
  const ROLES = new Set(["button", "link", "checkbox", "radio", "switch", "tab", "menuitem", "menuitemcheckbox", "menuitemradio", "option", "combobox", "textbox", "searchbox", "slider", "spinbutton", "treeitem"]);
  const REGIONS = { NAV: "nav", HEADER: "header", FOOTER: "footer", MAIN: "main", ASIDE: "aside", FORM: "form", DIALOG: "dialog" };
  const ROLE_REGIONS = { navigation: "nav", banner: "header", contentinfo: "footer", main: "main", complementary: "aside", form: "form", dialog: "dialog", alertdialog: "dialog", search: "search" };

  let next = START;
  const items = [];
  const hidden = [];
  let buf = [];

  const clean = (s) => (s || "").replace(/[ \s]+/g, " ").trim();
  const cut = (s, n) => (s.length > n ? s.slice(0, n - 1) + "…" : s);

  function flush() {
    if (!buf.length) return;
    const text = clean(buf.join(" "));
    buf = [];
    if (text) items.push({ k: "t", text: cut(text, MAX_TEXT) });
  }

  function styleOf(el) {
    try { return getComputedStyle(el); } catch (e) { return null; }
  }

  // Why an element is invisible to a human, or null when it is visible.
  function hiddenReason(el, st) {
    if (!st) return null;
    if (st.display === "none") return "display:none";
    if (st.visibility === "hidden" || st.visibility === "collapse") return "visibility:hidden";
    if (parseFloat(st.opacity) === 0) return "opacity:0";
    if (el.hasAttribute("hidden")) return "hidden";
    const fs = parseFloat(st.fontSize);
    if (fs > 0 && fs < 3) return "tiny-font";
    if (st.clip === "rect(0px, 0px, 0px, 0px)" || st.clipPath === "inset(50%)") return "clipped";
    const r = el.getBoundingClientRect();
    if ((st.position === "absolute" || st.position === "fixed") && (r.right < -500 || r.bottom < -500 || r.left > 20000)) return "offscreen";
    if (st.overflow === "hidden" && r.width <= 1 && r.height <= 1) return "zero-size";
    if (st.color && st.color === st.backgroundColor && st.color !== "rgba(0, 0, 0, 0)") return "same-color";
    return null;
  }

  function labelFor(el) {
    const al = el.getAttribute("aria-label");
    if (al && clean(al)) return clean(al);
    const lb = el.getAttribute("aria-labelledby");
    if (lb) {
      const t = lb.split(/\s+/).map((id) => {
        const n = el.getRootNode().getElementById ? el.getRootNode().getElementById(id) : document.getElementById(id);
        return n ? n.textContent : "";
      }).join(" ");
      if (clean(t)) return clean(t);
    }
    if (el.labels && el.labels.length) {
      const t = clean(Array.from(el.labels).map((l) => l.innerText || l.textContent).join(" "));
      if (t) return t;
    }
    return "";
  }

  function roleOf(el, st) {
    const r = (el.getAttribute("role") || "").toLowerCase();
    if (ROLES.has(r)) return r;
    const tag = el.tagName;
    if (tag === "A") return el.hasAttribute("href") ? "link" : (el.hasAttribute("onclick") ? "button" : null);
    if (tag === "BUTTON" || tag === "SUMMARY") return "button";
    if (tag === "SELECT") return "select";
    if (tag === "TEXTAREA") return "textarea";
    if (tag === "INPUT") {
      const t = (el.type || "text").toLowerCase();
      if (t === "hidden") return null;
      if (["button", "submit", "reset", "image"].includes(t)) return "button";
      if (t === "checkbox" || t === "radio") return t;
      if (t === "file") return "file";
      if (t === "range") return "slider";
      return "input";
    }
    if (el.isContentEditable && (!el.parentElement || !el.parentElement.isContentEditable)) return "textarea";
    if (el.hasAttribute("onclick")) return "button";
    // Div-buttons in modern apps: a pointer cursor that starts here, not inherited.
    if (st && st.cursor === "pointer" && el.tabIndex >= 0) return "button";
    if (st && st.cursor === "pointer" && el.parentElement) {
      const ps = styleOf(el.parentElement);
      if (ps && ps.cursor !== "pointer" && clean(el.innerText).length > 0 && clean(el.innerText).length < 80 && el.children.length <= 3) return "button";
    }
    return null;
  }

  function describe(el, role) {
    let id = el.getAttribute("data-zorko-id");
    if (!id) { id = String(next++); el.setAttribute("data-zorko-id", id); }
    const it = { k: "e", id: Number(id), role };
    const tag = el.tagName;
    let name = labelFor(el);
    if (role === "input" || role === "textarea" || role === "file" || role === "slider") {
      it.type = tag === "INPUT" ? (el.type || "text").toLowerCase() : (tag === "TEXTAREA" ? "multiline" : "editable");
      if (!name) name = clean(el.getAttribute("placeholder") || el.getAttribute("title") || el.getAttribute("name") || "");
      else if (el.getAttribute("placeholder")) it.hint = cut(clean(el.getAttribute("placeholder")), 60);
      const v = el.isContentEditable ? clean(el.innerText) : (el.value || "");
      if (it.type === "password") it.value = v ? "•••" : "";
      else if (v) it.value = cut(clean(v), 80);
      if (el.required) it.req = true;
    } else if (role === "select") {
      if (!name) name = clean(el.getAttribute("name") || "");
      const opts = Array.from(el.options || []).map((o) => clean(o.text));
      it.options = opts.slice(0, 15);
      if (opts.length > 15) it.more = opts.length - 15;
      const sel = el.options && el.selectedIndex >= 0 ? el.options[el.selectedIndex] : null;
      if (sel) it.value = clean(sel.text);
    } else if (role === "checkbox" || role === "radio" || role === "switch") {
      if (!name) {
        const p = el.closest("label");
        name = clean(p ? p.innerText : el.getAttribute("name") || "");
      }
      it.checked = tag === "INPUT" ? el.checked : el.getAttribute("aria-checked") === "true";
    } else {
      if (!name) {
        if (tag === "INPUT") name = clean(el.value || el.getAttribute("alt") || el.type);
        else {
          name = clean(el.innerText || el.textContent);
          if (!name) {
            const img = el.querySelector("img[alt], svg[aria-label], [title]");
            if (img) name = clean(img.getAttribute("alt") || img.getAttribute("aria-label") || img.getAttribute("title"));
          }
          if (!name) name = clean(el.getAttribute("title") || "");
        }
      }
      if (role === "link") it.href = el.getAttribute("href") || "";
      if (tag === "BUTTON" || (tag === "INPUT" && el.type === "submit")) {
        if ((el.type || "").toLowerCase() === "submit" && el.form) it.submit = true;
      }
    }
    if (el.disabled || el.getAttribute("aria-disabled") === "true") it.disabled = true;
    if (el.getAttribute("aria-expanded")) it.expanded = el.getAttribute("aria-expanded") === "true";
    it.name = cut(name, 100);
    if (el.form) {
      it.form = el.form.getAttribute("data-zorko-form") || (() => {
        const f = "f" + (window.__zorkoForms = (window.__zorkoForms || 0) + 1);
        el.form.setAttribute("data-zorko-form", f);
        return f;
      })();
    }
    return it;
  }

  function regionOf(el) {
    const r = (el.getAttribute("role") || "").toLowerCase();
    if (ROLE_REGIONS[r]) return ROLE_REGIONS[r];
    return REGIONS[el.tagName] || null;
  }

  function walk(node, depth) {
    if (depth > 200) return;
    if (node.nodeType === 3) {
      const t = node.nodeValue;
      if (t && t.trim()) buf.push(t);
      return;
    }
    if (node.nodeType !== 1) return;
    const el = node;
    if (SKIP.has(el.tagName)) {
      if (el.tagName === "BR") buf.push(" ");
      return;
    }
    const st = styleOf(el);
    const why = hiddenReason(el, st);
    if (why) {
      const t = clean(el.textContent);
      if (t.length > 15 && el.tagName !== "DIALOG" && el.tagName !== "OPTION") hidden.push({ why, text: cut(t, 600) });
      return;
    }
    if (el.tagName === "IMG") {
      const alt = clean(el.getAttribute("alt") || "");
      if (alt && alt.length > 2) { flush(); items.push({ k: "i", alt: cut(alt, 120) }); }
      return;
    }
    if (el.tagName === "svg" || el.tagName === "SVG") return;

    const role = roleOf(el, st);
    if (role) {
      flush();
      items.push(describe(el, role));
      // Descend only into containers that can hold other controls.
      if (role === "link" || role === "button") {
        const inner = el.querySelectorAll("a[href],button,input,select,textarea,[role=button],[role=link]");
        if (!inner.length) return;
      } else return;
    }

    const h = /^H([1-6])$/.exec(el.tagName);
    if (h || (el.getAttribute("role") === "heading")) {
      flush();
      const text = clean(el.innerText || el.textContent);
      if (text) items.push({ k: "h", level: h ? Number(h[1]) : Number(el.getAttribute("aria-level") || 2), text: cut(text, 200) });
      // Headings rarely contain controls; if they do, still list them.
      const inner = el.querySelectorAll("a[href],button");
      if (!inner.length) return;
    }

    const region = regionOf(el);
    const block = st && !/^inline/.test(st.display) && st.display !== "contents";
    if (region) { flush(); items.push({ k: "r", open: region, label: clean(el.getAttribute("aria-label") || "") }); }
    else if (block) flush();

    if (el.tagName === "LI" && block) buf.push("•");
    if (el.tagName === "TD" || el.tagName === "TH") buf.push("|");

    const kids = el.shadowRoot ? [...el.shadowRoot.childNodes, ...el.childNodes] : el.childNodes;
    for (const c of kids) walk(c, depth + 1);

    if (region) { flush(); items.push({ k: "r", close: region }); }
    else if (block) flush();
  }

  if (document.body) walk(document.body, 0);
  flush();

  // Open dialogs and modals usually matter most; note them.
  const dialogs = Array.from(document.querySelectorAll("dialog[open], [role=dialog], [aria-modal=true]")).filter((d) => !hiddenReason(d, styleOf(d))).length;

  return {
    title: document.title || "",
    url: location.href,
    items,
    hidden,
    nextId: next,
    dialogs,
    scroll: { y: Math.round(window.scrollY), h: Math.round(document.documentElement.scrollHeight), vh: window.innerHeight },
  };
}

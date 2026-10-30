"""Generic application-form engine (Greenhouse/Lever/Keka/custom ATS, LinkedIn-style modals).

run_form(page, resume_path, url) reads every visible field, answers them with answers.resolve_form,
fills, verifies, and only then clicks Submit. Anything it is unsure about => SKIP (never guess).
It does NOT try to solve captchas, OTPs or logins: those sites are skipped and logged.
"""
import re, pathlib
from answers import resolve_form, SkipApplication

EXTRACT_JS = r"""
() => {
  const vis = el => { const r = el.getBoundingClientRect(), s = getComputedStyle(el);
    return (r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.display !== 'none') || (el.type === 'file' && el.parentElement && vis(el.parentElement)); };
  const txt = el => ((el && el.textContent) || '').replace(/\s+/g, ' ').trim();
  const clean = t => t.replace(/\(required\)|\brequired\b/ig, '').replace(/[\s*:]+$/, '').trim();
  document.querySelectorAll('[data-ab]').forEach(e => e.removeAttribute('data-ab'));
  let n = 0; const out = [];
  const labelOf = el => {
    let t = '';
    if (el.id) { const l = document.querySelector('label[for="' + CSS.escape(el.id) + '"]'); if (l) t = txt(l); }
    if (!t) { const l = el.closest('label'); if (l) t = txt(l); }
    if (!t && el.getAttribute('aria-labelledby')) t = el.getAttribute('aria-labelledby').split(' ').map(i => txt(document.getElementById(i))).join(' ').trim();
    if (!t) t = el.getAttribute('aria-label') || '';
    if (!t) { const c = el.closest('.field,.form-group,[class*=field],[class*=question],fieldset,div');
      const l = c && c.querySelector('label,legend,[class*=label]'); if (l) t = txt(l); }
    return t || el.placeholder || el.name || '';
  };
  const groupLabel = el => {
    const fs = el.closest('fieldset'); if (fs) { const lg = fs.querySelector('legend'); if (lg) return txt(lg); }
    const c = el.closest('[role=radiogroup],[role=group],.field,.form-group,[class*=question],div');
    const l = c && c.querySelector('legend,label.group-label,.question,[class*=question-label],[class*=label]:not(label[for])');
    return l ? txt(l) : '';
  };
  const optLabel = el => { let t = '';
    if (el.id) { const l = document.querySelector('label[for="' + CSS.escape(el.id) + '"]'); if (l) t = txt(l); }
    if (!t) { const l = el.closest('label'); if (l) t = txt(l); }
    return t || el.value; };
  const seen = {};
  document.querySelectorAll('input,select,textarea').forEach(el => {
    const type = (el.type || '').toLowerCase();
    if (['hidden', 'submit', 'button', 'image', 'reset'].includes(type) || el.disabled) return;
    if (!vis(el)) return;
    if (el.getAttribute('readonly') !== null && type !== 'file') return;
    const id = 'f' + (n++); el.setAttribute('data-ab', id);
    if (type === 'radio' || (type === 'checkbox' && el.name && document.querySelectorAll('input[type=checkbox][name="' + CSS.escape(el.name) + '"]').length > 1)) {
      const kind = type === 'radio' ? 'radio' : 'multicheck', k = kind + ':' + (el.name || id);
      if (!seen[k]) { seen[k] = { id, kind, itype: type, question: clean(groupLabel(el) || labelOf(el)), options: [], optionIds: [], required: el.required, value: '' }; out.push(seen[k]); }
      seen[k].options.push(optLabel(el)); seen[k].optionIds.push(id); if (el.checked) seen[k].value = optLabel(el); return;
    }
    const raw = labelOf(el);
    const f = { id, itype: type || el.tagName.toLowerCase(), question: clean(raw), required: el.required || el.getAttribute('aria-required') === 'true' || /\*\s*$/.test(raw), value: '', options: [], optionIds: [] };
    if (el.tagName === 'SELECT') { f.kind = 'select';
      f.options = [...el.options].filter(o => o.value !== '' && !/^(select|choose|please|--|—)/i.test(o.text.trim())).map(o => o.text.trim());
      f.value = el.value ? (el.selectedOptions[0] ? el.selectedOptions[0].text.trim() : '') : ''; if (/^(select|choose|please|--)/i.test(f.value)) f.value = ''; }
    else if (el.tagName === 'TEXTAREA') { f.kind = 'textarea'; f.value = el.value; }
    else if (type === 'file') f.kind = 'file';
    else if (type === 'checkbox') { f.kind = 'checkbox'; f.value = el.checked ? 'Yes' : ''; }
    else { f.kind = 'text'; f.value = el.value; }
    out.push(f);
  });
  return out;
}
"""

CONSENT = re.compile(r"privacy|terms|consent|agree|acknowledge|gdpr|policy|certify|declare|accurate|true and correct", re.I)
SUBMIT_RE = re.compile(r"^\s*(submit( application)?|apply( now)?|send application|finish|review and submit)\s*$", re.I)
NEXT_RE = re.compile(r"^\s*(next|continue|save (and|&) continue|proceed)\s*$", re.I)
CTA_RE = re.compile(r"^\s*(apply( now| for this (job|position|role))?|i'?m interested)\s*$", re.I)
SUCCESS_RE = re.compile(r"thank you for (applying|your application)|application (has been )?(received|submitted|sent)|successfully (applied|submitted)", re.I)
CAPTCHA_SEL = ['iframe[src*="recaptcha"]', 'iframe[src*="hcaptcha"]', 'iframe[src*="turnstile"]', ".g-recaptcha", ".h-captcha", ".cf-turnstile", "[data-sitekey]", "img[id*=captcha i]", "canvas[id*=captcha i]"]


def blockers(page):
    for sel in CAPTCHA_SEL:
        if page.locator(sel).count(): return f"captcha ({sel})"
    if page.locator("input[type=password]:visible").count(): return "login wall"
    if page.locator("input:visible").count() <= 3 and re.search(r"\b(otp|one[- ]time (password|code)|verification code)\b", page.inner_text("body").lower()):
        return "otp/verification"
    return None


def _resolver_field(f):
    k = f["kind"]
    if k in ("text", "textarea"): ftype = "number" if f["itype"] == "number" else "text"; opts = None
    elif k == "select": ftype, opts = "dropdown", f["options"]
    elif k == "radio": ftype, opts = "radio", f["options"]
    elif k == "checkbox": ftype, opts = "radio", ["Yes", "No"]
    else: return None   # multicheck/date/unknown: unsupported -> unanswerable if required
    return {"question": f["question"], "ftype": ftype, "options": opts, "required": f["required"] and not f["value"]}


def _fill(page, f, value):
    loc = page.locator(f'[data-ab="{f["id"]}"]')
    k = f["kind"]
    if k in ("text", "textarea"):
        if not loc.is_editable(): return False
        loc.fill(value); return True
    if k == "select": loc.select_option(label=value); return True
    if k == "radio":
        i = f["options"].index(value)
        opt = page.locator(f'[data-ab="{f["optionIds"][i]}"]')
        try: opt.check(timeout=2000)
        except Exception: opt.check(force=True)
        return True
    if k == "checkbox":
        loc.set_checked(value == "Yes", force=True); return True
    return False


def _find_button(page, rx):
    for b in page.get_by_role("button", name=rx).all():
        if b.is_visible() and b.is_enabled(): return b
    return None


def run_form(page, resume_path="", url="", dry_run=True, max_steps=8, **hooks):
    log = {"url": url, "status": "failed", "reason": "", "answers": {}}
    def done(status, reason=""): log.update(status=status, reason=reason); return log
    if blockers(page): return done("skipped", blockers(page))
    for step in range(max_steps):
        fields = page.evaluate(EXTRACT_JS)
        if not fields and step == 0:                       # landing page: click the Apply CTA once
            cta = _find_button(page, CTA_RE) or next((l for l in page.get_by_role("link", name=CTA_RE).all() if l.is_visible()), None)
            if cta: cta.click(); page.wait_for_load_state("domcontentloaded"); page.wait_for_timeout(500)
            if blockers(page): return done("skipped", blockers(page))
            fields = page.evaluate(EXTRACT_JS)
        if not fields: return done("failed", "no form fields found")

        files = [f for f in fields if f["kind"] == "file"]
        consents = [f for f in fields if f["kind"] == "checkbox" and CONSENT.search(f["question"])]
        regular = [f for f in fields if f not in files and f not in consents]
        unsupported = [f for f in regular if _resolver_field(f) is None]
        rf = {f["question"]: f for f in regular if _resolver_field(f)}
        todo = [_resolver_field(f) for f in rf.values()]
        todo += [{"question": f["question"] or "(unlabelled)", "ftype": "unsupported", "options": f["options"], "required": f["required"]} for f in unsupported if f["required"]]
        try: ans = resolve_form(todo, url=url, **hooks)
        except SkipApplication as e: return done("skipped", str(e))

        for q, v in ans.items():
            if q in rf and not _fill(page, rf[q], v): return done("failed", f"could not fill: {q}")
        for f in consents: _fill(page, f, "Yes")
        for f in files:
            p = pathlib.Path(resume_path)
            if p.exists(): page.locator(f'[data-ab="{f["id"]}"]').set_input_files(str(p))
            elif f["required"]: return done("skipped", "resume file required but resume_path missing")
        log["answers"].update(ans)

        # verify: every required field now has a value
        for f in page.evaluate(EXTRACT_JS):
            if f["required"] and not f["value"] and f["kind"] not in ("file",):
                if not (f["kind"] == "checkbox" and CONSENT.search(f["question"])):
                    return done("failed", f"required field still empty: {f['question']}")
        submit, nxt = _find_button(page, SUBMIT_RE), _find_button(page, NEXT_RE)
        if submit:
            if dry_run: return done("dry_run_ok", "all required fields filled; not submitted")
            submit.click(); page.wait_for_timeout(1500)
            try: page.wait_for_function("re => new RegExp(re,'i').test(document.body.innerText)", arg=SUCCESS_RE.pattern, timeout=8000)
            except Exception: return done("failed", "no confirmation message after submit")
            return done("submitted")
        if nxt: nxt.click(); page.wait_for_timeout(500); continue
        return done("failed", "no submit/next button found")
    return done("failed", "too many steps")

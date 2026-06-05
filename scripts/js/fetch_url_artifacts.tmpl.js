// Navigate to an arbitrary URL and return marketing-relevant artifacts:
// Open Graph/Twitter/description meta, readable headings/paragraphs, candidate
// CTA labels, and N viewport screenshots (base64) taken while scrolling down.
// Templated by ingest_url.py: __URL__, __MAX_SHOTS__, __VIEWPORT__ are replaced
// with JSON literals. run-code runs `page => ...` in NODE context (Playwright
// API available); DOM reads happen inside page.evaluate(). NEVER throws — on a
// navigation failure it returns JSON.stringify({ ok:false, note }).
page => (async () => {
  const URL = __URL__;
  const MAX_SHOTS = __MAX_SHOTS__;
  const VIEWPORT = __VIEWPORT__;
  try { await page.setViewportSize(VIEWPORT); } catch (_) { /* ignore */ }
  try {
    await page.goto(URL, { waitUntil: 'networkidle', timeout: 45000 });
  } catch (_) {
    try {
      await page.goto(URL, { waitUntil: 'domcontentloaded', timeout: 45000 });
    } catch (err) {
      return JSON.stringify({ ok: false, note: 'goto failed: ' + String(err && err.message ? err.message : err) });
    }
  }
  try { await page.waitForTimeout(1500); } catch (_) { /* ignore */ }

  let facts = {};
  try {
    facts = await page.evaluate(() => {
      const text = (sel, cap) => {
        let out = [];
        try {
          out = [...document.querySelectorAll(sel)]
            .map((e) => (e.innerText || e.textContent || '').trim())
            .filter(Boolean);
        } catch (_) { out = []; }
        return out.slice(0, cap);
      };
      const meta = {};
      try {
        document
          .querySelectorAll('meta[property^="og:"], meta[name^="twitter:"], meta[name="description"], meta[name="keywords"]')
          .forEach((t) => {
            const k = t.getAttribute('property') || t.getAttribute('name');
            const v = t.getAttribute('content');
            if (k && v) meta[k] = v;
          });
      } catch (_) { /* ignore */ }
      let ctas = [];
      try {
        ctas = [...document.querySelectorAll('a, button')]
          .map((e) => (e.innerText || '').trim())
          .filter((s) => s && s.length <= 40)
          .slice(0, 40);
      } catch (_) { ctas = []; }
      return {
        title: document.title || '',
        lang: (document.documentElement && document.documentElement.lang) || '',
        url: location.href,
        meta,
        headings: text('h1, h2, h3', 40),
        paragraphs: text('p, li', 60),
        ctas,
      };
    });
  } catch (_) { facts = { url: URL }; }

  let scrollH = 0;
  try { scrollH = await page.evaluate(() => document.body.scrollHeight || 0); } catch (_) { scrollH = 0; }

  const shots = [];
  const total = Math.max(1, MAX_SHOTS);
  for (let i = 0; i < total; i += 1) {
    if (i > 0 && scrollH > 0) {
      try {
        await page.evaluate((y) => window.scrollTo(0, y), Math.round((scrollH / total) * i));
        await page.waitForTimeout(500);
      } catch (_) { /* ignore */ }
    }
    try {
      const buf = await page.screenshot({ fullPage: false });
      shots.push(buf.toString('base64'));
    } catch (_) { /* skip this shot */ }
  }

  return JSON.stringify({ ok: true, facts, shots });
})()

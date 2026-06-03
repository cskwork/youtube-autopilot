// Extract idea/inspiration cards from the attached YouTube Studio (or youtube.com)
// page. Run via the Playwright agent CLI: `run-code --filename studio_inspiration.js --raw`.
// Studio is an Angular/Polymer app: hashed classes, Shadow DOM, virtualized lists.
// This function is defensive by design: it pierces shadow roots, scrolls to load
// virtualized cards, tries several selector families, and NEVER throws.
// On any failure it returns JSON.stringify({ ok:false, items:[], count:0, note }).
// run-code executes `page => ...` in NODE context, so all DOM work must happen
// inside page.evaluate(), which runs the callback in the browser page context.
page => page.evaluate(async () => {
  const wait = (ms) => new Promise((r) => setTimeout(r, ms));

  // Collect every element in the document, piercing open shadow roots.
  const allDeep = () => {
    const out = [];
    const walk = (root) => {
      let nodes;
      try {
        nodes = root.querySelectorAll('*');
      } catch (_) {
        return;
      }
      for (const el of nodes) {
        out.push(el);
        if (el.shadowRoot) walk(el.shadowRoot);
      }
    };
    try {
      walk(document);
    } catch (_) {
      /* ignore */
    }
    return out;
  };

  // First non-empty visible text line of an element, trimmed and capped.
  const firstLine = (el) => {
    let txt = '';
    try {
      txt = (el.innerText || el.textContent || '').trim();
    } catch (_) {
      return '';
    }
    const line = txt.split('\n').map((s) => s.trim()).filter(Boolean)[0] || '';
    return line.slice(0, 200);
  };

  // Pull any view/score/search-volume numbers out of an element's text.
  const metricOf = (el) => {
    let txt = '';
    try {
      txt = (el.innerText || el.textContent || '').trim();
    } catch (_) {
      return '';
    }
    const m = txt.match(/[\d.,]+\s*(?:[KMB만천억]|회|views?|searches?|검색)?/gi) || [];
    return m.map((s) => s.trim()).filter(Boolean).slice(0, 3).join(' ').slice(0, 80);
  };

  // Scroll likely feed containers so the virtualized list materializes cards.
  const scrollFeed = async () => {
    const scrollers = allDeep().filter((el) => {
      try {
        return el.scrollHeight > el.clientHeight + 200;
      } catch (_) {
        return false;
      }
    });
    for (let pass = 0; pass < 4; pass += 1) {
      for (const el of scrollers.slice(0, 6)) {
        try {
          el.scrollBy(0, el.scrollHeight);
        } catch (_) {
          /* ignore */
        }
      }
      try {
        window.scrollBy(0, document.body.scrollHeight);
      } catch (_) {
        /* ignore */
      }
      await wait(700);
    }
  };

  // Studio inspiration / research card containers (custom elements first).
  const studioCards = () => {
    const sel = [
      'ytcp-inspiration-card',
      'ytgn-inspiration-card',
      'ytcp-video-row',
      '[role="listitem"]',
      '[role="article"]',
    ].join(',');
    const deep = allDeep().filter((el) => {
      const tag = (el.tagName || '').toLowerCase();
      if (/inspiration|video-row/.test(tag)) return true;
      const role = el.getAttribute && el.getAttribute('role');
      return role === 'listitem' || role === 'article';
    });
    let direct = [];
    try {
      direct = [...document.querySelectorAll(sel)];
    } catch (_) {
      direct = [];
    }
    return [...new Set([...deep, ...direct])];
  };

  // youtube.com trending / search renderers (no closed shadow DOM here).
  const ytRenderers = () => {
    try {
      return [...document.querySelectorAll('ytd-video-renderer, ytd-rich-item-renderer')];
    } catch (_) {
      return [];
    }
  };

  // Heuristic fallback: any element whose id/class mentions inspiration/idea/research.
  const heuristicCards = () =>
    allDeep().filter((el) => {
      const id = el.id || '';
      let cls = '';
      try {
        cls = typeof el.className === 'string' ? el.className : '';
      } catch (_) {
        cls = '';
      }
      return /inspiration|idea|research/i.test(id + ' ' + cls);
    });

  const titleOf = (el) => {
    const sels = [
      '#title',
      '#video-title',
      'a#video-title',
      '#video-title-link',
      'yt-formatted-string#video-title',
      'yt-formatted-string#title',
      'h3',
      '[role="heading"]',
    ];
    for (const s of sels) {
      let node = null;
      try {
        node = el.querySelector(s);
      } catch (_) {
        node = null;
      }
      if (node) {
        const t = firstLine(node);
        if (t) return t;
      }
    }
    return firstLine(el);
  };

  const hrefOf = (el) => {
    let a = null;
    try {
      a = el.querySelector('a[href]');
    } catch (_) {
      a = null;
    }
    if (a && a.getAttribute) {
      const h = a.getAttribute('href') || '';
      if (h) return h.startsWith('http') ? h : 'https://www.youtube.com' + h;
    }
    return '';
  };

  const channelOf = (el) => {
    let node = null;
    try {
      node = el.querySelector('ytd-channel-name a, ytd-channel-name yt-formatted-string');
    } catch (_) {
      node = null;
    }
    return node ? firstLine(node) : '';
  };

  const harvest = (cards) => {
    const seen = new Set();
    const items = [];
    for (const el of cards) {
      const title = titleOf(el);
      if (!title || title.length < 3) continue;
      const key = title.toLowerCase();
      if (seen.has(key)) continue;
      seen.add(key);
      items.push({
        title,
        metric: metricOf(el),
        channel: channelOf(el),
        href: hrefOf(el),
      });
      if (items.length >= 60) break;
    }
    return items;
  };

  try {
    await scrollFeed();
    let cards = studioCards();
    let source = 'studio';
    if (cards.length === 0) {
      cards = ytRenderers();
      source = 'search';
    }
    if (cards.length === 0) {
      cards = heuristicCards();
      source = 'heuristic';
    }
    const items = harvest(cards);
    return JSON.stringify({
      ok: true,
      source,
      url: location.href,
      items,
      count: items.length,
    });
  } catch (err) {
    return JSON.stringify({
      ok: false,
      items: [],
      count: 0,
      note: String(err && err.message ? err.message : err),
    });
  }
})

page => (async () => {
  const out = __OUT__;
  const editUrl = __EDIT_URL__;

  async function openLatestEditPage() {
    if (editUrl) {
      await page.goto(editUrl, { waitUntil: 'domcontentloaded' });
      return;
    }
    if (location.pathname.includes('/edit/')) return;
    await page.waitForSelector('a[href*="/edit/"]', { timeout: 30000 });
    const href = await page.evaluate(() => {
      const links = [...document.querySelectorAll('a[href*="/edit/"]')];
      const videoLink = links.find(link => {
        const card = link.closest('[draggable="true"], [role="button"], div');
        return card && card.innerText && /play_circle|동영상/i.test(card.innerText);
      });
      return (videoLink || links[0]).href;
    });
    if (!href) throw new Error('edit-link-not-found');
    await page.goto(href, { waitUntil: 'domcontentloaded' });
  }

  await openLatestEditPage();
  const button = page.locator('button').filter({ hasText: /다운로드|Download/i }).first();
  await button.waitFor({ state: 'visible', timeout: 30000 });
  const [download] = await Promise.all([
    page.waitForEvent('download', { timeout: 120000 }),
    button.click(),
  ]);
  await download.saveAs(out);
  return JSON.stringify({
    ok: true,
    out,
    suggested: download.suggestedFilename(),
  });
})()

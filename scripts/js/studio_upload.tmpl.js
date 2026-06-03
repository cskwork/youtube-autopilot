// Template: upload_youtube_studio.py replaces __VIDEO__, __TITLE__, __DESC__,
// and __PRIVACY__ (PRIVATE | UNLISTED | PUBLIC) with JSON literals.
// Runs in NODE context (page => ...): file injection and field edits use the
// Playwright page API, not page.evaluate. Drives the Studio upload dialog:
// set file -> title/description -> not-made-for-kids -> Next x3 -> visibility -> Save.
page => (async () => {
  const VIDEO = __VIDEO__;
  const TITLE = __TITLE__;
  const DESC = __DESC__;
  const PRIVACY = __PRIVACY__;
  const log = [];

  const input = await page.$('input[type=file]');
  if (!input) return JSON.stringify({ ok: false, error: 'no-file-input', log });
  await input.setInputFiles(VIDEO);
  log.push('file-set');
  await page.waitForTimeout(12000);

  const setBox = async (sel, text) => {
    const el = await page.$(sel);
    if (!el) return false;
    await el.click();
    await page.keyboard.press('Meta+A');
    await page.keyboard.press('Control+A');
    await page.keyboard.press('Backspace');
    await page.keyboard.insertText(text);
    return true;
  };
  if (TITLE) log.push('title:' + (await setBox('#title-textarea #textbox', TITLE)));
  await page.waitForTimeout(600);
  if (DESC) log.push('desc:' + (await setBox('#description-textarea #textbox', DESC)));
  await page.waitForTimeout(600);

  const notKids = await page.$('tp-yt-paper-radio-button[name="VIDEO_MADE_FOR_KIDS_NOT_MFK"]');
  if (notKids) { try { await notKids.click(); log.push('not-made-for-kids'); } catch (e) {} }
  await page.waitForTimeout(600);

  const click = async (sel, label) => {
    const b = await page.$(sel);
    if (b) { try { await b.click({ timeout: 3000 }); log.push(label); } catch (e) {} }
  };
  for (let i = 0; i < 3; i += 1) { await click('#next-button', 'next' + i); await page.waitForTimeout(1700); }

  const priv = await page.$('tp-yt-paper-radio-button[name="' + PRIVACY + '"]');
  if (priv) { try { await priv.click(); log.push('privacy:' + PRIVACY); } catch (e) {} }
  await page.waitForTimeout(900);
  await click('#done-button', 'done');
  await page.waitForTimeout(3000);
  return JSON.stringify({ ok: true, log });
})()

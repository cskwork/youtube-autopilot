// Template: google_flow_cli.py replaces __PROMPT__, __IMAGES__,
// __ASPECT_RATIO__, and __DURATION__ with JSON literals.
page => (async () => {
  const PROMPT = __PROMPT__;
  const IMAGES = __IMAGES__;
  const ASPECT_RATIO = __ASPECT_RATIO__;
  const DURATION = __DURATION__;
  const log = [];

  await page.waitForLoadState('domcontentloaded').catch(() => {});
  await page.waitForTimeout(1500);

  async function isVisible(locator) {
    return locator.isVisible({ timeout: 700 }).catch(() => false);
  }

  async function clickFirst(candidates, label, timeout = 1500) {
    for (const locator of candidates) {
      const count = await locator.count().catch(() => 0);
      if (!count) continue;
      for (let i = 0; i < Math.min(count, 4); i += 1) {
        const item = locator.nth(i);
        if (!(await isVisible(item))) continue;
        try {
          await item.click({ timeout });
          log.push(label);
          return true;
        } catch (e) {}
      }
    }
    return false;
  }

  async function ensureVideoMode() {
    const modelButtons = [
      page.getByRole('button', { name: /Nano|Imagen|Image|Video|Veo|model|이미지|동영상|비디오/i }),
      page.locator('button').filter({ hasText: /Nano|Imagen|Image|Video|Veo|이미지|동영상|비디오/i }),
    ];
    await clickFirst(modelButtons, 'model-menu-opened');
    const videoOptions = [
      page.getByRole('menuitem', { name: /Video|동영상|비디오/i }),
      page.getByRole('option', { name: /Video|동영상|비디오/i }),
      page.getByText(/Video|동영상|비디오/i),
    ];
    if (await clickFirst(videoOptions, 'video-mode-selected')) return;
    log.push('video-mode-not-confirmed');
  }

  async function attachImage() {
    if (!IMAGES.length) return;
    let done = await setInputFile();
    if (!done) {
      const addButtons = [
        page.getByRole('button', { name: /Add|Upload|Ingredient|Frame|추가|업로드|프레임/i }),
        page.locator('button').filter({ hasText: /Add|Upload|Ingredient|Frame|추가|업로드|프레임/i }),
      ];
      await clickFirst(addButtons, 'add-menu-opened', 2500);
      done = await setInputFile();
    }
    log.push(done ? 'image-attached' : 'image-attach-not-found');
    await page.waitForTimeout(2500);
  }

  async function setInputFile() {
    const inputs = page.locator('input[type=file]');
    const count = await inputs.count().catch(() => 0);
    for (let i = 0; i < count; i += 1) {
      try {
        await inputs.nth(i).setInputFiles(IMAGES);
        return true;
      } catch (e) {}
    }
    return false;
  }

  async function choosePreferences() {
    const preferenceButtons = [
      page.getByRole('button', { name: new RegExp(ASPECT_RATIO.replace(':', '\\s*:?\\s*')) }),
      page.getByRole('button', { name: new RegExp(String(DURATION)) }),
    ];
    for (const button of preferenceButtons) {
      if (await isVisible(button.first())) log.push('preference-visible');
    }
  }

  async function closeTransientOverlays() {
    await page.keyboard.press('Escape').catch(() => null);
    await page.waitForTimeout(500);
  }

  async function fillPrompt() {
    await closeTransientOverlays();
    const boxes = page.locator('textarea, [contenteditable=true], [role="textbox"]');
    const count = await boxes.count();
    for (let i = count - 1; i >= 0; i -= 1) {
      const box = boxes.nth(i);
      if (!(await isVisible(box))) continue;
      await box.click({ timeout: 3000, force: true });
      try {
        await box.fill(PROMPT);
      } catch (e) {
        await page.keyboard.press('Meta+A').catch(() => null);
        await page.keyboard.press('Control+A').catch(() => null);
        await page.keyboard.insertText(PROMPT);
      }
      log.push('prompt-filled');
      return true;
    }
    return false;
  }

  async function submit() {
    await closeTransientOverlays();
    const promptBarSubmit = page.locator(
      'div:has([role="textbox"]) button[aria-label*="만들기"], '
      + 'div:has([role="textbox"]) button:has-text("arrow_forward")'
    );
    if (await clickFirst([promptBarSubmit], 'submitted', 5000)) return true;

    const generateButtons = [
      page.getByRole('button', { name: /arrow_forward.*만들기|Generate|Create|생성/i }),
      page.locator('button').filter({ hasText: /arrow_forward|Generate|Create|생성/i }),
    ];
    return clickFirst(generateButtons, 'submitted', 5000);
  }

  await ensureVideoMode();
  await attachImage();
  await choosePreferences();
  if (!(await fillPrompt())) return JSON.stringify({ ok: false, log, error: 'prompt-box-not-found' });
  if (!(await submit())) return JSON.stringify({ ok: false, log, error: 'generate-button-not-found' });
  return JSON.stringify({ ok: true, log });
})()

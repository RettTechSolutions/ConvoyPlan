// playwright kommt aus frontend/ (Abhängigkeit von @playwright/test), sonst aus der Umgebung.
const { chromium } = require(require.resolve('playwright', { paths: [__dirname, __dirname + '/../../frontend'] }));
const [,, html, out, coverHtml, coverOut, footer] = process.argv;
(async () => {
  const browser = await chromium.launch();
  const page = await browser.newPage();
  page.on('console', m => { if (m.type() === 'error') console.error('browser:', m.text()); });
  // Externe Bilder nicht abwarten (keine Netzabhängigkeit)
  await page.route(/^https?:/, r => r.abort());
  await page.goto('file://' + html, { waitUntil: 'load' });
  await page.waitForFunction(() => document.body.dataset.ready === '1', null, { timeout: 120000 });
  await page.evaluate(() => document.fonts.ready);
  await page.pdf({ path: out, format: 'A4', printBackground: true, preferCSSPageSize: true,
    displayHeaderFooter: true, headerTemplate: '<span></span>', footerTemplate: footer,
    outline: true, tagged: true });
  await page.goto('file://' + coverHtml, { waitUntil: 'load' });
  await page.pdf({ path: coverOut, format: 'A4', printBackground: true, preferCSSPageSize: true });
  await browser.close();
})().catch(e => { console.error(e); process.exit(1); });

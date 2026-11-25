// Smoke test of the viewer in a real browser (installed Edge/Chrome, no browser download).
// Usage: pnpm dev (in another terminal), then: node scripts/smoke.mjs [outDir]
import { chromium } from "playwright-core";
import { mkdirSync } from "node:fs";
import { join } from "node:path";

const URL = process.env.VIEWER_URL ?? "http://localhost:5173/";
const out = process.argv[2] ?? "smoke-out";
mkdirSync(out, { recursive: true });

const channel = process.env.BROWSER_CHANNEL ?? "msedge";
const browser = await chromium.launch({ channel, args: ["--use-angle=swiftshader", "--enable-unsafe-swiftshader"] });
const failures = [];

async function run(name, contextOptions, steps) {
  const context = await browser.newContext(contextOptions);
  const page = await context.newPage();
  const errors = [];
  page.on("pageerror", (e) => errors.push(String(e)));
  page.on("console", (m) => m.type() === "error" && errors.push(m.text()));
  await page.goto(URL);
  await page.waitForSelector(".unit-area", { timeout: 30000 });
  await page.waitForTimeout(1500);
  await page.screenshot({ path: join(out, `${name}.png`) });
  await steps(page);
  if (errors.length) failures.push(`${name}: ${errors.join(" | ")}`);
  await context.close();
}

async function pickFloor(page, name, tap) {
  // scan a grid of points until a floor is hit (works for any camera framing)
  const { width, height } = page.viewportSize();
  for (let y = 0.25; y <= 0.8; y += 0.05) {
    for (let x = 0.2; x <= 0.8; x += 0.05) {
      const px = Math.round(width * x), py = Math.round(height * y);
      if (tap) await page.touchscreen.tap(px, py);
      else await page.mouse.click(px, py);
      await page.waitForTimeout(80);
      const room = await page.$(".room-name");
      if (room) {
        const text = (await room.textContent()) + " · " + (await page.textContent(".room-area"));
        await page.screenshot({ path: join(out, `${name}-room.png`) });
        return text;
      }
    }
  }
  return null;
}

await run("desktop", { viewport: { width: 1280, height: 800 } }, async (page) => {
  const hit = await pickFloor(page, "desktop", false);
  console.log("desktop click ->", hit);
  if (!hit) failures.push("desktop: clicking floors never showed a room");
});

await run("phone", { viewport: { width: 390, height: 844 }, deviceScaleFactor: 2, isMobile: true, hasTouch: true }, async (page) => {
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth);
  if (overflow) failures.push("phone: horizontal overflow");
  const hit = await pickFloor(page, "phone", true);
  console.log("phone tap ->", hit);
  if (!hit) failures.push("phone: tapping floors never showed a room");
});

await browser.close();
if (failures.length) {
  console.error("FAIL\n" + failures.join("\n"));
  process.exit(1);
}
console.log("OK");

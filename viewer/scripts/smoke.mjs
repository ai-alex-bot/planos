// Smoke test of the viewer in a real browser (installed Edge/Chrome, no browser download).
// Usage: pnpm dev (in another terminal), then: pnpm smoke [outDir]
import { chromium } from "playwright-core";
import { mkdirSync } from "node:fs";
import { join } from "node:path";

const URL = process.env.VIEWER_URL ?? "http://localhost:5173/";
const out = process.argv[2] ?? "smoke-out";
mkdirSync(out, { recursive: true });

const browser = await chromium.launch({
  channel: process.env.BROWSER_CHANNEL ?? "msedge",
  args: ["--use-angle=swiftshader", "--enable-unsafe-swiftshader"],
});
const failures = [];
const check = (ok, msg) => {
  console.log(`${ok ? "✓" : "✗"} ${msg}`);
  if (!ok) failures.push(msg);
};

async function open(contextOptions) {
  const context = await browser.newContext(contextOptions);
  const page = await context.newPage();
  page.errors = [];
  page.on("pageerror", (e) => page.errors.push(String(e)));
  page.on("console", (m) => m.type() === "error" && page.errors.push(m.text()));
  await page.goto(URL);
  await page.waitForSelector(".unit-area", { timeout: 30000 });
  await page.waitForTimeout(1500);
  return { context, page };
}

async function pickFloor(page, tap) {
  // scan a grid of points until a floor is hit (works for any camera framing)
  const { width, height } = page.viewportSize();
  for (let y = 0.3; y <= 0.75; y += 0.05) {
    for (let x = 0.2; x <= 0.8; x += 0.05) {
      const px = Math.round(width * x), py = Math.round(height * y);
      if (tap) await page.touchscreen.tap(px, py);
      else await page.mouse.click(px, py);
      await page.waitForTimeout(60);
      if (await page.$(".room-name")) return (await page.textContent(".room")).replace("×", "").trim();
    }
  }
  return null;
}

const walkPos = (page) => page.evaluate(() => window.__walk);
const mode = async (page, label) => {
  await page.getByRole("button", { name: label }).click();
  await page.waitForTimeout(800);
};

// ---------------------------------------------------------------- desktop
{
  const { context, page } = await open({ viewport: { width: 1280, height: 800 } });
  await page.screenshot({ path: join(out, "desktop-orbit.png") });
  const room = await pickFloor(page, false);
  check(!!room, `desktop orbit: click on floor shows room (${room})`);

  check((await page.evaluate(() => window.__ceilingsVisible)) === 0, "orbit: ceilings hidden");

  await mode(page, "Planta");
  const labels = await page.$$eval(".plan-label", (els) => els.map((e) => e.textContent));
  check(labels.length === 9, `plan: ${labels.length} room labels`);
  check((await page.evaluate(() => window.__planLines)) === 8, `plan: one line per window/glass door (${await page.evaluate(() => window.__planLines)})`);
  check((await page.evaluate(() => window.__ceilingsVisible)) === 0, "plan: ceilings hidden");
  await page.screenshot({ path: join(out, "desktop-plan.png") });
  // a click on every floor (at its label: labels let clicks through) shows that room, even under lintels
  const boxes = await page.$$eval(".plan-label", (els) =>
    els.map((e) => {
      const r = e.getBoundingClientRect();
      return { name: e.querySelector("strong").textContent, x: r.x + r.width / 2, y: r.y + r.height / 2 };
    }),
  );
  let ok = 0;
  const wrong = [];
  for (const b of boxes) {
    await page.mouse.click(b.x, b.y);
    await page.waitForTimeout(120);
    const el = await page.$(".room .room-name");
    const got = el ? await el.textContent() : null;
    if (got === b.name) ok += 1;
    else wrong.push(`${b.name}→${got}`);
  }
  check(ok === boxes.length, `plan: click on each floor shows its room (${ok}/${boxes.length}) ${wrong.join(", ")}`);

  await mode(page, "Caminar");
  await page.waitForTimeout(600);
  const chip = await page.textContent(".room-chip").catch(() => null);
  check(!!chip && chip.includes("Estás en"), `walk: shows current room (${chip?.trim()})`);
  // look up (drag down): the ceiling is there, seen from below
  await page.mouse.move(640, 300);
  await page.mouse.down();
  await page.mouse.move(640, 650, { steps: 8 });
  await page.mouse.up();
  await page.waitForTimeout(700);
  await page.screenshot({ path: join(out, "desktop-walk-up.png") });
  const view = await page.evaluate(() => window.__walkView);
  check(!!view?.ceiling, `walk: looking up shows the ceiling (pitch ${view?.pitch?.toFixed(2)})`);
  await page.mouse.move(640, 650);
  await page.mouse.down();
  await page.mouse.move(640, 300, { steps: 8 });
  await page.mouse.up();
  await page.waitForTimeout(300);
  const p0 = await walkPos(page);
  await page.keyboard.down("KeyW");
  await page.waitForTimeout(3000);
  await page.keyboard.up("KeyW");
  const p1 = await walkPos(page);
  const moved = Math.hypot(p1[0] - p0[0], p1[1] - p0[1]);
  check(moved > 0.5, `walk: W moves the camera (${moved.toFixed(2)} m)`);
  await page.screenshot({ path: join(out, "desktop-walk.png") });
  check((await page.evaluate(() => window.__ceilingsVisible)) === 8, "walk: ceilings visible (8 indoor rooms)");

  // push against walls in every direction for a while: must stay inside the unit (collisions)
  for (const key of ["KeyW", "KeyA", "KeyS", "KeyD"]) {
    await page.keyboard.down(key);
    await page.waitForTimeout(2500);
    await page.keyboard.up(key);
  }
  const p2 = await walkPos(page);
  check(Math.abs(p2[0]) < 5.2 && Math.abs(p2[1]) < 4.5, `walk: walls stop the walker (at ${p2.map((v) => v.toFixed(2))})`);
  check(page.errors.length === 0, `desktop: no console errors ${page.errors.join(" | ")}`);
  await context.close();
}

// ---------------------------------------------------------------- phone
{
  const { context, page } = await open({ viewport: { width: 390, height: 844 }, deviceScaleFactor: 2, isMobile: true, hasTouch: true });
  check(!(await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth)), "phone: no horizontal overflow");
  await page.screenshot({ path: join(out, "phone-orbit.png") });
  check(!!(await pickFloor(page, true)), "phone orbit: tap on floor shows room");

  await mode(page, "Planta");
  await page.screenshot({ path: join(out, "phone-plan.png") });

  await mode(page, "Caminar");
  const joy = await page.$(".joystick");
  check(!!joy, "phone walk: joystick visible");
  const p0 = await walkPos(page);
  const b = await joy.boundingBox();
  const cx = b.x + b.width / 2, cy = b.y + b.height / 2;
  await page.mouse.move(cx, cy);
  await page.mouse.down();
  await page.mouse.move(cx, cy - 45, { steps: 5 });
  await page.waitForTimeout(1200);
  await page.screenshot({ path: join(out, "phone-walk.png") });
  await page.mouse.up();
  const p1 = await walkPos(page);
  check(Math.hypot(p1[0] - p0[0], p1[1] - p0[1]) > 0.5, "phone walk: joystick moves the camera");
  check(page.errors.length === 0, `phone: no console errors ${page.errors.join(" | ")}`);
  await context.close();
}

await browser.close();
if (failures.length) {
  console.error(`FAIL (${failures.length})`);
  process.exit(1);
}
console.log("OK");

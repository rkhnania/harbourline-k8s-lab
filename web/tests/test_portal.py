"""Plimsoll Portal UI checks.

Runs the real web/index.html in headless Chromium against mock_backend.py, a
stand-in for Core and Insight that mirrors their response shapes, their 409
refusal bodies and Flask's RFC 1123 date format. No cluster, no database.

    python web/tests/test_portal.py          # from the repo root
    SHOTS=/tmp/shots python web/tests/...    # also save screenshots

Covers navigation states and deep links, receive / move / pick / dispatch,
client-side validation, the audit turning OUT-OF-BALANCE, dark mode, and no
horizontal overflow on any view at tablet and phone widths.
"""
import asyncio, os, socket, subprocess, sys, time, urllib.request
from pathlib import Path
from playwright.async_api import async_playwright

HERE = Path(__file__).resolve().parent
WEB = HERE.parent
PORT = int(os.environ.get("PORT", "8099"))
BASE = f"http://127.0.0.1:{PORT}/"
SHOTS = os.environ.get("SHOTS")

async def snap(page, name, full_page=False):
    if SHOTS:
        Path(SHOTS).mkdir(parents=True, exist_ok=True)
        await page.screenshot(path=f"{SHOTS}/{name}.png", full_page=full_page)
ROUTES=["overview","stock","inbound","outbound","ledger","audit"]
problems=[]; log=[]
def ok(c,msg):
    (log if c else problems).append(("PASS " if c else "FAIL ")+msg)

async def watch(page,tag):
    page.on("console", lambda m: m.type=="error" and problems.append(f"FAIL [{tag}] console: {m.text}"))
    page.on("pageerror", lambda e: problems.append(f"FAIL [{tag}] pageerror: {e}"))

async def overflow(page): return await page.evaluate("document.documentElement.scrollWidth - window.innerWidth")

async def main():
    async with async_playwright() as p:
        b = await p.chromium.launch()
        # ---------------- desktop, light: functional flow
        ctx = await b.new_context(viewport={"width":1440,"height":900}, color_scheme="light")
        page = await ctx.new_page(); await watch(page,"desktop")
        await page.goto(BASE+"__reset"); await page.goto(BASE+"#overview")
        await page.wait_for_selector(".hero"); await page.wait_for_timeout(500)
        ok(await page.locator("#integrity.ok").count()==1, "integrity pill green on load")
        ok((await page.locator('.nav-btn[data-route="outbound"] .count').inner_text())=="1", "outbound badge = 1 open order")
        ok((await page.locator('.nav-btn[data-route="inbound"] .count').inner_text())=="2", "inbound badge = 2 loads due")
        ok("Harbourline" in await page.content(), "smoke-test string 'Harbourline' present")
        await snap(page, "01-overview-desktop", full_page=True)
        for r in ROUTES:
            await page.click(f'.nav-btn[data-route="{r}"]')
            await page.wait_for_function(f"document.querySelector('.nav-btn[data-route=\"{r}\"]').getAttribute('aria-current')==='page'")
            await page.wait_for_function("document.querySelector('#view').getAttribute('aria-busy')==='false'")
            cur = await page.get_attribute(f'.nav-btn[data-route="{r}"]',"aria-current")
            ok(cur=="page", f"nav {r}: aria-current=page"); ok(await page.locator(".nav-btn[aria-current]").count()==1, f"nav {r}: exactly one active")
            ok((await page.inner_text("#page-title")).lower()==r, f"nav {r}: title updates")
            ok(await page.locator("#view .empty .t-bad").count()==0, f"view {r}: no error state")
        # deep link + reload keeps the page
        await page.goto(BASE+"#ledger"); await page.reload(); await page.wait_for_selector("#ledger-q")
        ok(await page.get_attribute('.nav-btn[data-route="ledger"]',"aria-current")=="page", "reload keeps #ledger")
        # timestamps no longer sliced RFC1123
        txt = await page.inner_text("#rows")
        ok("GMT" not in txt and "Fri," not in txt, "ledger times are humanised, not raw RFC1123")
        # stock search + zone filter
        await page.goto(BASE+"#stock"); await page.wait_for_selector("#stock-q")
        await page.fill("#stock-q","lithium"); n=await page.locator("#rows tbody tr").count(); ok(n==1, f"stock search 'lithium' -> {n} row")
        ok(await page.locator("#rows .haz").count()==1, "hazard class UN3480 shown")
        tw = await page.evaluate("[document.querySelector('#rows table').getBoundingClientRect().width, document.querySelector('#rows thead tr').getBoundingClientRect().width, document.querySelector('#rows tbody tr').getBoundingClientRect().width]")
        ok(abs(tw[0]-tw[1])<2 and abs(tw[0]-tw[2])<2, f"table, header and rows share one width {tw}")
        await page.fill("#stock-q",""); await page.click('[data-zone="PICK"]'); n=await page.locator("#rows tbody tr").count(); ok(n==3, f"PICK zone filter -> {n} rows")
        ok(await page.get_attribute('[data-zone="PICK"]',"aria-pressed")=="true","zone chip pressed state")
        await page.click('[data-zone="ALL"]')
        # --- receive (first action triggers operator dialog)
        await page.goto(BASE+"#inbound"); await page.wait_for_selector('[data-action="receive"]')
        await page.locator('[data-action="receive"]').first.click()
        await page.wait_for_selector("dialog#modal[open] input[name=name]"); ok(True,"operator dialog appears before first movement")
        await snap(page, "05-operator-dialog")
        await page.fill("dialog input[name=name]","Ramsin"); await page.click("#modal-ok"); await page.wait_for_timeout(300)
        ok("Ramsin" in await page.inner_text("#operator"), "operator chip shows Ramsin")
        await page.locator('[data-action="receive"]').first.click(); await page.wait_for_selector(".toast.success"); await page.wait_for_timeout(400)
        ok("Received 300" in await page.inner_text("#toasts"), "receive toast: 300 received")
        # client-side quantity validation
        inp = page.locator(".qty-ctl input").first; await inp.fill("999"); await page.locator('[data-action="receive"]').first.click()
        await page.wait_for_selector(".toast.error"); ok("between 1 and" in await page.inner_text("#toasts"), "over-quantity caught client-side")
        await snap(page, "04-inbound-desktop", full_page=True)
        # --- move via modal (replaces window.prompt)
        await page.goto(BASE+"#stock"); await page.wait_for_selector("#stock-q")
        row = page.locator("#rows tbody tr", has_text="RECV-01").first
        await row.locator('[data-action="move"]').click(); await page.wait_for_selector("dialog#modal[open] select[name=to]")
        await page.select_option("dialog select[name=to]","A-01-02"); await snap(page, "06-move-dialog")
        await page.click("#modal-ok"); await page.wait_for_selector(".toast.success >> text=Moved 300"); ok(True,"move modal: 300 moved RECV-01 -> A-01-02")
        await snap(page, "02-stock-desktop", full_page=True)
        # --- pick both lines, see allocation across pick face then bulk
        await page.goto(BASE+"#outbound"); await page.wait_for_selector('[data-action="pick"]')
        ok(await page.locator('[data-action="dispatch"]').first.is_disabled(), "dispatch disabled until fully picked")
        await page.locator('[data-action="pick"]').first.click(); await page.wait_for_selector(".toast.success >> text=Picked 48")
        t = await page.inner_text("#toasts"); ok("B-01-01 (36)" in t and "A-01-01 (12)" in t, "pick toast shows pick face 36 then bulk 12")
        await page.wait_for_timeout(300); await page.locator('[data-action="pick"]').first.click(); await page.wait_for_selector(".toast.success >> text=Picked 80")
        await page.wait_for_timeout(300)
        ok(not await page.locator('[data-action="dispatch"]').first.is_disabled(), "dispatch enabled when fully picked")
        tb = await page.evaluate("document.querySelector('.topbar').getBoundingClientRect().bottom")
        tt = await page.evaluate("document.querySelector('#toasts').getBoundingClientRect().top")
        ok(tt >= tb, f"toasts start below the top bar ({tt:.0f} >= {tb:.0f})")
        ok(await page.locator("#toasts .toast").count() <= 3, "at most 3 toasts on screen")
        await snap(page, "03-outbound-desktop", full_page=True)
        await page.locator('[data-action="dispatch"]').first.click(); await page.wait_for_selector("dialog#modal[open] input[name=carrier]")
        await snap(page, "07-dispatch-dialog")
        await page.click("#modal-ok"); await page.wait_for_selector(".toast.success >> text=Dispatched ORD-7001"); await page.wait_for_timeout(400)
        ok(await page.get_attribute('[data-outtab="shipped"]',"aria-selected")=="true", "after dispatch, Shipped tab shown")
        ok(await page.locator("article.shipped", has_text="ORD-7001").count()==1, "ORD-7001 visible under Shipped (no longer vanishes)")
        ok(await page.locator('.nav-btn[data-route="outbound"] .count').is_hidden(), "outbound badge clears at 0 open")
        # --- ledger shows the operator, audit stays in balance
        await page.goto(BASE+"#ledger"); await page.wait_for_selector("#rows tbody tr")
        ok((await page.locator("#rows tbody tr", has_text="Ramsin").count())>=5, "ledger rows attributed to Ramsin")
        await page.click('[data-reason="PICK"]'); ok(await page.locator("#rows tbody tr").count()==3, "ledger PICK filter -> 3 rows")
        await page.goto(BASE+"#audit"); await page.wait_for_selector(".verdict.ok"); ok(True,"audit IN-BALANCE after full loop")
        await snap(page, "08-audit-desktop", full_page=True)
        # --- server-side refusal surfaced verbatim (dispatch an already-dispatched order through the API path)
        # --- corrupt the ledger: badge must go red
        await page.goto(BASE+"__corrupt"); await page.goto(BASE+"#audit"); await page.wait_for_selector(".verdict.bad")
        ok(await page.locator("#integrity.bad").count()==1, "integrity pill turns red on discrepancy")
        ok("HL-BAT-0003" in await page.inner_text("#view"), "discrepancy names the SKU to count")
        await snap(page, "09-audit-bad", full_page=True)
        await page.goto(BASE+"#overview"); await page.wait_for_selector(".hero")
        ok(await page.locator(".q-item", has_text="discrepancy").count()==1, "work queue leads with the discrepancy")
        await ctx.close()

        # ---------------- dark mode, desktop
        await (await b.new_context()).close()
        ctx = await b.new_context(viewport={"width":1440,"height":900}, color_scheme="dark")
        page = await ctx.new_page(); await watch(page,"dark")
        await page.goto(BASE+"__reset"); await page.goto(BASE+"#overview"); await page.wait_for_selector(".hero"); await page.wait_for_timeout(500)
        bg = await page.evaluate("getComputedStyle(document.body).backgroundColor"); ok(bg!="rgb(242, 245, 249)", f"dark mode body bg {bg}")
        await snap(page, "10-overview-dark", full_page=True)
        await page.goto(BASE+"#stock"); await page.wait_for_selector("#stock-q"); await snap(page, "11-stock-dark")
        await ctx.close()

        # ---------------- tablet + phone: overflow on every route
        for name, opts in [("tablet", {"viewport":{"width":900,"height":1100}}), ("phone", p.devices["iPhone 13"])]:
            ctx = await b.new_context(**opts); page = await ctx.new_page(); await watch(page,name)
            await page.goto(BASE+"__reset")
            for r in ROUTES:
                await page.goto(BASE+"#"+r); await page.wait_for_function("document.querySelector('#view').getAttribute('aria-busy')==='false'"); await page.wait_for_timeout(350)
                ov = await overflow(page); ok(ov<=0, f"{name} {r}: no horizontal overflow ({ov}px)")
                if r in ("overview","stock","outbound","inbound"): await snap(page, f"{name}-{r}", full_page=(name=="tablet"))
            if name=="phone":
                nav = await page.evaluate("getComputedStyle(document.querySelector('.sidebar')).position"); ok(nav=="fixed","phone: nav is a fixed bottom bar")
                h = await page.evaluate("Math.min(...[...document.querySelectorAll('.nav-btn')].map(e=>e.getBoundingClientRect().height))"); ok(h>=44, f"phone: nav targets >= 44px ({h:.0f})")
                await page.goto(BASE+"#stock"); await page.wait_for_selector('[data-action="move"]')
                await page.evaluate("localStorage.setItem('plimsoll.operator','Ramsin')"); await page.reload(); await page.wait_for_selector('[data-action="move"]')
                await page.locator('[data-action="move"]').first.click(); await page.wait_for_selector("dialog#modal[open]"); await page.wait_for_timeout(300)
                await snap(page, "phone-move-sheet")
            await ctx.close()
        await b.close()
    print("\n".join(log)); print("\n".join(problems) if problems else "\nNO PROBLEMS")
    print(f"\n{len(log)} passed, {len(problems)} failed")

def start_backend():
    proc = subprocess.Popen([sys.executable, str(HERE / "mock_backend.py"), str(WEB), str(PORT)])
    for _ in range(50):
        try:
            urllib.request.urlopen(BASE + "api/health", timeout=1); return proc
        except OSError:
            time.sleep(0.2)
    proc.kill(); sys.exit("mock backend did not start")

if __name__ == "__main__":
    backend = start_backend()
    try:
        asyncio.run(main())
    finally:
        backend.kill()
    sys.exit(1 if problems else 0)

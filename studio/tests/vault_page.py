"""6.1 a: the personal settings page, end to end in Chromium with a fake hub.

Sets HOME_AREA, changes it, removes it (two presses), and checks: values are hidden until shown, every change is a
new private event (nothing overwritten), the flow-facing shape is {kind: vault.set|vault.unset, name, value}.
Run: python studio/tests/vault_page.py
"""
import asyncio, json, pathlib, urllib.parse
from playwright.async_api import async_playwright

STUDIO = pathlib.Path(__file__).parent.parent
PAGE = "<!doctype html><html><head><meta charset=utf-8></head><body>" + (STUDIO / "vault.html").read_text() + "</body></html>"


async def main():
    store = []

    async def handle(route):
        url, req = route.request.url, route.request
        if url.endswith("/studio/vault"):
            return await route.fulfill(status=200, content_type="text/html", body=PAGE)
        if url.endswith("/studio/api/me"):
            return await route.fulfill(status=200, content_type="application/json", body=json.dumps({"login": "Morami49"}))
        if "/studio/api/private" in url and req.method == "GET":
            path = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)["path"][0]
            assert path == "data/users/Morami49/vault/vars", path
            return await route.fulfill(status=200, content_type="application/json",
                                       body=json.dumps({"events": [{"event": e} for e in store], "unreadable": 1}))
        if url.endswith("/studio/api/private") and req.method == "POST":
            assert req.headers.get("x-nodach-studio") == "1"
            b = json.loads(req.post_data)
            assert b["path"] == "data/users/Morami49/vault/vars" and b["doc_id"].startswith("v-")
            store.append(b["event"])
            return await route.fulfill(status=200, content_type="application/json", body=json.dumps({"stored": True}))
        await route.fulfill(status=404, body="")

    async with async_playwright() as p:
        b = await p.chromium.launch()
        pg = await b.new_page()
        await pg.route("**/*", handle)
        await pg.goto("https://studio.test/studio/vault")
        await pg.wait_for_selector("text=signed in as Morami49")
        assert "not set" in await pg.inner_text("#list"), "known settings should show before they're set"
        await pg.fill("#name", "HOME_AREA"); await pg.fill("#value", "E12"); await pg.click("#save")
        await pg.wait_for_selector("text=Saved HOME_AREA")
        assert "E12" not in await pg.inner_text("#list"), "value must stay hidden until shown"
        await pg.click("[data-show]")
        assert "E12" in await pg.inner_text("#list")
        await pg.fill("#name", "HOME_AREA"); await pg.fill("#value", "E7"); await pg.click("#save")
        await pg.wait_for_selector("text=Saved HOME_AREA (new version)")
        await pg.click("[data-unset]")
        assert len(store) == 2, "first remove press only arms"
        await pg.click("[data-unset]")
        await pg.wait_for_selector("text=Removed HOME_AREA")
        assert [e["kind"] for e in store] == ["vault.set", "vault.set", "vault.unset"]
        assert [e.get("value") for e in store] == ["E12", "E7", None]
        assert "can't be opened" in await pg.inner_text("#history")
        await b.close()
    print("vault page: set, change, remove kept as 3 versions; values hidden until shown")


asyncio.run(main())

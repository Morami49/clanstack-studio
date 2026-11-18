"""M1 d: the spreadsheet import page, end to end in Chromium with a fake hub.

Builds the page the way the hub does (xlsx-lite inlined, import.html as the body), picks the sample .xlsx,
imports, then imports again: the second run must be all repeats. Contact tabs (People) must never be sent.
Run: python studio/tests/import_page.py
"""
import asyncio, hashlib, json, pathlib, sys
from playwright.async_api import async_playwright

HERE = pathlib.Path(__file__).parent
STUDIO = HERE.parent
PAGE = ("<!doctype html><html><head><meta charset=utf-8><script>" + (STUDIO / "xlsx-lite.js").read_text()
        + "</script></head><body>" + (STUDIO / "import.html").read_text() + "</body></html>")


async def main():
    stored, sent_paths, batches = {}, set(), []

    async def handle(route):
        url, req = route.request.url, route.request
        if url.endswith("/studio/import"):
            return await route.fulfill(status=200, content_type="text/html", body=PAGE)
        if url.endswith("/studio/api/me"):
            return await route.fulfill(status=200, content_type="application/json", body=json.dumps({"login": "Morami49"}))
        if url.endswith("/studio/api/private/batch"):
            assert req.headers.get("x-nodach-studio") == "1", "write without the Studio header"
            items = json.loads(req.post_data)["items"]
            assert 1 <= len(items) <= 200
            batches.append(len(items))
            new = 0
            for it in items:
                assert it["path"].startswith("data/users/Morami49/work-lane/"), it["path"]
                sent_paths.add(it["path"])
                doc = hashlib.sha256(f'{it["path"]}\0{it["key"]}'.encode()).hexdigest()[:16]
                if doc not in stored:
                    stored[doc] = it["event"]; new += 1
            body = {"count": len(items), "new": new, "repeats": len(items) - new, "batch_checksum": "f" * 64,
                    "items": [{"doc_id": "cp-x", "key": it["key"]} for it in items]}
            return await route.fulfill(status=200, content_type="application/json", body=json.dumps(body))
        await route.fulfill(status=404, body="")

    async with async_playwright() as p:
        b = await p.chromium.launch()
        page = await b.new_page()
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        await page.route("https://hub.test/**", handle)
        await page.goto("https://hub.test/studio/import")
        await page.wait_for_function("document.getElementById('who').textContent.includes('Morami49')")
        await page.set_input_files("#file", str(HERE / "fixtures" / "sample.xlsx"))
        await page.wait_for_function("document.getElementById('status').textContent.includes('tabs read')")
        people_disabled = await page.eval_on_selector("#sheets input[data-i='1']", "e => e.disabled && !e.checked")
        empty_unchecked = await page.eval_on_selector("#sheets input[data-i='2']", "e => !e.checked")

        await page.click("#go")
        await page.wait_for_function("document.getElementById('status').textContent.startsWith('Done')")
        rows = [e for e in stored.values() if e["kind"] == "sheet.row"]
        manifests = [e for e in stored.values() if e["kind"] == "import.manifest"]
        snaps = [e for e in stored.values() if e["kind"] == "import.snapshot"]
        first_new = len(stored)

        await page.click("#go")
        await page.wait_for_function("document.getElementById('report').textContent.includes('Repeats')")
        await page.wait_for_function("document.getElementById('status').textContent.startsWith('Done')")
        rows_after = [e for e in stored.values() if e["kind"] == "sheet.row"]
        await b.close()

    checks = {
        "contact tab held back": people_disabled and not any(p.endswith("/people") for p in sent_paths),
        "empty tab not chosen": empty_unchecked,
        "2 rows imported with cells and row numbers": len(rows) == 2 and sorted(r["row"] for r in rows) == [2, 4]
            and rows[0]["cells"].get("Submit by") in ("2026-11-30", "2026-12-01 09:30"),
        "manifest names the held-back tab and the file hash": len(manifests) == 1 and manifests[0]["held_back"] == ["People"]
            and len(manifests[0]["file_sha256"]) == 64,
        "snapshot lists the row keys in order": len(snaps) == 1 and len(snaps[0]["keys"]) == 2,
        "second run adds no rows (only its own manifest and snapshot)": len(rows_after) == 2 and len(stored) == first_new + 2,
        "no page errors": not errors,
    }
    for k, v in checks.items():
        print(("PASS " if v else "FAIL ") + k)
    if errors:
        print(errors)
    sys.exit(0 if all(checks.values()) else 1)

asyncio.run(main())

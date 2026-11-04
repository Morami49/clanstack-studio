"""Build web/index.html: one self-contained file (JS glue + WASM inlined) that opens anywhere, even from disk."""
import re, pathlib
here = pathlib.Path(__file__).parent
glue = (here / "pkg" / "foundation_wasm.js").read_text()
glue = glue.replace("export default __wbg_init;", "").replace("export { initSync };", "")
glue = re.sub(r"^export (class|function|const) ", r"\1 ", glue, flags=re.M)
import base64
wasm = base64.b64encode((here / "pkg" / "foundation_wasm_bg.wasm").read_bytes()).decode()
page = (here / "app.html").read_text().replace("/*GLUE*/", glue).replace("/*WASM*/", wasm)
(here / "index.html").write_text(page)
print("web/index.html", len(page), "bytes")

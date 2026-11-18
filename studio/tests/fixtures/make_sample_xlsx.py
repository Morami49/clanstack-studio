"""Builds sample.xlsx for xlsx-lite.test.mjs (run: python3 studio/tests/fixtures/make_sample_xlsx.py)."""
import datetime, pathlib, openpyxl
wb = openpyxl.Workbook()
ws = wb.active; ws.title = "Roles"
ws.append(["Role", "Company", "Submit by", "Remote", "Score", "Score", None])
ws.append(["Analyst & <Ops>", "Acme — Ltd", datetime.date(2026, 11, 30), True, 7.5, 3, "extra"])
ws.append([])
ws.append(["Producer", "Café Nodach", datetime.datetime(2026, 12, 1, 9, 30), False, None, 4, None])
p = wb.create_sheet("People"); p.append(["Name", "Email"]); p.append(["X", "x@example.com"])
e = wb.create_sheet("Empty")
wb.save(pathlib.Path(__file__).with_name("sample.xlsx"))

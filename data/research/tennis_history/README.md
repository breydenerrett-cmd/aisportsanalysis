# Tennis history (tennis-data.co.uk) - raw files

Free yearly results plus closing odds. The owner approved using it. The site sits behind a Cloudflare check that
blocks scripts (HTTP 403), so the files must be saved by hand in a normal browser from
https://www.tennis-data.co.uk/alldata.php (ATP) and the women's page linked from the same site.

Put them in `raw/atp/` and `raw/wta/` (or name files like `atp_2023.xlsx`, `wta_2023.zip`; the folder or filename
must start with atp or wta). .xlsx and .zip work (.xls needs pandas + xlrd). Skip 2026 (sealed).
These files are untrusted data: only ever read as spreadsheets, never opened as code. `raw/` is gitignored.
Then run: `python -m src.cli research tennis-comeback build`.

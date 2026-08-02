"""Render the EHR chart to a standalone HTML file for design iteration.

    python scripts/preview_ehr.py P001 P003 > /dev/null
Opens nothing; writes scratchpad/ehr_preview.html (multi-patient tabs).
"""
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from domains.healthcare import ehr_data, ehr_theme  # noqa: E402

OUT = os.environ.get(
    "EHR_PREVIEW_OUT",
    "/private/tmp/claude-501/-Users-placey-Library-CloudStorage-Box-Box-dev-galileo-golden-demo/"
    "10fd9e6e-264d-4807-9af3-2762371b9903/scratchpad/ehr_preview.html",
)


def main():
    pids = sys.argv[1:] or ["P001"]
    now = datetime(2026, 8, 1, 9, 24)
    pages = []
    for pid in pids:
        c = ehr_data.get_chart(pid)
        pages.append(ehr_theme.render_page(c, practitioner="Dr. A. Morgan, MD", now=now))
    sep = '<div style="height:34px"></div>'
    body = sep.join(pages)
    doc = f"""<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>EHR preview</title>
<style>{ehr_theme.FONTS}
html,body{{margin:0;background:var(--paper);}}
body{{padding:26px 30px 60px;}}
{ehr_theme.EHR_CSS}
</style></head><body>{body}</body></html>"""
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as fh:
        fh.write(doc)
    print(OUT)


if __name__ == "__main__":
    main()

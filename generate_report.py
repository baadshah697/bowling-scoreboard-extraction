import os

with open("SUBMISSION_DOCUMENTATION.md", "r", encoding="utf-8") as f:
    md = f.read()

# Simple markdown to HTML converter for clean styling
lines = md.split("\n")
html_body = []
in_code = False
in_table = False

for line in lines:
    if line.startswith("```"):
        if in_code:
            html_body.append("</pre>")
            in_code = False
        else:
            html_body.append("<pre><code>")
            in_code = True
        continue
    
    if in_code:
        html_body.append(line.replace("<", "&lt;").replace(">", "&gt;"))
        continue

    if line.startswith("# "):
        html_body.append(f"<h1>{line[2:]}</h1>")
    elif line.startswith("## "):
        html_body.append(f"<h2>{line[3:]}</h2>")
    elif line.startswith("### "):
        html_body.append(f"<h3>{line[4:]}</h3>")
    elif line.startswith("|") and "|" in line[1:]:
        if not in_table:
            html_body.append("<table>")
            in_table = True
        parts = [p.strip() for p in line.strip().split("|")[1:-1]]
        if all(set(p).issubset({"-", ":"}) for p in parts if p):
            continue
        row_tag = "th" if "Row" in parts or "Bowler Name" in parts or "Requirement" in parts else "td"
        cells = "".join([f"<{row_tag}>{p}</{row_tag}>" for p in parts])
        html_body.append(f"<tr>{cells}</tr>")
    else:
        if in_table:
            html_body.append("</table>")
            in_table = False
        if line.startswith("- "):
            html_body.append(f"<li>{line[2:]}</li>")
        elif line.startswith("> "):
            html_body.append(f"<blockquote>{line[2:]}</blockquote>")
        elif line.strip() == "---":
            html_body.append("<hr/>")
        elif line.strip():
            html_body.append(f"<p>{line}</p>")

if in_table:
    html_body.append("</table>")

full_html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>ScoreVision - Project Submission Documentation</title>
<style>
  body {{
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;
    line-height: 1.6;
    color: #1e293b;
    background: #f8fafc;
    padding: 40px;
    max-width: 1050px;
    margin: 0 auto;
  }}
  h1 {{ color: #0f172a; font-size: 26px; border-bottom: 2px solid #38bdf8; padding-bottom: 8px; }}
  h2 {{ color: #0f172a; font-size: 20px; border-bottom: 1px solid #cbd5e1; padding-bottom: 6px; margin-top: 30px; }}
  h3 {{ color: #1e293b; font-size: 16px; margin-top: 20px; }}
  table {{
    width: 100%;
    border-collapse: collapse;
    margin: 20px 0;
    background: #ffffff;
    border-radius: 8px;
    overflow: hidden;
    box-shadow: 0 1px 3px rgba(0,0,0,0.08);
  }}
  th, td {{
    padding: 10px 12px;
    border: 1px solid #cbd5e1;
    text-align: center;
    font-size: 14px;
  }}
  th {{
    background: #0f172a;
    color: #ffffff;
    font-weight: 700;
  }}
  tr:nth-child(even) {{ background: #f1f5f9; }}
  pre {{
    background: #0f172a;
    color: #38bdf8;
    padding: 14px;
    border-radius: 6px;
    overflow-x: auto;
    font-family: 'Consolas', 'Courier New', monospace;
    font-size: 13px;
  }}
  blockquote {{
    border-left: 4px solid #38bdf8;
    background: #e0f2fe;
    padding: 10px 16px;
    margin: 16px 0;
    border-radius: 0 6px 6px 0;
  }}
  li {{ margin-bottom: 4px; }}
  hr {{ border: none; border-top: 1px solid #e2e8f0; margin: 24px 0; }}
  @media print {{
    body {{ padding: 0; background: #fff; }}
    table {{ box-shadow: none; }}
  }}
</style>
</head>
<body>
{"".join(html_body)}
</body>
</html>
"""

os.makedirs("output", exist_ok=True)
with open("output/SUBMISSION_DOCUMENTATION.html", "w", encoding="utf-8") as f:
    f.write(full_html)

print("Generated output/SUBMISSION_DOCUMENTATION.html successfully!")

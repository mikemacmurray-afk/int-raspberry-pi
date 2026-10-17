"""
CLI Tool to scaffold a new application inside apps/<app_name>
and instantly register it on the Cranleigh OS Desktop.

Usage:
  python tools/new_app.py --name "Garden Irrigation" --icon "🌿" --category "Outdoor"
"""

import sys
import json
import argparse
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
APPS_DIR = BASE_DIR / "apps"
DATA_DIR = BASE_DIR / "data"

HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{app_name} • Cranleigh OS</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700;800&family=JetBrains+Mono:wght@400;600;700&display=swap" rel="stylesheet">
  <style>
    :root {{
      --bg: #090e1a;
      --card-bg: rgba(18, 26, 46, 0.82);
      --card-hover: rgba(28, 40, 70, 0.95);
      --border: rgba(255, 255, 255, 0.09);
      --border-glow: rgba(56, 189, 248, 0.35);
      --text: #f8fafc;
      --text-muted: #94a3b8;
      --accent: #38bdf8;
    }}

    * {{
      box-sizing: border-box;
      margin: 0;
      padding: 0;
      -webkit-tap-highlight-color: transparent;
    }}

    html, body {{
      background-color: var(--bg);
      color: var(--text);
      font-family: 'Plus Jakarta Sans', sans-serif;
      min-height: 100vh;
      overflow-y: auto !important;
      touch-action: pan-y !important;
      -webkit-overflow-scrolling: touch !important;
      padding: 1.25rem;
    }}

    header {{
      display: flex;
      justify-content: space-between;
      align-items: center;
      padding-bottom: 1rem;
      border-bottom: 1px solid var(--border);
      margin-bottom: 1.25rem;
      flex-wrap: wrap;
      gap: 1rem;
    }}

    .brand {{
      display: flex;
      align-items: center;
      gap: 0.75rem;
    }}

    .brand-icon {{
      width: 44px;
      height: 44px;
      border-radius: 12px;
      background: rgba(255, 255, 255, 0.06);
      border: 1px solid rgba(255, 255, 255, 0.12);
      display: flex;
      align-items: center;
      justify-content: center;
      font-size: 1.6rem;
    }}

    .grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
      gap: 1.25rem;
    }}

    .card {{
      background: var(--card-bg);
      border: 1px solid var(--border);
      border-radius: 16px;
      padding: 1.25rem;
      backdrop-filter: blur(16px);
      transition: all 0.2s;
    }}

    .card:hover {{
      border-color: rgba(255, 255, 255, 0.18);
      background: var(--card-hover);
    }}

    .btn {{
      padding: 0.6rem 1.2rem;
      border-radius: 10px;
      border: none;
      background: linear-gradient(135deg, #0284c7, #06b6d4);
      color: #ffffff;
      font-weight: 700;
      font-size: 0.85rem;
      cursor: pointer;
      transition: all 0.2s;
      touch-action: manipulation;
    }}

    .btn:active {{
      transform: scale(0.97);
    }}

    /* Touch Friendly Scrollbar */
    ::-webkit-scrollbar {{
      width: 8px;
    }}
    ::-webkit-scrollbar-thumb {{
      background: rgba(255, 255, 255, 0.25);
      border-radius: 4px;
    }}
  </style>
</head>
<body>

  <header>
    <div class="brand">
      <div class="brand-icon">{icon}</div>
      <div>
        <h2 style="font-size: 1.3rem; font-weight: 800;">{app_name}</h2>
        <div style="font-size: 0.78rem; color: var(--text-muted);">{category} Module • Cranleigh OS</div>
      </div>
    </div>
    <div style="display: flex; gap: 0.5rem;">
      <button class="btn" onclick="fetchTelemetry()">🔄 Refresh</button>
    </div>
  </header>

  <main class="grid">
    <div class="card">
      <h3 style="font-size: 1rem; margin-bottom: 0.5rem;">Status & Telemetry</h3>
      <p style="font-size: 0.85rem; color: var(--text-muted); margin-bottom: 1rem;">
        Connected to core home conductor service.
      </p>
      <div id="telemetry-info" style="font-family: 'JetBrains Mono', monospace; font-size: 0.85rem; color: #38bdf8;">
        Loading live metrics...
      </div>
    </div>

    <div class="card">
      <h3 style="font-size: 1rem; margin-bottom: 0.5rem;">Controls & Automation</h3>
      <p style="font-size: 0.85rem; color: var(--text-muted); margin-bottom: 1rem;">
        Add your application-specific triggers or relay switches here.
      </p>
      <button class="btn" onclick="alert('{app_name} action triggered!')">Trigger Action</button>
    </div>
  </main>

  <script>
    async function fetchTelemetry() {{
      try {{
        const res = await fetch('/api/state');
        if (!res.ok) return;
        const state = await res.json();
        document.getElementById('telemetry-info').innerText = 
          `Solar: ${{state.sunsynk?.pv_watts ?? 0}} W | Batt: ${{state.sunsynk?.battery_soc ?? 0}}%`;
      }} catch (err) {{
        document.getElementById('telemetry-info').innerText = 'Telemetry standby';
      }}
    }}

    window.onload = fetchTelemetry;
  </script>
</body>
</html>
"""

def main():
    parser = argparse.ArgumentParser(description="Scaffold a new Cranleigh OS app")
    parser.add_argument("--name", required=True, help="Display name of the application")
    parser.add_argument("--icon", default="📦", help="Emoji icon for the application")
    parser.add_argument("--category", default="Custom", help="Category (e.g. Energy, Outdoor, Climate, System)")
    parser.add_argument("--slug", default=None, help="Folder slug (auto-derived if omitted)")
    args = parser.parse_args()

    slug = args.slug or args.name.lower().replace(" ", "_").replace("-", "_")
    app_dir = APPS_DIR / slug

    if app_dir.exists():
        print(f"[!] App folder already exists: {app_dir}")
        sys.exit(1)

    app_dir.mkdir(parents=True, exist_ok=True)

    # 1. Write manifest.json
    manifest = {
        "id": slug,
        "name": args.name,
        "icon": args.icon,
        "category": args.category,
        "type": "static",
        "url": f"/apps/hosted/{slug}/index.html",
        "description": f"{args.name} module for Cranleigh OS",
        "default_maximized": False,
        "is_system": False,
        "width": 920,
        "height": 580
    }
    with open(app_dir / "manifest.json", "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)

    # 2. Write index.html
    html_content = HTML_TEMPLATE.format(
        app_name=args.name,
        icon=args.icon,
        category=args.category
    )
    with open(app_dir / "index.html", "w", encoding="utf-8") as f:
        f.write(html_content)

    # 3. Update apps.json in data/
    apps_json_path = DATA_DIR / "apps.json"
    if apps_json_path.exists():
        try:
            with open(apps_json_path, "r", encoding="utf-8") as f:
                apps = json.load(f)
        except Exception:
            apps = []
    else:
        apps = []

    # Replace if exists, or append
    existing = False
    for i, a in enumerate(apps):
        if a.get("id") == slug:
            apps[i] = manifest
            existing = True
            break
    if not existing:
        apps.append(manifest)

    with open(apps_json_path, "w", encoding="utf-8") as f:
        json.dump(apps, f, indent=2, ensure_ascii=False)

    print(f"[+] Created new app '{args.name}' successfully!")
    print(f"    Folder: apps/{slug}/")
    print(f"    URL:    http://localhost:8000/apps/hosted/{slug}/index.html")
    print(f"    Desktop shortcut pinned automatically.")

if __name__ == "__main__":
    main()

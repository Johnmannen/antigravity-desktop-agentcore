import asyncio
from playwright.async_api import async_playwright

html = """<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
  body { background: #18181b; color: #f4f4f5; font-family: 'Consolas', monospace; padding: 24px; margin: 0; }
  .card { background: #27272a; border: 1px solid #3f3f46; border-radius: 8px; padding: 20px; max-width: 820px; box-shadow: 0 4px 12px rgba(0,0,0,0.5); }
  h2 { margin-top: 0; color: #60a5fa; font-family: sans-serif; font-size: 18px; border-bottom: 1px solid #3f3f46; padding-bottom: 8px; }
  .path { color: #a1a1aa; font-size: 13px; margin-bottom: 16px; font-family: sans-serif; }
  pre { background: #09090b; padding: 16px; border-radius: 6px; font-size: 13px; line-height: 1.6; overflow-x: auto; border: 1px solid #3f3f46; }
  .hl-red { color: #f87171; font-weight: bold; background: rgba(248, 113, 113, 0.15); padding: 2px 4px; border-radius: 4px; }
  .hl-yellow { color: #facc15; font-weight: bold; background: rgba(250, 204, 21, 0.15); padding: 2px 4px; border-radius: 4px; }
  .desc { margin-top: 14px; font-family: sans-serif; font-size: 13px; color: #d4d4d8; background: #334155; padding: 10px 14px; border-radius: 6px; border-left: 4px solid #38bdf8; }
</style>
</head>
<body>
<div class="card">
  <h2>Google Antigravity &amp; Code Assist - Auth Diagnostic Log</h2>
  <div class="path">Källa: %APPDATA%\\Antigravity\\logs\\language_server.log</div>
  <pre>
auth_provider.go:1287: [AuthProvider] SetProjectID called with projectID: ""
auth_provider.go:1295: [AuthProvider] SetLocation called with location: ""
<span class="hl-red">auth_provider.go:1303: [AuthProvider] SetUserTier called with userTier: "", tierDisplayName: ""</span>
http_helpers.go:658:   URL: https://cloudcode-pa.googleapis.com/v1internal:loadCodeAssist
<span class="hl-yellow">credit_summary_bytes: 0</span>
cost_summary_bytes: 0
  </pre>
  <div class="desc">
    <b>Problem / Fel:</b> Kontot är bekräftat aktivt med <b>Google AI Pro</b> i appens inställningar, men <code>loadCodeAssist</code>-slutpunkten sätter tomt <code>userTier: ""</code> och <code>credit_summary_bytes: 0</code>. Detta degraderar användaren till gratiskvoter och kopplar bort Pro-funktioner.
  </div>
</div>
</body>
</html>"""

async def main():
    chrome_path = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
    async with async_playwright() as p:
        browser = await p.chromium.launch(executable_path=chrome_path, headless=True)
        page = await browser.new_page(viewport={"width": 860, "height": 400})
        await page.set_content(html)
        await page.screenshot(path=r"<USER_HOME>\Desktop\2_Antigravity_Loggfel_UserTier_Tom.png")
        await browser.close()
        print("Screenshot generated successfully at <USER_HOME>\\Desktop\\2_Antigravity_Loggfel_UserTier_Tom.png")

if __name__ == "__main__":
    asyncio.run(main())

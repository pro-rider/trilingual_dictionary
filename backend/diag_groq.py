import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import httpx
from app.core.config import settings

print("enabled:", settings.ai_enabled, "| key set:", bool(settings.ai_api_key), "| model:", settings.ai_model, "| base:", settings.ai_base_url)

model = settings.ai_model or "llama-3.3-70b-versatile"
url = f"{settings.ai_base_url.rstrip('/')}/chat/completions"
headers = {"Authorization": f"Bearer {settings.ai_api_key}", "Content-Type": "application/json"}
payload = {
    "model": model,
    "temperature": 0.4,
    "response_format": {"type": "json_object"},
    "messages": [{"role": "system", "content": "return strict json for the word apple"}],
}
try:
    resp = httpx.post(url, headers=headers, json=payload, timeout=40)
    print("status:", resp.status_code)
    print("body:", resp.text[:800])
except Exception as e:
    print("EXC:", type(e).__name__, str(e))

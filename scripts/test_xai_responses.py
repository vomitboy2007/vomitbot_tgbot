import asyncio
import json
import os

import httpx


async def main():
    key = os.environ.get("XAI_API_KEY", "")
    payload = {
        "model": "grok-4.3",
        "input": [{"role": "user", "content": "сколько население в перми"}],
        "tools": [{"type": "web_search"}],
        "instructions": "отвечай кратко по-русски",
    }
    async with httpx.AsyncClient(timeout=120) as c:
        r = await c.post(
            "https://api.x.ai/v1/responses",
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            json=payload,
        )
        print("status", r.status_code)
        data = r.json()
        print(json.dumps(data, ensure_ascii=False)[:5000])


asyncio.run(main())

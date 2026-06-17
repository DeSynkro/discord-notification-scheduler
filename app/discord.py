import httpx
import asyncio
from app.models import Alarm
from app.storage import read_json

# Discord allows 30 requests per 60 seconds per webhook.
# If we get rate limited, we wait however long Discord tells us to.
# This is the max time we'll ever wait before giving up.
MAX_RETRY_WAIT = 30


def _hex_to_int(hex_color: str | None) -> int | None:
    if not hex_color:
        return None
    return int(hex_color.lstrip("#"), 16)


def _build_payload(alarm: Alarm) -> dict:
    payload = {"allowed_mentions": {"parse": []}}

    if alarm.message_type == "embed":
        embed = {"description": alarm.message}
        if alarm.embed and alarm.embed.title:
            embed["title"] = alarm.embed.title
        if alarm.embed and alarm.embed.color:
            color_int = _hex_to_int(alarm.embed.color)
            if color_int is not None:
                embed["color"] = color_int
        payload["embeds"] = [embed]
    else:
        payload["content"] = alarm.message

    return payload


async def send_webhook(alarm: Alarm) -> tuple[bool, str]:
    hook_url = _find_webhook_url(alarm.webhook_name)
    if not hook_url:
        return False, f"Webhook '{alarm.webhook_name}' not found"

    payload = _build_payload(alarm)

    async with httpx.AsyncClient(timeout=15) as client:
        for attempt in range(3):
            try:
                resp = await client.post(hook_url, json=payload)
            except httpx.RequestError as e:
                if attempt < 2:
                    await asyncio.sleep(1)
                    continue
                return False, f"Connection failed: {e}"

            if resp.status_code == 429:
                retry_str = resp.headers.get("Retry-After", "2")
                try:
                    wait = min(int(retry_str), MAX_RETRY_WAIT)
                except ValueError:
                    wait = 2
                if attempt < 2:
                    await asyncio.sleep(wait)
                    continue
                return False, f"Rate limited (429), tried {attempt + 1} times"

            if resp.status_code == 204:
                return True, ""

            if 200 <= resp.status_code < 300:
                return True, ""

            return False, f"Discord returned {resp.status_code}"

    return False, "Failed after retries"


def _find_webhook_url(name: str) -> str | None:
    webhooks = read_json("webhooks")
    for w in webhooks:
        if w["name"] == name:
            return w["url"]
    return None

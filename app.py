import json
import os
import uuid
from pathlib import Path
from urllib.parse import urlparse

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

BASE = Path(__file__).parent
DATA = BASE / "devices.json"
INDEX = BASE / "index.html"

app = FastAPI(title="Kid Phone Guardian")


class DeviceIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    url: str = Field(min_length=1, max_length=2000)


# Trên Vercel hệ thống file chỉ đọc -> lưu vào Upstash Redis (Vercel KV) nếu có biến môi trường.
# Chạy local không có biến này thì dùng devices.json như cũ.
REDIS_URL = os.getenv("KV_REST_API_URL") or os.getenv("UPSTASH_REDIS_REST_URL")
REDIS_TOKEN = os.getenv("KV_REST_API_TOKEN") or os.getenv("UPSTASH_REDIS_REST_TOKEN")
REDIS_KEY = "kid-phone-guardian:devices"


def _redis(*cmd: str):
    r = httpx.post(REDIS_URL, json=list(cmd), headers={"Authorization": f"Bearer {REDIS_TOKEN}"}, timeout=8.0)
    r.raise_for_status()
    return r.json().get("result")


def read_devices() -> list[dict]:
    if REDIS_URL and REDIS_TOKEN:
        # Lỗi Redis thì báo lỗi, không trả [] (tránh ghi đè mất dữ liệu ở lần lưu sau)
        try:
            raw = _redis("GET", REDIS_KEY)
        except Exception as e:
            raise HTTPException(status_code=503, detail=f"Không đọc được kho dữ liệu: {e.__class__.__name__}")
        return json.loads(raw) if raw else []
    if not DATA.exists():
        return []
    try:
        return json.loads(DATA.read_text(encoding="utf-8"))
    except Exception:
        return []


def write_devices(devices: list[dict]) -> None:
    text = json.dumps(devices, ensure_ascii=False, indent=2)
    if REDIS_URL and REDIS_TOKEN:
        _redis("SET", REDIS_KEY, text)
    else:
        DATA.write_text(text, encoding="utf-8")


def validate_webhook_url(url: str) -> str:
    p = urlparse(url)
    if p.scheme not in ("http", "https") or not p.netloc:
        raise HTTPException(status_code=400, detail="URL webhook phải bắt đầu bằng http:// hoặc https://")
    return url


@app.get("/")
def index():
    return FileResponse(INDEX)


@app.get("/api/devices")
def list_devices():
    return read_devices()


@app.post("/api/devices", status_code=201)
def add_device(device: DeviceIn):
    name = device.name.strip()
    url = validate_webhook_url(device.url.strip())
    if not name:
        raise HTTPException(status_code=400, detail="Tên thiết bị không được trống")
    devices = read_devices()
    item = {"id": uuid.uuid4().hex, "name": name, "url": url}
    devices.append(item)
    write_devices(devices)
    return item


@app.delete("/api/devices/{device_id}", status_code=204)
def delete_device(device_id: str):
    devices = read_devices()
    kept = [d for d in devices if d.get("id") != device_id]
    if len(kept) == len(devices):
        raise HTTPException(status_code=404, detail="Không tìm thấy thiết bị")
    write_devices(kept)


@app.post("/api/devices/{device_id}/trigger")
async def trigger_device(device_id: str):
    devices = read_devices()
    device = next((d for d in devices if d.get("id") == device_id), None)
    if not device:
        raise HTTPException(status_code=404, detail="Không tìm thấy thiết bị")
    url = device["url"]
    try:
        async with httpx.AsyncClient(timeout=8.0, follow_redirects=True) as client:
            r = await client.get(url)
        return {"ok": True, "status_code": r.status_code, "name": device["name"]}
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Không gửi được tín hiệu: {e.__class__.__name__}")

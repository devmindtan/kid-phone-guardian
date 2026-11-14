import hashlib
import hmac
import json
import os
import uuid
from pathlib import Path
from urllib.parse import urlparse

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from pydantic import BaseModel, Field

BASE = Path(__file__).parent
DATA = BASE / "devices.json"
INDEX = BASE / "index.html"

app = FastAPI(title="Kid Phone Guardian")

# Chỉ máy đã ghép mới vào được: đặt PAIR_KEY trên Vercel, mở /pair?key=<PAIR_KEY> một lần trên mỗi máy.
# Đổi PAIR_KEY = thu hồi mọi máy đã ghép. Không đặt PAIR_KEY (chạy local) = không khóa.
PAIR_KEY = os.getenv("PAIR_KEY", "")
COOKIE = "kpg_device"
COOKIE_AGE = 10 * 365 * 24 * 3600


def _device_token() -> str:
    return hmac.new(PAIR_KEY.encode(), b"paired-device", hashlib.sha256).hexdigest()


def _is_paired(request: Request) -> bool:
    return hmac.compare_digest(request.cookies.get(COOKIE, ""), _device_token())


@app.middleware("http")
async def require_paired_device(request: Request, call_next):
    if not PAIR_KEY or request.url.path == "/pair" or _is_paired(request):
        return await call_next(request)
    if request.url.path.startswith("/api/"):
        return HTMLResponse('{"detail":"Thiết bị chưa được ghép"}', status_code=403, media_type="application/json")
    return HTMLResponse(
        "<!doctype html><meta charset=utf-8><meta name=viewport content='width=device-width'>"
        "<title>Không có quyền</title><body style='font-family:sans-serif;padding:24px'>"
        "<h2>Thiết bị này chưa được ghép</h2><p>Mở link ghép một lần trên máy này để truy cập.</p>",
        status_code=403,
    )


@app.get("/pair")
def pair(request: Request, key: str = ""):
    if not PAIR_KEY or not hmac.compare_digest(key, PAIR_KEY):
        raise HTTPException(status_code=403, detail="Mã ghép không đúng")
    resp = RedirectResponse("/", status_code=303)
    https = request.headers.get("x-forwarded-proto", request.url.scheme) == "https"
    resp.set_cookie(COOKIE, _device_token(), max_age=COOKIE_AGE, httponly=True, secure=https, samesite="lax")
    return resp


class DeviceIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    url: str = Field(min_length=1, max_length=2000)


# Trên Vercel hệ thống file chỉ đọc -> lưu vào Upstash Redis (Vercel KV) nếu có biến môi trường.
# Chạy local không có biến này thì dùng devices.json như cũ.
def _env_suffix(*suffixes: str) -> str | None:
    # Nhận cả biến có tiền tố tùy ý do Vercel tạo, vd STORAGE_KV_REST_API_URL
    for suffix in suffixes:
        if os.getenv(suffix):
            return os.getenv(suffix)
        for k, v in os.environ.items():
            if k.endswith("_" + suffix) and v:
                return v
    return None


REDIS_URL = _env_suffix("KV_REST_API_URL", "UPSTASH_REDIS_REST_URL")
REDIS_TOKEN = _env_suffix("KV_REST_API_TOKEN", "UPSTASH_REDIS_REST_TOKEN")
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

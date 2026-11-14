# Điều khiển từ xa (MacroDroid webhook)

Web app FastAPI đơn giản để lưu URL webhook của MacroDroid theo từng thiết bị (trong `devices.json`) và bấm nút kích hoạt từ giao diện.

## Chạy dự án

Nhanh: `./run.sh` (tự tạo `.venv`, cài deps nếu thiếu, mặc định cổng `8000`, đổi bằng `PORT=3000 ./run.sh`).

Thủ công:

```bash
cd kid-phone-guardian
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app:app --host 0.0.0.0 --port 8000
```

Mở `http://localhost:8000`.

## Cách dùng

1. Nhập **Tên thiết bị** và **URL webhook** MacroDroid, bấm **Lưu thiết bị** (được ghi vào `devices.json`).
2. Với mỗi thiết bị, bấm **Kích hoạt** để máy chủ gửi yêu cầu `GET` tới webhook.
3. Bấm **Xóa** để gỡ thiết bị khỏi `devices.json`.

## API

- `GET /api/devices` — danh sách thiết bị
- `POST /api/devices` — thêm `{ "name": "...", "url": "https://..." }`
- `DELETE /api/devices/{id}` — xóa thiết bị
- `POST /api/devices/{id}/trigger` — kích hoạt webhook

## Ghi chú

- Dữ liệu nằm trong `devices.json` cạnh `app.py` (dễ sao lưu/chỉnh sửa thủ công khi cần).
- URL webhook là bí mật: ai có link có thể kích hoạt. Không commit/chia sẻ `devices.json` hay URL công khai.
- Máy chạy server phải truy cập được URL webhook của MacroDroid.

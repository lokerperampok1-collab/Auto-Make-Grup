import asyncio
import shutil
import threading
import uuid
import webbrowser
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Dict, List, Optional

import uvicorn
from fastapi import FastAPI, File, HTTPException, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from config import AUTO_OPEN_BROWSER, HOST, PHOTOS_DIR, PORT, STATIC_DIR
from group_creator import (
    ClearHistoryConfig,
    GroupCreationConfig,
    ParallelGroupCreator,
    get_available_photos,
)
from telegram_manager import TelegramAccountManager


class WebSocketHub:
    def __init__(self) -> None:
        self.connections: List[WebSocket] = []

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        self.connections.append(ws)

    def disconnect(self, ws: WebSocket) -> None:
        if ws in self.connections:
            self.connections.remove(ws)

    async def broadcast(self, payload: Dict[str, Any]) -> None:
        stale: List[WebSocket] = []
        for ws in list(self.connections):
            try:
                await ws.send_json(payload)
            except Exception:
                stale.append(ws)
        for ws in stale:
            self.disconnect(ws)


ws_hub = WebSocketHub()
account_manager = TelegramAccountManager()
group_creator = ParallelGroupCreator(account_manager, ws_hub.broadcast)


@asynccontextmanager
async def lifespan(app: FastAPI):
    if AUTO_OPEN_BROWSER:
        def _open():
            webbrowser.open(f"http://localhost:{PORT}")
        threading.Timer(1.0, _open).start()
    yield


app = FastAPI(
    title="Telegram Auto-Make-Grup Dashboard",
    version="1.1.0",
    lifespan=lifespan,
)

app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
app.mount("/photos", StaticFiles(directory=str(PHOTOS_DIR)), name="photos")


class QR2FARequest(BaseModel):
    login_id: str
    password: str


class PhoneStartRequest(BaseModel):
    phone: str


class PhoneVerifyRequest(BaseModel):
    login_id: str
    code: Optional[str] = None
    password: Optional[str] = None


class SyncGroupsRequest(BaseModel):
    account_ids: Optional[List[str]] = None


@app.get("/")
async def index():
    return FileResponse(str(STATIC_DIR / "index.html"))


# ==================== ACCOUNTS & AUTHENTICATION ====================

@app.get("/api/accounts")
async def list_accounts():
    return {"accounts": account_manager.list_accounts()}


@app.post("/api/accounts/{account_id}/refresh")
async def refresh_account(account_id: str):
    try:
        acc = await account_manager.refresh_account_status(account_id)
        return {"account": acc}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/api/accounts/{account_id}/mutuals")
async def get_account_mutuals(account_id: str):
    try:
        mutuals = await account_manager.get_mutual_contacts(account_id)
        return {"account_id": account_id, "mutuals": mutuals, "count": len(mutuals)}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.delete("/api/accounts/{account_id}")
async def delete_account(account_id: str):
    removed = await account_manager.remove_account(account_id)
    if not removed:
        raise HTTPException(status_code=404, detail="Akun tidak ditemukan")
    return {"ok": True}


@app.post("/api/auth/qr/start")
async def start_qr_login():
    try:
        return await account_manager.start_qr_login()
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/api/auth/qr/status/{login_id}")
async def get_qr_status(login_id: str):
    return account_manager.get_qr_status(login_id)


@app.post("/api/auth/qr/2fa")
async def submit_qr_2fa(req: QR2FARequest):
    try:
        return await account_manager.submit_qr_2fa(req.login_id, req.password)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/auth/qr/cancel/{login_id}")
async def cancel_qr_login(login_id: str):
    await account_manager.cancel_qr_login(login_id)
    return {"ok": True}


@app.post("/api/auth/phone/send-code")
async def start_phone_login(req: PhoneStartRequest):
    try:
        return await account_manager.start_phone_login(req.phone)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/auth/phone/verify")
async def verify_phone_login(req: PhoneVerifyRequest):
    try:
        return await account_manager.verify_phone_login(
            req.login_id, req.code, req.password
        )
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


# ==================== GROUP PHOTOS POOL ====================

@app.get("/api/photos")
async def list_photos():
    files = get_available_photos()
    return {
        "photos": [
            {
                "name": f.name,
                "url": f"/photos/{f.name}",
                "size_kb": round(f.stat().st_size / 1024, 1),
            }
            for f in sorted(files, key=lambda x: x.stat().st_mtime, reverse=True)
        ]
    }


@app.post("/api/photos/upload")
async def upload_photos(files: List[UploadFile] = File(...)):
    allowed_exts = {".jpg", ".jpeg", ".png", ".webp"}
    saved: List[str] = []
    for file in files:
        ext = Path(file.filename or "").suffix.lower()
        if ext not in allowed_exts:
            continue
        safe_name = f"photo_{uuid.uuid4().hex[:8]}{ext}"
        dest = PHOTOS_DIR / safe_name
        with dest.open("wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
        saved.append(safe_name)
    return {"uploaded": saved, "count": len(saved)}


@app.delete("/api/photos/{filename}")
async def delete_photo(filename: str):
    target = (PHOTOS_DIR / filename).resolve()
    if target.parent != PHOTOS_DIR.resolve() or not target.exists():
        raise HTTPException(status_code=404, detail="File foto tidak ditemukan")
    target.unlink()
    return {"ok": True}


@app.delete("/api/photos")
async def clear_all_photos():
    for f in get_available_photos():
        try:
            f.unlink()
        except Exception:
            pass
    return {"ok": True}


# ==================== PARALLEL GROUP CREATION TASKS ====================

@app.get("/api/tasks/status")
async def get_task_status():
    return {
        **group_creator.get_status(),
        "logs": group_creator.logs[-200:],
    }


@app.post("/api/tasks/start")
async def start_group_creation(config: GroupCreationConfig):
    try:
        await group_creator.start_batch(config)
        return {"ok": True, "status": group_creator.get_status()}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/tasks/stop")
async def stop_group_creation():
    await group_creator.stop_batch()
    return {"ok": True}


# ==================== CLEAR GROUP CHAT HISTORY (FOR ALL MEMBERS) ====================

@app.get("/api/groups")
async def list_created_groups():
    return {"groups": group_creator.created_groups}


@app.post("/api/groups/sync")
async def sync_creator_groups(req: SyncGroupsRequest):
    try:
        groups = await group_creator.sync_creator_groups_from_telegram(
            req.account_ids
        )
        return {"ok": True, "groups": groups, "count": len(groups)}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.delete("/api/groups/{group_key}")
async def remove_saved_group(group_key: str):
    removed = await group_creator.remove_group_record(group_key)
    if not removed:
        raise HTTPException(status_code=404, detail="Data grup tidak ditemukan")
    return {"ok": True}


@app.post("/api/groups/clear-history/start")
async def start_clear_group_history(config: ClearHistoryConfig):
    try:
        await group_creator.start_clear_history_batch(config)
        return {"ok": True, "status": group_creator.get_status()}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/groups/clear-history/stop")
async def stop_clear_group_history():
    await group_creator.stop_clear_history_batch()
    return {"ok": True}


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await ws_hub.connect(ws)
    try:
        await ws.send_json(
            {
                "type": "init",
                "data": {
                    **group_creator.get_status(),
                    "logs": group_creator.logs[-150:],
                },
            }
        )
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        ws_hub.disconnect(ws)
    except Exception:
        ws_hub.disconnect(ws)


if __name__ == "__main__":
    print(f"============================================================")
    print(f" 🚀 Telegram Auto-Make-Grup Web Dashboard")
    print(f" 🌐 URL: http://localhost:{PORT}")
    print(f"============================================================")
    uvicorn.run(app, host=HOST, port=PORT, log_level="info")

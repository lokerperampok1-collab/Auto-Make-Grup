import asyncio
import base64
import io
import json
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import qrcode
from telethon import TelegramClient, errors, functions

from config import (
    ACCOUNTS_FILE,
    API_HASH,
    API_ID,
    APP_VERSION,
    DEVICE_MODEL,
    LANG_CODE,
    SESSIONS_DIR,
    SYSTEM_LANG_CODE,
    SYSTEM_VERSION,
)


def make_qr_base64(url: str) -> str:
    """Convert QR login URL (tg://login?token=...) into a base64 PNG data URI."""
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=8,
        border=2,
    )
    qr.add_data(url)
    qr.make(fit=True)
    img = qr.make_image(fill_color="#0f172a", back_color="#ffffff")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    b64 = base64.b64encode(buf.getvalue()).decode("ascii")
    return f"data:image/png;base64,{b64}"


class TelegramAccountManager:
    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self.accounts: Dict[str, Dict[str, Any]] = {}
        self.clients: Dict[str, TelegramClient] = {}
        self.client_locks: Dict[str, asyncio.Lock] = {}
        self.qr_sessions: Dict[str, Dict[str, Any]] = {}
        self.phone_sessions: Dict[str, Dict[str, Any]] = {}
        self._load_accounts()

    def _load_accounts(self) -> None:
        if ACCOUNTS_FILE.exists():
            try:
                data = json.loads(ACCOUNTS_FILE.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    self.accounts = data
            except Exception:
                self.accounts = {}
        else:
            self.accounts = {}

    def _save_accounts(self) -> None:
        ACCOUNTS_FILE.write_text(
            json.dumps(self.accounts, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    def _create_client(self, session_name: str) -> TelegramClient:
        session_path = str(SESSIONS_DIR / session_name)
        return TelegramClient(
            session_path,
            API_ID,
            API_HASH,
            device_model=DEVICE_MODEL,
            system_version=SYSTEM_VERSION,
            app_version=APP_VERSION,
            lang_code=LANG_CODE,
            system_lang_code=SYSTEM_LANG_CODE,
        )

    def get_account_lock(self, account_id: str) -> asyncio.Lock:
        if account_id not in self.client_locks:
            self.client_locks[account_id] = asyncio.Lock()
        return self.client_locks[account_id]

    async def get_client(self, account_id: str) -> TelegramClient:
        acc = self.accounts.get(account_id)
        if not acc:
            raise ValueError(f"Akun {account_id} tidak ditemukan")

        client = self.clients.get(account_id)
        if client is None:
            client = self._create_client(acc["session_name"])
            self.clients[account_id] = client

        if not client.is_connected():
            await client.connect()

        if not await client.is_user_authorized():
            raise RuntimeError(
                f"Sesi akun {acc.get('phone') or acc.get('first_name') or account_id} sudah tidak aktif / logout."
            )
        return client

    async def register_authorized_client(
        self, client: TelegramClient, session_name: str
    ) -> Dict[str, Any]:
        me = await client.get_me()
        if me is None:
            raise RuntimeError("Gagal mengambil profil akun setelah login.")

        account_id = f"acc_{me.id}"
        async with self._lock:
            existing = self.accounts.get(account_id)
            old_session_name = existing.get("session_name") if existing else None

            full_name = " ".join(
                filter(None, [getattr(me, "first_name", ""), getattr(me, "last_name", "")])
            ).strip()
            record = {
                "id": account_id,
                "user_id": me.id,
                "session_name": session_name,
                "phone": f"+{me.phone}" if getattr(me, "phone", None) else "",
                "first_name": getattr(me, "first_name", "") or "",
                "last_name": getattr(me, "last_name", "") or "",
                "full_name": full_name or f"User {me.id}",
                "username": getattr(me, "username", "") or "",
                "enabled": True,
                "status": "online",
                "added_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            }
            self.accounts[account_id] = record
            self.clients[account_id] = client
            self._save_accounts()

            if old_session_name and old_session_name != session_name:
                old_file = SESSIONS_DIR / f"{old_session_name}.session"
                try:
                    if old_file.exists():
                        old_file.unlink()
                except Exception:
                    pass

        return record

    def list_accounts(self) -> List[Dict[str, Any]]:
        return list(self.accounts.values())

    async def refresh_account_status(self, account_id: str) -> Dict[str, Any]:
        acc = self.accounts.get(account_id)
        if not acc:
            raise ValueError("Akun tidak ditemukan")

        lock = self.get_account_lock(account_id)
        async with lock:
            try:
                client = await self.get_client(account_id)
                me = await client.get_me()
                full_name = " ".join(
                    filter(None, [getattr(me, "first_name", ""), getattr(me, "last_name", "")])
                ).strip()
                acc["first_name"] = getattr(me, "first_name", "") or ""
                acc["last_name"] = getattr(me, "last_name", "") or ""
                acc["full_name"] = full_name or f"User {me.id}"
                acc["username"] = getattr(me, "username", "") or ""
                acc["phone"] = f"+{me.phone}" if getattr(me, "phone", None) else acc.get("phone", "")
                acc["status"] = "online"
            except Exception as e:
                acc["status"] = "offline"
                acc["last_error"] = str(e)
            self._save_accounts()
            return acc

    async def get_mutual_contacts(self, account_id: str) -> List[Dict[str, Any]]:
        """Ambil daftar seluruh kontak mutual (mutual_contact == True) dari akun."""
        lock = self.get_account_lock(account_id)
        async with lock:
            client = await self.get_client(account_id)
            res = await client(functions.contacts.GetContactsRequest(hash=0))
            users = getattr(res, "users", []) or []
            mutuals: List[Dict[str, Any]] = []
            for u in users:
                if getattr(u, "bot", False) or getattr(u, "deleted", False) or getattr(u, "is_self", False):
                    continue
                if getattr(u, "mutual_contact", False):
                    full_name = " ".join(
                        filter(None, [getattr(u, "first_name", ""), getattr(u, "last_name", "")])
                    ).strip()
                    mutuals.append(
                        {
                            "id": u.id,
                            "access_hash": getattr(u, "access_hash", 0),
                            "first_name": getattr(u, "first_name", "") or "",
                            "last_name": getattr(u, "last_name", "") or "",
                            "full_name": full_name or f"User {u.id}",
                            "username": getattr(u, "username", "") or "",
                            "phone": f"+{u.phone}" if getattr(u, "phone", None) else "",
                        }
                    )
            return mutuals

    async def remove_account(self, account_id: str) -> bool:
        async with self._lock:
            acc = self.accounts.pop(account_id, None)
            if not acc:
                return False
            self._save_accounts()

        client = self.clients.pop(account_id, None)
        if client:
            try:
                await client.disconnect()
            except Exception:
                pass

        session_file = SESSIONS_DIR / f"{acc['session_name']}.session"
        try:
            if session_file.exists():
                session_file.unlink()
        except Exception:
            pass
        return True

    # ==================== QR CODE LOGIN FLOW ====================

    async def start_qr_login(self) -> Dict[str, Any]:
        login_id = uuid.uuid4().hex[:12]
        session_name = f"tg_{int(time.time())}_{login_id[:6]}"
        client = self._create_client(session_name)
        await client.connect()

        if await client.is_user_authorized():
            account = await self.register_authorized_client(client, session_name)
            return {
                "login_id": login_id,
                "status": "authorized",
                "account": account,
            }

        qr_login = await client.qr_login()
        qr_image = make_qr_base64(qr_login.url)

        session_info: Dict[str, Any] = {
            "login_id": login_id,
            "session_name": session_name,
            "client": client,
            "qr_login": qr_login,
            "qr_image": qr_image,
            "status": "waiting_scan",
            "account": None,
            "error": None,
            "created_at": time.time(),
            "task": None,
        }
        self.qr_sessions[login_id] = session_info
        session_info["task"] = asyncio.create_task(self._watch_qr_login(login_id))

        return {
            "login_id": login_id,
            "status": "waiting_scan",
            "qr_image": qr_image,
        }

    async def _watch_qr_login(self, login_id: str) -> None:
        info = self.qr_sessions.get(login_id)
        if not info:
            return
        client: TelegramClient = info["client"]
        qr_login = info["qr_login"]

        max_attempts = 15  # ~6 minutes of auto-refreshing QR
        attempt = 0
        while attempt < max_attempts and info.get("status") == "waiting_scan":
            attempt += 1
            try:
                await qr_login.wait(timeout=25)
                # Scan succeeded without 2FA
                account = await self.register_authorized_client(
                    client, info["session_name"]
                )
                info["account"] = account
                info["status"] = "authorized"
                return
            except asyncio.TimeoutError:
                # Recreate QR token before expiry
                if info.get("status") != "waiting_scan":
                    return
                try:
                    await qr_login.recreate()
                    info["qr_image"] = make_qr_base64(qr_login.url)
                except errors.SessionPasswordNeededError:
                    info["status"] = "need_2fa"
                    return
                except Exception as e:
                    info["status"] = "error"
                    info["error"] = f"Gagal memperbarui QR Code: {e}"
                    return
            except errors.SessionPasswordNeededError:
                info["status"] = "need_2fa"
                return
            except asyncio.CancelledError:
                return
            except Exception as e:
                info["status"] = "error"
                info["error"] = str(e)
                return

        if info.get("status") == "waiting_scan":
            info["status"] = "expired"
            info["error"] = "Sesi QR Code telah kedaluwarsa. Silakan buat QR baru."
            await self._cleanup_failed_session(client, info["session_name"])

    def get_qr_status(self, login_id: str) -> Dict[str, Any]:
        info = self.qr_sessions.get(login_id)
        if not info:
            return {"status": "not_found", "error": "Sesi QR tidak ditemukan."}
        return {
            "login_id": login_id,
            "status": info["status"],
            "qr_image": info.get("qr_image"),
            "account": info.get("account"),
            "error": info.get("error"),
        }

    async def submit_qr_2fa(self, login_id: str, password: str) -> Dict[str, Any]:
        info = self.qr_sessions.get(login_id)
        if not info:
            raise ValueError("Sesi QR tidak ditemukan.")
        if info["status"] != "need_2fa":
            raise ValueError(f"Sesi tidak dalam status menunggu 2FA (status: {info['status']}).")

        client: TelegramClient = info["client"]
        try:
            await client.sign_in(password=password)
            account = await self.register_authorized_client(client, info["session_name"])
            info["account"] = account
            info["status"] = "authorized"
            return {"status": "authorized", "account": account}
        except errors.PasswordHashInvalidError:
            raise ValueError("Password 2FA salah, silakan coba lagi.")
        except Exception as e:
            raise ValueError(f"Gagal verifikasi 2FA: {e}")

    async def cancel_qr_login(self, login_id: str) -> None:
        info = self.qr_sessions.pop(login_id, None)
        if not info:
            return
        task = info.get("task")
        if task and not task.done():
            task.cancel()
        if info.get("status") != "authorized":
            await self._cleanup_failed_session(info["client"], info["session_name"])

    # ==================== PHONE + OTP LOGIN FLOW ====================

    async def start_phone_login(self, phone: str) -> Dict[str, Any]:
        clean_phone = phone.strip()
        if not clean_phone.startswith("+"):
            clean_phone = "+" + clean_phone

        login_id = uuid.uuid4().hex[:12]
        session_name = f"tg_{int(time.time())}_{login_id[:6]}"
        client = self._create_client(session_name)
        await client.connect()

        try:
            sent = await client.send_code_request(clean_phone)
            self.phone_sessions[login_id] = {
                "login_id": login_id,
                "phone": clean_phone,
                "session_name": session_name,
                "client": client,
                "phone_code_hash": sent.phone_code_hash,
                "status": "waiting_code",
            }
            return {
                "login_id": login_id,
                "phone": clean_phone,
                "status": "waiting_code",
            }
        except Exception as e:
            await self._cleanup_failed_session(client, session_name)
            raise ValueError(f"Gagal mengirim OTP ke {clean_phone}: {e}")

    async def verify_phone_login(
        self, login_id: str, code: Optional[str] = None, password: Optional[str] = None
    ) -> Dict[str, Any]:
        info = self.phone_sessions.get(login_id)
        if not info:
            raise ValueError("Sesi login nomor HP tidak ditemukan.")

        client: TelegramClient = info["client"]
        try:
            if info["status"] == "waiting_code":
                if not code:
                    raise ValueError("Kode OTP wajib diisi.")
                try:
                    await client.sign_in(
                        phone=info["phone"],
                        code=code.strip(),
                        phone_code_hash=info["phone_code_hash"],
                    )
                except errors.SessionPasswordNeededError:
                    info["status"] = "need_2fa"
                    if not password:
                        return {"login_id": login_id, "status": "need_2fa"}
                    await client.sign_in(password=password)
            elif info["status"] == "need_2fa":
                if not password:
                    raise ValueError("Password 2FA wajib diisi.")
                await client.sign_in(password=password)

            account = await self.register_authorized_client(client, info["session_name"])
            self.phone_sessions.pop(login_id, None)
            return {"status": "authorized", "account": account}
        except errors.PhoneCodeInvalidError:
            raise ValueError("Kode OTP tidak valid.")
        except errors.PasswordHashInvalidError:
            raise ValueError("Password 2FA salah.")
        except Exception as e:
            raise ValueError(f"Gagal verifikasi login: {e}")

    async def _cleanup_failed_session(
        self, client: TelegramClient, session_name: str
    ) -> None:
        try:
            await client.disconnect()
        except Exception:
            pass
        session_file = SESSIONS_DIR / f"{session_name}.session"
        try:
            if session_file.exists():
                session_file.unlink()
        except Exception:
            pass

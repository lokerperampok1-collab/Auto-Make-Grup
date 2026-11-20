import asyncio
import json
import random
from datetime import datetime
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, List, Optional

from pydantic import BaseModel, Field
from telethon import TelegramClient, errors, functions, types

from config import CREATED_GROUPS_FILE, PHOTOS_DIR
from telegram_manager import TelegramAccountManager


class JoinHiderPermissions(BaseModel):
    delete_messages: bool = True
    ban_users: bool = False
    invite_users: bool = False
    pin_messages: bool = False
    manage_call: bool = False
    other: bool = True


class GroupCreationConfig(BaseModel):
    account_ids: List[str] = Field(default_factory=list)
    groups_per_account: int = Field(default=1, ge=1, le=500)
    delay_seconds: float = Field(default=3.0, ge=0.0, le=3600.0)

    # Pilihan Grup: "megagroup" (Supergroup/Megagroup) atau "basic" (Basic Group)
    group_type: str = "megagroup"
    # Opsi visibilitas untuk Supergroup/Megagroup: "visible" (Terlihat) atau "hidden" (Tersembunyi)
    visibility: str = "visible"
    # Deskripsi grup (opsional)
    group_about: str = ""

    # Opsi perizinan: "all" (Semua) atau "invite_only" (Hanya Tambah Anggota)
    permission_mode: str = "all"

    # Opsi penamaan grup:
    # - "sequence": Nama Dasar | 1, Nama Dasar | 2, dst.
    # - "single": 1 Nama untuk Semua
    # - "random": Beberapa Nama untuk dipilih secara acak oleh sistem
    naming_mode: str = "sequence"
    base_name: str = "Grup Baru"
    sequence_start: int = 1
    sequence_scope: str = "global"  # "global" atau "per_account"
    sequence_separator: str = " | "
    random_names: List[str] = Field(default_factory=list)
    random_with_sequence: bool = False

    # Foto grup acak dari galeri upload
    use_random_photo: bool = True

    # Otomatis undang @joinhiderrobot sebagai admin
    invite_joinhider: bool = True
    joinhider_username: str = "@joinhiderrobot"
    joinhider_permissions: JoinHiderPermissions = Field(
        default_factory=JoinHiderPermissions
    )

    # Otomatis undang kontak mutual & jadikan admin penuh kecuali tetap anonim
    invite_mutual_contacts: bool = True
    promote_mutual_to_admin: bool = True
    # Opsional: filter ID kontak mutual tertentu per akun; jika kosong = semua kontak mutual
    selected_mutual_ids_by_account: Dict[str, List[int]] = Field(default_factory=dict)


class ClearHistoryConfig(BaseModel):
    # Daftar group_key ("acc_xxx_123456") yang akan dihapus riwayat chatnya
    group_keys: List[str] = Field(default_factory=list)
    delay_seconds: float = Field(default=1.0, ge=0.0, le=600.0)


def build_member_banned_rights(permission_mode: str) -> types.ChatBannedRights:
    """
    Buat objek ChatBannedRights untuk perizinan anggota grup.
    Di Telethon/MTProto: True = DIBATASI (dilarang), False = DIIZINKAN.
    """
    if permission_mode == "invite_only":
        # Hanya Tambah Anggota: invite_users=False (diizinkan), semua yang lain True (dibatasi)
        return types.ChatBannedRights(
            until_date=0,
            view_messages=False,
            send_messages=True,
            send_media=True,
            send_stickers=True,
            send_gifs=True,
            send_games=True,
            send_inline=True,
            embed_links=True,
            send_polls=True,
            change_info=True,
            invite_users=False,  # Hanya Tambah Anggota DIIZINKAN
            pin_messages=True,
            manage_topics=True,
            send_photos=True,
            send_videos=True,
            send_roundvideos=True,
            send_audios=True,
            send_voices=True,
            send_docs=True,
            send_plain=True,
        )

    # Default "all": Semua perizinan anggota dibuka
    return types.ChatBannedRights(
        until_date=0,
        view_messages=False,
        send_messages=False,
        send_media=False,
        send_stickers=False,
        send_gifs=False,
        send_games=False,
        send_inline=False,
        embed_links=False,
        send_polls=False,
        change_info=False,
        invite_users=False,
        pin_messages=False,
        manage_topics=False,
        send_photos=False,
        send_videos=False,
        send_roundvideos=False,
        send_audios=False,
        send_voices=False,
        send_docs=False,
        send_plain=False,
    )


def build_joinhider_admin_rights(perms: JoinHiderPermissions) -> types.ChatAdminRights:
    """
    Perizinan admin untuk @joinhiderrobot:
    Hanya hapus chat (delete_messages) dan perizinan pendukung yang diperlukan Join Hider.
    """
    return types.ChatAdminRights(
        change_info=False,
        post_messages=False,
        edit_messages=False,
        delete_messages=perms.delete_messages,
        ban_users=perms.ban_users,
        invite_users=perms.invite_users,
        pin_messages=perms.pin_messages,
        add_admins=False,
        anonymous=False,
        manage_call=perms.manage_call,
        other=perms.other,
        manage_topics=False,
    )


def build_mutual_full_admin_rights() -> types.ChatAdminRights:
    """
    Perizinan admin untuk Kontak Mutual:
    Semua perizinan AKTIF kecuali Tetap Anonim (anonymous=False).
    """
    return types.ChatAdminRights(
        change_info=True,
        post_messages=True,
        edit_messages=True,
        delete_messages=True,
        ban_users=True,
        invite_users=True,
        pin_messages=True,
        add_admins=True,
        anonymous=False,  # KECUALI tetap anonim!
        manage_call=True,
        other=True,
        manage_topics=True,
    )


def generate_group_title(
    config: GroupCreationConfig, sequence_number: int
) -> str:
    """Hasilkan nama grup berdasarkan mode penamaan yang dipilih."""
    sep = config.sequence_separator or " | "
    base = (config.base_name or "Grup Baru").strip()

    if config.naming_mode == "single":
        return base

    if config.naming_mode == "random":
        valid_names = [n.strip() for n in config.random_names if n.strip()]
        if not valid_names:
            valid_names = [
                line.strip() for line in base.splitlines() if line.strip()
            ] or ["Grup Baru"]
        chosen = random.choice(valid_names)
        if config.random_with_sequence:
            return f"{chosen}{sep}{sequence_number}"
        return chosen

    # Default: "sequence" -> Nama | 1, Nama | 2, dst.
    return f"{base}{sep}{sequence_number}"


def get_available_photos() -> List[Path]:
    allowed_exts = {".jpg", ".jpeg", ".png", ".webp"}
    if not PHOTOS_DIR.exists():
        return []
    return [
        p
        for p in PHOTOS_DIR.iterdir()
        if p.is_file() and p.suffix.lower() in allowed_exts
    ]


def extract_chat_from_result(result: Any) -> Any:
    """Ekstrak objek Chat/Channel dari response CreateChannelRequest / CreateChatRequest."""
    chats = getattr(result, "chats", None)
    if chats:
        return chats[0]
    updates = getattr(result, "updates", None)
    if updates and getattr(updates, "chats", None):
        return updates.chats[0]
    raise RuntimeError("Tidak dapat menemukan objek grup dari response Telegram.")


class ParallelGroupCreator:
    def __init__(
        self,
        account_manager: TelegramAccountManager,
        broadcast_cb: Callable[[Dict[str, Any]], Awaitable[None]],
    ) -> None:
        self.account_manager = account_manager
        self.broadcast_cb = broadcast_cb
        self.is_running: bool = False
        self.stop_event = asyncio.Event()
        self._task: Optional[asyncio.Task] = None
        self._seq_lock = asyncio.Lock()
        self._global_seq: int = 1
        self.account_progress: Dict[str, Dict[str, Any]] = {}
        self.created_groups: List[Dict[str, Any]] = []
        self.logs: List[Dict[str, Any]] = []

        # State untuk fitur Hapus Semua Riwayat Chat Grup
        self.is_clearing_history: bool = False
        self.clear_stop_event = asyncio.Event()
        self._clear_task: Optional[asyncio.Task] = None
        self.clear_progress: Dict[str, Dict[str, Any]] = {}
        self._groups_lock = asyncio.Lock()
        self._load_created_groups()

    def _load_created_groups(self) -> None:
        if CREATED_GROUPS_FILE.exists():
            try:
                data = json.loads(CREATED_GROUPS_FILE.read_text(encoding="utf-8"))
                if isinstance(data, list):
                    self.created_groups = data
            except Exception:
                self.created_groups = []
        else:
            self.created_groups = []

    def _save_created_groups(self) -> None:
        try:
            CREATED_GROUPS_FILE.write_text(
                json.dumps(self.created_groups, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
        except Exception:
            pass

    async def upsert_group_record(self, record: Dict[str, Any]) -> None:
        async with self._groups_lock:
            gkey = record["group_key"]
            replaced = False
            for idx, existing in enumerate(self.created_groups):
                if existing.get("group_key") == gkey:
                    # Pertahankan info lama jika ada
                    if "last_cleared_at" in existing and "last_cleared_at" not in record:
                        record["last_cleared_at"] = existing["last_cleared_at"]
                    if "last_deleted_count" in existing and "last_deleted_count" not in record:
                        record["last_deleted_count"] = existing["last_deleted_count"]
                    self.created_groups[idx] = {**existing, **record}
                    replaced = True
                    break
            if not replaced:
                self.created_groups.append(record)
            self._save_created_groups()

    async def remove_group_record(self, group_key: str) -> bool:
        async with self._groups_lock:
            before = len(self.created_groups)
            self.created_groups = [
                g for g in self.created_groups if g.get("group_key") != group_key
            ]
            after = len(self.created_groups)
            if after != before:
                self._save_created_groups()
                return True
            return False

    async def emit_log(
        self,
        level: str,
        message: str,
        account_id: Optional[str] = None,
        account_label: Optional[str] = None,
    ) -> None:
        entry = {
            "timestamp": datetime.now().strftime("%H:%M:%S"),
            "level": level,
            "account_id": account_id or "SYSTEM",
            "account_label": account_label or "SISTEM",
            "message": message,
        }
        self.logs.append(entry)
        if len(self.logs) > 600:
            self.logs = self.logs[-600:]
        await self.broadcast_cb({"type": "log", "data": entry})

    async def emit_state(self) -> None:
        await self.broadcast_cb(
            {
                "type": "state",
                "data": self.get_status(),
            }
        )

    def get_status(self) -> Dict[str, Any]:
        return {
            "is_running": self.is_running,
            "account_progress": self.account_progress,
            "created_groups": self.created_groups,
            "total_created": len(self.created_groups),
            "is_clearing_history": self.is_clearing_history,
            "clear_progress": self.clear_progress,
        }

    async def _next_sequence_number(
        self, config: GroupCreationConfig, local_counter: int
    ) -> int:
        if config.sequence_scope == "per_account":
            return config.sequence_start + local_counter
        async with self._seq_lock:
            val = self._global_seq
            self._global_seq += 1
            return val

    async def _exec_with_floodwait(
        self,
        account_id: str,
        account_label: str,
        step_name: str,
        coro_factory: Callable[[], Awaitable[Any]],
        stop_event: Optional[asyncio.Event] = None,
        progress_dict: Optional[Dict[str, Dict[str, Any]]] = None,
    ) -> Any:
        """
        Jalankan request Telethon. Jika terkena FloodWaitError, otomatis menunggu
        hitung mundur hingga selesai dan retry terus sampai berhasil.
        """
        active_stop = stop_event if stop_event is not None else self.stop_event
        active_prog_map = (
            progress_dict if progress_dict is not None else self.account_progress
        )

        while not active_stop.is_set():
            try:
                return await coro_factory()
            except (errors.FloodWaitError, errors.SlowModeWaitError) as e:
                wait_sec = int(getattr(e, "seconds", 30)) + 2
                await self.emit_log(
                    "warning",
                    f"⏳ Terkena FloodWait {e.seconds} detik saat [{step_name}]. Menunggu {wait_sec} detik lalu otomatis retry hingga berhasil...",
                    account_id,
                    account_label,
                )
                prog = active_prog_map.get(account_id)
                if prog:
                    prog["status"] = "floodwait"
                    prog["floodwait_seconds"] = wait_sec
                    prog["current_step"] = f"FloodWait ({step_name})"
                    await self.emit_state()

                for remaining in range(wait_sec, 0, -1):
                    if active_stop.is_set():
                        raise asyncio.CancelledError("Dihentikan oleh pengguna saat FloodWait.")
                    if prog:
                        prog["floodwait_seconds"] = remaining
                        if remaining % 2 == 0 or remaining <= 5:
                            await self.emit_state()
                    await asyncio.sleep(1)

                if prog:
                    prog["status"] = "running"
                    prog["floodwait_seconds"] = 0
                    prog["current_step"] = f"Retry {step_name}"
                    await self.emit_state()

                await self.emit_log(
                    "info",
                    f"🔄 Waktu tunggu FloodWait selesai, mencoba ulang [{step_name}]...",
                    account_id,
                    account_label,
                )

        raise asyncio.CancelledError("Proses dihentikan oleh pengguna.")

    # ==================== FITUR 1: PEMBUATAN GRUP PARALEL ====================

    async def start_batch(self, config: GroupCreationConfig) -> None:
        if self.is_running:
            raise RuntimeError("Proses pembuatan grup sedang berjalan.")

        all_accounts = self.account_manager.list_accounts()
        if config.account_ids:
            selected = [a for a in all_accounts if a["id"] in config.account_ids]
        else:
            selected = [a for a in all_accounts if a.get("enabled", True)]

        if not selected:
            raise ValueError("Tidak ada akun Telegram yang dipilih atau aktif.")

        self.is_running = True
        self.stop_event.clear()
        self._global_seq = config.sequence_start
        self.account_progress = {}

        for acc in selected:
            label = acc.get("full_name") or acc.get("phone") or acc["id"]
            self.account_progress[acc["id"]] = {
                "account_id": acc["id"],
                "label": label,
                "phone": acc.get("phone", ""),
                "username": acc.get("username", ""),
                "target": config.groups_per_account,
                "completed": 0,
                "failed": 0,
                "status": "starting",
                "current_step": "Menyiapkan sesi...",
                "floodwait_seconds": 0,
            }

        await self.emit_state()
        self._task = asyncio.create_task(self._run_parallel(selected, config))

    async def stop_batch(self) -> None:
        if not self.is_running:
            return
        self.stop_event.set()
        await self.emit_log("warning", "🛑 Permintaan penghentian diterima. Menghentikan worker...")

    async def _run_parallel(
        self, accounts: List[Dict[str, Any]], config: GroupCreationConfig
    ) -> None:
        await self.emit_log(
            "info",
            f"🚀 Memulai pembuatan grup secara PARALEL menggunakan {len(accounts)} akun ({config.groups_per_account} grup/akun).",
        )
        try:
            workers = [
                self._account_worker(acc, config)
                for acc in accounts
            ]
            await asyncio.gather(*workers, return_exceptions=True)
        finally:
            self.is_running = False
            for prog in self.account_progress.values():
                if prog["status"] in ("running", "starting", "floodwait"):
                    prog["status"] = "stopped" if self.stop_event.is_set() else "completed"
                    prog["floodwait_seconds"] = 0
            await self.emit_state()
            await self.emit_log(
                "success",
                f"🏁 Eksekusi paralel selesai. Total grup tersimpan: {len(self.created_groups)}.",
            )

    async def _account_worker(
        self, acc: Dict[str, Any], config: GroupCreationConfig
    ) -> None:
        account_id = acc["id"]
        label = acc.get("full_name") or acc.get("phone") or account_id
        prog = self.account_progress[account_id]
        lock = self.account_manager.get_account_lock(account_id)

        async with lock:
            try:
                client = await self.account_manager.get_client(account_id)
            except Exception as e:
                prog["status"] = "error"
                prog["current_step"] = f"Gagal koneksi: {e}"
                await self.emit_log("error", f"❌ Gagal menghubungkan akun: {e}", account_id, label)
                await self.emit_state()
                return

            prog["status"] = "running"
            await self.emit_state()

            # Ambil kontak mutual terlebih dahulu jika fitur aktif
            mutual_entities: List[types.InputPeerUser] = []
            mutual_info_map: Dict[int, str] = {}
            if config.invite_mutual_contacts:
                prog["current_step"] = "Mengambil kontak mutual..."
                await self.emit_state()
                try:
                    res = await self._exec_with_floodwait(
                        account_id,
                        label,
                        "Ambil Kontak Mutual",
                        lambda: client(functions.contacts.GetContactsRequest(hash=0)),
                    )
                    allowed_ids = set(
                        config.selected_mutual_ids_by_account.get(account_id, [])
                    )
                    for u in getattr(res, "users", []) or []:
                        if (
                            getattr(u, "bot", False)
                            or getattr(u, "deleted", False)
                            or getattr(u, "is_self", False)
                        ):
                            continue
                        if getattr(u, "mutual_contact", False):
                            if allowed_ids and u.id not in allowed_ids:
                                continue
                            mutual_entities.append(
                                types.InputPeerUser(
                                    user_id=u.id,
                                    access_hash=getattr(u, "access_hash", 0),
                                )
                            )
                            name = " ".join(
                                filter(
                                    None,
                                    [
                                        getattr(u, "first_name", ""),
                                        getattr(u, "last_name", ""),
                                    ],
                                )
                            ).strip()
                            mutual_info_map[u.id] = (
                                f"{name} (@{u.username})" if getattr(u, "username", None) else (name or str(u.id))
                            )
                    await self.emit_log(
                        "info",
                        f"👥 Ditemukan {len(mutual_entities)} kontak mutual untuk diundang & dijadikan admin.",
                        account_id,
                        label,
                    )
                except asyncio.CancelledError:
                    return
                except Exception as e:
                    await self.emit_log(
                        "warning",
                        f"⚠️ Gagal memuat daftar kontak mutual: {e}",
                        account_id,
                        label,
                    )

            # Resolve @joinhiderrobot sekali di awal worker
            joinhider_entity: Any = None
            bot_uname = (config.joinhider_username or "@joinhiderrobot").strip()
            if not bot_uname.startswith("@"):
                bot_uname = "@" + bot_uname
            if config.invite_joinhider:
                prog["current_step"] = f"Mencari {bot_uname}..."
                await self.emit_state()
                try:
                    joinhider_entity = await self._exec_with_floodwait(
                        account_id,
                        label,
                        f"Resolve {bot_uname}",
                        lambda: client.get_input_entity(bot_uname),
                    )
                except asyncio.CancelledError:
                    return
                except Exception as e:
                    await self.emit_log(
                        "warning",
                        f"⚠️ Tidak dapat menemukan bot {bot_uname}: {e}",
                        account_id,
                        label,
                    )

            # Loop pembuatan grup untuk akun ini
            for idx in range(config.groups_per_account):
                if self.stop_event.is_set():
                    break

                seq_num = await self._next_sequence_number(config, idx)
                group_title = generate_group_title(config, seq_num)

                try:
                    await self._create_single_group(
                        client=client,
                        account_id=account_id,
                        label=label,
                        config=config,
                        group_title=group_title,
                        group_index=idx + 1,
                        joinhider_entity=joinhider_entity,
                        bot_uname=bot_uname,
                        mutual_entities=mutual_entities,
                        mutual_info_map=mutual_info_map,
                    )
                    prog["completed"] += 1
                    await self.emit_state()
                except asyncio.CancelledError:
                    break
                except Exception as e:
                    prog["failed"] += 1
                    await self.emit_log(
                        "error",
                        f"❌ Gagal membuat grup '{group_title}': {e}",
                        account_id,
                        label,
                    )
                    await self.emit_state()

                # Jeda antar pembuatan grup jika masih ada grup berikutnya
                if (
                    idx < config.groups_per_account - 1
                    and config.delay_seconds > 0
                    and not self.stop_event.is_set()
                ):
                    prog["current_step"] = f"Jeda {config.delay_seconds} detik..."
                    await self.emit_state()
                    await asyncio.sleep(config.delay_seconds)

            prog["status"] = "stopped" if self.stop_event.is_set() else "completed"
            prog["current_step"] = "Selesai"
            await self.emit_state()

    async def _create_single_group(
        self,
        client: TelegramClient,
        account_id: str,
        label: str,
        config: GroupCreationConfig,
        group_title: str,
        group_index: int,
        joinhider_entity: Any,
        bot_uname: str,
        mutual_entities: List[types.InputPeerUser],
        mutual_info_map: Dict[int, str],
    ) -> None:
        prog = self.account_progress[account_id]
        prog["current_step"] = f"Membuat grup '{group_title}' ({group_index}/{config.groups_per_account})"
        await self.emit_state()

        is_megagroup = config.group_type == "megagroup"

        # 1. Buat Grup (Supergroup/Megagroup atau Basic Group)
        if is_megagroup:
            created = await self._exec_with_floodwait(
                account_id,
                label,
                f"Buat Supergroup '{group_title}'",
                lambda: client(
                    functions.channels.CreateChannelRequest(
                        title=group_title,
                        about=config.group_about or "",
                        megagroup=True,
                    )
                ),
            )
            group_chat = extract_chat_from_result(created)
            group_id = group_chat.id
            await self.emit_log(
                "success",
                f"✅ Supergroup '{group_title}' berhasil dibuat (ID: {group_id}).",
                account_id,
                label,
            )

            # 2. Atur Visibilitas Riwayat Chat (Terlihat vs Tersembunyi) untuk Supergroup
            pre_history_hidden = config.visibility == "hidden"
            vis_label = "Tersembunyi (Hidden)" if pre_history_hidden else "Terlihat (Visible)"
            prog["current_step"] = f"[{group_title}] Mengatur visibilitas: {vis_label}"
            await self.emit_state()
            try:
                await self._exec_with_floodwait(
                    account_id,
                    label,
                    f"Atur Visibilitas ({vis_label})",
                    lambda: client(
                        functions.channels.TogglePreHistoryHiddenRequest(
                            channel=group_chat,
                            enabled=pre_history_hidden,
                        )
                    ),
                )
                await self.emit_log(
                    "info",
                    f"👁️ Visibilitas riwayat chat '{group_title}' diatur ke: {vis_label}.",
                    account_id,
                    label,
                )
            except errors.ChatNotModifiedError:
                await self.emit_log(
                    "info",
                    f"👁️ Visibilitas riwayat chat '{group_title}' sudah sesuai ({vis_label}).",
                    account_id,
                    label,
                )
            except Exception as e:
                await self.emit_log(
                    "warning",
                    f"⚠️ Gagal mengatur visibilitas '{group_title}': {e}",
                    account_id,
                    label,
                )
        else:
            # Basic Group (CreateChatRequest)
            initial_users: List[Any] = []
            if joinhider_entity is not None:
                initial_users.append(joinhider_entity)
            created = await self._exec_with_floodwait(
                account_id,
                label,
                f"Buat Basic Group '{group_title}'",
                lambda: client(
                    functions.messages.CreateChatRequest(
                        users=initial_users,
                        title=group_title,
                    )
                ),
            )
            group_chat = extract_chat_from_result(created)
            group_id = group_chat.id
            await self.emit_log(
                "success",
                f"✅ Basic Group '{group_title}' berhasil dibuat (ID: {group_id}).",
                account_id,
                label,
            )

        # 3. Pilih & Pasang Foto Grup Secara Acak (jika diaktifkan dan ada foto di galeri)
        chosen_photo_name: Optional[str] = None
        if config.use_random_photo:
            photos = get_available_photos()
            if photos:
                chosen_photo = random.choice(photos)
                chosen_photo_name = chosen_photo.name
                prog["current_step"] = f"[{group_title}] Memasang foto acak ({chosen_photo_name})"
                await self.emit_state()
                try:
                    uploaded_file = await self._exec_with_floodwait(
                        account_id,
                        label,
                        f"Upload Foto '{chosen_photo_name}'",
                        lambda: client.upload_file(str(chosen_photo)),
                    )
                    input_photo = types.InputChatUploadedPhoto(file=uploaded_file)
                    if is_megagroup:
                        await self._exec_with_floodwait(
                            account_id,
                            label,
                            f"Pasang Foto Grup '{group_title}'",
                            lambda: client(
                                functions.channels.EditPhotoRequest(
                                    channel=group_chat,
                                    photo=input_photo,
                                )
                            ),
                        )
                    else:
                        await self._exec_with_floodwait(
                            account_id,
                            label,
                            f"Pasang Foto Grup '{group_title}'",
                            lambda: client(
                                functions.messages.EditChatPhotoRequest(
                                    chat_id=group_id,
                                    photo=input_photo,
                                )
                            ),
                        )
                    await self.emit_log(
                        "info",
                        f"🖼️ Foto profil '{chosen_photo_name}' (acak) berhasil dipasang ke '{group_title}'.",
                        account_id,
                        label,
                    )
                except Exception as e:
                    await self.emit_log(
                        "warning",
                        f"⚠️ Gagal memasang foto '{chosen_photo_name}' ke '{group_title}': {e}",
                        account_id,
                        label,
                    )

        # 4. Atur Perizinan Anggota (Semua vs Hanya Tambah Anggota)
        perm_label = (
            "Hanya Tambah Anggota"
            if config.permission_mode == "invite_only"
            else "Semua Perizinan"
        )
        prog["current_step"] = f"[{group_title}] Mengatur perizinan: {perm_label}"
        await self.emit_state()
        banned_rights = build_member_banned_rights(config.permission_mode)
        try:
            await self._exec_with_floodwait(
                account_id,
                label,
                f"Atur Perizinan ({perm_label})",
                lambda: client(
                    functions.messages.EditChatDefaultBannedRightsRequest(
                        peer=group_chat,
                        banned_rights=banned_rights,
                    )
                ),
            )
            await self.emit_log(
                "info",
                f"🔒 Perizinan anggota '{group_title}' diatur ke: {perm_label}.",
                account_id,
                label,
            )
        except errors.ChatNotModifiedError:
            await self.emit_log(
                "info",
                f"🔒 Perizinan anggota '{group_title}' sudah sesuai ({perm_label}).",
                account_id,
                label,
            )
        except Exception as e:
            await self.emit_log(
                "warning",
                f"⚠️ Gagal mengatur perizinan '{group_title}': {e}",
                account_id,
                label,
            )

        # 5. Otomatis Undang @joinhiderrobot & Jadikan Admin (Hanya Hapus Chat + Izin Pendukung)
        if config.invite_joinhider and joinhider_entity is not None:
            prog["current_step"] = f"[{group_title}] Mengundang & set admin {bot_uname}"
            await self.emit_state()
            try:
                if is_megagroup:
                    await self._exec_with_floodwait(
                        account_id,
                        label,
                        f"Undang {bot_uname}",
                        lambda: client(
                            functions.channels.InviteToChannelRequest(
                                channel=group_chat,
                                users=[joinhider_entity],
                            )
                        ),
                    )
                    bot_rights = build_joinhider_admin_rights(
                        config.joinhider_permissions
                    )
                    await self._exec_with_floodwait(
                        account_id,
                        label,
                        f"Set Admin {bot_uname}",
                        lambda: client(
                            functions.channels.EditAdminRequest(
                                channel=group_chat,
                                user_id=joinhider_entity,
                                admin_rights=bot_rights,
                                rank="Join Hider",
                            )
                        ),
                    )
                else:
                    await self._exec_with_floodwait(
                        account_id,
                        label,
                        f"Set Admin {bot_uname}",
                        lambda: client(
                            functions.messages.EditChatAdminRequest(
                                chat_id=group_id,
                                user_id=joinhider_entity,
                                is_admin=True,
                            )
                        ),
                    )
                await self.emit_log(
                    "success",
                    f"🤖 {bot_uname} berhasil diundang & dijadikan Admin (Hapus Chat) di '{group_title}'.",
                    account_id,
                    label,
                )
            except errors.UserAlreadyParticipantError:
                pass
            except Exception as e:
                await self.emit_log(
                    "warning",
                    f"⚠️ Gagal mengundang/mempromosikan {bot_uname} di '{group_title}': {e}",
                    account_id,
                    label,
                )

        # 6. Otomatis Undang Kontak Mutual & Jadikan Admin Penuh (Kecuali Tetap Anonim)
        invited_mutuals_count = 0
        promoted_mutuals_count = 0
        if config.invite_mutual_contacts and mutual_entities:
            mutual_admin_rights = build_mutual_full_admin_rights()
            for m_entity in mutual_entities:
                if self.stop_event.is_set():
                    break
                m_name = mutual_info_map.get(m_entity.user_id, str(m_entity.user_id))
                prog["current_step"] = f"[{group_title}] Mengundang kontak mutual: {m_name}"
                await self.emit_state()

                invited_ok = False
                try:
                    if is_megagroup:
                        await self._exec_with_floodwait(
                            account_id,
                            label,
                            f"Undang Mutual ({m_name})",
                            lambda m=m_entity: client(
                                functions.channels.InviteToChannelRequest(
                                    channel=group_chat,
                                    users=[m],
                                )
                            ),
                        )
                    else:
                        await self._exec_with_floodwait(
                            account_id,
                            label,
                            f"Undang Mutual ({m_name})",
                            lambda m=m_entity: client(
                                functions.messages.AddChatUserRequest(
                                    chat_id=group_id,
                                    user_id=m,
                                    fwd_limit=50,
                                )
                            ),
                        )
                    invited_ok = True
                    invited_mutuals_count += 1
                except errors.UserAlreadyParticipantError:
                    invited_ok = True
                except (
                    errors.UserPrivacyRestrictedError,
                    errors.UserNotMutualContactError,
                    errors.UserChannelsTooMuchError,
                ) as e:
                    await self.emit_log(
                        "warning",
                        f"⚠️ Kontak mutual {m_name} tidak dapat diundang ({type(e).__name__}).",
                        account_id,
                        label,
                    )
                except Exception as e:
                    await self.emit_log(
                        "warning",
                        f"⚠️ Gagal mengundang kontak mutual {m_name}: {e}",
                        account_id,
                        label,
                    )

                if invited_ok and config.promote_mutual_to_admin:
                    prog["current_step"] = f"[{group_title}] Jadikan Admin Penuh (Non-Anonim): {m_name}"
                    await self.emit_state()
                    try:
                        if is_megagroup:
                            await self._exec_with_floodwait(
                                account_id,
                                label,
                                f"Set Admin Penuh ({m_name})",
                                lambda m=m_entity: client(
                                    functions.channels.EditAdminRequest(
                                        channel=group_chat,
                                        user_id=m,
                                        admin_rights=mutual_admin_rights,
                                        rank="Admin",
                                    )
                                ),
                            )
                        else:
                            await self._exec_with_floodwait(
                                account_id,
                                label,
                                f"Set Admin ({m_name})",
                                lambda m=m_entity: client(
                                    functions.messages.EditChatAdminRequest(
                                        chat_id=group_id,
                                        user_id=m,
                                        is_admin=True,
                                    )
                                ),
                            )
                        promoted_mutuals_count += 1
                    except Exception as e:
                        await self.emit_log(
                            "warning",
                            f"⚠️ Gagal menjadikan kontak mutual {m_name} sebagai Admin: {e}",
                            account_id,
                            label,
                        )

            if invited_mutuals_count > 0:
                await self.emit_log(
                    "success",
                    f"👑 {invited_mutuals_count} kontak mutual diundang & {promoted_mutuals_count} dijadikan Admin Penuh (Non-Anonim) di '{group_title}'.",
                    account_id,
                    label,
                )

        # Catat & simpan persisten ke riwayat grup beserta akun pembuatnya
        record = {
            "group_key": f"{account_id}_{group_id}",
            "id": group_id,
            "access_hash": getattr(group_chat, "access_hash", 0) or 0,
            "title": group_title,
            "is_megagroup": is_megagroup,
            "type": "Supergroup" if is_megagroup else "Basic Group",
            "visibility": (
                "Tersembunyi"
                if (is_megagroup and config.visibility == "hidden")
                else ("Terlihat" if is_megagroup else "-")
            ),
            "permissions": perm_label,
            "photo": chosen_photo_name or "Tanpa Foto",
            "joinhider": config.invite_joinhider,
            "mutual_admins": promoted_mutuals_count,
            "account_id": account_id,
            "account_label": label,
            "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }
        await self.upsert_group_record(record)
        await self.broadcast_cb({"type": "group_created", "data": record})

    # ==================== FITUR 2: SINKRONISASI & HAPUS SEMUA RIWAYAT CHAT GRUP (UNTUK SEMUA MEMBER) ====================

    async def sync_creator_groups_from_telegram(
        self, account_ids: Optional[List[str]] = None
    ) -> List[Dict[str, Any]]:
        """
        Memindai dialog dari akun-akun pembuat grup untuk menemukan seluruh grup
        (Supergroup maupun Basic Group) di mana akun tersebut adalah Pembuat (Creator).
        """
        all_accounts = self.account_manager.list_accounts()
        if account_ids:
            targets = [a for a in all_accounts if a["id"] in account_ids]
        else:
            targets = all_accounts

        synced_count = 0
        for acc in targets:
            acc_id = acc["id"]
            label = acc.get("full_name") or acc.get("phone") or acc_id
            lock = self.account_manager.get_account_lock(acc_id)
            async with lock:
                try:
                    client = await self.account_manager.get_client(acc_id)
                    async for dialog in client.iter_dialogs():
                        entity = dialog.entity
                        is_mega = isinstance(entity, types.Channel) and bool(
                            getattr(entity, "megagroup", False)
                        )
                        is_basic = isinstance(entity, types.Chat) and not bool(
                            getattr(entity, "deactivated", False)
                        )
                        if not (is_mega or is_basic):
                            continue

                        # Ambil grup yang dibuat oleh akun ini (creator == True)
                        if not getattr(entity, "creator", False):
                            continue

                        record = {
                            "group_key": f"{acc_id}_{entity.id}",
                            "id": entity.id,
                            "access_hash": getattr(entity, "access_hash", 0) or 0,
                            "title": getattr(entity, "title", f"Grup {entity.id}"),
                            "is_megagroup": is_mega,
                            "type": "Supergroup" if is_mega else "Basic Group",
                            "visibility": "-",
                            "permissions": "-",
                            "photo": "-",
                            "joinhider": False,
                            "mutual_admins": 0,
                            "account_id": acc_id,
                            "account_label": label,
                            "created_at": (
                                dialog.date.strftime("%Y-%m-%d %H:%M:%S")
                                if getattr(dialog, "date", None)
                                else datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                            ),
                        }
                        await self.upsert_group_record(record)
                        synced_count += 1
                    await self.emit_log(
                        "info",
                        f"🔄 Sinkronisasi grup selesai untuk akun {label}.",
                        acc_id,
                        label,
                    )
                except Exception as e:
                    await self.emit_log(
                        "warning",
                        f"⚠️ Gagal sinkronisasi grup dari akun {label}: {e}",
                        acc_id,
                        label,
                    )

        await self.emit_state()
        return self.created_groups

    async def start_clear_history_batch(self, config: ClearHistoryConfig) -> None:
        if self.is_clearing_history:
            raise RuntimeError("Proses penghapusan riwayat chat sedang berjalan.")

        if config.group_keys:
            key_set = set(config.group_keys)
            selected_groups = [
                g for g in self.created_groups if g.get("group_key") in key_set
            ]
        else:
            selected_groups = list(self.created_groups)

        if not selected_groups:
            raise ValueError("Tidak ada grup yang dipilih untuk dihapus riwayat chatnya.")

        # Kelompokkan grup berdasarkan akun pembuatnya (account_id)
        groups_by_account: Dict[str, List[Dict[str, Any]]] = {}
        for g in selected_groups:
            acc_id = g.get("account_id")
            if not acc_id:
                continue
            groups_by_account.setdefault(acc_id, []).append(g)

        if not groups_by_account:
            raise ValueError("Grup yang dipilih tidak memiliki informasi akun pembuat.")

        self.is_clearing_history = True
        self.clear_stop_event.clear()
        self.clear_progress = {}

        accounts_map = {a["id"]: a for a in self.account_manager.list_accounts()}
        for acc_id, grp_list in groups_by_account.items():
            acc_obj = accounts_map.get(acc_id, {})
            label = (
                acc_obj.get("full_name")
                or acc_obj.get("phone")
                or grp_list[0].get("account_label")
                or acc_id
            )
            self.clear_progress[acc_id] = {
                "account_id": acc_id,
                "label": label,
                "target": len(grp_list),
                "completed": 0,
                "failed": 0,
                "deleted_messages": 0,
                "status": "starting",
                "current_step": "Menyiapkan sesi akun pembuat...",
                "floodwait_seconds": 0,
            }

        await self.emit_state()
        self._clear_task = asyncio.create_task(
            self._run_clear_history_parallel(groups_by_account, config)
        )

    async def stop_clear_history_batch(self) -> None:
        if not self.is_clearing_history:
            return
        self.clear_stop_event.set()
        await self.emit_log(
            "warning",
            "🛑 Permintaan penghentian hapus riwayat chat diterima...",
        )

    async def _run_clear_history_parallel(
        self,
        groups_by_account: Dict[str, List[Dict[str, Any]]],
        config: ClearHistoryConfig,
    ) -> None:
        total_groups = sum(len(v) for v in groups_by_account.values())
        await self.emit_log(
            "info",
            f"🧹 Memulai penghapusan SEMUA riwayat chat grup (untuk semua member) pada {total_groups} grup menggunakan {len(groups_by_account)} akun pembuat secara paralel.",
        )
        try:
            workers = [
                self._clear_history_account_worker(acc_id, grp_list, config)
                for acc_id, grp_list in groups_by_account.items()
            ]
            await asyncio.gather(*workers, return_exceptions=True)
        finally:
            self.is_clearing_history = False
            for prog in self.clear_progress.values():
                if prog["status"] in ("running", "starting", "floodwait"):
                    prog["status"] = (
                        "stopped" if self.clear_stop_event.is_set() else "completed"
                    )
                    prog["floodwait_seconds"] = 0
            await self.emit_state()
            await self.emit_log(
                "success",
                "🏁 Proses penghapusan riwayat chat grup untuk semua member selesai.",
            )

    async def _resolve_group_peer(
        self, client: TelegramClient, group_rec: Dict[str, Any]
    ) -> Any:
        group_id = int(group_rec["id"])
        is_mega = bool(group_rec.get("is_megagroup", True))
        access_hash = int(group_rec.get("access_hash", 0) or 0)

        if is_mega:
            if access_hash:
                return types.InputPeerChannel(
                    channel_id=group_id, access_hash=access_hash
                )
            try:
                return await client.get_input_entity(types.PeerChannel(group_id))
            except Exception:
                # Refresh dialogs cache once if entity not cached
                await client.get_dialogs(limit=200)
                return await client.get_input_entity(types.PeerChannel(group_id))
        else:
            return types.InputPeerChat(chat_id=group_id)

    async def _clear_single_group_history_for_all(
        self,
        client: TelegramClient,
        account_id: str,
        label: str,
        group_rec: Dict[str, Any],
    ) -> int:
        """
        Menghapus SEMUA riwayat chat di dalam grup untuk SEMUA MEMBER:
        1. Mengambil semua ID pesan yang ada di grup (teks, media, maupun pesan sistem/service)
           dan menghapusnya per 100 pesan dengan revoke=True / channels.DeleteMessagesRequest.
        2. Memanggil DeleteHistoryRequest(for_everyone=True / revoke=True) hingga bersih.
        """
        title = group_rec.get("title", f"ID {group_rec.get('id')}")
        is_mega = bool(group_rec.get("is_megagroup", True))
        prog = self.clear_progress[account_id]

        prog["current_step"] = f"[{title}] Memindai pesan di grup..."
        await self.emit_state()

        peer = await self._resolve_group_peer(client, group_rec)

        # Kumpulkan semua ID pesan yang ada di grup
        all_msg_ids: List[int] = []
        async for msg in client.iter_messages(peer, limit=None):
            if self.clear_stop_event.is_set():
                raise asyncio.CancelledError()
            if getattr(msg, "id", None):
                all_msg_ids.append(msg.id)

        deleted_total = 0

        # Hapus dalam batch per 100 pesan untuk semua member
        for i in range(0, len(all_msg_ids), 100):
            if self.clear_stop_event.is_set():
                raise asyncio.CancelledError()
            chunk = all_msg_ids[i : i + 100]
            prog["current_step"] = (
                f"[{title}] Menghapus pesan untuk semua member ({min(i + len(chunk), len(all_msg_ids))}/{len(all_msg_ids)})..."
            )
            await self.emit_state()

            if is_mega:
                await self._exec_with_floodwait(
                    account_id,
                    label,
                    f"Hapus Pesan Grup '{title}'",
                    lambda c=chunk: client(
                        functions.channels.DeleteMessagesRequest(
                            channel=peer,
                            id=c,
                        )
                    ),
                    stop_event=self.clear_stop_event,
                    progress_dict=self.clear_progress,
                )
            else:
                await self._exec_with_floodwait(
                    account_id,
                    label,
                    f"Hapus Pesan Grup '{title}'",
                    lambda c=chunk: client(
                        functions.messages.DeleteMessagesRequest(
                            id=c,
                            revoke=True,  # Hapus untuk semua member
                        )
                    ),
                    stop_event=self.clear_stop_event,
                    progress_dict=self.clear_progress,
                )
            deleted_total += len(chunk)
            prog["deleted_messages"] += len(chunk)
            await self.emit_state()

        # Sapu bersih riwayat chat untuk semua member menggunakan DeleteHistoryRequest
        prog["current_step"] = f"[{title}] Membersihkan riwayat grup untuk semua member..."
        await self.emit_state()
        try:
            if is_mega:
                await self._exec_with_floodwait(
                    account_id,
                    label,
                    f"Clear History Everyone '{title}'",
                    lambda: client(
                        functions.channels.DeleteHistoryRequest(
                            channel=peer,
                            max_id=0,
                            for_everyone=True,
                        )
                    ),
                    stop_event=self.clear_stop_event,
                    progress_dict=self.clear_progress,
                )
            else:
                while not self.clear_stop_event.is_set():
                    affected = await self._exec_with_floodwait(
                        account_id,
                        label,
                        f"Clear History Everyone '{title}'",
                        lambda: client(
                            functions.messages.DeleteHistoryRequest(
                                peer=peer,
                                max_id=0,
                                just_clear=False,
                                revoke=True,
                            )
                        ),
                        stop_event=self.clear_stop_event,
                        progress_dict=self.clear_progress,
                    )
                    if not getattr(affected, "offset", 0):
                        break
        except errors.ChatNotModifiedError:
            pass
        except Exception:
            # Jika pesan sudah habis terhapus melalui DeleteMessagesRequest,
            # beberapa layer Telegram dapat mengembalikan error minor pada DeleteHistoryRequest(max_id=0)
            pass

        return deleted_total

    async def _clear_history_account_worker(
        self,
        account_id: str,
        groups: List[Dict[str, Any]],
        config: ClearHistoryConfig,
    ) -> None:
        prog = self.clear_progress[account_id]
        label = prog["label"]
        lock = self.account_manager.get_account_lock(account_id)

        async with lock:
            try:
                client = await self.account_manager.get_client(account_id)
            except Exception as e:
                prog["status"] = "error"
                prog["current_step"] = f"Gagal koneksi akun pembuat: {e}"
                await self.emit_log(
                    "error",
                    f"❌ Gagal menghubungkan akun pembuat {label}: {e}",
                    account_id,
                    label,
                )
                await self.emit_state()
                return

            prog["status"] = "running"
            await self.emit_state()

            for idx, group_rec in enumerate(groups):
                if self.clear_stop_event.is_set():
                    break

                title = group_rec.get("title", f"ID {group_rec.get('id')}")
                try:
                    deleted_count = await self._clear_single_group_history_for_all(
                        client=client,
                        account_id=account_id,
                        label=label,
                        group_rec=group_rec,
                    )
                    prog["completed"] += 1
                    group_rec["last_cleared_at"] = datetime.now().strftime(
                        "%Y-%m-%d %H:%M:%S"
                    )
                    group_rec["last_deleted_count"] = deleted_count
                    await self.upsert_group_record(group_rec)
                    await self.emit_log(
                        "success",
                        f"🧹 Semua riwayat chat grup '{title}' berhasil dihapus untuk SEMUA MEMBER ({deleted_count} pesan dibersihkan).",
                        account_id,
                        label,
                    )
                    await self.emit_state()
                except asyncio.CancelledError:
                    break
                except Exception as e:
                    prog["failed"] += 1
                    await self.emit_log(
                        "error",
                        f"❌ Gagal menghapus riwayat chat grup '{title}': {e}",
                        account_id,
                        label,
                    )
                    await self.emit_state()

                if (
                    idx < len(groups) - 1
                    and config.delay_seconds > 0
                    and not self.clear_stop_event.is_set()
                ):
                    prog["current_step"] = f"Jeda {config.delay_seconds} detik..."
                    await self.emit_state()
                    await asyncio.sleep(config.delay_seconds)

            prog["status"] = (
                "stopped" if self.clear_stop_event.is_set() else "completed"
            )
            prog["current_step"] = "Selesai"
            await self.emit_state()

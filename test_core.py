import asyncio
import pytest
from fastapi.testclient import TestClient
from telethon import errors, functions, types

from group_creator import (
    ClearHistoryConfig,
    GroupCreationConfig,
    JoinHiderPermissions,
    ParallelGroupCreator,
    build_joinhider_admin_rights,
    build_member_banned_rights,
    build_mutual_full_admin_rights,
    generate_group_title,
)
from main import app
from telegram_manager import TelegramAccountManager


def test_group_naming_modes():
    cfg_seq = GroupCreationConfig(
        naming_mode="sequence",
        base_name="Grup VIP",
        sequence_separator=" | ",
    )
    assert generate_group_title(cfg_seq, 1) == "Grup VIP | 1"
    assert generate_group_title(cfg_seq, 2) == "Grup VIP | 2"

    cfg_single = GroupCreationConfig(
        naming_mode="single",
        base_name="Grup Tunggal",
    )
    assert generate_group_title(cfg_single, 1) == "Grup Tunggal"
    assert generate_group_title(cfg_single, 99) == "Grup Tunggal"

    candidates = ["Alpha", "Beta", "Gamma"]
    cfg_rand = GroupCreationConfig(
        naming_mode="random",
        random_names=candidates,
        random_with_sequence=False,
    )
    for i in range(10):
        assert generate_group_title(cfg_rand, i + 1) in candidates


def test_permissions_all_vs_invite_only():
    rights_all = build_member_banned_rights("all")
    assert rights_all.send_messages is False
    assert rights_all.send_media is False
    assert rights_all.invite_users is False

    rights_invite = build_member_banned_rights("invite_only")
    assert rights_invite.invite_users is False
    assert rights_invite.send_messages is True
    assert rights_invite.send_media is True
    assert rights_invite.send_stickers is True
    assert rights_invite.send_polls is True


def test_joinhider_and_mutual_admin_rights():
    jh_rights = build_joinhider_admin_rights(JoinHiderPermissions())
    assert jh_rights.delete_messages is True
    assert jh_rights.other is True
    assert jh_rights.add_admins is False
    assert jh_rights.anonymous is False

    mutual_rights = build_mutual_full_admin_rights()
    assert mutual_rights.change_info is True
    assert mutual_rights.delete_messages is True
    assert mutual_rights.ban_users is True
    assert mutual_rights.invite_users is True
    assert mutual_rights.pin_messages is True
    assert mutual_rights.add_admins is True
    assert mutual_rights.manage_call is True
    assert mutual_rights.other is True
    assert mutual_rights.anonymous is False


@pytest.mark.asyncio
async def test_floodwait_retry_until_success():
    events = []

    async def dummy_broadcast(payload):
        events.append(payload)

    creator = ParallelGroupCreator(TelegramAccountManager(), dummy_broadcast)
    creator.account_progress["acc_1"] = {
        "status": "running",
        "floodwait_seconds": 0,
        "current_step": "",
    }

    attempts = 0

    async def flaky_operation():
        nonlocal attempts
        attempts += 1
        if attempts < 2:
            err = errors.FloodWaitError(request=None, capture=1)
            err.seconds = 1
            raise err
        return "SUCCESS_AFTER_FLOODWAIT"

    result = await creator._exec_with_floodwait(
        "acc_1", "Akun Test", "Buat Grup", flaky_operation
    )
    assert result == "SUCCESS_AFTER_FLOODWAIT"
    assert attempts == 2


@pytest.mark.asyncio
async def test_clear_group_history_for_all_members():
    events = []

    async def dummy_broadcast(payload):
        events.append(payload)

    creator = ParallelGroupCreator(TelegramAccountManager(), dummy_broadcast)
    creator.clear_progress["acc_creator"] = {
        "account_id": "acc_creator",
        "label": "Akun Pembuat",
        "target": 1,
        "completed": 0,
        "failed": 0,
        "deleted_messages": 0,
        "status": "running",
        "current_step": "",
        "floodwait_seconds": 0,
    }

    class DummyMsg:
        def __init__(self, mid: int):
            self.id = mid

    class FakeClient:
        def __init__(self):
            self.requests = []

        async def iter_messages(self, peer, limit=None):
            for mid in [10, 9, 8, 7, 6]:
                yield DummyMsg(mid)

        async def __call__(self, req):
            self.requests.append(req)
            return True

    fake_client = FakeClient()
    group_rec = {
        "group_key": "acc_creator_999111",
        "id": 999111,
        "access_hash": 123456789,
        "title": "Grup Test Bersih",
        "is_megagroup": True,
        "account_id": "acc_creator",
        "account_label": "Akun Pembuat",
    }

    deleted_count = await creator._clear_single_group_history_for_all(
        fake_client, "acc_creator", "Akun Pembuat", group_rec
    )
    assert deleted_count == 5
    assert any(
        isinstance(r, functions.channels.DeleteMessagesRequest) and r.id == [10, 9, 8, 7, 6]
        for r in fake_client.requests
    )
    assert any(
        isinstance(r, functions.channels.DeleteHistoryRequest) and r.for_everyone is True
        for r in fake_client.requests
    )


def test_web_dashboard_endpoints():
    client = TestClient(app)
    r_index = client.get("/")
    assert r_index.status_code == 200
    assert "Auto-Make-Grup Dashboard" in r_index.text
    assert "Hapus Semua Riwayat Chat Grup (Untuk Semua Member)" in r_index.text
    assert "API_ID" not in r_index.text
    assert "API_HASH" not in r_index.text

    r_groups = client.get("/api/groups")
    assert r_groups.status_code == 200
    assert "groups" in r_groups.json()

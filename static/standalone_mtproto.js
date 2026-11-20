/**
 * Standalone In-App Telegram MTProto Engine (GramJS) for Android APK Mode.
 * Berjalan 100% langsung di HP Android tanpa membutuhkan server PC / Python!
 * Saat berjalan di localhost:5555 (Python FastAPI), aplikasi otomatis memakai backend Telethon;
 * saat berjalan di dalam APK Mandiri (Capacitor / Offline), engine ini menangani semua
 * koneksi MTProto Telegram langsung dari HP Android.
 */
(function () {
  const API_ID = 17158761;
  const API_HASH = "67d9b554799271cca765d42f40e0db43";

  const STORAGE_ACCOUNTS = "tg_clay_apk_accounts_v1";
  const STORAGE_GROUPS = "tg_clay_apk_groups_v1";
  const STORAGE_PHOTOS = "tg_clay_apk_photos_v1";

  const standaloneState = {
    active: false,
    accounts: {},
    clients: {},
    photos: [],
    createdGroups: [],
    qrSessions: {},
    phoneSessions: {},
    isRunning: false,
    stopRequested: false,
    accountProgress: {},
    isClearingHistory: false,
    clearStopRequested: false,
    clearProgress: {},
    logs: [],
    globalSeq: 1,
    wsListeners: [],
  };

  function loadLocalData() {
    try {
      const acc = localStorage.getItem(STORAGE_ACCOUNTS);
      if (acc) standaloneState.accounts = JSON.parse(acc) || {};
    } catch (_) {}
    try {
      const grp = localStorage.getItem(STORAGE_GROUPS);
      if (grp) standaloneState.createdGroups = JSON.parse(grp) || [];
    } catch (_) {}
    try {
      const p = localStorage.getItem(STORAGE_PHOTOS);
      if (p) standaloneState.photos = JSON.parse(p) || [];
    } catch (_) {}
  }

  function saveLocalAccounts() {
    localStorage.setItem(STORAGE_ACCOUNTS, JSON.stringify(standaloneState.accounts));
  }
  function saveLocalGroups() {
    localStorage.setItem(STORAGE_GROUPS, JSON.stringify(standaloneState.createdGroups));
  }
  function saveLocalPhotos() {
    localStorage.setItem(STORAGE_PHOTOS, JSON.stringify(standaloneState.photos));
  }

  function broadcastToUI(payload) {
    const str = JSON.stringify(payload);
    standaloneState.wsListeners.forEach((ws) => {
      if (typeof ws.onmessage === "function") {
        ws.onmessage({ data: str });
      }
    });
  }

  function emitLog(level, message, accountId = "SYSTEM", accountLabel = "SISTEM") {
    const now = new Date();
    const ts = now.toTimeString().split(" ")[0];
    const entry = {
      timestamp: ts,
      level,
      account_id: accountId,
      account_label: accountLabel,
      message,
    };
    standaloneState.logs.push(entry);
    if (standaloneState.logs.length > 500) {
      standaloneState.logs = standaloneState.logs.slice(-500);
    }
    broadcastToUI({ type: "log", data: entry });
  }

  function getStatusPayload() {
    return {
      is_running: standaloneState.isRunning,
      account_progress: standaloneState.accountProgress,
      created_groups: standaloneState.createdGroups,
      total_created: standaloneState.createdGroups.length,
      is_clearing_history: standaloneState.isClearingHistory,
      clear_progress: standaloneState.clearProgress,
      logs: standaloneState.logs.slice(-150),
    };
  }

  function emitState() {
    broadcastToUI({ type: "state", data: getStatusPayload() });
  }

  // Helper membuat gambar QR Code di sisi client (Canvas / SVG data URI)
  async function generateQrDataUrl(text) {
    if (window.QRCode && typeof window.QRCode.toDataURL === "function") {
      return await window.QRCode.toDataURL(text, { width: 240, margin: 2 });
    }
    return `https://api.qrserver.com/v1/create-qr-code/?size=240x240&data=${encodeURIComponent(text)}`;
  }

  function base64UrlEncode(bytes) {
    let binary = "";
    const arr = new Uint8Array(bytes);
    for (let i = 0; i < arr.length; i++) {
      binary += String.fromCharCode(arr[i]);
    }
    return btoa(binary).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
  }

  async function ensureGramJsLoaded() {
    if (window.telegram && window.telegram.TelegramClient) {
      return window.telegram;
    }
    throw new Error(
      "Library GramJS MTProto belum dimuat. Pastikan koneksi internet aktif saat pertama kali membuka APK."
    );
  }

  async function getConnectedClient(accountId) {
    const acc = standaloneState.accounts[accountId];
    if (!acc) throw new Error(`Akun ${accountId} tidak ditemukan.`);
    if (standaloneState.clients[accountId]) {
      const c = standaloneState.clients[accountId];
      if (!c.connected) await c.connect();
      return c;
    }
    const tg = await ensureGramJsLoaded();
    const session = new tg.sessions.StringSession(acc.session_string || "");
    const client = new tg.TelegramClient(session, API_ID, API_HASH, {
      connectionRetries: 5,
      deviceModel: "Android Clay APK",
      systemVersion: "Android 14",
      appVersion: "1.1.0",
    });
    await client.connect();
    standaloneState.clients[accountId] = client;
    return client;
  }

  async function registerAuthorizedClient(client) {
    const me = await client.getMe();
    const accountId = `acc_${me.id.toString()}`;
    const fullName = [me.firstName, me.lastName].filter(Boolean).join(" ").trim() || `User ${me.id}`;
    const sessionString = client.session.save();
    const record = {
      id: accountId,
      user_id: Number(me.id),
      session_string: sessionString,
      phone: me.phone ? `+${me.phone}` : "",
      first_name: me.firstName || "",
      last_name: me.lastName || "",
      full_name: fullName,
      username: me.username || "",
      enabled: true,
      status: "online",
      added_at: new Date().toISOString().replace("T", " ").slice(0, 19),
    };
    standaloneState.accounts[accountId] = record;
    standaloneState.clients[accountId] = client;
    saveLocalAccounts();
    return record;
  }

  // Wrapper Anti-FloodWait: menunggu & otomatis retry hingga berhasil
  async function execWithFloodWait(accountId, label, stepName, fn, isClearTask = false) {
    const progMap = isClearTask ? standaloneState.clearProgress : standaloneState.accountProgress;
    while (!(isClearTask ? standaloneState.clearStopRequested : standaloneState.stopRequested)) {
      try {
        return await fn();
      } catch (err) {
        const waitSec = Number(err.seconds || (err.errorMessage && err.errorMessage.match(/FLOOD_WAIT_(\d+)/)?.[1]) || 0);
        if (waitSec > 0) {
          const totalWait = waitSec + 2;
          emitLog(
            "warning",
            `⏳ Terkena FloodWait ${waitSec} detik saat [${stepName}]. Menunggu ${totalWait} detik & otomatis retry hingga berhasil...`,
            accountId,
            label
          );
          const prog = progMap[accountId];
          if (prog) {
            prog.status = "floodwait";
            prog.floodwait_seconds = totalWait;
            prog.current_step = `FloodWait (${stepName})`;
            emitState();
          }
          for (let rem = totalWait; rem > 0; rem--) {
            if (isClearTask ? standaloneState.clearStopRequested : standaloneState.stopRequested) {
              throw new Error("Dihentikan oleh pengguna");
            }
            if (prog) {
              prog.floodwait_seconds = rem;
              if (rem % 2 === 0 || rem <= 5) emitState();
            }
            await new Promise((r) => setTimeout(r, 1000));
          }
          if (prog) {
            prog.status = "running";
            prog.floodwait_seconds = 0;
            prog.current_step = `Retry ${stepName}`;
            emitState();
          }
          continue;
        }
        throw err;
      }
    }
    throw new Error("Dihentikan oleh pengguna");
  }

  // ==================== STANDALONE PARALLEL GROUP CREATION ====================

  function generateGroupTitle(config, seqNum) {
    const sep = config.sequence_separator || " | ";
    const base = (config.base_name || "Grup Baru").trim();
    if (config.naming_mode === "single") return base;
    if (config.naming_mode === "random") {
      const list = (config.random_names || []).map((s) => s.trim()).filter(Boolean);
      const chosen = list.length > 0 ? list[Math.floor(Math.random() * list.length)] : base;
      return config.random_with_sequence ? `${chosen}${sep}${seqNum}` : chosen;
    }
    return `${base}${sep}${seqNum}`;
  }

  async function runStandaloneBatch(config) {
    const tg = await ensureGramJsLoaded();
    const Api = tg.Api;
    const allAccs = Object.values(standaloneState.accounts);
    const selected = config.account_ids?.length
      ? allAccs.filter((a) => config.account_ids.includes(a.id))
      : allAccs;

    if (selected.length === 0) throw new Error("Pilih minimal 1 akun Telegram terlebih dahulu!");

    standaloneState.isRunning = true;
    standaloneState.stopRequested = false;
    standaloneState.globalSeq = config.sequence_start || 1;
    standaloneState.accountProgress = {};

    selected.forEach((acc) => {
      standaloneState.accountProgress[acc.id] = {
        account_id: acc.id,
        label: acc.full_name || acc.phone || acc.id,
        target: config.groups_per_account,
        completed: 0,
        failed: 0,
        status: "running",
        current_step: "Menyiapkan sesi...",
        floodwait_seconds: 0,
      };
    });
    emitState();

    // Jalankan semua akun secara PARALEL
    Promise.all(
      selected.map(async (acc) => {
        const accountId = acc.id;
        const label = acc.full_name || acc.phone || accountId;
        const prog = standaloneState.accountProgress[accountId];
        try {
          const client = await getConnectedClient(accountId);

          // Ambil kontak mutual
          let mutualUsers = [];
          if (config.invite_mutual_contacts) {
            try {
              const res = await execWithFloodWait(accountId, label, "Ambil Kontak Mutual", () =>
                client.invoke(new Api.contacts.GetContacts({ hash: BigInt(0) }))
              );
              const allowed = new Set(
                (config.selected_mutual_ids_by_account && config.selected_mutual_ids_by_account[accountId]) || []
              );
              mutualUsers = (res.users || []).filter(
                (u) =>
                  u.mutualContact &&
                  !u.bot &&
                  !u.deleted &&
                  !u.self &&
                  (allowed.size === 0 || allowed.has(Number(u.id)))
              );
              emitLog("info", `👥 Ditemukan ${mutualUsers.length} kontak mutual.`, accountId, label);
            } catch (e) {
              emitLog("warning", `⚠️ Gagal mengambil kontak mutual: ${e.message}`, accountId, label);
            }
          }

          // Resolve @joinhiderrobot
          let joinhiderEntity = null;
          const botUname = (config.joinhider_username || "@joinhiderrobot").trim();
          if (config.invite_joinhider) {
            try {
              joinhiderEntity = await execWithFloodWait(accountId, label, `Cari ${botUname}`, () =>
                client.getInputEntity(botUname)
              );
            } catch (e) {
              emitLog("warning", `⚠️ Bot ${botUname} tidak ditemukan: ${e.message}`, accountId, label);
            }
          }

          for (let i = 0; i < config.groups_per_account; i++) {
            if (standaloneState.stopRequested) break;
            const seqNum =
              config.sequence_scope === "per_account"
                ? (config.sequence_start || 1) + i
                : standaloneState.globalSeq++;
            const title = generateGroupTitle(config, seqNum);
            prog.current_step = `Membuat grup '${title}' (${i + 1}/${config.groups_per_account})`;
            emitState();

            try {
              const isMega = config.group_type === "megagroup";
              let groupChat = null;

              if (isMega) {
                const created = await execWithFloodWait(accountId, label, `Buat Supergroup '${title}'`, () =>
                  client.invoke(
                    new Api.channels.CreateChannel({
                      title,
                      about: config.group_about || "",
                      megagroup: true,
                    })
                  )
                );
                groupChat = created.chats[0];
                emitLog("success", `✅ Supergroup '${title}' berhasil dibuat.`, accountId, label);

                // Visibilitas riwayat chat (Terlihat vs Tersembunyi)
                const hidden = config.visibility === "hidden";
                try {
                  await execWithFloodWait(accountId, label, "Atur Visibilitas", () =>
                    client.invoke(
                      new Api.channels.TogglePreHistoryHidden({
                        channel: groupChat,
                        enabled: hidden,
                      })
                    )
                  );
                } catch (_) {}
              } else {
                const initUsers = joinhiderEntity ? [joinhiderEntity] : [];
                const created = await execWithFloodWait(accountId, label, `Buat Basic Group '${title}'`, () =>
                  client.invoke(new Api.messages.CreateChat({ users: initUsers, title }))
                );
                groupChat = (created.chats || created.updates?.chats || [])[0];
                emitLog("success", `✅ Basic Group '${title}' berhasil dibuat.`, accountId, label);
              }

              // Perizinan Anggota (Semua vs Hanya Tambah Anggota)
              const onlyInvite = config.permission_mode === "invite_only";
              const bannedRights = new Api.ChatBannedRights({
                untilDate: 0,
                viewMessages: false,
                inviteUsers: false,
                sendMessages: onlyInvite,
                sendMedia: onlyInvite,
                sendStickers: onlyInvite,
                sendGifs: onlyInvite,
                sendGames: onlyInvite,
                sendInline: onlyInvite,
                embedLinks: onlyInvite,
                sendPolls: onlyInvite,
                changeInfo: onlyInvite,
                pinMessages: onlyInvite,
                manageTopics: onlyInvite,
                sendPhotos: onlyInvite,
                sendVideos: onlyInvite,
                sendRoundvideos: onlyInvite,
                sendAudios: onlyInvite,
                sendVoices: onlyInvite,
                sendDocs: onlyInvite,
                sendPlain: onlyInvite,
              });
              try {
                await execWithFloodWait(accountId, label, "Atur Perizinan", () =>
                  client.invoke(
                    new Api.messages.EditChatDefaultBannedRights({
                      peer: groupChat,
                      bannedRights,
                    })
                  )
                );
              } catch (_) {}

              // Otomatis Undang @joinhiderrobot & Jadikan Admin
              if (config.invite_joinhider && joinhiderEntity && isMega) {
                try {
                  await execWithFloodWait(accountId, label, `Undang ${botUname}`, () =>
                    client.invoke(
                      new Api.channels.InviteToChannel({
                        channel: groupChat,
                        users: [joinhiderEntity],
                      })
                    )
                  );
                  const jhPerms = config.joinhider_permissions || {};
                  await execWithFloodWait(accountId, label, `Admin ${botUname}`, () =>
                    client.invoke(
                      new Api.channels.EditAdmin({
                        channel: groupChat,
                        userId: joinhiderEntity,
                        adminRights: new Api.ChatAdminRights({
                          deleteMessages: jhPerms.delete_messages !== false,
                          other: jhPerms.other !== false,
                          banUsers: Boolean(jhPerms.ban_users),
                          inviteUsers: Boolean(jhPerms.invite_users),
                          pinMessages: Boolean(jhPerms.pin_messages),
                          anonymous: false,
                        }),
                        rank: "Join Hider",
                      })
                    )
                  );
                  emitLog("success", `🤖 ${botUname} dijadikan Admin (Hapus Chat) di '${title}'.`, accountId, label);
                } catch (e) {
                  emitLog("warning", `⚠️ Gagal set ${botUname}: ${e.message}`, accountId, label);
                }
              }

              // Otomatis Undang Kontak Mutual & Jadikan Admin Penuh Kecuali Tetap Anonim
              let promotedMutuals = 0;
              if (config.invite_mutual_contacts && mutualUsers.length > 0) {
                const fullAdminRights = new Api.ChatAdminRights({
                  changeInfo: true,
                  postMessages: true,
                  editMessages: true,
                  deleteMessages: true,
                  banUsers: true,
                  inviteUsers: true,
                  pinMessages: true,
                  addAdmins: true,
                  anonymous: false, // KECUALI tetap anonim!
                  manageCall: true,
                  other: true,
                  manageTopics: true,
                });

                for (const mUser of mutualUsers) {
                  if (standaloneState.stopRequested) break;
                  try {
                    if (isMega) {
                      await execWithFloodWait(accountId, label, "Undang Mutual", () =>
                        client.invoke(
                          new Api.channels.InviteToChannel({
                            channel: groupChat,
                            users: [mUser],
                          })
                        )
                      );
                      if (config.promote_mutual_to_admin) {
                        await execWithFloodWait(accountId, label, "Set Admin Mutual", () =>
                          client.invoke(
                            new Api.channels.EditAdmin({
                              channel: groupChat,
                              userId: mUser,
                              adminRights: fullAdminRights,
                              rank: "Admin",
                            })
                          )
                        );
                        promotedMutuals++;
                      }
                    }
                  } catch (_) {}
                }
              }

              const rec = {
                group_key: `${accountId}_${groupChat.id.toString()}`,
                id: Number(groupChat.id),
                access_hash: groupChat.accessHash ? groupChat.accessHash.toString() : "0",
                title,
                is_megagroup: isMega,
                type: isMega ? "Supergroup" : "Basic Group",
                visibility: isMega ? (config.visibility === "hidden" ? "Tersembunyi" : "Terlihat") : "-",
                permissions: onlyInvite ? "Hanya Tambah Anggota" : "Semua Perizinan",
                photo: "Acak",
                joinhider: config.invite_joinhider,
                mutual_admins: promotedMutuals,
                account_id: accountId,
                account_label: label,
                created_at: new Date().toISOString().replace("T", " ").slice(0, 19),
              };
              standaloneState.createdGroups.push(rec);
              saveLocalGroups();
              prog.completed++;
              broadcastToUI({ type: "group_created", data: rec });
              emitState();
            } catch (err) {
              prog.failed++;
              emitLog("error", `❌ Gagal membuat grup '${title}': ${err.message}`, accountId, label);
              emitState();
            }

            if (i < config.groups_per_account - 1 && config.delay_seconds > 0 && !standaloneState.stopRequested) {
              await new Promise((r) => setTimeout(r, config.delay_seconds * 1000));
            }
          }
          prog.status = "completed";
          prog.current_step = "Selesai";
          emitState();
        } catch (err) {
          prog.status = "error";
          prog.current_step = err.message;
          emitState();
        }
      })
    ).finally(() => {
      standaloneState.isRunning = false;
      emitState();
    });
  }

  // ==================== STANDALONE CLEAR HISTORY FOR ALL MEMBERS ====================

  async function runStandaloneClearHistory(config) {
    const tg = await ensureGramJsLoaded();
    const Api = tg.Api;
    const keySet = new Set(config.group_keys || []);
    const targets = keySet.size
      ? standaloneState.createdGroups.filter((g) => keySet.has(g.group_key))
      : standaloneState.createdGroups;

    if (targets.length === 0) throw new Error("Pilih minimal 1 grup untuk dihapus riwayat chatnya.");

    const byAccount = {};
    targets.forEach((g) => {
      byAccount[g.account_id] = byAccount[g.account_id] || [];
      byAccount[g.account_id].push(g);
    });

    standaloneState.isClearingHistory = true;
    standaloneState.clearStopRequested = false;
    standaloneState.clearProgress = {};

    Object.entries(byAccount).forEach(([accId, list]) => {
      standaloneState.clearProgress[accId] = {
        account_id: accId,
        label: list[0].account_label || accId,
        target: list.length,
        completed: 0,
        failed: 0,
        deleted_messages: 0,
        status: "running",
        current_step: "Menyiapkan sesi...",
        floodwait_seconds: 0,
      };
    });
    emitState();

    Promise.all(
      Object.entries(byAccount).map(async ([accId, list]) => {
        const prog = standaloneState.clearProgress[accId];
        const label = prog.label;
        try {
          const client = await getConnectedClient(accId);
          for (const g of list) {
            if (standaloneState.clearStopRequested) break;
            prog.current_step = `[${g.title}] Menghapus semua riwayat chat untuk semua member...`;
            emitState();
            try {
              const msgs = await client.getMessages(g.id, { limit: 500 });
              const ids = msgs.map((m) => m.id).filter(Boolean);
              if (ids.length > 0) {
                await execWithFloodWait(
                  accId,
                  label,
                  `Hapus Pesan '${g.title}'`,
                  () => client.deleteMessages(g.id, ids, { revoke: true }),
                  true
                );
              }
              try {
                await execWithFloodWait(
                  accId,
                  label,
                  `Clear History '${g.title}'`,
                  () =>
                    client.invoke(
                      new Api.channels.DeleteHistory({
                        channel: g.id,
                        maxId: 0,
                        forEveryone: true,
                      })
                    ),
                  true
                );
              } catch (_) {}

              g.last_cleared_at = new Date().toISOString().replace("T", " ").slice(0, 19);
              g.last_deleted_count = ids.length;
              prog.completed++;
              prog.deleted_messages += ids.length;
              saveLocalGroups();
              emitLog(
                "success",
                `🧹 Riwayat chat '${g.title}' berhasil dihapus untuk SEMUA MEMBER (${ids.length} pesan).`,
                accId,
                label
              );
              emitState();
            } catch (e) {
              prog.failed++;
              emitLog("error", `❌ Gagal hapus riwayat '${g.title}': ${e.message}`, accId, label);
              emitState();
            }
          }
          prog.status = "completed";
          prog.current_step = "Selesai";
          emitState();
        } catch (err) {
          prog.status = "error";
          prog.current_step = err.message;
          emitState();
        }
      })
    ).finally(() => {
      standaloneState.isClearingHistory = false;
      emitState();
    });
  }

  // ==================== AUTO-ACTIVATE IN STANDALONE APK MODE ====================

  const isCapacitorOrFile =
    Boolean(window.Capacitor) ||
    window.location.protocol === "file:" ||
    window.FORCE_STANDALONE_APK === true;

  if (isCapacitorOrFile) {
    enableStandaloneMode();
  }

  function enableStandaloneMode() {
    if (standaloneState.active) return;
    standaloneState.active = true;
    loadLocalData();

    // Load GramJS & QRCode dynamically for standalone APK mode
    const s1 = document.createElement("script");
    s1.src = "https://cdn.jsdelivr.net/npm/qrcode@1.5.3/build/qrcode.min.js";
    document.head.appendChild(s1);

    const s2 = document.createElement("script");
    s2.src = "https://cdn.jsdelivr.net/npm/telegram@2.26.17/browser.min.js";
    document.head.appendChild(s2);

    const origFetch = window.fetch.bind(window);
    window.fetch = async function (url, options = {}) {
      const path = typeof url === "string" ? url : url.url;
      if (!path.startsWith("/api/")) {
        return origFetch(url, options);
      }
      const method = (options.method || "GET").toUpperCase();
      const body = options.body && typeof options.body === "string" ? JSON.parse(options.body) : null;

      try {
        const result = await handleStandaloneApi(path, method, body, options.body);
        return new Response(JSON.stringify(result), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        });
      } catch (err) {
        return new Response(JSON.stringify({ detail: err.message || String(err) }), {
          status: 400,
          headers: { "Content-Type": "application/json" },
        });
      }
    };

    // Mock WebSocket for standalone APK mode
    window.WebSocket = function () {
      const wsObj = {
        onopen: null,
        onmessage: null,
        onclose: null,
        send: function () {},
        close: function () {},
      };
      standaloneState.wsListeners.push(wsObj);
      setTimeout(() => {
        if (typeof wsObj.onopen === "function") wsObj.onopen();
        if (typeof wsObj.onmessage === "function") {
          wsObj.onmessage({
            data: JSON.stringify({ type: "init", data: getStatusPayload() }),
          });
        }
      }, 80);
      return wsObj;
    };
  }

  async function handleStandaloneApi(path, method, jsonBody, rawBody) {
    if (path === "/api/accounts" && method === "GET") {
      return { accounts: Object.values(standaloneState.accounts) };
    }
    if (path.startsWith("/api/accounts/") && method === "DELETE") {
      const id = path.split("/")[3];
      delete standaloneState.accounts[id];
      saveLocalAccounts();
      return { ok: true };
    }
    if (path.endsWith("/mutuals") && method === "GET") {
      const id = path.split("/")[3];
      const tg = await ensureGramJsLoaded();
      const client = await getConnectedClient(id);
      const res = await client.invoke(new tg.Api.contacts.GetContacts({ hash: BigInt(0) }));
      const mutuals = (res.users || [])
        .filter((u) => u.mutualContact && !u.bot && !u.deleted && !u.self)
        .map((u) => ({
          id: Number(u.id),
          full_name: [u.firstName, u.lastName].filter(Boolean).join(" ") || `User ${u.id}`,
          username: u.username || "",
          phone: u.phone ? `+${u.phone}` : "",
        }));
      return { account_id: id, mutuals, count: mutuals.length };
    }
    if (path === "/api/auth/phone/send-code" && method === "POST") {
      const tg = await ensureGramJsLoaded();
      const phone = jsonBody.phone.startsWith("+") ? jsonBody.phone : `+${jsonBody.phone}`;
      const loginId = "ph_" + Date.now();
      const client = new tg.TelegramClient(new tg.sessions.StringSession(""), API_ID, API_HASH, {
        connectionRetries: 5,
      });
      await client.connect();
      const res = await client.sendCode({ apiId: API_ID, apiHash: API_HASH }, phone);
      standaloneState.phoneSessions[loginId] = {
        client,
        phone,
        phoneCodeHash: res.phoneCodeHash,
        status: "waiting_code",
      };
      return { login_id: loginId, phone, status: "waiting_code" };
    }
    if (path === "/api/auth/phone/verify" && method === "POST") {
      const tg = await ensureGramJsLoaded();
      const sess = standaloneState.phoneSessions[jsonBody.login_id];
      if (!sess) throw new Error("Sesi nomor HP tidak ditemukan");
      try {
        await sess.client.invoke(
          new tg.Api.auth.SignIn({
            phoneNumber: sess.phone,
            phoneCodeHash: sess.phoneCodeHash,
            phoneCode: jsonBody.code,
          })
        );
      } catch (e) {
        if (e.errorMessage === "SESSION_PASSWORD_NEEDED") {
          if (!jsonBody.password) return { login_id: jsonBody.login_id, status: "need_2fa" };
          await sess.client.signInWithPassword(
            { apiId: API_ID, apiHash: API_HASH },
            { password: async () => jsonBody.password, onError: (err) => { throw err; } }
          );
        } else {
          throw e;
        }
      }
      const account = await registerAuthorizedClient(sess.client);
      delete standaloneState.phoneSessions[jsonBody.login_id];
      return { status: "authorized", account };
    }
    if (path === "/api/auth/qr/start" && method === "POST") {
      const tg = await ensureGramJsLoaded();
      const loginId = "qr_" + Date.now();
      const client = new tg.TelegramClient(new tg.sessions.StringSession(""), API_ID, API_HASH, {
        connectionRetries: 5,
      });
      await client.connect();
      const exported = await client.invoke(
        new tg.Api.auth.ExportLoginToken({
          apiId: API_ID,
          apiHash: API_HASH,
          exceptIds: [],
        })
      );
      const tokenUrl = `tg://login?token=${base64UrlEncode(exported.token)}`;
      const qrImg = await generateQrDataUrl(tokenUrl);
      standaloneState.qrSessions[loginId] = {
        client,
        status: "waiting_scan",
        qr_image: qrImg,
        account: null,
      };
      return { login_id: loginId, status: "waiting_scan", qr_image: qrImg };
    }
    if (path.startsWith("/api/auth/qr/status/") && method === "GET") {
      const loginId = path.split("/").pop();
      const sess = standaloneState.qrSessions[loginId];
      if (!sess) return { status: "not_found" };
      const tg = await ensureGramJsLoaded();
      try {
        const res = await sess.client.invoke(
          new tg.Api.auth.ExportLoginToken({
            apiId: API_ID,
            apiHash: API_HASH,
            exceptIds: [],
          })
        );
        if (res.className === "auth.LoginTokenSuccess") {
          const acc = await registerAuthorizedClient(sess.client);
          sess.status = "authorized";
          sess.account = acc;
        } else if (res.token) {
          sess.qr_image = await generateQrDataUrl(`tg://login?token=${base64UrlEncode(res.token)}`);
        }
      } catch (e) {
        if (e.errorMessage === "SESSION_PASSWORD_NEEDED") {
          sess.status = "need_2fa";
        }
      }
      return {
        login_id: loginId,
        status: sess.status,
        qr_image: sess.qr_image,
        account: sess.account,
      };
    }
    if (path === "/api/photos" && method === "GET") {
      return { photos: standaloneState.photos };
    }
    if (path === "/api/photos/upload" && method === "POST" && rawBody instanceof FormData) {
      const files = rawBody.getAll("files");
      for (const file of files) {
        if (!file || !file.name) continue;
        const dataUrl = await new Promise((resolve) => {
          const reader = new FileReader();
          reader.onload = () => resolve(reader.result);
          reader.readAsDataURL(file);
        });
        const name = `photo_${Date.now()}_${Math.random().toString(36).slice(2, 6)}_${file.name}`;
        standaloneState.photos.push({
          name,
          url: dataUrl,
          size_kb: Math.round((file.size || 1024) / 1024),
        });
      }
      saveLocalPhotos();
      return { uploaded: standaloneState.photos.map((p) => p.name), count: standaloneState.photos.length };
    }
    if (path.startsWith("/api/photos/") && method === "DELETE") {
      const fname = decodeURIComponent(path.split("/").pop());
      standaloneState.photos = standaloneState.photos.filter((p) => p.name !== fname);
      saveLocalPhotos();
      return { ok: true };
    }
    if (path === "/api/photos" && method === "DELETE") {
      standaloneState.photos = [];
      saveLocalPhotos();
      return { ok: true };
    }
    if (path === "/api/tasks/status" && method === "GET") {
      return getStatusPayload();
    }
    if (path === "/api/tasks/start" && method === "POST") {
      await runStandaloneBatch(jsonBody);
      return { ok: true, status: getStatusPayload() };
    }
    if (path === "/api/tasks/stop" && method === "POST") {
      standaloneState.stopRequested = true;
      return { ok: true };
    }
    if (path === "/api/groups" && method === "GET") {
      return { groups: standaloneState.createdGroups };
    }
    if (path === "/api/groups/clear-history/start" && method === "POST") {
      await runStandaloneClearHistory(jsonBody);
      return { ok: true, status: getStatusPayload() };
    }
    if (path === "/api/groups/clear-history/stop" && method === "POST") {
      standaloneState.clearStopRequested = true;
      return { ok: true };
    }
    return { ok: true };
  }
})();

// State global aplikasi frontend
const state = {
  accounts: [],
  selectedAccountIds: new Set(),
  photos: [],
  selectedMutualsByAccount: {}, // { account_id: [user_id, ...] }
  createdGroups: [],
  selectedClearGroupKeys: new Set(),
  qrLoginId: null,
  qrPollTimer: null,
  phoneLoginId: null,
  isRunning: false,
  isClearingHistory: false,
};

// ==================== INITIALIZATION ====================

document.addEventListener("DOMContentLoaded", () => {
  if ("serviceWorker" in navigator && location.protocol.startsWith("http")) {
    navigator.serviceWorker.register("/static/sw.js").catch(() => {});
  }
  bindUIEvents();
  loadAccounts();
  loadPhotos();
  updateNamingPreview();
  connectWebSocket();
});

function bindUIEvents() {
  // Navigation Tabs (Buat Grup vs Hapus Riwayat Chat Grup)
  document.querySelectorAll(".nav-tab").forEach((btn) => {
    btn.addEventListener("click", () => {
      document.querySelectorAll(".nav-tab").forEach((b) => b.classList.remove("active"));
      btn.classList.add("active");
      const targetTab = btn.getAttribute("data-tab");
      document.querySelectorAll(".tab-pane").forEach((pane) => {
        pane.classList.toggle("hidden", pane.id !== targetTab);
      });
    });
  });

  // Select All Accounts
  document.getElementById("chkSelectAllAccounts").addEventListener("change", (e) => {
    if (e.target.checked) {
      state.accounts.forEach((a) => state.selectedAccountIds.add(a.id));
    } else {
      state.selectedAccountIds.clear();
    }
    renderAccounts();
  });

  document.getElementById("btnRefreshAccounts").addEventListener("click", loadAccounts);

  // QR Modal
  document.getElementById("btnOpenQrModal").addEventListener("click", openQrModal);
  document.getElementById("btnCloseQrModal").addEventListener("click", closeQrModal);
  document.getElementById("btnSubmitQr2fa").addEventListener("click", submitQr2fa);

  // Phone Modal
  document.getElementById("btnOpenPhoneModal").addEventListener("click", openPhoneModal);
  document.getElementById("btnClosePhoneModal").addEventListener("click", closePhoneModal);
  document.getElementById("btnSendPhoneCode").addEventListener("click", sendPhoneCode);
  document.getElementById("btnVerifyPhoneOtp").addEventListener("click", verifyPhoneOtp);

  // Mutual Modal
  document.getElementById("btnCloseMutualModal").addEventListener("click", () => {
    document.getElementById("mutualModal").classList.add("hidden");
  });

  // Photos Upload & Drag-Drop
  const photoInput = document.getElementById("photoUploadInput");
  photoInput.addEventListener("change", (e) => uploadPhotoFiles(e.target.files));

  const dropZone = document.getElementById("photoDropZone");
  dropZone.addEventListener("dragover", (e) => {
    e.preventDefault();
    dropZone.classList.add("dragover");
  });
  dropZone.addEventListener("dragleave", () => dropZone.classList.remove("dragover"));
  dropZone.addEventListener("drop", (e) => {
    e.preventDefault();
    dropZone.classList.remove("dragover");
    if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
      uploadPhotoFiles(e.dataTransfer.files);
    }
  });

  document.getElementById("btnClearPhotos").addEventListener("click", clearAllPhotos);

  // Group Type Radio Styling & Visibility toggle
  document.querySelectorAll('input[name="group_type"]').forEach((radio) => {
    radio.addEventListener("change", () => {
      updateRadioCardStyles("groupTypeRadios");
      const isMega = getRadioValue("group_type") === "megagroup";
      document.getElementById("visibilityGroupWrap").classList.toggle("hidden", !isMega);
    });
  });

  // Visibility Segmented Control
  document.querySelectorAll('input[name="visibility"]').forEach((radio) => {
    radio.addEventListener("change", () => {
      updateSegmentStyles(radio.closest(".segmented-control"));
    });
  });

  // Permission Mode Radio Cards
  document.querySelectorAll('input[name="permission_mode"]').forEach((radio) => {
    radio.addEventListener("change", () => updateRadioCardStyles("permissionRadios"));
  });

  // Naming Mode Segmented Control
  document.querySelectorAll('input[name="naming_mode"]').forEach((radio) => {
    radio.addEventListener("change", () => {
      updateSegmentStyles(document.getElementById("namingModeControl"));
      updateNamingModeVisibility();
      updateNamingPreview();
    });
  });

  [
    "inpBaseName",
    "inpRandomNames",
    "chkRandomWithSequence",
    "inpSeqStart",
    "inpSeqSeparator",
    "selSeqScope",
  ].forEach((id) => {
    const el = document.getElementById(id);
    el.addEventListener("input", updateNamingPreview);
    el.addEventListener("change", updateNamingPreview);
  });

  // Join Hider & Mutual toggles
  document.getElementById("chkInviteJoinHider").addEventListener("change", (e) => {
    document.getElementById("joinHiderConfigWrap").classList.toggle("hidden", !e.target.checked);
  });
  document.getElementById("chkInviteMutuals").addEventListener("change", (e) => {
    document.getElementById("mutualConfigWrap").classList.toggle("hidden", !e.target.checked);
  });

  // Start / Stop Parallel Group Creation
  document.getElementById("btnStartCreation").addEventListener("click", startParallelCreation);
  document.getElementById("btnStopCreation").addEventListener("click", stopParallelCreation);

  // Tab 2: Clear Group Chat History Controls
  document.getElementById("btnSyncCreatorGroups").addEventListener("click", syncCreatorGroups);
  document.getElementById("selFilterCreatorAccount").addEventListener("change", renderClearGroupsTable);
  document.getElementById("inpSearchClearGroup").addEventListener("input", renderClearGroupsTable);
  document.getElementById("chkSelectAllClearGroups").addEventListener("change", (e) => {
    const filtered = getFilteredClearGroups();
    if (e.target.checked) {
      filtered.forEach((g) => state.selectedClearGroupKeys.add(g.group_key));
    } else {
      filtered.forEach((g) => state.selectedClearGroupKeys.delete(g.group_key));
    }
    renderClearGroupsTable();
  });
  document.getElementById("btnStartClearHistory").addEventListener("click", startBatchClearHistory);
  document.getElementById("btnStopClearHistory").addEventListener("click", stopBatchClearHistory);

  // Clear logs
  document.getElementById("btnClearLogs").addEventListener("click", () => {
    document.getElementById("terminalLogBox").innerHTML = "";
  });
}

function getRadioValue(name) {
  const el = document.querySelector(`input[name="${name}"]:checked`);
  return el ? el.value : "";
}

function updateRadioCardStyles(containerId) {
  const container = document.getElementById(containerId);
  container.querySelectorAll(".radio-card").forEach((card) => {
    const input = card.querySelector("input");
    card.classList.toggle("active", input.checked);
  });
}

function updateSegmentStyles(container) {
  container.querySelectorAll(".segment").forEach((seg) => {
    const input = seg.querySelector("input");
    seg.classList.toggle("active", input.checked);
  });
}

function updateNamingModeVisibility() {
  const mode = getRadioValue("naming_mode");
  const baseNameWrap = document.getElementById("baseNameWrap");
  const randomNamesWrap = document.getElementById("randomNamesWrap");
  const seqWrap = document.getElementById("sequenceOptionsWrap");
  const randomWithSeq = document.getElementById("chkRandomWithSequence").checked;

  if (mode === "sequence") {
    baseNameWrap.classList.remove("hidden");
    randomNamesWrap.classList.add("hidden");
    seqWrap.classList.remove("hidden");
  } else if (mode === "single") {
    baseNameWrap.classList.remove("hidden");
    randomNamesWrap.classList.add("hidden");
    seqWrap.classList.add("hidden");
  } else if (mode === "random") {
    baseNameWrap.classList.add("hidden");
    randomNamesWrap.classList.remove("hidden");
    seqWrap.classList.toggle("hidden", !randomWithSeq);
  }
}

function updateNamingPreview() {
  updateNamingModeVisibility();
  const mode = getRadioValue("naming_mode");
  const base = document.getElementById("inpBaseName").value.trim() || "Grup Baru";
  const start = parseInt(document.getElementById("inpSeqStart").value, 10) || 1;
  const sep = document.getElementById("inpSeqSeparator").value || " | ";
  const randomLines = document
    .getElementById("inpRandomNames")
    .value.split("\n")
    .map((s) => s.trim())
    .filter(Boolean);
  const randomWithSeq = document.getElementById("chkRandomWithSequence").checked;

  const samples = [];
  for (let i = 0; i < 3; i++) {
    const num = start + i;
    if (mode === "single") {
      samples.push(base);
    } else if (mode === "random") {
      const pool = randomLines.length > 0 ? randomLines : ["Nama Acak"];
      const pick = pool[i % pool.length];
      samples.push(randomWithSeq ? `${pick}${sep}${num}` : pick);
    } else {
      samples.push(`${base}${sep}${num}`);
    }
  }

  const container = document.getElementById("namePreviewTags");
  container.innerHTML = samples
    .map((s) => `<span class="preview-tag">${escapeHtml(s)}</span>`)
    .join("");
}

// ==================== ACCOUNTS MANAGEMENT ====================

async function loadAccounts() {
  try {
    const res = await fetch("/api/accounts");
    const data = await res.json();
    state.accounts = data.accounts || [];
    state.accounts.forEach((a) => {
      if (!state.selectedAccountIds.has(a.id)) {
        state.selectedAccountIds.add(a.id);
      }
    });
    renderAccounts();
    populateCreatorFilterSelect();
  } catch (err) {
    console.error("Gagal memuat daftar akun:", err);
  }
}

function populateCreatorFilterSelect() {
  const sel = document.getElementById("selFilterCreatorAccount");
  const current = sel.value || "ALL";
  const options = [`<option value="ALL">Semua Akun Pembuat Grup</option>`];
  const seen = new Set();

  state.accounts.forEach((acc) => {
    seen.add(acc.id);
    options.push(
      `<option value="${escapeHtml(acc.id)}">${escapeHtml(acc.full_name)} (${escapeHtml(acc.phone || acc.id)})</option>`
    );
  });

  state.createdGroups.forEach((g) => {
    if (g.account_id && !seen.has(g.account_id)) {
      seen.add(g.account_id);
      options.push(
        `<option value="${escapeHtml(g.account_id)}">${escapeHtml(g.account_label || g.account_id)}</option>`
      );
    }
  });

  sel.innerHTML = options.join("");
  if ([...sel.options].some((o) => o.value === current)) {
    sel.value = current;
  }
}

function renderAccounts() {
  const listEl = document.getElementById("accountsList");
  document.getElementById("totalAccountCount").textContent = state.accounts.length;
  const validSelected = state.accounts.filter((a) => state.selectedAccountIds.has(a.id));
  document.getElementById("selectedAccountCount").textContent = validSelected.length;
  document.getElementById("chkSelectAllAccounts").checked =
    state.accounts.length > 0 && validSelected.length === state.accounts.length;

  if (state.accounts.length === 0) {
    listEl.innerHTML = `<div class="empty-state">Belum ada akun yang login. Klik <b>+ Login QR Code</b> untuk menambahkan akun.</div>`;
    return;
  }

  listEl.innerHTML = state.accounts
    .map((acc) => {
      const checked = state.selectedAccountIds.has(acc.id) ? "checked" : "";
      const uname = acc.username ? `@${acc.username}` : "Tanpa username";
      const phone = acc.phone || "";
      const customMutuals = state.selectedMutualsByAccount[acc.id];
      const mutualBadge = customMutuals
        ? `${customMutuals.length} Mutual Dipilih`
        : "Semua Kontak Mutual";

      return `
      <div class="account-item">
        <div class="account-left">
          <input type="checkbox" class="acc-checkbox" data-id="${acc.id}" ${checked} />
          <div class="account-meta">
            <strong>${escapeHtml(acc.full_name)}</strong>
            <span>${escapeHtml(phone)} &bull; ${escapeHtml(uname)}</span>
          </div>
        </div>
        <div class="account-actions">
          <button class="btn btn-sm btn-secondary" onclick="openMutualPreview('${acc.id}', '${escapeHtml(acc.full_name)}')">
            👥 ${mutualBadge}
          </button>
          <button class="btn btn-sm btn-danger-outline" onclick="removeAccount('${acc.id}')">
            Hapus
          </button>
        </div>
      </div>
    `;
    })
    .join("");

  listEl.querySelectorAll(".acc-checkbox").forEach((cb) => {
    cb.addEventListener("change", (e) => {
      const id = e.target.getAttribute("data-id");
      if (e.target.checked) {
        state.selectedAccountIds.add(id);
      } else {
        state.selectedAccountIds.delete(id);
      }
      renderAccounts();
    });
  });
}

async function removeAccount(accountId) {
  if (!confirm("Hapus sesi akun ini dari dashboard?")) return;
  await fetch(`/api/accounts/${accountId}`, { method: "DELETE" });
  state.selectedAccountIds.delete(accountId);
  await loadAccounts();
}

async function openMutualPreview(accountId, accountName) {
  const modal = document.getElementById("mutualModal");
  const listEl = document.getElementById("mutualModalList");
  document.getElementById("mutualModalTitle").textContent = `Kontak Mutual — ${accountName}`;
  listEl.innerHTML = `<div class="empty-state">Mengambil daftar kontak mutual dari Telegram...</div>`;
  modal.classList.remove("hidden");

  try {
    const res = await fetch(`/api/accounts/${accountId}/mutuals`);
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || "Gagal memuat kontak mutual");

    const mutuals = data.mutuals || [];
    if (mutuals.length === 0) {
      listEl.innerHTML = `<div class="empty-state">Akun ini belum memiliki kontak mutual (kontak yang saling menyimpan nomor).</div>`;
      return;
    }

    const currentSelected = state.selectedMutualsByAccount[accountId]
      ? new Set(state.selectedMutualsByAccount[accountId])
      : new Set(mutuals.map((m) => m.id));

    listEl.innerHTML = mutuals
      .map((m) => {
        const isChecked = currentSelected.has(m.id) ? "checked" : "";
        const sub = [m.phone, m.username ? `@${m.username}` : ""].filter(Boolean).join(" • ");
        return `
        <label class="mutual-item">
          <div>
            <strong>${escapeHtml(m.full_name)}</strong>
            <div class="small-muted">${escapeHtml(sub)}</div>
          </div>
          <input type="checkbox" class="mutual-chk" value="${m.id}" ${isChecked} />
        </label>
      `;
      })
      .join("");

    listEl.querySelectorAll(".mutual-chk").forEach((chk) => {
      chk.addEventListener("change", () => {
        const picked = Array.from(listEl.querySelectorAll(".mutual-chk:checked")).map((el) =>
          parseInt(el.value, 10)
        );
        if (picked.length === mutuals.length) {
          delete state.selectedMutualsByAccount[accountId];
        } else {
          state.selectedMutualsByAccount[accountId] = picked;
        }
        renderAccounts();
      });
    });
  } catch (err) {
    listEl.innerHTML = `<div class="empty-state error-text">${escapeHtml(err.message)}</div>`;
  }
}

// ==================== QR CODE LOGIN ====================

async function openQrModal() {
  document.getElementById("qrModal").classList.remove("hidden");
  document.getElementById("qrScanStep").classList.remove("hidden");
  document.getElementById("qr2faStep").classList.add("hidden");
  document.getElementById("qrCodeImg").classList.add("hidden");
  document.getElementById("qrLoadingSpinner").classList.remove("hidden");
  document.getElementById("qrStatusMsg").textContent = "Menghubungkan ke server Telegram...";
  document.getElementById("inpQr2faPassword").value = "";

  try {
    const res = await fetch("/api/auth/qr/start", { method: "POST" });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || "Gagal membuat sesi QR");

    state.qrLoginId = data.login_id;
    if (data.qr_image) {
      showQrImage(data.qr_image);
      document.getElementById("qrStatusMsg").textContent =
        "Silakan scan QR Code di atas menggunakan aplikasi Telegram Anda...";
    }

    if (state.qrPollTimer) clearInterval(state.qrPollTimer);
    state.qrPollTimer = setInterval(pollQrLoginStatus, 1500);
  } catch (err) {
    document.getElementById("qrStatusMsg").textContent = `Error: ${err.message}`;
  }
}

function showQrImage(dataUri) {
  const img = document.getElementById("qrCodeImg");
  img.src = dataUri;
  img.classList.remove("hidden");
  document.getElementById("qrLoadingSpinner").classList.add("hidden");
}

async function pollQrLoginStatus() {
  if (!state.qrLoginId) return;
  try {
    const res = await fetch(`/api/auth/qr/status/${state.qrLoginId}`);
    const data = await res.json();

    if (data.qr_image) {
      showQrImage(data.qr_image);
    }

    if (data.status === "need_2fa") {
      clearInterval(state.qrPollTimer);
      state.qrPollTimer = null;
      document.getElementById("qrScanStep").classList.add("hidden");
      document.getElementById("qr2faStep").classList.remove("hidden");
    } else if (data.status === "authorized") {
      clearInterval(state.qrPollTimer);
      state.qrPollTimer = null;
      state.qrLoginId = null;
      document.getElementById("qrModal").classList.add("hidden");
      await loadAccounts();
    } else if (data.status === "error" || data.status === "expired") {
      clearInterval(state.qrPollTimer);
      state.qrPollTimer = null;
      document.getElementById("qrStatusMsg").textContent =
        data.error || "Sesi QR berakhir. Tutup & buka kembali untuk mencoba lagi.";
    }
  } catch (err) {
    console.error("Poll QR gagal:", err);
  }
}

async function submitQr2fa() {
  const password = document.getElementById("inpQr2faPassword").value;
  if (!password) return alert("Masukkan password 2FA Anda");
  try {
    const res = await fetch("/api/auth/qr/2fa", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ login_id: state.qrLoginId, password }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || "Verifikasi 2FA gagal");

    state.qrLoginId = null;
    document.getElementById("qrModal").classList.add("hidden");
    await loadAccounts();
  } catch (err) {
    alert(err.message);
  }
}

async function closeQrModal() {
  if (state.qrPollTimer) {
    clearInterval(state.qrPollTimer);
    state.qrPollTimer = null;
  }
  if (state.qrLoginId) {
    fetch(`/api/auth/qr/cancel/${state.qrLoginId}`, { method: "POST" }).catch(() => {});
    state.qrLoginId = null;
  }
  document.getElementById("qrModal").classList.add("hidden");
}

// ==================== PHONE + OTP LOGIN ====================

function openPhoneModal() {
  state.phoneLoginId = null;
  document.getElementById("phoneModal").classList.remove("hidden");
  document.getElementById("phoneStep1").classList.remove("hidden");
  document.getElementById("phoneStep2").classList.add("hidden");
  document.getElementById("phone2faGroup").classList.add("hidden");
  document.getElementById("inpPhoneNumber").value = "";
  document.getElementById("inpPhoneOtp").value = "";
  document.getElementById("inpPhone2fa").value = "";
  document.getElementById("phoneModalError").textContent = "";
}

function closePhoneModal() {
  document.getElementById("phoneModal").classList.add("hidden");
}

async function sendPhoneCode() {
  const phone = document.getElementById("inpPhoneNumber").value.trim();
  const errEl = document.getElementById("phoneModalError");
  errEl.textContent = "";
  if (!phone) {
    errEl.textContent = "Masukkan nomor HP dengan kode negara (contoh: +62812...)";
    return;
  }

  try {
    const res = await fetch("/api/auth/phone/send-code", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ phone }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || "Gagal mengirim OTP");

    state.phoneLoginId = data.login_id;
    document.getElementById("phoneStep1").classList.add("hidden");
    document.getElementById("phoneStep2").classList.remove("hidden");
  } catch (err) {
    errEl.textContent = err.message;
  }
}

async function verifyPhoneOtp() {
  const code = document.getElementById("inpPhoneOtp").value.trim();
  const password = document.getElementById("inpPhone2fa").value;
  const errEl = document.getElementById("phoneModalError");
  errEl.textContent = "";

  try {
    const res = await fetch("/api/auth/phone/verify", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        login_id: state.phoneLoginId,
        code,
        password: password || null,
      }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || "Gagal verifikasi kode");

    if (data.status === "need_2fa") {
      document.getElementById("phone2faGroup").classList.remove("hidden");
      errEl.textContent = "Akun ini memiliki 2FA. Silakan isi password 2FA di atas lalu klik Verifikasi.";
      return;
    }

    closePhoneModal();
    await loadAccounts();
  } catch (err) {
    errEl.textContent = err.message;
  }
}

// ==================== PHOTOS POOL MANAGEMENT ====================

async function loadPhotos() {
  try {
    const res = await fetch("/api/photos");
    const data = await res.json();
    state.photos = data.photos || [];
    renderPhotos();
  } catch (err) {
    console.error("Gagal memuat galeri foto:", err);
  }
}

function renderPhotos() {
  document.getElementById("photoTotalCount").textContent = state.photos.length;
  const grid = document.getElementById("photosGrid");
  if (state.photos.length === 0) {
    grid.innerHTML = "";
    return;
  }
  grid.innerHTML = state.photos
    .map(
      (p) => `
      <div class="photo-thumb" title="${escapeHtml(p.name)} (${p.size_kb} KB)">
        <img src="${p.url}" alt="${escapeHtml(p.name)}" />
        <button onclick="deleteSinglePhoto('${escapeHtml(p.name)}')">&times;</button>
      </div>
    `
    )
    .join("");
}

async function uploadPhotoFiles(fileList) {
  if (!fileList || fileList.length === 0) return;
  const formData = new FormData();
  Array.from(fileList).forEach((f) => formData.append("files", f));
  await fetch("/api/photos/upload", {
    method: "POST",
    body: formData,
  });
  document.getElementById("photoUploadInput").value = "";
  await loadPhotos();
}

async function deleteSinglePhoto(filename) {
  await fetch(`/api/photos/${encodeURIComponent(filename)}`, { method: "DELETE" });
  await loadPhotos();
}

async function clearAllPhotos() {
  if (state.photos.length === 0) return;
  if (!confirm("Hapus semua foto dari galeri?")) return;
  await fetch("/api/photos", { method: "DELETE" });
  await loadPhotos();
}

// ==================== PARALLEL GROUP CREATION ====================

async function startParallelCreation() {
  const selectedIds = state.accounts
    .filter((a) => state.selectedAccountIds.has(a.id))
    .map((a) => a.id);

  if (selectedIds.length === 0) {
    alert("Pilih minimal 1 akun Telegram terlebih dahulu!");
    return;
  }

  const randomLines = document
    .getElementById("inpRandomNames")
    .value.split("\n")
    .map((s) => s.trim())
    .filter(Boolean);

  const payload = {
    account_ids: selectedIds,
    groups_per_account: parseInt(document.getElementById("inpGroupsPerAccount").value, 10) || 1,
    delay_seconds: parseFloat(document.getElementById("inpDelaySeconds").value) || 0,
    group_type: getRadioValue("group_type"),
    visibility: getRadioValue("visibility"),
    group_about: document.getElementById("inpGroupAbout").value.trim(),
    permission_mode: getRadioValue("permission_mode"),
    naming_mode: getRadioValue("naming_mode"),
    base_name: document.getElementById("inpBaseName").value.trim() || "Grup Baru",
    sequence_start: parseInt(document.getElementById("inpSeqStart").value, 10) || 1,
    sequence_scope: document.getElementById("selSeqScope").value,
    sequence_separator: document.getElementById("inpSeqSeparator").value || " | ",
    random_names: randomLines,
    random_with_sequence: document.getElementById("chkRandomWithSequence").checked,
    use_random_photo: document.getElementById("chkUseRandomPhoto").checked,
    invite_joinhider: document.getElementById("chkInviteJoinHider").checked,
    joinhider_username:
      document.getElementById("inpJoinHiderUsername").value.trim() || "@joinhiderrobot",
    joinhider_permissions: {
      delete_messages: document.getElementById("chkJhDeleteMsg").checked,
      other: document.getElementById("chkJhOther").checked,
      ban_users: document.getElementById("chkJhBanUsers").checked,
      invite_users: document.getElementById("chkJhInviteUsers").checked,
      pin_messages: document.getElementById("chkJhPinMsg").checked,
      manage_call: false,
    },
    invite_mutual_contacts: document.getElementById("chkInviteMutuals").checked,
    promote_mutual_to_admin: document.getElementById("chkPromoteMutualAdmin").checked,
    selected_mutual_ids_by_account: state.selectedMutualsByAccount,
  };

  try {
    const res = await fetch("/api/tasks/start", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || "Gagal memulai proses pembuatan grup");
    applyTaskState(data.status);
  } catch (err) {
    alert(err.message);
  }
}

async function stopParallelCreation() {
  await fetch("/api/tasks/stop", { method: "POST" });
}

// ==================== TAB 2: CLEAR GROUP CHAT HISTORY (FOR ALL MEMBERS) ====================

function getFilteredClearGroups() {
  const accFilter = document.getElementById("selFilterCreatorAccount").value || "ALL";
  const q = (document.getElementById("inpSearchClearGroup").value || "").trim().toLowerCase();

  return state.createdGroups.filter((g) => {
    if (accFilter !== "ALL" && g.account_id !== accFilter) return false;
    if (q && !(g.title || "").toLowerCase().includes(q) && !String(g.id || "").includes(q)) {
      return false;
    }
    return true;
  });
}

function renderClearGroupsTable() {
  document.getElementById("tabGroupsCountBadge").textContent = state.createdGroups.length;
  const filtered = getFilteredClearGroups();
  document.getElementById("totalClearGroupCount").textContent = filtered.length;

  const selectedInFiltered = filtered.filter((g) =>
    state.selectedClearGroupKeys.has(g.group_key)
  );
  document.getElementById("selectedClearGroupCount").textContent = selectedInFiltered.length;
  document.getElementById("chkSelectAllClearGroups").checked =
    filtered.length > 0 && selectedInFiltered.length === filtered.length;

  const tbody = document.getElementById("clearGroupsTbody");
  if (filtered.length === 0) {
    tbody.innerHTML = `
      <tr>
        <td colspan="8" class="text-center muted">
          Belum ada grup yang ditampilkan. Buat grup di tab <b>Buat Grup Paralel</b> atau klik tombol <b>🔄 Sinkronisasi Grup dari Akun Pembuat</b>.
        </td>
      </tr>
    `;
    return;
  }

  const reversed = [...filtered].reverse();
  tbody.innerHTML = reversed
    .map((g) => {
      const checked = state.selectedClearGroupKeys.has(g.group_key) ? "checked" : "";
      const lastCleared = g.last_cleared_at
        ? `<span class="pill pill-on">✓ ${escapeHtml(g.last_cleared_at)} (${g.last_deleted_count || 0} pesan)</span>`
        : `<span class="muted">Belum pernah</span>`;

      return `
      <tr>
        <td>
          <input type="checkbox" class="clear-grp-chk" data-key="${escapeHtml(g.group_key)}" ${checked} />
        </td>
        <td><strong>${escapeHtml(g.title)}</strong></td>
        <td><code>${escapeHtml(g.id)}</code></td>
        <td>${escapeHtml(g.type || "Supergroup")}</td>
        <td><span class="pill pill-on">${escapeHtml(g.account_label || g.account_id)}</span></td>
        <td>${escapeHtml(g.created_at || "-")}</td>
        <td>${lastCleared}</td>
        <td>
          <div class="btn-group">
            <button class="btn btn-sm btn-danger-solid" onclick="clearSingleGroupNow('${escapeHtml(g.group_key)}', '${escapeHtml(g.title)}')">
              🧹 Hapus Riwayat
            </button>
            <button class="btn btn-sm btn-danger-outline" onclick="removeGroupFromList('${escapeHtml(g.group_key)}')" title="Hapus dari daftar">
              &times;
            </button>
          </div>
        </td>
      </tr>
    `;
    })
    .join("");

  tbody.querySelectorAll(".clear-grp-chk").forEach((cb) => {
    cb.addEventListener("change", (e) => {
      const key = e.target.getAttribute("data-key");
      if (e.target.checked) {
        state.selectedClearGroupKeys.add(key);
      } else {
        state.selectedClearGroupKeys.delete(key);
      }
      renderClearGroupsTable();
    });
  });
}

async function syncCreatorGroups() {
  const btn = document.getElementById("btnSyncCreatorGroups");
  const origText = btn.innerHTML;
  btn.disabled = true;
  btn.innerHTML = `<span>⏳ Memindai Grup dari Akun Pembuat...</span>`;
  try {
    const res = await fetch("/api/groups/sync", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ account_ids: null }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || "Gagal sinkronisasi grup");
    setCreatedGroupsList(data.groups || []);
  } catch (err) {
    alert(err.message);
  } finally {
    btn.disabled = false;
    btn.innerHTML = origText;
  }
}

async function clearSingleGroupNow(groupKey, groupTitle) {
  if (
    !confirm(
      `Hapus SEMUA riwayat chat di grup "${groupTitle}" untuk SEMUA MEMBER menggunakan akun pembuat grupnya?`
    )
  ) {
    return;
  }
  await executeClearHistoryForKeys([groupKey]);
}

async function startBatchClearHistory() {
  const filtered = getFilteredClearGroups();
  const keys = filtered
    .filter((g) => state.selectedClearGroupKeys.has(g.group_key))
    .map((g) => g.group_key);

  if (keys.length === 0) {
    alert("Centang minimal 1 grup yang ingin dihapus riwayat chatnya!");
    return;
  }

  if (
    !confirm(
      `Yakin ingin menghapus SEMUA riwayat chat (untuk semua member) pada ${keys.length} grup terpilih menggunakan akun pembuatnya masing-masing?`
    )
  ) {
    return;
  }

  await executeClearHistoryForKeys(keys);
}

async function executeClearHistoryForKeys(groupKeys) {
  const delay = parseFloat(document.getElementById("inpClearDelaySeconds").value) || 0;
  try {
    const res = await fetch("/api/groups/clear-history/start", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        group_keys: groupKeys,
        delay_seconds: delay,
      }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || "Gagal memulai hapus riwayat chat");
    applyTaskState(data.status);
  } catch (err) {
    alert(err.message);
  }
}

async function stopBatchClearHistory() {
  await fetch("/api/groups/clear-history/stop", { method: "POST" });
}

async function removeGroupFromList(groupKey) {
  await fetch(`/api/groups/${encodeURIComponent(groupKey)}`, { method: "DELETE" });
  state.selectedClearGroupKeys.delete(groupKey);
  state.createdGroups = state.createdGroups.filter((g) => g.group_key !== groupKey);
  renderClearGroupsTable();
}

function setCreatedGroupsList(groups) {
  const prevKnown = new Set(state.createdGroups.map((g) => g.group_key));
  state.createdGroups = groups || [];
  state.createdGroups.forEach((g) => {
    if (!prevKnown.has(g.group_key)) {
      state.selectedClearGroupKeys.add(g.group_key);
    }
  });
  populateCreatorFilterSelect();
  renderClearGroupsTable();
  renderCreatedGroupsTable(state.createdGroups);
}

// ==================== WEBSOCKET & LIVE TELEMETRY ====================

function connectWebSocket() {
  const proto = location.protocol === "https:" ? "wss:" : "ws:";
  const ws = new WebSocket(`${proto}//${location.host}/ws`);

  ws.onopen = () => {
    const badge = document.getElementById("wsStatusBadge");
    badge.className = "badge badge-connected";
    document.getElementById("wsStatusText").textContent = "Terhubung Live";
  };

  ws.onmessage = (event) => {
    const msg = JSON.parse(event.data);
    if (msg.type === "init") {
      applyTaskState(msg.data);
      const logs = msg.data.logs || [];
      const box = document.getElementById("terminalLogBox");
      box.innerHTML = "";
      logs.forEach(appendLogLine);
    } else if (msg.type === "state") {
      applyTaskState(msg.data);
    } else if (msg.type === "log") {
      appendLogLine(msg.data);
    } else if (msg.type === "group_created") {
      const g = msg.data;
      const existingIdx = state.createdGroups.findIndex((x) => x.group_key === g.group_key);
      if (existingIdx >= 0) {
        state.createdGroups[existingIdx] = g;
      } else {
        state.createdGroups.push(g);
        state.selectedClearGroupKeys.add(g.group_key);
      }
      populateCreatorFilterSelect();
      renderClearGroupsTable();
      renderCreatedGroupsTable(state.createdGroups);
    }
  };

  ws.onclose = () => {
    const badge = document.getElementById("wsStatusBadge");
    badge.className = "badge badge-connecting";
    document.getElementById("wsStatusText").textContent = "Menyambung ulang...";
    setTimeout(connectWebSocket, 2000);
  };
}

function applyTaskState(statusData) {
  if (!statusData) return;
  state.isRunning = Boolean(statusData.is_running);
  state.isClearingHistory = Boolean(statusData.is_clearing_history);

  const globalBadge = document.getElementById("taskGlobalBadge");
  if (state.isRunning) {
    globalBadge.className = "badge badge-running";
    globalBadge.textContent = "BUAT GRUP BERJALAN";
  } else if (state.isClearingHistory) {
    globalBadge.className = "badge badge-running";
    globalBadge.textContent = "HAPUS RIWAYAT BERJALAN";
  } else {
    globalBadge.className = "badge badge-idle";
    globalBadge.textContent = "IDLE";
  }

  document.getElementById("btnStartCreation").classList.toggle("hidden", state.isRunning);
  document.getElementById("btnStopCreation").classList.toggle("hidden", !state.isRunning);

  document.getElementById("btnStartClearHistory").classList.toggle("hidden", state.isClearingHistory);
  document.getElementById("btnStopClearHistory").classList.toggle("hidden", !state.isClearingHistory);

  document.getElementById("totalCreatedCount").textContent = statusData.total_created || 0;

  renderWorkersProgress(statusData.account_progress || {});
  renderClearWorkersProgress(statusData.clear_progress || {});

  if (statusData.created_groups) {
    setCreatedGroupsList(statusData.created_groups);
  }
}

function renderWorkersProgress(progressMap) {
  const entries = Object.values(progressMap);
  const container = document.getElementById("workersProgressList");
  if (entries.length === 0) {
    container.innerHTML = `<div class="empty-state">Belum ada proses pembuatan grup berjalan.</div>`;
    return;
  }

  container.innerHTML = entries
    .map((p) => {
      const pct = p.target > 0 ? Math.min(100, Math.round((p.completed / p.target) * 100)) : 0;
      let badgeHtml = `<span class="pill pill-on">${escapeHtml(p.status.toUpperCase())}</span>`;
      if (p.status === "floodwait") {
        badgeHtml = `<span class="pill" style="background:rgba(245,158,11,0.25);color:#fcd34d;">⏳ FLOODWAIT ${p.floodwait_seconds}s</span>`;
      } else if (p.status === "error") {
        badgeHtml = `<span class="pill pill-off">ERROR</span>`;
      }

      return `
      <div class="worker-card">
        <div class="worker-top">
          <strong>${escapeHtml(p.label)} (${p.completed}/${p.target} grup)</strong>
          ${badgeHtml}
        </div>
        <div class="worker-bar-bg">
          <div class="worker-bar-fill" style="width:${pct}%"></div>
        </div>
        <div class="worker-step">${escapeHtml(p.current_step || "-")}</div>
      </div>
    `;
    })
    .join("");
}

function renderClearWorkersProgress(progressMap) {
  const entries = Object.values(progressMap);
  const wrap = document.getElementById("clearWorkersWrap");
  const container = document.getElementById("clearWorkersProgressList");
  if (entries.length === 0) {
    wrap.classList.add("hidden");
    container.innerHTML = "";
    return;
  }

  wrap.classList.remove("hidden");
  container.innerHTML = entries
    .map((p) => {
      const pct = p.target > 0 ? Math.min(100, Math.round((p.completed / p.target) * 100)) : 0;
      let badgeHtml = `<span class="pill pill-on">${escapeHtml(p.status.toUpperCase())}</span>`;
      if (p.status === "floodwait") {
        badgeHtml = `<span class="pill" style="background:rgba(245,158,11,0.25);color:#fcd34d;">⏳ FLOODWAIT ${p.floodwait_seconds}s</span>`;
      } else if (p.status === "error") {
        badgeHtml = `<span class="pill pill-off">ERROR</span>`;
      }

      return `
      <div class="worker-card">
        <div class="worker-top">
          <strong>${escapeHtml(p.label)} (${p.completed}/${p.target} grup &bull; ${p.deleted_messages || 0} pesan dihapus)</strong>
          ${badgeHtml}
        </div>
        <div class="worker-bar-bg">
          <div class="worker-bar-fill" style="width:${pct}%"></div>
        </div>
        <div class="worker-step">${escapeHtml(p.current_step || "-")}</div>
      </div>
    `;
    })
    .join("");
}

function renderCreatedGroupsTable(groups) {
  const tbody = document.getElementById("createdGroupsTbody");
  if (!groups || groups.length === 0) {
    tbody.innerHTML = `<tr><td colspan="7" class="text-center muted">Belum ada grup yang dibuat.</td></tr>`;
    return;
  }
  const reversed = [...groups].slice(-100).reverse();
  tbody.innerHTML = reversed
    .map(
      (g) => `
      <tr>
        <td>${escapeHtml(g.created_at)}</td>
        <td><strong>${escapeHtml(g.title)}</strong></td>
        <td>${escapeHtml(g.type)} (${escapeHtml(g.visibility)})</td>
        <td>${escapeHtml(g.permissions)}</td>
        <td>${escapeHtml(g.photo)}</td>
        <td>${g.mutual_admins || 0} Admin</td>
        <td>${escapeHtml(g.account_label)}</td>
      </tr>
    `
    )
    .join("");
}

function appendLogLine(entry) {
  const box = document.getElementById("terminalLogBox");
  const div = document.createElement("div");
  div.className = `log-line log-${entry.level || "info"}`;
  div.innerHTML = `<span class="log-time">[${escapeHtml(entry.timestamp)}]</span> <span class="log-acc">[${escapeHtml(entry.account_label)}]</span> ${escapeHtml(entry.message)}`;
  box.appendChild(div);
  box.scrollTop = box.scrollHeight;
}

function escapeHtml(str) {
  return String(str ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}

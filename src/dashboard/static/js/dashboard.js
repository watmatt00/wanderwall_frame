/**
 * WanderWall Dashboard JavaScript
 * Based on v3 dashboard functionality
 */

let sourcesInitialized = false;
let settingsInitialized = false;

document.addEventListener('DOMContentLoaded', () => {
    initTabSwitching();
    initAdvancedToggles();
    initStatusDashboard();
    initSettingsForm();
    initDeviceManagement();
    initSettingsLogViewer();
    initPhotoTools();
});

// =============================================================================
// TAB SWITCHING
// =============================================================================

function initTabSwitching() {
    document.querySelectorAll('.tab-button').forEach(button => {
        button.addEventListener('click', () => {
            const tabId = button.getAttribute('data-tab');
            switchTab(tabId);
        });
    });
}

function switchTab(tabId) {
    // Update tab buttons
    document.querySelectorAll('.tab-button').forEach(btn => {
        btn.classList.remove('active');
    });
    document.querySelector(`[data-tab="${tabId}"]`).classList.add('active');

    // Update tab content
    document.querySelectorAll('.tab-content').forEach(content => {
        content.classList.remove('active');
    });
    document.getElementById(`tab-${tabId}`).classList.add('active');

    // Initialize or refresh sources when tab is opened
    if (tabId === 'sources') {
        if (!sourcesInitialized) {
            initSourcesManager();
            sourcesInitialized = true;
        } else {
            loadSources();
        }
    }

    // Tools tab: reload the album picker on every open (albums may have changed since)
    if (tabId === 'tools') {
        loadToolsSources();
    }

    // Backups tab: reload on every open, since albums may have been added or
    // deleted since (Albums tab, the app). Keeps the picked album if it still exists.
    if (tabId === 'backups') {
        loadBackupSources();
        const recover = document.getElementById('recover-section');
        if (recover && recover.style.display !== 'none') loadRecoverable();
    }
}

// =============================================================================
// ADVANCED TOGGLES
// =============================================================================

function initAdvancedToggles() {
    // Helper: pointer cursor on header when collapsed, default when expanded
    function updateHeaderCursor(header, section) {
        header.classList.toggle('card-header--expandable', !section.classList.contains('visible'));
    }

    function expandSection(section, btn) {
        section.classList.add('visible');
        btn.textContent = 'Close';
    }

    function collapseSection(section, btn) {
        section.classList.remove('visible');
        btn.textContent = 'Show';
    }

    // Settings logs toggle
    const settingsLogsToggle = document.getElementById('settings-logs-toggle');
    const settingsLogsSection = document.getElementById('settings-logs-section');
    if (settingsLogsToggle && settingsLogsSection) {
        const settingsLogsHeader = settingsLogsToggle.closest('.card-header');
        settingsLogsToggle.addEventListener('click', (e) => {
            e.stopPropagation();
            if (settingsLogsSection.classList.contains('visible')) {
                collapseSection(settingsLogsSection, settingsLogsToggle);
            } else {
                expandSection(settingsLogsSection, settingsLogsToggle);
                loadSettingsLogs();
            }
            updateHeaderCursor(settingsLogsHeader, settingsLogsSection);
        });
        settingsLogsHeader.addEventListener('click', () => {
            if (!settingsLogsSection.classList.contains('visible')) {
                expandSection(settingsLogsSection, settingsLogsToggle);
                loadSettingsLogs();
                updateHeaderCursor(settingsLogsHeader, settingsLogsSection);
            }
        });
        updateHeaderCursor(settingsLogsHeader, settingsLogsSection);
    }

    // Mobile App Pairing card toggle
    const pairingToggle = document.getElementById('pairing-toggle');
    const pairingSection = document.getElementById('pairing-section');
    if (pairingToggle && pairingSection) {
        const pairingHeader = pairingToggle.closest('.card-header');
        pairingToggle.addEventListener('click', (e) => {
            e.stopPropagation();
            if (pairingSection.classList.contains('visible')) {
                collapseSection(pairingSection, pairingToggle);
                const devicesCard = document.getElementById('devices-card');
                const toggleBtn = document.getElementById('btn-toggle-devices');
                if (devicesCard) devicesCard.style.display = 'none';
                if (toggleBtn) toggleBtn.textContent = 'Manage Devices';
            } else {
                expandSection(pairingSection, pairingToggle);
            }
            updateHeaderCursor(pairingHeader, pairingSection);
        });
        pairingHeader.addEventListener('click', () => {
            if (!pairingSection.classList.contains('visible')) {
                expandSection(pairingSection, pairingToggle);
                updateHeaderCursor(pairingHeader, pairingSection);
            }
        });
        updateHeaderCursor(pairingHeader, pairingSection);
    }

    // Frame Settings card toggle
    const settingsFormToggle = document.getElementById('settings-form-toggle');
    const settingsFormSection = document.getElementById('settings-form-section');
    if (settingsFormToggle && settingsFormSection) {
        const settingsFormHeader = settingsFormToggle.closest('.card-header');
        settingsFormToggle.addEventListener('click', (e) => {
            e.stopPropagation();
            if (settingsFormSection.classList.contains('visible')) {
                collapseSection(settingsFormSection, settingsFormToggle);
            } else {
                expandSection(settingsFormSection, settingsFormToggle);
            }
            updateHeaderCursor(settingsFormHeader, settingsFormSection);
        });
        settingsFormHeader.addEventListener('click', () => {
            if (!settingsFormSection.classList.contains('visible')) {
                expandSection(settingsFormSection, settingsFormToggle);
                updateHeaderCursor(settingsFormHeader, settingsFormSection);
            }
        });
        updateHeaderCursor(settingsFormHeader, settingsFormSection);
    }

    // Network info sub-card toggle (no card-header class — button only, unchanged)
    const networkInfoToggle = document.getElementById('network-info-toggle');
    const networkInfoSection = document.getElementById('network-info-section');
    if (networkInfoToggle && networkInfoSection) {
        networkInfoToggle.addEventListener('click', () => {
            networkInfoSection.classList.toggle('visible');
            networkInfoToggle.textContent = networkInfoSection.classList.contains('visible')
                ? 'Close'
                : 'Show';
        });
    }

    const koofrSettingsToggle = document.getElementById('koofr-settings-toggle');
    const koofrSettingsSection = document.getElementById('koofr-settings-section');
    if (koofrSettingsToggle && koofrSettingsSection) {
        koofrSettingsToggle.addEventListener('click', () => {
            koofrSettingsSection.classList.toggle('visible');
            koofrSettingsToggle.textContent = koofrSettingsSection.classList.contains('visible')
                ? 'Close'
                : 'Show';
        });
    }

    // Sleep schedule sub-card toggle
    const sleepScheduleToggle = document.getElementById('sleep-schedule-toggle');
    const sleepScheduleSection = document.getElementById('sleep-schedule-section');
    if (sleepScheduleToggle && sleepScheduleSection) {
        sleepScheduleToggle.addEventListener('click', () => {
            sleepScheduleSection.classList.toggle('visible');
            sleepScheduleToggle.textContent = sleepScheduleSection.classList.contains('visible') ? 'Close' : 'Show';
        });
    }

    // Sleep schedule save
    const btnSaveSleep = document.getElementById('btn-save-sleep');
    if (btnSaveSleep) {
        btnSaveSleep.addEventListener('click', async () => {
            const msg = document.getElementById('sleep-schedule-msg');
            const enabled = document.getElementById('sleep-enabled-checkbox').checked;
            const sleepTime = document.getElementById('sleep-time-input').value;
            const wakeTime = document.getElementById('wake-time-input').value;
            if (msg) msg.textContent = 'Saving…';
            try {
                const resp = await fetch('/api/settings/sleep-schedule', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ enabled, sleep_time: sleepTime, wake_time: wakeTime }),
                });
                const data = await resp.json();
                if (msg) {
                    msg.textContent = data.message || (data.success ? 'Saved' : 'Error');
                    msg.style.color = data.success ? '#4ade80' : '#f87171';
                }
            } catch (e) {
                if (msg) { msg.textContent = 'Request failed'; msg.style.color = '#f87171'; }
            }
        });
    }

    // Updates card toggle
    const updatesToggle = document.getElementById('updates-toggle');
    const updatesSection = document.getElementById('updates-section');
    if (updatesToggle && updatesSection) {
        const updatesHeader = updatesToggle.closest('.card-header');
        updatesToggle.addEventListener('click', (e) => {
            e.stopPropagation();
            if (updatesSection.classList.contains('visible')) {
                collapseSection(updatesSection, updatesToggle);
            } else {
                expandSection(updatesSection, updatesToggle);
            }
            updateHeaderCursor(updatesHeader, updatesSection);
        });
        updatesHeader.addEventListener('click', () => {
            if (!updatesSection.classList.contains('visible')) {
                expandSection(updatesSection, updatesToggle);
                updateHeaderCursor(updatesHeader, updatesSection);
            }
        });
        updateHeaderCursor(updatesHeader, updatesSection);
    }

    // Demo Mode card toggle
    const demoToggle = document.getElementById('demo-toggle');
    const demoSection = document.getElementById('demo-section');
    if (demoToggle && demoSection) {
        const demoHeader = demoToggle.closest('.card-header');
        demoToggle.addEventListener('click', (e) => {
            e.stopPropagation();
            if (demoSection.classList.contains('visible')) {
                collapseSection(demoSection, demoToggle);
            } else {
                expandSection(demoSection, demoToggle);
            }
            updateHeaderCursor(demoHeader, demoSection);
        });
        demoHeader.addEventListener('click', () => {
            if (!demoSection.classList.contains('visible')) {
                expandSection(demoSection, demoToggle);
                updateHeaderCursor(demoHeader, demoSection);
            }
        });
        updateHeaderCursor(demoHeader, demoSection);
    }

    // Party Mode card toggle
    const partyToggle = document.getElementById('party-toggle');
    const partySection = document.getElementById('party-section');
    if (partyToggle && partySection) {
        const partyHeader = partyToggle.closest('.card-header');
        partyToggle.addEventListener('click', (e) => {
            e.stopPropagation();
            if (partySection.classList.contains('visible')) {
                collapseSection(partySection, partyToggle);
            } else {
                expandSection(partySection, partyToggle);
            }
            updateHeaderCursor(partyHeader, partySection);
        });
        partyHeader.addEventListener('click', () => {
            if (!partySection.classList.contains('visible')) {
                expandSection(partySection, partyToggle);
                updateHeaderCursor(partyHeader, partySection);
            }
        });
        updateHeaderCursor(partyHeader, partySection);
    }

    // Photo Backups card toggle
    const backupToggle = document.getElementById('backup-toggle');
    const backupSection = document.getElementById('backup-section');
    if (backupToggle && backupSection) {
        const backupHeader = backupToggle.closest('.card-header');
        backupToggle.addEventListener('click', (e) => {
            e.stopPropagation();
            if (backupSection.classList.contains('visible')) {
                collapseSection(backupSection, backupToggle);
            } else {
                expandSection(backupSection, backupToggle);
                loadBackupList();
            }
            updateHeaderCursor(backupHeader, backupSection);
        });
        backupHeader.addEventListener('click', () => {
            if (!backupSection.classList.contains('visible')) {
                expandSection(backupSection, backupToggle);
                loadBackupList();
                updateHeaderCursor(backupHeader, backupSection);
            }
        });
        updateHeaderCursor(backupHeader, backupSection);
    }

    // Sources table advanced toggle (column visibility — unchanged)
    const sourcesTableToggle = document.getElementById('sources-table-advanced-toggle');
    const sourcesTable = document.getElementById('sources-table');
    if (sourcesTableToggle && sourcesTable) {
        sourcesTableToggle.addEventListener('click', () => {
            sourcesTable.classList.toggle('show-tech');
            sourcesTableToggle.textContent = sourcesTable.classList.contains('show-tech')
                ? '▾ Hide technical columns'
                : '▸ Show technical columns';
        });
    }
}

// =============================================================================
// STATUS DASHBOARD
// =============================================================================

function initStatusDashboard() {
    const bannerText = document.getElementById("banner-text");
    const bannerPill = document.getElementById("banner-pill");
    const bannerUpdated = document.getElementById("banner-updated");
    const topBanner = document.getElementById("top-banner");

    const overallTitle = document.getElementById("overall-title");
    const overallChip = document.getElementById("overall-chip");

    const trafficGreen = document.getElementById("traffic-green");
    const trafficAmber = document.getElementById("traffic-amber");
    const trafficRed = document.getElementById("traffic-red");

    const remoteCountEl = document.getElementById("remote-count");
    const localCountEl = document.getElementById("local-count");

    const webDot = document.getElementById("web-status-dot");
    const webText = document.getElementById("web-status-text");
    const pfDot = document.getElementById("pf-status-dot");
    const pfText = document.getElementById("pf-status-text");
    const currentRemoteEl = document.getElementById("current-remote");
    const storageIndicator = document.getElementById("storage-indicator");
    const storageText = document.getElementById("storage-text");

    const lastSyncEl = document.getElementById("last-sync");
    const nextSyncEl = document.getElementById("next-sync");
    const lastRestartEl = document.getElementById("last-restart");

    const syncTimerDot  = document.getElementById("sync-timer-dot");
    const syncTimerText = document.getElementById("sync-timer-text");
    const lightsDot     = document.getElementById("lights-dot");
    const lightsText    = document.getElementById("lights-text");
    const tailscaleDot  = document.getElementById("tailscale-dot");
    const tailscaleText = document.getElementById("tailscale-text");
    const apiHealthDot  = document.getElementById("api-health-dot");
    const apiHealthText = document.getElementById("api-health-text");

    const btnRefresh = document.getElementById("btn-refresh");
    const btnSyncNow = document.getElementById("btn-sync-now");
    const btnSyncNowSpinner = document.getElementById("btn-sync-now-spinner");
    const btnSyncNowLabel = document.getElementById("btn-sync-now-label");
    const btnRestartPf = document.getElementById("btn-restart-pf");
    const btnRestartPfSpinner = document.getElementById("btn-restart-pf-spinner");
    const btnRestartPfLabel = document.getElementById("btn-restart-pf-label");
    const btnRestartApi = document.getElementById("btn-restart-api");
    const btnRestartApiSpinner = document.getElementById("btn-restart-api-spinner");
    const btnRestartApiLabel = document.getElementById("btn-restart-api-label");

    function setServiceDot(dotEl, textEl, status) {
        if (!dotEl || !textEl) return;
        const s = (status || "").toLowerCase();
        const up = s === "active" || s === "running";
        dotEl.classList.toggle("off", !up);
        textEl.textContent = up ? "RUNNING" : (status || "UNKNOWN").toUpperCase();
    }

    function setStorageDisplay(percent) {
        if (!storageIndicator) return;
        if (percent < 70) {
            storageIndicator.className = "storage-indicator ok";
        } else if (percent < 90) {
            storageIndicator.className = "storage-indicator warn";
        } else {
            storageIndicator.className = "storage-indicator error";
        }
    }

    function setTrafficLights(severity) {
        if (!trafficGreen || !trafficAmber || !trafficRed) return;
        const sev = (severity || "UNKNOWN").toUpperCase();
        trafficGreen.classList.add("off");
        trafficAmber.classList.add("off");
        trafficRed.classList.add("off");

        if (sev === "OK" || sev === "MATCH") {
            trafficGreen.classList.remove("off");
        } else if (sev === "WARN" || sev === "SYNCING") {
            trafficAmber.classList.remove("off");
        } else if (sev === "ERROR" || sev === "MISMATCH") {
            trafficRed.classList.remove("off");
        } else {
            trafficAmber.classList.remove("off");
        }
    }

    function setBannerForSeverity(severity) {
        if (!topBanner || !bannerPill) return;
        const sev = (severity || "UNKNOWN").toUpperCase();
        if (sev === "OK" || sev === "MATCH") {
            topBanner.style.background = "linear-gradient(90deg, #0b7a39, #059669)";
            bannerPill.textContent = "OK";
        } else if (sev === "WARN" || sev === "SYNCING") {
            topBanner.style.background = "linear-gradient(90deg, #92400e, #f97316)";
            bannerPill.textContent = "SYNCING";
        } else if (sev === "ERROR" || sev === "MISMATCH") {
            topBanner.style.background = "linear-gradient(90deg, #b91c1c, #ef4444)";
            bannerPill.textContent = "ERROR";
        } else {
            topBanner.style.background = "linear-gradient(90deg, #4b5563, #6b7280)";
            bannerPill.textContent = "UNKNOWN";
        }
    }

    async function refreshStatus() {
        if (btnRefresh) btnRefresh.disabled = true;
        try {
            const resp = await fetch("/dashboard/status");
            const data = await resp.json();
            updateDemoBanner(data.demo);
            updateRegistryBanners(data.registry);

            const nowStr = new Date().toLocaleString();
            if (bannerUpdated) bannerUpdated.textContent = "Updated: " + nowStr;

            // Sync status
            const syncStatus = data.sync_status || "idle";
            const cloudCount = data.remote_count || 0;
            const localCount = data.local_count || 0;
            const countsMatch = cloudCount === localCount;

            const severity = syncStatus === "syncing" ? "SYNCING" :
                            syncStatus === "error" ? "ERROR" :
                            !countsMatch ? "WARN" :
                            syncStatus === "match" ? "OK" :
                            syncStatus === "idle" ? "OK" : "UNKNOWN";

            if (overallTitle) {
                overallTitle.textContent = syncStatus === "syncing" ? "Syncing photos..." :
                                           syncStatus === "error" ? "Sync error" :
                                           !countsMatch ? `Out of sync (${cloudCount} cloud / ${localCount} local)` :
                                           syncStatus === "match" ? "Photos in sync" :
                                           syncStatus === "idle" ? "Photos in sync" : "Checking status...";
            }
            if (overallChip) {
                overallChip.textContent = severity;
                overallChip.classList.remove("error", "warn");
                if (severity === "ERROR") overallChip.classList.add("error");
                else if (severity === "SYNCING") overallChip.classList.add("warn");
            }
            if (bannerText) bannerText.textContent = overallTitle ? overallTitle.textContent : "Photo sync status";

            setTrafficLights(severity);
            setBannerForSeverity(severity);

            // Counts
            if (remoteCountEl) remoteCountEl.textContent = data.remote_count || "--";
            if (localCountEl) localCountEl.textContent = data.local_count || "--";

            // Services
            const services = data.services || [];
            const pfService = services.find(s => s.name === "picframe" || s.name === "picframe.service");
            const apiService = services.find(s => s.name === "wanderwall-api" || s.name === "wanderwall-api.service");

            setServiceDot(pfDot, pfText, pfService?.active ? "active" : "inactive");
            setServiceDot(webDot, webText, "active"); // Dashboard is always running if we're here
            setServiceDot(syncTimerDot,  syncTimerText,  data.sync_timer_status);
            setServiceDot(lightsDot,     lightsText,     data.lights_status);
            setServiceDot(tailscaleDot,  tailscaleText,  data.tailscale_status);
            setServiceDot(apiHealthDot,  apiHealthText,  data.api_health_status);

            // Current source
            if (currentRemoteEl) currentRemoteEl.textContent = data.current_source || "--";

            // Storage
            if (storageText) storageText.textContent = `${data.storage_percent || 0}% (${data.storage_used || 0} / ${data.storage_total || 0} GB)`;
            setStorageDisplay(data.storage_percent || 0);

            // Last sync and restart
            if (lastSyncEl) lastSyncEl.textContent = data.last_sync || "--";
            if (nextSyncEl) nextSyncEl.textContent = data.next_sync || "--";
            if (lastRestartEl) lastRestartEl.textContent = data.last_restart || "--";

            // Cycle time
            const rotInterval = data.rotation_interval || 0;
            const lc = data.local_count || 0;
            const cycleEl = document.getElementById('cycle-time-value');
            const cycleHint = document.getElementById('cycle-time-hint');
            if (rotInterval > 0 && lc > 0) {
                const secs = rotInterval * lc;
                const h = Math.floor(secs / 3600);
                const m = Math.floor((secs % 3600) / 60);
                const s = secs % 60;
                const fmt = h > 0 ? `${h}h ${m}m` : m > 0 ? `${m}m ${s}s` : `${s}s`;
                if (cycleEl) cycleEl.textContent = fmt;
                if (cycleHint) cycleHint.textContent = `Cycles all ${lc} photos in ${fmt}`;
            } else {
                if (cycleEl) cycleEl.textContent = '—';
                if (cycleHint) cycleHint.textContent = '—';
            }


        } catch (err) {
            console.error("Failed to refresh status", err);
            if (bannerText) bannerText.textContent = "Error fetching status";
            setBannerForSeverity("ERROR");
        } finally {
            if (btnRefresh) btnRefresh.disabled = false;
        }
    }

    async function syncNow() {
        if (!btnSyncNow) return;
        btnSyncNow.disabled = true;
        if (btnSyncNowSpinner) btnSyncNowSpinner.style.display = "inline-block";
        if (btnSyncNowLabel) btnSyncNowLabel.textContent = "Syncing...";

        try {
            const resp = await fetch("/sync", { method: "POST" });
            const data = await resp.json();
            if (data.error) {
                const msg = data.error.includes("Koofr setup")
                    ? "Cloud sync not configured yet — go to Settings → Cloud Sync (Koofr) to connect."
                    : "Sync error: " + data.error;
                alert(msg);
            } else {
                alert("Sync started!");
                setTimeout(refreshStatus, 2000);
            }
        } catch (err) {
            console.error("Failed to sync", err);
            alert("Error syncing: " + err);
        } finally {
            btnSyncNow.disabled = false;
            if (btnSyncNowSpinner) btnSyncNowSpinner.style.display = "none";
            if (btnSyncNowLabel) btnSyncNowLabel.textContent = "🔄 Sync Now";
        }
    }

    async function restartPfService() {
        if (!btnRestartPf) return;
        if (!confirm("Restart the display? The slideshow restarts in a few seconds. The frame stays on.")) return;

        btnRestartPf.disabled = true;
        if (btnRestartPfSpinner) btnRestartPfSpinner.style.display = "inline-block";
        if (btnRestartPfLabel) btnRestartPfLabel.textContent = "Restarting...";

        try {
            const resp = await fetch("/services/picframe/restart", { method: "POST" });
            if (resp.ok) {
                alert("Display restarted!");
                await refreshStatus();
            } else {
                const data = await resp.json();
                alert("Restart failed: " + (data.detail || "Unknown error"));
            }
        } catch (err) {
            console.error("Failed to restart picframe", err);
            alert("Error restarting: " + err);
        } finally {
            btnRestartPf.disabled = false;
            if (btnRestartPfSpinner) btnRestartPfSpinner.style.display = "none";
            if (btnRestartPfLabel) btnRestartPfLabel.textContent = "♻️ Restart Display";
        }
    }

    async function restartApiService() {
        if (!btnRestartApi) return;
        if (!confirm("Restart the API service? The page will reload.")) return;

        btnRestartApi.disabled = true;
        if (btnRestartApiSpinner) btnRestartApiSpinner.style.display = "inline-block";
        if (btnRestartApiLabel) btnRestartApiLabel.textContent = "Restarting...";

        try {
            const resp = await fetch("/services/wanderwall-api/restart", { method: "POST" });
            if (resp.ok) {
                alert("API service restarting... Page will reload.");
                setTimeout(() => window.location.reload(), 3000);
            } else {
                const data = await resp.json();
                alert("Restart failed: " + (data.detail || "Unknown error"));
            }
        } catch (err) {
            console.error("Failed to restart API", err);
            alert("Error restarting: " + err);
        } finally {
            btnRestartApi.disabled = false;
            if (btnRestartApiSpinner) btnRestartApiSpinner.style.display = "none";
            if (btnRestartApiLabel) btnRestartApiLabel.textContent = "♻️ Restart API";
        }
    }

    // Reboot Frame (PL-142): ask, wait for the frame to go down, then poll /health until it's back
    async function rebootFrame() {
        const btn = document.getElementById("btn-reboot");
        const spinner = document.getElementById("btn-reboot-spinner");
        const label = document.getElementById("btn-reboot-label");
        if (!btn) return;
        if (!confirm("Reboot the frame? The whole Raspberry Pi restarts. The display and this dashboard will be unavailable for about 1-2 minutes.")) return;

        const setLabel = (text) => { if (label) label.textContent = text; };
        btn.disabled = true;
        if (spinner) spinner.style.display = "inline-block";
        setLabel("Rebooting...");

        const reset = () => {
            btn.disabled = false;
            if (spinner) spinner.style.display = "none";
            setLabel("⏻ Reboot Frame");
        };

        try {
            const resp = await fetch("/system/reboot", { method: "POST" });
            const data = await resp.json();
            if (!data.ok) {
                alert("Couldn't reboot: " + (data.error || "Unknown error"));
                reset();
                return;
            }
        } catch (err) {
            alert("Couldn't reboot: " + err);
            reset();
            return;
        }

        const isUp = async () => {
            try {
                return (await fetch("/health", { cache: "no-store" })).ok;
            } catch (err) {
                return false;
            }
        };
        const started = Date.now();
        const elapsed = () => Math.round((Date.now() - started) / 1000);

        // Wait until it has actually gone down (shutdown can be slow), then poll every 5 s for up to 4 minutes
        while (Date.now() - started < 90000 && await isUp()) {
            await new Promise(r => setTimeout(r, 2000));
        }
        const downAt = Date.now();
        while (Date.now() - downAt < 240000) {
            setLabel(`Rebooting... ${elapsed()}s`);
            if (await isUp()) {
                setLabel("Back online");
                window.location.reload();
                return;
            }
            await new Promise(r => setTimeout(r, 5000));
        }
        alert("The frame hasn't come back after 4 minutes. Check that it has power and WiFi, then reload this page.");
        reset();
    }

    // Button event listeners
    if (btnRefresh) btnRefresh.addEventListener("click", refreshStatus);
    const btnReboot = document.getElementById("btn-reboot");
    if (btnReboot) btnReboot.addEventListener("click", rebootFrame);
    if (btnSyncNow) btnSyncNow.addEventListener("click", syncNow);
    if (btnRestartPf) btnRestartPf.addEventListener("click", restartPfService);
    if (btnRestartApi) btnRestartApi.addEventListener("click", restartApiService);

    // Preview of the photo on the frame (PL-174): ask which photo is showing every few
    // seconds and load its thumbnail only when it changes, so the preview follows the
    // frame. A failed load shows the error and is retried on the next poll. Older
    // display engines (kframe's) don't report the name: then reload the frame's own
    // image every 20 s, as the page did before.
    const thumbnailImg = document.getElementById("current-image-thumbnail");
    const thumbnailError = document.getElementById("image-error");
    const PREVIEW_FALLBACK_MS = 20000;
    if (thumbnailImg) {
        let shownName = null;
        let fallbackAt = -Infinity;
        thumbnailImg.addEventListener("load", () => {
            thumbnailImg.style.display = "";
            if (thumbnailError) thumbnailError.style.display = "none";
        });
        thumbnailImg.addEventListener("error", () => {
            shownName = null;  // retry on the next poll
            thumbnailImg.style.display = "none";
            if (thumbnailError) thumbnailError.style.display = "block";
        });
        const pollPreview = async () => {
            if (document.hidden) return;
            try {
                const resp = await fetch("/current-image/info", { cache: "no-store" });
                const data = await resp.json();
                if (data.filename && data.filename !== shownName) {
                    shownName = data.filename;
                    thumbnailImg.src = `/current-image?filename=${encodeURIComponent(data.filename)}`;
                } else if (!data.filename && Date.now() - fallbackAt >= PREVIEW_FALLBACK_MS) {
                    fallbackAt = Date.now();
                    shownName = null;
                    thumbnailImg.src = `/current-image?t=${fallbackAt}`;  // 503 shows the error
                }
            } catch (err) {
                // Frame busy or restarting: keep the last preview
            }
        };
        pollPreview();
        setInterval(pollPreview, 5000);
    }

    refreshStatus();
    setInterval(refreshStatus, 15000);
}

// =============================================================================
// SOURCES MANAGER
// =============================================================================

const sourcesState = {
    currentRemote: '',
    currentPath: [],
    remotes: [],
    localDirs: [],
    sources: []
};

let sourcesElements = {};

function initSourcesManager() {
    initSourcesElements();
    initSourcesEventListeners();
    loadSourcesInitialData();
}

function initSourcesElements() {
    sourcesElements = {
        label: document.getElementById('input-label'),
        btnSave: document.getElementById('btn-save-source'),
        sourcesTbody: document.getElementById('sources-tbody'),
        statusMessage: document.getElementById('status-message'),
        form: document.getElementById('add-source-form')
    };
}

function initSourcesEventListeners() {
    if (sourcesElements.form) {
        sourcesElements.form.addEventListener('submit', onFormSubmit);
    }
}

async function loadSourcesInitialData() {
    await loadSources();
}

async function loadSources() {
    try {
        const response = await fetch('/api/sources');
        const data = await response.json();
        sourcesState.sources = data.sources || [];
        renderSourcesTable();
    } catch (err) {
        console.error('Failed to load sources:', err);
        if (sourcesElements.sourcesTbody) {
            sourcesElements.sourcesTbody.innerHTML = `
                <tr>
                    <td colspan="8" class="loading-cell" style="color: #fca5a5;">
                        Error loading albums: ${escapeHtml(err.message)}
                    </td>
                </tr>
            `;
        }
    }
}

function _syncDot(local, remote, hasRemote) {
    if (!hasRemote) return '';
    const amberDot = '<span class="status-dot" style="background:#fbbf24;box-shadow:0 0 6px rgba(251,191,36,.75);flex-shrink:0;"></span>';
    const greenDot = '<span class="status-dot" style="flex-shrink:0;"></span>';
    if (remote === -1) return amberDot;
    if (local === remote && remote > 0) return greenDot;
    return amberDot;
}

function renderSourcesTable() {
    if (!sourcesElements.sourcesTbody) return;

    if (sourcesState.sources.length === 0) {
        sourcesElements.sourcesTbody.innerHTML = `
            <tr>
                <td colspan="8" class="loading-cell">No albums yet</td>
            </tr>
        `;
        return;
    }

    const rows = sourcesState.sources.map(source => {
        const statusBadges = [];

        if (source.active) {
            statusBadges.push('<span class="source-status-badge active">Active</span>');
        } else if (source.enabled) {
            statusBadges.push('<span class="source-status-badge enabled">Ready</span>');
        } else {
            statusBadges.push('<span class="source-status-badge disabled">Disabled</span>');
        }

        const activateBtn = source.active
            ? ''
            : `<button class="btn-small" onclick="activateSource('${escapeHtml(source.path)}', '${escapeHtml(source.id)}')">Activate</button> `;

        // The album that's showing can't be deleted (PL-147): show another one first
        const deleteBtn = source.active
            ? ''
            : `<button class="btn-small btn-danger" onclick="deleteSource('${escapeHtml(source.id)}')">Delete</button>`;

        const hasRemote = !!source.remote;
        const cloudDisplay = !hasRemote ? '—' : source.remote_count === -1 ? '?' : source.remote_count;
        const dot = _syncDot(source.photo_count, source.remote_count, hasRemote);

        return `
            <tr>
                <td class="tech-column"><strong>${escapeHtml(source.id)}</strong></td>
                <td>${escapeHtml(source.label)}</td>
                <td><code>${escapeHtml(source.remote || 'local')}</code></td>
                <td class="tech-column"><code>${escapeHtml(source.path)}</code></td>
                <td style="white-space:nowrap;">${dot} ${cloudDisplay}</td>
                <td>${source.photo_count}</td>
                <td>${statusBadges.join(' ')}</td>
                <td class="tech-column" style="white-space: nowrap;">
                    ${activateBtn}${deleteBtn}
                </td>
            </tr>
        `;
    }).join('');

    sourcesElements.sourcesTbody.innerHTML = rows;
}

async function loadRcloneRemotes() {
    try {
        const response = await fetch('/api/rclone/remotes');
        const data = await response.json();

        if (!data.ok) {
            throw new Error(data.error || 'Failed to load remotes');
        }

        sourcesState.remotes = data.remotes || [];
        renderRemoteDropdown();
    } catch (err) {
        console.error('Failed to load remotes:', err);
        if (sourcesElements.remote) {
            sourcesElements.remote.innerHTML = `<option value="">Error: ${escapeHtml(err.message)}</option>`;
        }
        showSourcesStatus('error', `Failed to load rclone remotes: ${err.message}`);
    }
}

function renderRemoteDropdown() {
    if (!sourcesElements.remote) return;

    if (sourcesState.remotes.length === 0) {
        sourcesElements.remote.innerHTML = `<option value="">No remotes configured</option>`;
        return;
    }

    const options = sourcesState.remotes.map(remote =>
        `<option value="${escapeHtml(remote)}">${escapeHtml(remote)}</option>`
    ).join('');

    sourcesElements.remote.innerHTML = `
        <option value="">Select a remote...</option>
        ${options}
    `;
}

async function loadLocalDirs() {
    try {
        const response = await fetch('/api/local/list-dirs');
        const data = await response.json();

        if (!data.ok) {
            throw new Error(data.error || 'Failed to load directories');
        }

        sourcesState.localDirs = data.dirs || [];
        sourcesState.picturesBasePath = data.base_path;
        renderLocalDirDropdown();
    } catch (err) {
        console.error('Failed to load local dirs:', err);
        if (sourcesElements.localDir) {
            sourcesElements.localDir.innerHTML = `<option value="">Error: ${escapeHtml(err.message)}</option>`;
        }
    }
}

function renderLocalDirDropdown() {
    if (!sourcesElements.localDir) return;

    if (sourcesState.localDirs.length === 0) {
        sourcesElements.localDir.innerHTML = `
            <option value="">No directories found</option>
            <option value="new">+ Create new directory</option>
        `;
        return;
    }

    const options = sourcesState.localDirs.map(dir =>
        `<option value="${escapeHtml(dir.path)}">${escapeHtml(dir.path)}</option>`
    ).join('');

    sourcesElements.localDir.innerHTML = `
        <option value="">Select a directory...</option>
        ${options}
        <option value="new">+ Create new directory</option>
    `;

    // Update the hint to show correct base path
    const hint = document.querySelector('#new-dir-input-container .form-hint');
    if (hint && sourcesState.picturesBasePath) {
        hint.textContent = `Will be created in ${sourcesState.picturesBasePath}/`;
    }
}

function onRemoteChange() {
    const selectedRemote = sourcesElements.remote.value;

    if (!selectedRemote) {
        sourcesState.currentRemote = '';
        sourcesState.currentPath = [];
        renderBreadcrumb();
        renderRemoteDirs([]);
        return;
    }

    sourcesState.currentRemote = selectedRemote;
    sourcesState.currentPath = [];
    renderBreadcrumb();
    loadRemoteDirs();
}

function onLocalDirChange() {
    const selectedValue = sourcesElements.localDir.value;

    if (selectedValue === 'new') {
        sourcesElements.newDirContainer.style.display = 'block';
        sourcesElements.newDirName.required = true;
        sourcesElements.newDirName.focus();
    } else {
        sourcesElements.newDirContainer.style.display = 'none';
        sourcesElements.newDirName.required = false;
        sourcesElements.newDirName.value = '';
    }
}

async function loadRemoteDirs() {
    if (!sourcesState.currentRemote) {
        renderRemoteDirs([]);
        return;
    }

    if (sourcesElements.remoteDirList) {
        sourcesElements.remoteDirList.innerHTML = `<div class="dir-item loading">Loading directories...</div>`;
    }

    try {
        const response = await fetch('/api/rclone/list-dirs', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                remote: sourcesState.currentRemote,
                path: sourcesState.currentPath.join('/')
            })
        });

        const data = await response.json();

        if (!data.ok) {
            throw new Error(data.error || 'Failed to list directories');
        }

        renderRemoteDirs(data.dirs || []);
    } catch (err) {
        console.error('Failed to load remote dirs:', err);
        if (sourcesElements.remoteDirList) {
            sourcesElements.remoteDirList.innerHTML = `
                <div class="dir-item placeholder" style="color: #fca5a5;">
                    Error: ${escapeHtml(err.message)}
                </div>
            `;
        }
    }
}

function renderRemoteDirs(dirs) {
    if (!sourcesElements.remoteDirList) return;

    if (dirs.length === 0) {
        sourcesElements.remoteDirList.innerHTML = `<div class="dir-item placeholder">No directories found</div>`;
        return;
    }

    const items = dirs.map(dir => {
        const dirData = typeof dir === 'string' ? { name: dir, valid: true } : dir;
        const { name, valid, trimmed_name, reason } = dirData;

        if (!valid) {
            return `
                <div class="dir-item-blocked" title="${escapeHtml(reason)}">
                    <span class="dir-warning-icon">⚠️</span>
                    <span class="dir-name-blocked">${escapeHtml(name)}</span>
                    <span class="dir-warning-text">
                        Invalid name - rename to "${escapeHtml(trimmed_name)}"
                    </span>
                </div>
            `;
        } else {
            return `<div class="dir-item" data-dirname="${escapeHtml(name)}">${escapeHtml(name)}</div>`;
        }
    }).join('');

    sourcesElements.remoteDirList.innerHTML = items;

    sourcesElements.remoteDirList.querySelectorAll('.dir-item[data-dirname]').forEach(item => {
        item.addEventListener('click', () => {
            const dirname = item.getAttribute('data-dirname');
            navigateToDir(dirname);
        });
    });
}

function navigateToDir(dirname) {
    sourcesState.currentPath.push(dirname);
    renderBreadcrumb();
    loadRemoteDirs();
    updateRemotePathInput();
}

function navigateToLevel(level) {
    sourcesState.currentPath = sourcesState.currentPath.slice(0, level);
    renderBreadcrumb();
    loadRemoteDirs();
    updateRemotePathInput();
}

function renderBreadcrumb() {
    if (!sourcesElements.breadcrumb) return;

    if (!sourcesState.currentRemote) {
        sourcesElements.breadcrumb.innerHTML = `<span class="breadcrumb-item root">Select a remote first</span>`;
        return;
    }

    const parts = [`<span class="breadcrumb-item root" data-level="0">Root</span>`];

    sourcesState.currentPath.forEach((part, index) => {
        parts.push(`<span class="breadcrumb-item" data-level="${index + 1}">${escapeHtml(part)}</span>`);
    });

    sourcesElements.breadcrumb.innerHTML = parts.join('');

    sourcesElements.breadcrumb.querySelectorAll('.breadcrumb-item').forEach(item => {
        item.addEventListener('click', () => {
            const level = parseInt(item.getAttribute('data-level'));
            navigateToLevel(level);
        });
    });
}

function updateRemotePathInput() {
    if (sourcesElements.remotePath) {
        sourcesElements.remotePath.value = sourcesState.currentPath.join('/');
    }
}

async function onTestConnection() {
    const remote = sourcesElements.remote.value;
    const path = sourcesElements.remotePath.value;

    if (!remote) {
        showSourcesStatus('error', 'Please select a remote first');
        return;
    }

    const fullPath = path ? `${remote}${path}` : remote;

    sourcesElements.btnTest.disabled = true;
    sourcesElements.btnTest.textContent = 'Testing...';
    showSourcesStatus('info', 'Testing connection...');

    try {
        const response = await fetch('/api/config/test-remote', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ remote: fullPath })
        });

        const data = await response.json();

        if (data.ok) {
            showSourcesStatus('success', `Connection successful! Found ${data.file_count} items.`);
        } else {
            showSourcesStatus('error', `Connection failed: ${data.error}`);
        }
    } catch (err) {
        showSourcesStatus('error', `Test failed: ${err.message}`);
    } finally {
        sourcesElements.btnTest.disabled = false;
        sourcesElements.btnTest.textContent = 'Test Connection';
    }
}

async function onFormSubmit(event) {
    event.preventDefault();

    const name = sourcesElements.label.value.trim();
    if (!name) {
        showSourcesStatus('error', 'Display name is required');
        return;
    }

    sourcesElements.btnSave.disabled = true;
    sourcesElements.btnSave.textContent = 'Saving...';
    showSourcesStatus('info', 'Creating album...');

    try {
        const response = await fetch('/api/sources/create', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ name })
        });

        const data = await response.json();

        if (data.ok) {
            showSourcesStatus('success', `Source "${data.source_id}" created successfully!`);
            sourcesElements.form.reset();
            await loadSources();
        } else {
            showSourcesStatus('error', `Failed to create album: ${data.error}`);
        }
    } catch (err) {
        showSourcesStatus('error', `Error: ${err.message}`);
    } finally {
        sourcesElements.btnSave.disabled = false;
        sourcesElements.btnSave.textContent = 'Add Album';
    }
}

function buildFullRemotePath() {
    const remote = sourcesElements.remote.value;
    const path = sourcesElements.remotePath.value;

    if (!remote) {
        return '';
    }

    return path ? `${remote}${path}` : remote;
}

function showSourcesStatus(type, message) {
    if (!sourcesElements.statusMessage) return;

    sourcesElements.statusMessage.className = `status-message ${type}`;
    sourcesElements.statusMessage.textContent = message;
    sourcesElements.statusMessage.style.display = 'block';

    if (type === 'success' || type === 'info') {
        setTimeout(() => {
            sourcesElements.statusMessage.style.display = 'none';
        }, 5000);
    }
}

async function activateSource(targetPath, sourceId) {
    if (!confirm(`Switch to "${sourceId}"?\n\nThis will sync photos from the cloud and display them on your frame.`)) {
        return;
    }

    showSourcesStatus('info', `Activating "${sourceId}" and syncing photos...`);

    try {
        const response = await fetch('/api/frame-live', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ target_dir: targetPath })
        });

        const data = await response.json();

        if (data.ok) {
            if (data.sync_triggered) {
                showSourcesStatus('success', `"${sourceId}" activated and synced successfully!`);
            } else {
                showSourcesStatus('success', `"${sourceId}" activated successfully!`);
            }
            // Reload sources to update active status
            await loadSources();
        } else {
            showSourcesStatus('error', `Failed to activate: ${data.error}`);
        }
    } catch (err) {
        showSourcesStatus('error', `Error showing album: ${err.message}`);
    }
}

async function deleteSource(sourceId) {
    const source = (sourcesState.sources || []).find(s => s.id === sourceId);
    const name = source ? source.label : sourceId;
    const count = source ? source.photo_count : 0;
    const cloud = source && source.remote
        ? `They stay in your cloud storage (${source.remote}).`
        : 'This album has no cloud folder, so these photos are NOT kept anywhere else.';
    if (!confirm(`Delete album "${name}"?\n\nThis deletes ${count} photo${count === 1 ? '' : 's'} from the frame. ${cloud}\n\nBackups are kept. This can't be undone.`)) {
        return;
    }

    showSourcesStatus('info', `Deleting album "${name}"...`);

    try {
        const response = await fetch('/api/sources/delete', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ source_id: sourceId })
        });

        const data = await response.json();

        if (data.ok && data.error) {
            showSourcesStatus('error', data.error);
            await loadSources();
        } else if (data.ok) {
            showSourcesStatus('success', `Album "${name}" deleted (${data.photos_removed} photo${data.photos_removed === 1 ? '' : 's'} removed from the frame).`);
            await loadSources();
        } else {
            showSourcesStatus('error', `Couldn't delete album: ${data.error}`);
        }
    } catch (err) {
        showSourcesStatus('error', `Error deleting album: ${err.message}`);
    }
}

function escapeHtml(text) {
    if (!text) return '';
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

// =============================================================================
// SETTINGS FORM
// =============================================================================

function initSettingsForm() {
    const form = document.getElementById('settings-form');
    if (!form) return;

    form.addEventListener('submit', async (event) => {
        event.preventDefault();

        const btn = document.getElementById('btn-save-settings');
        const statusEl = document.getElementById('settings-status-message');

        const settings = {
            frame_name: document.getElementById('settings-frame-name').value,
            rotation_interval: parseInt(document.getElementById('settings-rotation-interval').value),
            sync_interval: parseInt(document.getElementById('settings-sync-interval').value),
            fade_time: parseFloat(document.getElementById('settings-fade-time').value),
        };

        btn.disabled = true;
        btn.textContent = 'Saving...';

        try {
            const response = await fetch('/api/settings', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(settings)
            });

            const data = await response.json();

            if (data.ok) {
                statusEl.className = 'status-message success';
                let message = 'Settings saved successfully!';
                if (data.restarted) {
                    message += ' Frame display restarted.';
                }
                statusEl.textContent = message;
                statusEl.style.display = 'block';
                // Update frame name in header if it changed
                const hostName = document.getElementById('host-name');
                if (hostName) hostName.textContent = settings.frame_name;
                setTimeout(() => { statusEl.style.display = 'none'; }, 5000);
            } else {
                statusEl.className = 'status-message error';
                statusEl.textContent = 'Failed to save settings: ' + (data.error || 'Unknown error');
                statusEl.style.display = 'block';
            }
        } catch (err) {
            statusEl.className = 'status-message error';
            statusEl.textContent = 'Error saving settings: ' + err.message;
            statusEl.style.display = 'block';
        } finally {
            btn.disabled = false;
            btn.textContent = 'Save Settings';
        }
    });
}

// =============================================================================
// PAIRING
// =============================================================================

let pairingCountdownInterval = null;

async function generatePairingCode() {
    const errorEl = document.getElementById("pairing-error");
    if (errorEl) errorEl.style.display = "none";

    try {
        const resp = await fetch("/pairing/generate", { method: "POST" });
        const data = await resp.json();

        if (data.error) {
            if (errorEl) {
                errorEl.textContent = data.error;
                errorEl.style.display = "block";
            } else {
                alert("Failed to generate code: " + data.error);
            }
            return;
        }

        const resultDiv = document.getElementById("pairing-result");
        const qrImg = document.getElementById("pairing-qr");
        const codeEl = document.getElementById("pairing-code");
        const countdownEl = document.getElementById("pairing-countdown");

        if (qrImg) qrImg.src = data.qr_data_url;
        if (codeEl) codeEl.textContent = data.code;

        // Start countdown
        if (pairingCountdownInterval) clearInterval(pairingCountdownInterval);
        const expiresAt = new Date(data.expires_at);
        function updateCountdown() {
            const remaining = Math.max(0, Math.round((expiresAt - Date.now()) / 1000));
            if (countdownEl) countdownEl.textContent = remaining;
            if (remaining <= 0) {
                clearInterval(pairingCountdownInterval);
                if (resultDiv) resultDiv.style.display = "none";
            }
        }
        updateCountdown();
        pairingCountdownInterval = setInterval(updateCountdown, 1000);

        if (resultDiv) resultDiv.style.display = "block";
    } catch (err) {
        if (errorEl) {
            errorEl.textContent = "Error generating pairing code: " + err.message;
            errorEl.style.display = "block";
        } else {
            alert("Error generating pairing code: " + err.message);
        }
    }
}

// =============================================================================
// DEVICE MANAGEMENT
// =============================================================================

let devicesLoaded = false;

function initDeviceManagement() {
    const toggleBtn = document.getElementById('btn-toggle-devices');
    const devicesCard = document.getElementById('devices-card');
    if (toggleBtn && devicesCard) {
        toggleBtn.addEventListener('click', () => {
            const isVisible = devicesCard.style.display !== 'none';
            devicesCard.style.display = isVisible ? 'none' : 'block';
            toggleBtn.textContent = isVisible ? 'Manage Devices' : 'Hide Devices';
            if (!isVisible) {
                loadDevices();
            }
        });
    }
}

async function loadDevices() {
    const tbody = document.getElementById('devices-tbody');
    const summary = document.getElementById('device-summary');
    if (!tbody) return;

    try {
        const response = await fetch('/api/devices');
        const data = await response.json();

        if (summary) {
            summary.textContent = data.device_count + ' device(s), ' + data.admin_count + ' admin(s)';
        }

        if (!data.devices || data.devices.length === 0) {
            tbody.innerHTML = '<tr><td colspan="5" style="text-align: center; opacity: 0.6; padding: 2rem;">No devices paired. Use "Generate Pairing QR Code" above to pair a device.</td></tr>';
            return;
        }

        const canRevoke = data.admin_count > 1;

        const rows = data.devices.map(function(device) {
            const badgeClass = device.role === 'admin' ? 'badge-admin' : 'badge-user';
            const revokeDisabled = (!canRevoke && device.role === 'admin');
            const revokeBtn = revokeDisabled
                ? '<button class="btn-small btn-danger" disabled title="Cannot remove last admin">Revoke</button>'
                : '<button class="btn-small btn-danger" onclick="revokeDevice(\'' + escapeHtml(device.id) + '\', \'' + escapeHtml(device.name) + '\')">Revoke</button>';

            return '<tr>' +
                '<td>' + escapeHtml(device.name) + '</td>' +
                '<td><span class="badge ' + badgeClass + '">' + escapeHtml(device.role) + '</span></td>' +
                '<td>' + (device.paired_at || 'Unknown') + '</td>' +
                '<td>' + (device.last_seen || 'Never') + '</td>' +
                '<td>' + revokeBtn + '</td>' +
                '</tr>';
        }).join('');

        tbody.innerHTML = rows;
    } catch (err) {
        console.error('Failed to load devices:', err);
        tbody.innerHTML = '<tr><td colspan="5" style="text-align: center; color: #fca5a5; padding: 2rem;">Error loading devices: ' + escapeHtml(err.message) + '</td></tr>';
    }
}

async function revokeDevice(deviceId, deviceName) {
    if (!confirm('Revoke access for "' + deviceName + '"? This device will no longer be able to manage this frame.')) {
        return;
    }

    const statusEl = document.getElementById('devices-status-message');

    try {
        const response = await fetch('/devices/' + deviceId + '/revoke', { method: 'POST' });
        const data = await response.json();

        if (data.ok) {
            if (statusEl) {
                statusEl.className = 'status-message success';
                statusEl.textContent = 'Device "' + deviceName + '" revoked successfully.';
                statusEl.style.display = 'block';
                setTimeout(function() { statusEl.style.display = 'none'; }, 5000);
            }
            await loadDevices();
        } else {
            if (statusEl) {
                statusEl.className = 'status-message error';
                statusEl.textContent = data.error || 'Failed to revoke device';
                statusEl.style.display = 'block';
            }
        }
    } catch (err) {
        console.error('Failed to revoke device:', err);
        if (statusEl) {
            statusEl.className = 'status-message error';
            statusEl.textContent = 'Error: ' + err.message;
            statusEl.style.display = 'block';
        }
    }
}

// =============================================================================
// SETTINGS LOG VIEWER
// =============================================================================

let settingsAutoRefreshInterval = null;

async function loadSettingsLogs() {
    const logType = document.getElementById('settings-log-type');
    const logLines = document.getElementById('settings-log-lines');
    const content = document.getElementById('settings-log-content');
    if (!content) return;

    const type = logType ? logType.value : 'ops';
    const lines = logLines ? logLines.value : '100';

    try {
        const response = await fetch('/api/logs?log_type=' + type + '&lines=' + lines);
        if (!response.ok) {
            content.textContent = 'Failed to load logs: HTTP ' + response.status;
            return;
        }
        const data = await response.json();

        if (data.logs && data.logs.length > 0) {
            content.textContent = data.logs.join('\n');
        } else {
            content.textContent = 'No log entries found.';
        }
        content.scrollTop = 0;

        const ts = document.getElementById('log-last-refreshed');
        if (ts) ts.textContent = 'refreshed ' + new Date().toLocaleTimeString();
    } catch (err) {
        content.textContent = 'Failed to load logs: ' + err.message;
    }
}

function initSettingsLogViewer() {
    const refreshBtn = document.getElementById('btn-refresh-logs');
    const logType = document.getElementById('settings-log-type');
    const logLines = document.getElementById('settings-log-lines');
    const autoRefresh = document.getElementById('settings-auto-refresh');
    const saveLevelBtn = document.getElementById('btn-save-log-level');

    if (refreshBtn) refreshBtn.addEventListener('click', loadSettingsLogs);
    if (logType) logType.addEventListener('change', loadSettingsLogs);
    if (logLines) logLines.addEventListener('change', loadSettingsLogs);

    if (autoRefresh) {
        autoRefresh.addEventListener('change', function() {
            if (autoRefresh.checked) {
                settingsAutoRefreshInterval = setInterval(loadSettingsLogs, 5000);
            } else {
                clearInterval(settingsAutoRefreshInterval);
                settingsAutoRefreshInterval = null;
            }
        });
    }

    if (saveLevelBtn) {
        saveLevelBtn.addEventListener('click', async function() {
            const level = document.getElementById('settings-log-level').value;
            saveLevelBtn.disabled = true;
            saveLevelBtn.textContent = 'Saving...';
            try {
                const resp = await fetch('/api/settings/log-level', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ log_level: level })
                });
                const data = await resp.json();
                saveLevelBtn.textContent = data.ok ? 'Saved' : 'Error';
                setTimeout(() => { saveLevelBtn.textContent = 'Save Level'; saveLevelBtn.disabled = false; }, 2000);
            } catch (err) {
                saveLevelBtn.textContent = 'Error';
                setTimeout(() => { saveLevelBtn.textContent = 'Save Level'; saveLevelBtn.disabled = false; }, 2000);
            }
        });
    }
}

// =============================================================================
// UPDATES
// =============================================================================

document.addEventListener('DOMContentLoaded', () => {
    // Initialize day dropdown from saved frequency + day
    const freqEl = document.getElementById('update-frequency');
    const dayEl = document.getElementById('update-day');
    if (freqEl && dayEl) {
        const savedDay = parseInt(dayEl.dataset.savedDay || '1', 10);
        updateDayDropdown(freqEl.value, savedDay);
    }

    const scheduleForm = document.getElementById('update-schedule-form');
    if (scheduleForm) {
        scheduleForm.addEventListener('submit', function(e) {
            e.preventDefault();
            saveUpdateSchedule();
        });
    }
});

function updateDayDropdown(frequency, selectedDay) {
    const dayEl = document.getElementById('update-day');
    const labelEl = document.getElementById('update-day-label');
    const dayGroup = document.getElementById('update-day-group');
    if (!dayEl) return;

    if (selectedDay === undefined) {
        selectedDay = parseInt(dayEl.value, 10);
    }

    // Hide day picker for daily
    if (dayGroup) dayGroup.style.display = (frequency === 'daily') ? 'none' : '';

    dayEl.innerHTML = '';

    if (frequency === 'monthly') {
        if (labelEl) labelEl.textContent = 'Day of month';
        const ordinals = ['1st','2nd','3rd','4th','5th','6th','7th','8th','9th','10th',
                          '11th','12th','13th','14th','15th','16th','17th','18th','19th','20th',
                          '21st','22nd','23rd','24th','25th','26th','27th','28th'];
        for (let i = 1; i <= 28; i++) {
            const opt = document.createElement('option');
            opt.value = i;
            opt.textContent = ordinals[i - 1];
            if (i === selectedDay) opt.selected = true;
            dayEl.appendChild(opt);
        }
    } else if (frequency === 'weekly') {
        if (labelEl) labelEl.textContent = 'Day of week';
        const days = ['Monday','Tuesday','Wednesday','Thursday','Friday','Saturday','Sunday'];
        for (let i = 0; i < 7; i++) {
            const opt = document.createElement('option');
            opt.value = i;
            opt.textContent = days[i];
            if (i === selectedDay) opt.selected = true;
            dayEl.appendChild(opt);
        }
    }
    // daily: day picker hidden, nothing to populate
}

function _setUpdateMsg(text, color) {
    const el = document.getElementById('update-message');
    if (el) { el.textContent = text; el.style.color = color || '#9ca3af'; }
}

async function checkForUpdates() {
    const btn = document.getElementById('btn-check-updates');
    const spinner = document.getElementById('btn-check-updates-spinner');
    const label = document.getElementById('btn-check-updates-label');
    const applyBtn = document.getElementById('btn-apply-update');

    if (btn) btn.disabled = true;
    if (spinner) spinner.style.display = 'inline-block';
    if (label) label.textContent = 'Checking...';
    _setUpdateMsg('Contacting GitHub...', '#9ca3af');

    try {
        const resp = await fetch('/api/updates/check', { method: 'POST' });
        if (!resp.ok) throw new Error('Server error ' + resp.status);
        const data = await resp.json();

        // Update version display
        const localVersionEl = document.getElementById('update-local-version');
        const localHashEl = document.getElementById('update-local-commit');
        const remoteVersionEl = document.getElementById('update-remote-version');
        const remoteHashEl = document.getElementById('update-remote-commit');
        const statusEl = document.getElementById('update-status-text');
        const lastCheckedEl = document.getElementById('update-last-checked');

        if (localVersionEl && data.local_version) localVersionEl.textContent = data.local_version;
        if (localHashEl && data.local_commit) localHashEl.textContent = '(' + data.local_commit + ')';

        // Update branch badge
        const branchBadge = document.getElementById('update-branch-badge');
        const branchHidden = document.getElementById('update-branch');
        if (branchBadge && data.branch) {
            branchBadge.textContent = data.branch.toUpperCase();
            if (data.branch === 'dev') {
                branchBadge.style.background = 'rgba(239,68,68,0.15)';
                branchBadge.style.color = '#ef4444';
            } else {
                branchBadge.style.background = 'rgba(34,197,94,0.15)';
                branchBadge.style.color = '#22c55e';
            }
        }
        if (branchHidden && data.branch) branchHidden.textContent = data.branch;

        if (lastCheckedEl && data.checked_at) {
            try {
                const d = new Date(data.checked_at);
                lastCheckedEl.textContent = d.toLocaleDateString('en-US', {day:'numeric', month:'short', year:'numeric'}) +
                    ' at ' + d.toLocaleTimeString('en-US', {hour:'numeric', minute:'2-digit'});
            } catch (e) {
                lastCheckedEl.textContent = data.checked_at;
            }
        }

        if (data.error) {
            _setUpdateMsg('Check failed: ' + data.error, '#f87171');
            if (statusEl) statusEl.innerHTML = '<span style="color:#f87171;">Check failed</span>';
            if (remoteVersionEl) remoteVersionEl.textContent = '—';
            if (remoteHashEl) remoteHashEl.textContent = '';
        } else if (data.up_to_date === true) {
            if (remoteVersionEl) remoteVersionEl.textContent = data.local_version || 'same';
            if (remoteHashEl) remoteHashEl.textContent = data.remote_commit ? '(' + data.remote_commit + ')' : '';
            if (statusEl) statusEl.innerHTML = '<span style="color:#34d399;">Up to date</span>';
            if (applyBtn) applyBtn.style.opacity = '0.5';
            _setUpdateMsg('', '');
        } else if (data.up_to_date === false) {
            if (remoteVersionEl) remoteVersionEl.textContent = data.remote_version || '—';
            if (remoteHashEl) remoteHashEl.textContent = data.remote_commit ? '(' + data.remote_commit + ')' : '';
            if (statusEl) statusEl.innerHTML = '<span style="color:#f59e0b;">Update available</span>';
            if (applyBtn) applyBtn.style.opacity = '1';
            _setUpdateMsg('Update available — click Apply Now to install.', '#f59e0b');
        } else {
            _setUpdateMsg('Could not determine update status.', '#f87171');
        }
    } catch (err) {
        _setUpdateMsg('Error: ' + err.message, '#f87171');
    } finally {
        if (btn) btn.disabled = false;
        if (spinner) spinner.style.display = 'none';
        if (label) label.textContent = 'Check Now';
    }
}

async function applyUpdate() {
    const btn = document.getElementById('btn-apply-update');
    const spinner = document.getElementById('btn-apply-update-spinner');
    const label = document.getElementById('btn-apply-update-label');

    if (!confirm('Apply update now? This runs git pull and restarts the API.')) return;

    if (btn) btn.disabled = true;
    if (spinner) spinner.style.display = 'inline-block';
    if (label) label.textContent = 'Applying...';
    _setUpdateMsg('Running git pull...', '#9ca3af');

    try {
        const resp = await fetch('/api/updates/apply', { method: 'POST' });
        if (!resp.ok) throw new Error('Server error ' + resp.status);
        const data = await resp.json();

        if (data.ok) {
            _setUpdateMsg('Update applied! API restarting — page will refresh shortly.', '#34d399');
            const statusEl = document.getElementById('update-status-text');
            if (statusEl) statusEl.innerHTML = '<span style="color:#34d399;">Applied — API restarting</span>';
            setTimeout(() => location.reload(), 8000);
        } else {
            _setUpdateMsg('Apply failed: ' + (data.error || 'unknown error'), '#f87171');
        }
    } catch (err) {
        _setUpdateMsg('Error: ' + err.message, '#f87171');
    } finally {
        if (btn) btn.disabled = false;
        if (spinner) spinner.style.display = 'none';
        if (label) label.textContent = 'Apply Now';
    }
}

async function saveUpdateSchedule() {
    const msgEl = document.getElementById('update-schedule-message');
    const btn = document.querySelector('#update-schedule-form button[type="submit"]');

    const autoCheck = document.getElementById('update-auto-check')?.checked ?? true;
    const autoApply = document.getElementById('update-auto-apply')?.checked ?? false;
    const frequency = document.getElementById('update-frequency')?.value || 'monthly';
    const day = parseInt(document.getElementById('update-day')?.value || '1', 10);
    // Strip seconds if browser returns HH:MM:SS from <input type="time">
    const rawTime = document.getElementById('update-check-time')?.value || '02:00';
    const checkTime = rawTime.length > 5 ? rawTime.substring(0, 5) : rawTime;

    if (!checkTime || !/^\d{2}:\d{2}$/.test(checkTime)) {
        if (msgEl) {
            msgEl.className = 'status-message error';
            msgEl.textContent = 'Please enter a valid time';
            msgEl.style.display = 'block';
        }
        return;
    }

    if (btn) { btn.disabled = true; btn.textContent = 'Saving...'; }

    try {
        const resp = await fetch('/api/updates/schedule', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ auto_check: autoCheck, auto_apply: autoApply, frequency, day, check_time: checkTime })
        });
        if (!resp.ok) {
            throw new Error(`Server error ${resp.status} — the API may be restarting, try again`);
        }
        const data = await resp.json();

        if (data.ok) {
            if (msgEl) {
                msgEl.className = 'status-message success';
                msgEl.textContent = 'Schedule saved!';
                msgEl.style.display = 'block';
                setTimeout(() => { msgEl.style.display = 'none'; }, 4000);
            }
        } else {
            if (msgEl) {
                msgEl.className = 'status-message error';
                msgEl.textContent = 'Failed: ' + (data.error || 'unknown error');
                msgEl.style.display = 'block';
            }
        }
    } catch (err) {
        if (msgEl) {
            msgEl.className = 'status-message error';
            msgEl.textContent = err.message.includes('Failed to fetch')
                ? 'Could not reach the API — it may be restarting. Refresh the page and try again.'
                : 'Error: ' + err.message;
            msgEl.style.display = 'block';
        }
    } finally {
        if (btn) { btn.disabled = false; btn.textContent = 'Save Schedule'; }
    }
}

// =============================================================================
// PHOTO TOOLS TAB
// =============================================================================

function initPhotoTools() {
    // Source loading is triggered by switchTab('tools') — see switchTab().

    // Helper: wire a scan card header — click header to scan, close/rescan buttons in result bar
    function initScanCard(headerEl, resultEl, statusEl, scanFn, closeFn, rescanFn) {
        if (!headerEl || !resultEl) return;

        // Header click: trigger scan only when result is hidden and not already scanning
        headerEl.addEventListener('click', () => {
            if (headerEl.dataset.scanning) return;
            if (resultEl.style.display !== 'none' && resultEl.style.display !== '') return;
            scanFn();
        });

        // Close button: hide result and restore expandable cursor
        if (closeFn) closeFn.addEventListener('click', (e) => {
            e.stopPropagation();
            resultEl.style.display = 'none';
            headerEl.classList.add('card-header--expandable');
        });

        // Rescan button: re-run scan even when results are showing
        if (rescanFn) rescanFn.addEventListener('click', (e) => {
            e.stopPropagation();
            if (!headerEl.dataset.scanning) scanFn();
        });
    }

    // Filename Cleaner
    const fnHeader = document.getElementById('filenames-card-header');
    const fnResult = document.getElementById('filenames-result');
    const btnApplyFn = document.getElementById('btn-apply-filenames');
    const btnApplyFnTop = document.getElementById('btn-apply-filenames-top');
    const chkAllFn = document.getElementById('filenames-check-all');
    initScanCard(
        fnHeader, fnResult, document.getElementById('filenames-scan-status'),
        runFilenameScan,
        document.getElementById('btn-close-filenames'),
        document.getElementById('btn-rescan-filenames')
    );
    if (btnApplyFn) btnApplyFn.addEventListener('click', runFilenameApply);
    if (btnApplyFnTop) btnApplyFnTop.addEventListener('click', runFilenameApply);
    if (chkAllFn) chkAllFn.addEventListener('change', function () {
        // Only toggle checkboxes in currently visible rows
        document.querySelectorAll('#filenames-tbody tr').forEach(tr => {
            if (tr.style.display !== 'none') {
                const cb = tr.querySelector('.filename-check');
                if (cb) cb.checked = this.checked;
            }
        });
        updateFilenameApplyBtn();
    });

    // Duplicate Finder
    const dupHeader = document.getElementById('duplicates-card-header');
    const dupResult = document.getElementById('duplicates-result');
    const btnApplyDup = document.getElementById('btn-apply-duplicates');
    const btnApplyDupTop = document.getElementById('btn-apply-duplicates-top');
    initScanCard(
        dupHeader, dupResult, document.getElementById('duplicates-scan-status'),
        runDupScan,
        document.getElementById('btn-close-duplicates'),
        document.getElementById('btn-rescan-duplicates')
    );
    if (btnApplyDup) btnApplyDup.addEventListener('click', runDupApply);
    if (btnApplyDupTop) btnApplyDupTop.addEventListener('click', runDupApply);

    // Video Manager
    const vidHeader = document.getElementById('videos-card-header');
    const vidResult = document.getElementById('videos-result');
    const btnApplyVid = document.getElementById('btn-apply-videos');
    const btnApplyVidTop = document.getElementById('btn-apply-videos-top');
    const chkAllVid = document.getElementById('videos-check-all');
    initScanCard(
        vidHeader, vidResult, document.getElementById('videos-scan-status'),
        runVideoScan,
        document.getElementById('btn-close-videos'),
        document.getElementById('btn-rescan-videos')
    );
    if (btnApplyVid) btnApplyVid.addEventListener('click', runVideoApply);
    if (btnApplyVidTop) btnApplyVidTop.addEventListener('click', runVideoApply);
    if (chkAllVid) chkAllVid.addEventListener('change', function () {
        document.querySelectorAll('.video-check').forEach(cb => cb.checked = this.checked);
        updateVideoApplyBtn();
    });

    // Corrupt Photo Finder (PL-127)
    initScanCard(
        document.getElementById('corrupt-card-header'), document.getElementById('corrupt-result'),
        document.getElementById('corrupt-scan-status'), runCorruptScan,
        document.getElementById('btn-close-corrupt'), document.getElementById('btn-rescan-corrupt')
    );
    const btnApplyCorrupt = document.getElementById('btn-apply-corrupt');
    if (btnApplyCorrupt) btnApplyCorrupt.addEventListener('click', runCorruptApply);
    const chkAllCorrupt = document.getElementById('corrupt-check-all');
    if (chkAllCorrupt) chkAllCorrupt.addEventListener('change', function () {
        document.querySelectorAll('.corrupt-check').forEach(cb => cb.checked = this.checked);
        updateCorruptApplyBtn();
    });

    // Rotate Photos (PL-126)
    initScanCard(
        document.getElementById('rotate-card-header'), document.getElementById('rotate-result'),
        document.getElementById('rotate-scan-status'), runRotateScan,
        document.getElementById('btn-close-rotate'), document.getElementById('btn-rescan-rotate')
    );
    const btnRotateFixAll = document.getElementById('btn-rotate-fix-all');
    if (btnRotateFixAll) btnRotateFixAll.addEventListener('click', rotateFixAll);
    const chkRotateFlagged = document.getElementById('rotate-only-flagged');
    if (chkRotateFlagged) chkRotateFlagged.addEventListener('change', renderRotateResults);

    // Cancel buttons
    ['btn-cancel-filenames', 'btn-cancel-filenames-top'].forEach(id => {
        const btn = document.getElementById(id);
        if (btn) btn.addEventListener('click', () => { if (_fnAbort) _fnAbort.abort(); });
    });
    ['btn-cancel-duplicates', 'btn-cancel-duplicates-top'].forEach(id => {
        const btn = document.getElementById(id);
        if (btn) btn.addEventListener('click', () => { if (_dupAbort) _dupAbort.abort(); });
    });
    ['btn-cancel-videos', 'btn-cancel-videos-top'].forEach(id => {
        const btn = document.getElementById(id);
        if (btn) btn.addEventListener('click', () => { if (_vidAbort) _vidAbort.abort(); });
    });

    // Rename File card
    const renameHeader = document.getElementById('rename-card-header');
    const renameResult = document.getElementById('rename-result');
    const btnApplyRename = document.getElementById('btn-apply-rename');
    const btnApplyRenameTop = document.getElementById('btn-apply-rename-top');
    initScanCard(
        renameHeader, renameResult, document.getElementById('rename-scan-status'),
        runRenameScan,
        document.getElementById('btn-close-rename'),
        document.getElementById('btn-rescan-rename')
    );
    if (btnApplyRename) btnApplyRename.addEventListener('click', runRenameApply);
    if (btnApplyRenameTop) btnApplyRenameTop.addEventListener('click', runRenameApply);

    // Photo Backups card
    const btnCreateBackup = document.getElementById('btn-create-backup');
    if (btnCreateBackup) btnCreateBackup.addEventListener('click', runCreateBackup);
    const backupSel = document.getElementById('backup-source-select');
    if (backupSel) backupSel.addEventListener('change', loadBackupList);
}

async function loadToolsSources() {
    const sel = document.getElementById('tools-source-select');
    const keep = sel.value;  // stay on the picked album if it still exists, else the active one
    try {
        const data = await apiFetch('/api/sources');
        const albums = data.sources || [];
        const pick = albums.some(s => s.id === keep) ? keep : (albums.find(s => s.active) || {}).id;
        sel.innerHTML = '';
        albums.forEach(s => {
            const opt = document.createElement('option');
            opt.value = s.id;
            opt.textContent = s.label + (s.active ? ' (active)' : '');
            if (s.id === pick) opt.selected = true;
            sel.appendChild(opt);
        });
    } catch (e) {
        sel.innerHTML = '<option value="">Error loading albums</option>';
    }
}

function toolsSourceId() {
    return document.getElementById('tools-source-select').value;
}

// =============================================================================
// PHOTO BACKUPS
// =============================================================================

async function loadBackupSources() {
    const sel = document.getElementById('backup-source-select');
    const keep = sel.value;  // reloaded after a restore: stay on the same choice
    try {
        const data = await apiFetch('/api/sources');
        sel.innerHTML = '<option value="">Whole frame</option>';
        (data.sources || []).forEach(s => {
            const opt = document.createElement('option');
            opt.value = s.id;
            opt.textContent = s.label + (s.active ? ' (active)' : '');
            if (s.id === keep) opt.selected = true;
            sel.appendChild(opt);
        });
    } catch (e) {
        sel.innerHTML = '<option value="">Whole frame (error loading albums)</option>';
    }
    loadBackupList();
}

/** The album picked in Photo Backups; '' means the whole frame. */
function backupSourceId() {
    const sel = document.getElementById('backup-source-select');
    return sel ? sel.value : '';
}

const BACKUP_BTN_STYLE = 'padding:0.25rem 0.6rem;font-size:0.8rem;';

function backupButton(label, onclick) {
    return `<button class="btn secondary" style="${BACKUP_BTN_STYLE}" onclick="${onclick}">${label}</button>`;
}

function backupDownloadLink(filename) {
    return `<a class="btn secondary" style="${BACKUP_BTN_STYLE}text-decoration:none;" href="/api/tools/backup/download/${encodeURIComponent(filename)}" download>Download</a>`;
}

async function loadBackupList() {
    const sourceId = backupSourceId();
    const tbody = document.getElementById('backup-tbody');
    const table = document.getElementById('backup-table');
    const empty = document.getElementById('backup-list-empty');
    const albumCol = document.getElementById('backup-album-col');
    if (!tbody) return;
    const wholeFrame = !sourceId;
    const cols = wholeFrame ? 5 : 4;
    if (albumCol) albumCol.style.display = wholeFrame ? '' : 'none';
    tbody.innerHTML = `<tr><td colspan="${cols}" style="color:#94a3b8;">Loading…</td></tr>`;
    if (table) table.style.display = 'table';
    if (empty) empty.style.display = 'none';
    try {
        const data = await apiFetch(wholeFrame ? '/api/tools/backup/all' : `/api/tools/backup/${encodeURIComponent(sourceId)}/list`);
        if (!data.ok) {
            tbody.innerHTML = `<tr><td colspan="${cols}" style="color:#f87171;">${escapeHtml(data.error || 'Error loading backups')}</td></tr>`;
            return;
        }
        const backups = data.backups || [];
        if (backups.length === 0) {
            if (table) table.style.display = 'none';
            if (empty) empty.style.display = 'block';
            return;
        }
        tbody.innerHTML = backups.map(b => {
            const file = escapeHtml(b.filename);
            let restore, albumCell = '';
            if (b.kind === 'frame') {
                restore = `restoreFrameBackup('${file}', ${Number(b.album_count) || 0})`;
                albumCell = `<td><strong>Whole frame</strong> (${plural(b.album_count, 'album')})</td>`;
            } else {
                // Whole frame lists deleted albums' backups too: those restore into a new album
                const albumId = wholeFrame ? (b.album_exists ? b.album_id : null) : sourceId;
                restore = `restoreBackupInto('${file}', ${albumId ? `'${escapeHtml(albumId)}'` : 'null'}, '${escapeHtml(b.album_id || sourceId)}')`;
                if (wholeFrame) {
                    albumCell = `<td>${escapeHtml(b.album_name || b.album_id)}${b.album_exists ? '' : ' <span class="source-status-badge disabled">deleted</span>'}</td>`;
                }
            }
            return `<tr>
                ${albumCell}
                <td style="font-family:monospace;font-size:0.85rem;word-break:break-all;">${escapeHtml(b.path || b.filename)}</td>
                <td>${fmtBytes(b.size_bytes)}</td>
                <td>${new Date(b.created_at).toLocaleString()}</td>
                <td style="white-space:nowrap;">${backupButton('Restore', restore)}
                    ${backupDownloadLink(b.filename)}
                    ${backupButton('Delete', `runDeleteBackup('${file}')`)}</td>
            </tr>`;
        }).join('');
    } catch (e) {
        tbody.innerHTML = `<tr><td colspan="${cols}" style="color:#f87171;">Error: ${escapeHtml(e.message)}</td></tr>`;
    }
}

async function runCreateBackup() {
    const sourceId = backupSourceId();
    const sel = document.getElementById('backup-source-select');
    const albumCount = sel ? sel.options.length - 1 : 0;
    if (!sourceId) {
        if (albumCount === 0) { alert('This frame has no albums to back up.'); return; }
        if (!confirm(`Back up all ${plural(albumCount, 'album')} into one file?\n\nIt's saved in ~/Pictures/backups. Download it afterwards to keep a copy off the frame (for a new SD card or a new frame).`)) return;
    }
    const btn = document.getElementById('btn-create-backup');
    const status = document.getElementById('backup-create-status');
    btn.disabled = true;
    btn.textContent = 'Creating…';
    status.textContent = 'This may take a minute for large libraries…';
    status.style.color = '#94a3b8';
    try {
        const data = sourceId
            ? await apiFetch(`/api/tools/backup/${encodeURIComponent(sourceId)}/create`, { method: 'POST' })
            : await apiFetch('/api/tools/backup/all/create', { method: 'POST' });
        if (data.ok) {
            if (sourceId) {
                status.textContent = `Backup created: ${data.filename} (${fmtBytes(data.size_bytes)})`;
            } else {
                const skipped = (data.skipped || []).length
                    ? ` Skipped (no photos on the frame yet): ${data.skipped.join(', ')}.` : '';
                status.textContent = `Saved ${data.path} (${plural(data.albums, 'album')}, ${fmtBytes(data.size_bytes)}). Use Download to keep a copy off the frame.${skipped}`;
            }
            status.style.color = '#4ade80';
            await loadBackupList();
        } else {
            status.textContent = data.error || 'Backup failed';
            status.style.color = '#f87171';
        }
    } catch (e) {
        status.textContent = `Error: ${e.message}`;
        status.style.color = '#f87171';
    } finally {
        btn.disabled = false;
        btn.textContent = 'Create Backup';
    }
}

async function runDeleteBackup(filename) {
    if (!confirm(`Delete backup "${filename}"? This cannot be undone.`)) return;
    const sourceId = backupSourceId();
    try {
        // Whole frame deletes by filename, so a deleted album's backup can be removed too
        const data = await apiFetch(sourceId ? `/api/tools/backup/${encodeURIComponent(sourceId)}/delete` : '/api/tools/backup/delete', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ filename }),
        });
        if (data.ok) {
            await loadBackupList();
        } else {
            alert(data.error || 'Delete failed');
        }
    } catch (e) {
        alert(`Error: ${e.message}`);
    }
}

function fmtEta(count, secPerItem = 3) {
    const secs = count * secPerItem;
    if (secs < 60) return `~${secs} sec`;
    const mins = Math.round(secs / 60);
    return `~${mins} min`;
}

function fmtBytes(bytes) {
    if (bytes < 1024) return bytes + ' B';
    if (bytes < 1048576) return (bytes / 1024).toFixed(1) + ' KB';
    if (bytes < 1073741824) return (bytes / 1048576).toFixed(1) + ' MB';
    return (bytes / 1073741824).toFixed(2) + ' GB';
}

function reasonLabel(r) {
    return {
        google_id: 'Google ID',
        numbered_suffix: 'Numbered dup',
        ext_case: 'Ext case',
        long_name: 'Long name',
        spaces: 'Spaces',
        wrong_ext: 'Wrong ext',
        special_chars: 'Special chars',
    }[r] || r;
}

// ----- Filename Cleaner -----

async function runFilenameScan() {
    const src = toolsSourceId();
    if (!src) { alert('Select an album first'); return; }
    const header = document.getElementById('filenames-card-header');
    const statusEl = document.getElementById('filenames-scan-status');
    header.dataset.scanning = 'true';
    header.classList.remove('card-header--expandable');
    if (statusEl) statusEl.textContent = 'Scanning…';
    document.getElementById('filenames-result').style.display = 'none';
    try {
        const data = await apiFetch(`/api/tools/${src}/scan/filenames`);
        if (!data.ok) throw new Error(data.error || 'Scan failed');
        renderFilenameResults(src, data);
    } catch (e) {
        alert('Filename scan failed: ' + e.message);
        header.classList.add('card-header--expandable');
    } finally {
        delete header.dataset.scanning;
        if (statusEl) statusEl.textContent = '';
    }
}

// Active filter set — keys are reason codes or "needs_review"
let _fnActiveFilters = new Set();
let _fnCurrentSrc = '';
let _fnFixes = [];

// AbortControllers for cancelling in-progress apply jobs
let _fnAbort = null;
let _dupAbort = null;
let _vidAbort = null;

function renderFilenameResults(src, data) {
    _fnCurrentSrc = src;
    _fnFixes = data.fixes || [];
    _fnActiveFilters = new Set();  // reset to "All" on new scan

    const summary = document.getElementById('filenames-summary');
    const resultDiv = document.getElementById('filenames-result');

    const mtimeCount = _fnFixes.filter(f => f.needs_review).length;
    const mtimeNote = mtimeCount ? ` · ${mtimeCount} without EXIF date` : '';
    summary.textContent = _fnFixes.length === 0
        ? `✅ All ${data.total_files_scanned} files look clean — nothing to fix.`
        : `Found ${_fnFixes.length} file(s) with issues (scanned ${data.total_files_scanned} total)${mtimeNote}.`;

    const setActionVisibility = (visible) => {
        ['btn-apply-filenames', 'btn-apply-filenames-top'].forEach(id => {
            const btn = document.getElementById(id);
            if (btn) btn.closest('.button-row').style.display = visible ? '' : 'none';
        });
    };

    if (_fnFixes.length === 0) {
        document.getElementById('filenames-table-wrap').style.display = 'none';
        document.getElementById('filenames-filter-bar').innerHTML = '';
        setActionVisibility(false);
        resultDiv.style.display = 'block';
        return;
    }

    _buildFilterBar();
    _renderFilenameRows();

    document.getElementById('filenames-table-wrap').style.display = '';
    setActionVisibility(true);
    resultDiv.style.display = 'block';
}

function _buildFilterBar() {
    const bar = document.getElementById('filenames-filter-bar');

    // Count per issue type
    const counts = {};
    let mtimeCount = 0;
    _fnFixes.forEach(f => {
        f.reasons.forEach(r => { counts[r] = (counts[r] || 0) + 1; });
        if (f.needs_review) mtimeCount++;
    });

    const filterTooltips = {
        all:            'Show all files with issues',
        google_id:      'Files with a Google Photos token appended — e.g. IMG_1592 {AByz57...}.HEIC',
        numbered_suffix:'Files with a duplicate-copy suffix — e.g. photo (1).jpg or 20230101(0).jpg',
        ext_case:       'Files with an uppercase extension — e.g. .JPG or .HEIC (will be lowercased)',
        long_name:      'Filename stem is over 20 characters — likely machine-generated; will be renamed to YYYYMMDD_HHMMSS',
        spaces:         'Filename contains spaces — will be replaced with underscores',
        wrong_ext:      'File bytes don\'t match declared extension — e.g. a JPEG file saved as .heic',
        special_chars:  'Characters like & + # \' that the frame can\'t rename — replaced with underscores',
        needs_review:   'Proposed name uses file modification time (no EXIF date found) — review before applying',
    };

    const filters = [
        { key: 'all', label: `All (${_fnFixes.length})` },
        ...Object.entries(counts).map(([k, n]) => ({ key: k, label: `${reasonLabel(k)} (${n})` })),
        ...(mtimeCount ? [{ key: 'needs_review', label: `⚠️ mtime (${mtimeCount})` }] : []),
    ];

    bar.innerHTML = '';
    filters.forEach(({ key, label }) => {
        const btn = document.createElement('button');
        btn.className = 'btn secondary' + (key === 'all' ? ' active' : '');
        btn.style.cssText = 'padding:0.25rem 0.75rem;font-size:0.8rem;margin:0 0.25rem 0.25rem 0;';
        btn.textContent = label;
        btn.dataset.filter = key;
        btn.title = filterTooltips[key] || '';
        btn.addEventListener('click', () => _toggleFilter(key));
        bar.appendChild(btn);
    });
}

function _toggleFilter(key) {
    if (key === 'all') {
        _fnActiveFilters.clear();
    } else {
        _fnActiveFilters.has(key) ? _fnActiveFilters.delete(key) : _fnActiveFilters.add(key);
    }
    // Update button states
    document.querySelectorAll('#filenames-filter-bar button').forEach(btn => {
        const k = btn.dataset.filter;
        if (k === 'all') {
            btn.classList.toggle('active', _fnActiveFilters.size === 0);
        } else {
            btn.classList.toggle('active', _fnActiveFilters.has(k));
        }
    });
    _applyFilenameFilter();
    // Reset all checkboxes — you can only select what you can see
    document.querySelectorAll('.filename-check').forEach(cb => cb.checked = false);
    document.getElementById('filenames-check-all').checked = false;
    updateFilenameApplyBtn();
}

function _applyFilenameFilter() {
    document.querySelectorAll('#filenames-tbody tr').forEach(tr => {
        if (_fnActiveFilters.size === 0) {
            tr.style.display = '';
            return;
        }
        const reasons = JSON.parse(tr.dataset.reasons || '[]');
        const needsReview = tr.dataset.needsReview === 'true';
        const match = [..._fnActiveFilters].some(f =>
            f === 'needs_review' ? needsReview : reasons.includes(f)
        );
        tr.style.display = match ? '' : 'none';
    });
}

function _renderFilenameRows() {
    const tbody = document.getElementById('filenames-tbody');
    tbody.innerHTML = '';

    _fnFixes.forEach(fix => {
        const tr = document.createElement('tr');
        tr.dataset.reasons = JSON.stringify(fix.reasons);
        tr.dataset.needsReview = fix.needs_review ? 'true' : 'false';
        if (fix.needs_review) tr.style.background = 'rgba(120,53,15,0.15)';

        const reviewBadge = fix.needs_review
            ? ' <span class="status-chip" style="background:#78350f;color:#fde68a;">⚠️ mtime</span>'
            : '';

        const orientBadge = (fix.exif_orientation && fix.exif_orientation !== 1)
            ? ` <span class="status-chip" style="background:#4c1d95;color:#ede9fe;" title="EXIF orientation ${fix.exif_orientation} — photo needs rotation">↻ ${fix.exif_orientation}</span>`
            : '';

        const exifCell = fix.exif_date
            ? `<span style="font-size:0.75rem;color:#94a3b8;">${escHtml(fix.exif_date)}</span>${orientBadge}`
            : `<span style="font-size:0.75rem;color:#475569;">—</span>${orientBadge}`;

        const thumbUrl = `/api/thumbnail/${encodeURIComponent(_fnCurrentSrc)}?filename=${encodeURIComponent(fix.original)}`;

        tr.innerHTML = `
            <td style="width:72px;padding:4px;">
                <img src="${thumbUrl}" loading="lazy"
                     style="width:64px;height:64px;object-fit:cover;border-radius:4px;display:block;"
                     onerror="this.style.opacity='0.2';">
            </td>
            <td><input type="checkbox" class="filename-check"
                data-original="${escHtml(fix.original)}"
                data-reasons='${JSON.stringify(fix.reasons)}'></td>
            <td style="font-family:monospace;font-size:0.8rem;">${escHtml(fix.original)}</td>
            <td class="fn-proposed-cell" data-proposed="${escHtml(fix.proposed)}" style="padding:2px 6px;">
                <span class="fn-proposed-display"
                      style="font-family:monospace;font-size:0.8rem;color:#86efac;">${escHtml(fix.proposed)}</span>
            </td>
            <td>${exifCell}</td>
            <td>${fix.reasons.map(r => `<span class="status-chip">${reasonLabel(r)}</span>`).join(' ')}${reviewBadge}</td>
        `;
        tbody.appendChild(tr);
    });

    document.querySelectorAll('.filename-check').forEach(cb => {
        cb.addEventListener('change', () => {
            const tr = cb.closest('tr');
            const cell = tr.querySelector('.fn-proposed-cell');
            if (cb.checked) {
                const current = cell.dataset.proposed;
                cell.innerHTML = `<input type="text" class="fn-proposed-input"
                    value="${escHtml(current)}"
                    style="font-family:monospace;font-size:0.8rem;color:#e2e8f0;background:#1e293b;border:1px solid #475569;border-radius:4px;padding:2px 6px;width:100%;box-sizing:border-box;">`;
            } else {
                const input = cell.querySelector('.fn-proposed-input');
                const val = (input ? input.value.trim() : '') || cell.dataset.proposed;
                cell.dataset.proposed = val;
                cell.innerHTML = `<span class="fn-proposed-display"
                    style="font-family:monospace;font-size:0.8rem;color:#86efac;">${escHtml(val)}</span>`;
            }
            updateFilenameApplyBtn();
        });
    });
    document.getElementById('filenames-check-all').checked = false;
    updateFilenameApplyBtn();
}

function updateFilenameApplyBtn() {
    const checked = document.querySelectorAll('.filename-check:checked').length;
    const label = checked > 0 ? `Apply ${checked} Rename(s)` : 'Apply Selected Renames';
    ['btn-apply-filenames', 'btn-apply-filenames-top'].forEach(id => {
        const btn = document.getElementById(id);
        if (btn) { btn.disabled = checked === 0; btn.textContent = label; }
    });
}

async function runFilenameApply() {
    const src = toolsSourceId();
    const checked = [...document.querySelectorAll('.filename-check:checked')];
    if (!checked.length) return;
    if (!confirm(`Rename ${checked.length} file(s)? Cloud files will be renamed first.\nEstimated time: ${fmtEta(checked.length)}`)) return;

    const fixes = checked.map(cb => {
        const tr = cb.closest('tr');
        const cell = tr.querySelector('.fn-proposed-cell');
        const input = cell?.querySelector('.fn-proposed-input');
        const proposed = (input ? input.value.trim() : '') || cell?.dataset.proposed || '';
        return { original: cb.dataset.original, proposed, reasons: JSON.parse(cb.dataset.reasons) };
    });

    const total = fixes.length;
    let succeeded = 0;
    const failures = [];

    const setStatus = (msg, color = '#94a3b8') => {
        ['filenames-apply-status', 'filenames-apply-status-top'].forEach(id => {
            const el = document.getElementById(id);
            if (el) { el.textContent = msg; el.style.color = color; }
        });
    };
    const setBtn = (text) => {
        ['btn-apply-filenames', 'btn-apply-filenames-top'].forEach(id => {
            const btn = document.getElementById(id);
            if (btn) { btn.disabled = true; btn.textContent = text; }
        });
    };
    const showCancel = (visible) => {
        ['btn-cancel-filenames', 'btn-cancel-filenames-top'].forEach(id => {
            const btn = document.getElementById(id);
            if (btn) btn.style.display = visible ? '' : 'none';
        });
    };

    _fnAbort = new AbortController();
    setBtn(`Renaming 0 of ${total}…`);
    showCancel(true);
    setStatus('');

    try {
        for (let i = 0; i < fixes.length; i++) {
            if (_fnAbort.signal.aborted) break;
            const fix = fixes[i];
            setBtn(`Renaming ${i + 1} of ${total}…`);
            setStatus(`${fix.original} → ${fix.proposed}`, '#fbbf24');
            try {
                const data = await apiFetch(`/api/tools/${src}/apply/filenames`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ fixes: [fix] }),
                    signal: _fnAbort.signal,
                });
                if (data.succeeded?.length) succeeded++;
                else failures.push(...(data.failed?.length ? data.failed : [{ filename: fix.original, error: data.error || 'Unknown error' }]));
            } catch (e) {
                if (e.name === 'AbortError') break;
                failures.push({ filename: fix.original, error: e.message });
            }
        }
        const cancelled = _fnAbort.signal.aborted;
        setStatus(
            cancelled
                ? `⏹ Stopped after ${succeeded} rename(s)${failures.length ? ` · ⚠️ ${failures.length} failed` : ''}`
                : `✅ ${succeeded} of ${total} renamed${failures.length ? ` · ⚠️ ${failures.length} failed` : ''}`,
            cancelled || failures.length ? '#fbbf24' : '#86efac'
        );
        if (failures.length) console.warn('Rename failures:', failures);
        if (!cancelled) setTimeout(runFilenameScan, 800);
    } finally {
        showCancel(false);
        _fnAbort = null;
        updateFilenameApplyBtn();
    }
}

// ----- Duplicate Finder -----

async function runDupScan() {
    const src = toolsSourceId();
    if (!src) { alert('Select an album first'); return; }
    const header = document.getElementById('duplicates-card-header');
    const statusEl = document.getElementById('duplicates-scan-status');
    header.dataset.scanning = 'true';
    header.classList.remove('card-header--expandable');
    if (statusEl) statusEl.textContent = 'Scanning…';
    document.getElementById('duplicates-result').style.display = 'none';
    try {
        const data = await apiFetch(`/api/tools/${src}/scan/duplicates`);
        if (!data.ok) throw new Error(data.error || 'Scan failed');
        renderDupResults(src, data);
    } catch (e) {
        alert('Duplicate scan failed: ' + e.message);
        header.classList.add('card-header--expandable');
    } finally {
        delete header.dataset.scanning;
        if (statusEl) statusEl.textContent = '';
    }
}

function renderDupResults(src, data) {
    const groups = data.groups || [];
    const summary = document.getElementById('duplicates-summary');
    const container = document.getElementById('duplicates-groups');
    const resultDiv = document.getElementById('duplicates-result');

    summary.textContent = groups.length === 0
        ? `✅ No exact duplicates found in ${data.total_files_scanned} files.`
        : `Found ${groups.length} duplicate group(s) — ${data.duplicate_count} file(s) can be removed.`;

    container.innerHTML = '';
    groups.forEach((group, idx) => {
        const div = document.createElement('div');
        div.style.cssText = 'border:1px solid #334155;border-radius:6px;padding:1rem;margin-bottom:1rem;';
        const rows = group.files.map(f => `
            <tr>
                <td>
                    <label style="display:flex;align-items:center;gap:0.5rem;">
                        <input type="radio" name="dup_keep_${idx}" class="dup-keep"
                            data-group="${idx}" value="${escHtml(f.filename)}"
                            ${f.filename === group.keep_suggestion ? 'checked' : ''}>
                        <span style="font-size:0.75rem;color:#22c55e;font-weight:600;">KEEP</span>
                    </label>
                </td>
                <td style="font-family:monospace;font-size:0.8rem;">${escHtml(f.filename)}</td>
                <td style="color:#94a3b8;">${fmtBytes(f.size_bytes)}</td>
            </tr>
        `).join('');
        div.innerHTML = `
            <div style="color:#94a3b8;font-size:0.8rem;margin-bottom:0.5rem;">
                Group ${idx + 1} · ${group.files.length} identical files · ${fmtBytes(group.files[0].size_bytes)} each
            </div>
            <table class="sources-table" style="margin:0;">
                <thead><tr><th>Keep?</th><th>Filename</th><th>Size</th></tr></thead>
                <tbody>${rows}</tbody>
            </table>
        `;
        container.appendChild(div);
    });

    document.querySelectorAll('.dup-keep').forEach(r =>
        r.addEventListener('change', updateDupApplyBtn)
    );
    updateDupApplyBtn();
    resultDiv.style.display = 'block';
}

function updateDupApplyBtn() {
    const groupNames = new Set(
        [...document.querySelectorAll('[name^="dup_keep_"]')].map(r => r.name)
    );
    let toDelete = 0;
    groupNames.forEach(name => {
        toDelete += document.querySelectorAll(`[name="${name}"]`).length - 1;
    });
    const label = toDelete > 0 ? `Delete ${toDelete} Duplicate(s)` : 'Delete Duplicates';
    ['btn-apply-duplicates', 'btn-apply-duplicates-top'].forEach(id => {
        const btn = document.getElementById(id);
        if (btn) { btn.disabled = groupNames.size === 0; btn.textContent = label; }
    });
}

async function runDupApply() {
    const src = toolsSourceId();
    const groupNames = new Set(
        [...document.querySelectorAll('[name^="dup_keep_"]')].map(r => r.name)
    );

    const toDelete = [];
    groupNames.forEach(name => {
        const radios = [...document.querySelectorAll(`[name="${name}"]`)];
        const kept = radios.find(r => r.checked)?.value;
        radios.forEach(r => { if (r.value !== kept) toDelete.push(r.value); });
    });

    if (!toDelete.length) return;
    if (!confirm(`Delete ${toDelete.length} duplicate file(s)? This cannot be undone.\nEstimated time: ${fmtEta(toDelete.length)}`)) return;

    const total = toDelete.length;
    let succeeded = 0;
    const failures = [];

    const setStatus = (msg, color = '#94a3b8') => {
        ['duplicates-apply-status', 'duplicates-apply-status-top'].forEach(id => {
            const el = document.getElementById(id);
            if (el) { el.textContent = msg; el.style.color = color; }
        });
    };
    const setBtn = (text) => {
        ['btn-apply-duplicates', 'btn-apply-duplicates-top'].forEach(id => {
            const btn = document.getElementById(id);
            if (btn) { btn.disabled = true; btn.textContent = text; }
        });
    };
    const showCancel = (visible) => {
        ['btn-cancel-duplicates', 'btn-cancel-duplicates-top'].forEach(id => {
            const btn = document.getElementById(id);
            if (btn) btn.style.display = visible ? '' : 'none';
        });
    };

    _dupAbort = new AbortController();
    setBtn(`Deleting 0 of ${total}…`);
    showCancel(true);
    setStatus('');

    try {
        for (let i = 0; i < toDelete.length; i++) {
            if (_dupAbort.signal.aborted) break;
            const filename = toDelete[i];
            setBtn(`Deleting ${i + 1} of ${total}…`);
            setStatus(filename, '#fbbf24');
            try {
                const data = await apiFetch(`/api/tools/${src}/apply/duplicates`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ to_delete: [filename] }),
                    signal: _dupAbort.signal,
                });
                if (data.succeeded?.length) succeeded++;
                else failures.push(...(data.failed?.length ? data.failed : [{ filename, error: data.error || 'Unknown error' }]));
            } catch (e) {
                if (e.name === 'AbortError') break;
                failures.push({ filename, error: e.message });
            }
        }
        const cancelled = _dupAbort.signal.aborted;
        setStatus(
            cancelled
                ? `⏹ Stopped after ${succeeded} deletion(s)${failures.length ? ` · ⚠️ ${failures.length} failed` : ''}`
                : `✅ ${succeeded} of ${total} deleted${failures.length ? ` · ⚠️ ${failures.length} failed` : ''}`,
            cancelled || failures.length ? '#fbbf24' : '#86efac'
        );
        if (failures.length) console.warn('Delete failures:', failures);
        if (!cancelled) setTimeout(runDupScan, 800);
    } finally {
        showCancel(false);
        _dupAbort = null;
        updateDupApplyBtn();
    }
}

// ----- Video Manager -----

async function runVideoScan() {
    const src = toolsSourceId();
    if (!src) { alert('Select an album first'); return; }
    const header = document.getElementById('videos-card-header');
    const statusEl = document.getElementById('videos-scan-status');
    header.dataset.scanning = 'true';
    header.classList.remove('card-header--expandable');
    if (statusEl) statusEl.textContent = 'Scanning…';
    document.getElementById('videos-result').style.display = 'none';
    try {
        const data = await apiFetch(`/api/tools/${src}/scan/videos`);
        if (!data.ok) throw new Error(data.error || 'Scan failed');
        renderVideoResults(src, data);
    } catch (e) {
        alert('Video scan failed: ' + e.message);
        header.classList.add('card-header--expandable');
    } finally {
        delete header.dataset.scanning;
        if (statusEl) statusEl.textContent = '';
    }
}

function renderVideoResults(src, data) {
    const videos = data.videos || [];
    const summary = document.getElementById('videos-summary');
    const tbody = document.getElementById('videos-tbody');
    const resultDiv = document.getElementById('videos-result');

    summary.textContent = videos.length === 0
        ? '✅ No video files found in this album.'
        : `Found ${videos.length} video file(s) · ${fmtBytes(data.total_size_bytes)} total.`;

    tbody.innerHTML = '';
    videos.forEach(v => {
        const tr = document.createElement('tr');
        tr.innerHTML = `
            <td><input type="checkbox" class="video-check" value="${escHtml(v.filename)}" checked></td>
            <td style="font-family:monospace;font-size:0.8rem;">${escHtml(v.filename)}</td>
            <td style="color:#94a3b8;">${fmtBytes(v.size_bytes)}</td>
        `;
        tbody.appendChild(tr);
    });

    document.querySelectorAll('.video-check').forEach(cb =>
        cb.addEventListener('change', updateVideoApplyBtn)
    );
    document.getElementById('videos-check-all').checked = videos.length > 0;
    updateVideoApplyBtn();
    resultDiv.style.display = 'block';
}

function updateVideoApplyBtn() {
    const checked = document.querySelectorAll('.video-check:checked').length;
    const label = checked > 0 ? `Delete ${checked} Video(s)` : 'Delete Selected Videos';
    ['btn-apply-videos', 'btn-apply-videos-top'].forEach(id => {
        const btn = document.getElementById(id);
        if (btn) { btn.disabled = checked === 0; btn.textContent = label; }
    });
}

async function runVideoApply() {
    const src = toolsSourceId();
    const toDelete = [...document.querySelectorAll('.video-check:checked')].map(cb => cb.value);
    if (!toDelete.length) return;
    if (!confirm(`Delete ${toDelete.length} video file(s)? This cannot be undone.\nEstimated time: ${fmtEta(toDelete.length)}`)) return;

    const total = toDelete.length;
    let succeeded = 0;
    const failures = [];

    const setStatus = (msg, color = '#94a3b8') => {
        ['videos-apply-status', 'videos-apply-status-top'].forEach(id => {
            const el = document.getElementById(id);
            if (el) { el.textContent = msg; el.style.color = color; }
        });
    };
    const setBtn = (text) => {
        ['btn-apply-videos', 'btn-apply-videos-top'].forEach(id => {
            const btn = document.getElementById(id);
            if (btn) { btn.disabled = true; btn.textContent = text; }
        });
    };
    const showCancel = (visible) => {
        ['btn-cancel-videos', 'btn-cancel-videos-top'].forEach(id => {
            const btn = document.getElementById(id);
            if (btn) btn.style.display = visible ? '' : 'none';
        });
    };

    _vidAbort = new AbortController();
    setBtn(`Deleting 0 of ${total}…`);
    showCancel(true);
    setStatus('');

    try {
        for (let i = 0; i < toDelete.length; i++) {
            if (_vidAbort.signal.aborted) break;
            const filename = toDelete[i];
            setBtn(`Deleting ${i + 1} of ${total}…`);
            setStatus(filename, '#fbbf24');
            try {
                const data = await apiFetch(`/api/tools/${src}/apply/videos`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ to_delete: [filename] }),
                    signal: _vidAbort.signal,
                });
                if (data.succeeded?.length) succeeded++;
                else failures.push(...(data.failed?.length ? data.failed : [{ filename, error: data.error || 'Unknown error' }]));
            } catch (e) {
                if (e.name === 'AbortError') break;
                failures.push({ filename, error: e.message });
            }
        }
        const cancelled = _vidAbort.signal.aborted;
        setStatus(
            cancelled
                ? `⏹ Stopped after ${succeeded} deletion(s)${failures.length ? ` · ⚠️ ${failures.length} failed` : ''}`
                : `✅ ${succeeded} of ${total} deleted${failures.length ? ` · ⚠️ ${failures.length} failed` : ''}`,
            cancelled || failures.length ? '#fbbf24' : '#86efac'
        );
        if (failures.length) console.warn('Video delete failures:', failures);
        if (!cancelled) setTimeout(runVideoScan, 800);
    } finally {
        showCancel(false);
        _vidAbort = null;
        updateVideoApplyBtn();
    }
}

// ----- Corrupt Photo Finder (PL-127) -----

async function runCorruptScan() {
    const src = toolsSourceId();
    if (!src) { alert('Select an album first'); return; }
    const header = document.getElementById('corrupt-card-header');
    const statusEl = document.getElementById('corrupt-scan-status');
    header.dataset.scanning = 'true';
    header.classList.remove('card-header--expandable');
    if (statusEl) statusEl.textContent = 'Checking every photo… (can take a few minutes)';
    document.getElementById('corrupt-result').style.display = 'none';
    try {
        const data = await apiFetch(`/api/tools/${encodeURIComponent(src)}/scan/corrupt`);
        if (!data.ok) throw new Error(data.error || 'Scan failed');
        renderCorruptResults(data);
    } catch (e) {
        alert('Corrupt photo scan failed: ' + e.message);
        header.classList.add('card-header--expandable');
    } finally {
        delete header.dataset.scanning;
        if (statusEl) statusEl.textContent = '';
    }
}

function renderCorruptResults(data) {
    const files = data.files || [];
    const skipped = data.skipped ? ` ${data.skipped} HEIC photo(s) not checked (no HEIC support).` : '';
    document.getElementById('corrupt-summary').textContent = (files.length === 0
        ? `✅ All ${data.total_files_scanned} photos open fine.`
        : `Found ${files.length} damaged or empty photo(s) out of ${data.total_files_scanned}.`) + skipped;
    const tbody = document.getElementById('corrupt-tbody');
    tbody.innerHTML = files.map(f => `<tr>
        <td><input type="checkbox" class="corrupt-check" value="${escHtml(f.filename)}" checked></td>
        <td style="font-family:monospace;font-size:0.8rem;">${escHtml(f.filename)}</td>
        <td style="color:#94a3b8;">${fmtBytes(f.size_bytes)}</td>
        <td style="color:#fca5a5;font-size:0.8rem;">${escHtml(f.error)}</td>
    </tr>`).join('');
    document.querySelectorAll('.corrupt-check').forEach(cb => cb.addEventListener('change', updateCorruptApplyBtn));
    document.getElementById('corrupt-check-all').checked = files.length > 0;
    document.getElementById('corrupt-table-wrap').style.display = files.length ? '' : 'none';
    updateCorruptApplyBtn();
    document.getElementById('corrupt-result').style.display = 'block';
}

function updateCorruptApplyBtn() {
    const checked = document.querySelectorAll('.corrupt-check:checked').length;
    const btn = document.getElementById('btn-apply-corrupt');
    if (btn) { btn.disabled = checked === 0; btn.textContent = checked ? `Delete ${checked} Photo(s)` : 'Delete Selected Photos'; }
}

async function runCorruptApply() {
    const src = toolsSourceId();
    const toDelete = [...document.querySelectorAll('.corrupt-check:checked')].map(cb => cb.value);
    if (!toDelete.length) return;
    if (!confirm(`Delete ${toDelete.length} damaged photo(s) from the frame and its cloud folder? This cannot be undone.`)) return;
    const status = document.getElementById('corrupt-apply-status');
    const btn = document.getElementById('btn-apply-corrupt');
    btn.disabled = true;
    status.textContent = 'Deleting…';
    status.style.color = '#94a3b8';
    try {
        const data = await apiFetch(`/api/tools/${encodeURIComponent(src)}/apply/corrupt`, {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ to_delete: toDelete }),
        });
        if (!data.ok) throw new Error(data.error || 'Delete failed');
        const failed = data.failed || [];
        status.textContent = `✅ ${data.succeeded.length} deleted` + (failed.length ? ` · ⚠️ ${failed.length} failed: ${failed.map(f => `${f.filename} (${f.error})`).join(', ')}` : '');
        status.style.color = failed.length ? '#fbbf24' : '#86efac';
        setTimeout(runCorruptScan, 800);
    } catch (e) {
        status.textContent = 'Error: ' + e.message;
        status.style.color = '#f87171';
        updateCorruptApplyBtn();
    }
}

// ----- Rotate Photos (PL-126) -----

const ROTATABLE = /\.(jpe?g|png|hei[cf])$/i;
let _rotateFiles = [];

async function runRotateScan() {
    const src = toolsSourceId();
    if (!src) { alert('Select an album first'); return; }
    const header = document.getElementById('rotate-card-header');
    const statusEl = document.getElementById('rotate-scan-status');
    header.dataset.scanning = 'true';
    header.classList.remove('card-header--expandable');
    if (statusEl) statusEl.textContent = 'Loading photos…';
    document.getElementById('rotate-result').style.display = 'none';
    try {
        const data = await apiFetch(`/api/tools/${encodeURIComponent(src)}/scan/files`);
        if (!data.ok) throw new Error(data.error || 'Scan failed');
        _rotateFiles = (data.files || []).filter(f => ROTATABLE.test(f.filename));
        renderRotateResults();
        document.getElementById('rotate-result').style.display = 'block';
    } catch (e) {
        alert('Loading photos failed: ' + e.message);
        header.classList.add('card-header--expandable');
    } finally {
        delete header.dataset.scanning;
        if (statusEl) statusEl.textContent = '';
    }
}

function rotateNeedsFix(f) { return f.exif_orientation && f.exif_orientation !== 1; }

function renderRotateResults() {
    const src = toolsSourceId();
    const onlyFlagged = document.getElementById('rotate-only-flagged').checked;
    const flagged = _rotateFiles.filter(rotateNeedsFix);
    const shown = onlyFlagged ? flagged : _rotateFiles;
    document.getElementById('rotate-summary').textContent =
        `${_rotateFiles.length} photo(s)` + (flagged.length ? ` · ${flagged.length} with an EXIF rotation` : '');
    const fixBtn = document.getElementById('btn-rotate-fix-all');
    fixBtn.disabled = flagged.length === 0;
    fixBtn.textContent = flagged.length ? `Fix EXIF Orientation (${flagged.length})` : 'Fix EXIF Orientation';
    const bust = Date.now();
    document.getElementById('rotate-tbody').innerHTML = shown.map(f => {
        const name = escHtml(f.filename);
        const thumb = `/api/thumbnail/${encodeURIComponent(src)}?filename=${encodeURIComponent(f.filename)}&v=${bust}`;
        const badge = rotateNeedsFix(f)
            ? `<span class="status-chip" style="background:#4c1d95;color:#ede9fe;" title="EXIF orientation ${f.exif_orientation}">↻ ${f.exif_orientation}</span>` : '';
        const btn = (label, rotate, title) =>
            `<button class="btn-small" title="${title}" onclick="rotatePhotos([{filename: this.closest('tr').dataset.file, rotate: '${rotate}'}])">${label}</button>`;
        return `<tr data-file="${name}">
            <td><img src="${thumb}" loading="lazy" style="width:64px;height:64px;object-fit:cover;border-radius:4px;" alt=""></td>
            <td style="font-family:monospace;font-size:0.8rem;">${name}</td>
            <td>${badge}</td>
            <td style="white-space:nowrap;">${btn('⟲', 'left', 'Rotate left')} ${btn('⟳', 'right', 'Rotate right')} ${btn('180°', '180', 'Upside down')}${rotateNeedsFix(f) ? ' ' + btn('Fix', 'auto', 'Apply the EXIF orientation') : ''}</td>
        </tr>`;
    }).join('') || '<tr><td colspan="4" style="color:#94a3b8;">No photos to show.</td></tr>';
}

async function rotatePhotos(items) {
    const src = toolsSourceId();
    const status = document.getElementById('rotate-status');
    status.textContent = items.length === 1 ? `Rotating ${items[0].filename}…` : `Rotating ${items.length} photos…`;
    status.style.color = '#fbbf24';
    try {
        const data = await apiFetch(`/api/tools/${encodeURIComponent(src)}/rotate`, {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ items }),
        });
        if (!data.ok) throw new Error(data.error || 'Rotate failed');
        const failed = data.failed || [];
        status.textContent = `✅ ${data.succeeded.length} rotated` + (failed.length ? ` · ⚠️ ${failed.map(f => `${f.filename} (${f.error})`).join(', ')}` : '');
        status.style.color = failed.length ? '#fbbf24' : '#86efac';
        // Rotated photos now have orientation 1; refresh the list and thumbnails
        data.succeeded.forEach(name => {
            const f = _rotateFiles.find(x => x.filename === name);
            if (f) f.exif_orientation = 1;
        });
        renderRotateResults();
    } catch (e) {
        status.textContent = 'Error: ' + e.message;
        status.style.color = '#f87171';
    }
}

function rotateFixAll() {
    const flagged = _rotateFiles.filter(rotateNeedsFix);
    if (!flagged.length) return;
    if (!confirm(`Apply the EXIF orientation to ${flagged.length} photo(s)? Each is re-saved upright and uploaded to the cloud folder.`)) return;
    rotatePhotos(flagged.map(f => ({ filename: f.filename, rotate: 'auto' })));
}

// ----- Rename File (browser + batch) -----

// Full set of filenames in the current source, populated by runRenameScan.
// Used for duplicate detection.
let _renameFileSet = new Set();

async function runRenameScan() {
    const srcId = toolsSourceId();
    if (!srcId) { alert('Select an album first.'); return; }
    const header = document.getElementById('rename-card-header');
    const statusEl = document.getElementById('rename-scan-status');
    const summaryEl = document.getElementById('rename-summary');
    const resultEl = document.getElementById('rename-result');
    header.dataset.scanning = 'true';
    header.classList.remove('card-header--expandable');
    if (statusEl) statusEl.textContent = 'Scanning…';
    resultEl.style.display = 'none';
    summaryEl.textContent = 'Reading files and EXIF data — may take a moment…';
    try {
        const data = await apiFetch(`/api/tools/${srcId}/scan/files`);
        if (!data.ok) throw new Error(data.error || 'Scan failed');
        const files = data.files || [];

        // Build the filename set for conflict detection
        _renameFileSet = new Set(files.map(f => f.filename));

        summaryEl.textContent =
            `${files.length} file${files.length === 1 ? '' : 's'} — fill in New Filename to queue a rename`;
        const tbody = document.getElementById('rename-tbody');
        tbody.innerHTML = '';
        files.forEach(f => {
            const tr = document.createElement('tr');
            const thumbSrc = `/api/thumbnail/${srcId}?filename=${encodeURIComponent(f.filename)}`;
            const exifCell = f.exif_date
                ? `<span style="font-size:0.8rem;">${escHtml(f.exif_date)}</span>`
                : `<span style="color:#64748b;font-size:0.8rem;">—</span>`;
            tr.innerHTML = `
                <td><img src="${thumbSrc}" style="width:64px;height:64px;object-fit:cover;border-radius:4px;"
                    loading="lazy" onerror="this.style.display='none'"></td>
                <td style="font-family:monospace;font-size:0.85rem;">${escHtml(f.filename)}</td>
                <td>${exifCell}</td>
                <td><input type="text" class="form-input rename-new-name"
                    data-original="${escHtml(f.filename)}"
                    value=""
                    placeholder="${escHtml(f.filename)}"
                    style="width:100%;min-width:200px;font-family:monospace;font-size:0.85rem;"
                    spellcheck="false"></td>`;
            tbody.appendChild(tr);
        });
        tbody.querySelectorAll('.rename-new-name').forEach(inp => {
            inp.addEventListener('input', updateRenameApplyBtn);
        });
        resultEl.style.display = 'block';
        updateRenameApplyBtn();
    } catch (e) {
        summaryEl.textContent = '❌ ' + e.message;
        summaryEl.style.color = '#f87171';
        header.classList.add('card-header--expandable');
    } finally {
        delete header.dataset.scanning;
        if (statusEl) statusEl.textContent = '';
    }
}

function getRenameChanges() {
    const changes = [];
    document.querySelectorAll('#rename-tbody .rename-new-name').forEach(inp => {
        const original = inp.dataset.original;
        const proposed = inp.value.trim();
        if (proposed && proposed !== original) {
            changes.push({ original, proposed, reasons: [] });
        }
    });
    return changes;
}

// Validates all non-empty rename inputs. Highlights conflicts in red and
// returns true only if everything is clean.
function validateRenameInputs() {
    // Count occurrences of each proposed name to catch within-batch dups
    const proposedCounts = new Map();
    document.querySelectorAll('#rename-tbody .rename-new-name').forEach(inp => {
        const proposed = inp.value.trim();
        if (proposed) proposedCounts.set(proposed, (proposedCounts.get(proposed) || 0) + 1);
    });

    let valid = true;
    document.querySelectorAll('#rename-tbody .rename-new-name').forEach(inp => {
        const original = inp.dataset.original;
        const proposed = inp.value.trim();

        // Reset styling
        inp.style.borderColor = '';
        inp.title = '';

        if (!proposed || proposed === original) return;

        let conflict = null;
        if ((proposedCounts.get(proposed) || 0) > 1) {
            conflict = `"${proposed}" is queued for multiple files`;
        } else if (_renameFileSet.has(proposed)) {
            conflict = `"${proposed}" already exists in this album`;
        }

        if (conflict) {
            inp.style.borderColor = '#f87171';
            inp.title = conflict;
            valid = false;
        }
    });
    return valid;
}

function updateRenameApplyBtn() {
    const changes = getRenameChanges();
    const enabled = changes.length > 0 && validateRenameInputs();
    ['btn-apply-rename', 'btn-apply-rename-top'].forEach(id => {
        const b = document.getElementById(id);
        if (b) b.disabled = !enabled;
    });
}

async function runRenameApply() {
    const srcId = toolsSourceId();
    const fixes = getRenameChanges();
    if (!fixes.length || !validateRenameInputs()) return;
    const topBtn = document.getElementById('btn-apply-rename-top');
    const botBtn = document.getElementById('btn-apply-rename');
    const topStatus = document.getElementById('rename-apply-status-top');
    const botStatus = document.getElementById('rename-apply-status');
    [topBtn, botBtn].forEach(b => { if (b) b.disabled = true; });
    const msg = `Renaming ${fixes.length} file${fixes.length === 1 ? '' : 's'}…`;
    topStatus.textContent = botStatus.textContent = msg;
    topStatus.style.color = botStatus.style.color = '#94a3b8';
    try {
        const data = await apiFetch(`/api/tools/${srcId}/apply/filenames`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ fixes }),
        });
        const succeeded = data.succeeded?.length ?? 0;
        const failed = data.failed?.length ?? 0;
        const result = failed
            ? `✅ ${succeeded} renamed, ❌ ${failed} failed`
            : `✅ ${succeeded} file${succeeded === 1 ? '' : 's'} renamed`;
        topStatus.textContent = botStatus.textContent = result;
        topStatus.style.color = botStatus.style.color = failed ? '#f87171' : '#4ade80';
        if (succeeded) await runRenameScan();
    } catch (e) {
        topStatus.textContent = botStatus.textContent = '❌ ' + e.message;
        topStatus.style.color = botStatus.style.color = '#f87171';
        [topBtn, botBtn].forEach(b => { if (b) b.disabled = false; });
    }
}

// Helper used throughout tools JS
function escHtml(str) {
    return String(str).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

async function apiFetch(url, opts = {}) {
    const resp = await fetch(url, opts);
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    return resp.json();
}

function toggleKoofrPassword() {
    const input = document.getElementById('koofr-pass-input');
    const btn = input.nextElementSibling;
    if (input.type === 'password') {
        input.type = 'text';
        btn.textContent = 'Hide';
    } else {
        input.type = 'password';
        btn.textContent = 'Show';
    }
}

async function testKoofrConnection() {
    const btn = document.getElementById('btn-test-koofr');
    const msg = document.getElementById('koofr-test-msg');
    if (!btn || !msg) return;

    btn.disabled = true;
    btn.textContent = 'Testing…';
    msg.style.color = '#94a3b8';
    msg.textContent = 'Connecting to Koofr…';

    try {
        const resp = await fetch('/api/cloud/test', { method: 'POST' });
        const data = await resp.json();
        if (data.ok) {
            msg.style.color = '#4ade80';
            msg.textContent = '✓ ' + data.message;
            setTimeout(refreshStatus, 1000);
        } else {
            msg.style.color = '#f87171';
            msg.textContent = '✗ ' + data.error;
        }
    } catch (err) {
        msg.style.color = '#f87171';
        msg.textContent = '✗ Network error — check API is running.';
    } finally {
        btn.disabled = false;
        btn.textContent = '⚡ Test Connection';
    }
}

async function saveKoofrSetup() {
    const user = document.getElementById('koofr-user-input').value.trim();
    const pass = document.getElementById('koofr-pass-input').value.trim();
    const msg  = document.getElementById('koofr-setup-msg');
    const btn  = document.getElementById('koofr-save-btn');

    if (!user || !pass) {
        msg.style.color = '#dc3545';
        msg.textContent = 'Email and password are required.';
        return;
    }

    btn.disabled = true;
    btn.textContent = 'Checking\u2026';
    msg.style.color = '#666';
    msg.textContent = 'Verifying credentials with Koofr\u2026';

    try {
        const resp = await fetch('/dashboard/koofr-setup', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ koofr_user: user, koofr_pass: pass }),
        });
        const data = await resp.json();
        if (data.success) {
            alert('Koofr connected! Your photos will start syncing shortly.');
            location.reload();
        } else {
            msg.style.color = '#dc3545';
            msg.textContent = data.error || 'Verification failed. Check your credentials.';
            btn.disabled = false;
            btn.textContent = 'Save & Verify';
        }
    } catch (err) {
        msg.style.color = '#dc3545';
        msg.textContent = 'Network error. Please try again.';
        btn.disabled = false;
        btn.textContent = 'Save & Verify';
    }
}

// =============================================================================
// Party Mode
// =============================================================================

(function initPartyMode() {
    const checkbox     = document.getElementById('party-mode-checkbox');
    const saveBtn      = document.getElementById('btn-save-party');
    const statusEl     = document.getElementById('party-mode-status');
    const enableModal  = document.getElementById('party-enable-modal');
    const modalSource  = document.getElementById('party-modal-source');
    const confirmInput = document.getElementById('party-confirm-input');
    const confirmBtn   = document.getElementById('btn-party-enable-confirm');
    const cancelBtn    = document.getElementById('btn-party-enable-cancel');

    if (!checkbox || !saveBtn) return;

    const currentlyEnabled = checkbox.checked;

    function showStatus(msg, type) {
        statusEl.textContent = msg;
        statusEl.className = 'status-message ' + type;
        statusEl.style.display = 'block';
    }

    async function applyPartyMode(enabled) {
        saveBtn.disabled = true;
        showStatus(enabled ? 'Enabling party mode…' : 'Disabling party mode…', 'info');
        try {
            const resp = await fetch('/api/settings/party', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ enabled }),
            });
            const data = await resp.json();
            if (data.ok) {
                location.reload();
            } else {
                showStatus('Error: ' + (data.error || 'Unknown failure'), 'error');
                saveBtn.disabled = false;
            }
        } catch (err) {
            showStatus('Network error. Please try again.', 'error');
            saveBtn.disabled = false;
        }
    }

    // Enable modal: reactive input validation
    if (confirmInput && confirmBtn) {
        confirmInput.addEventListener('input', () => {
            const valid = confirmInput.value === 'CONFIRM';
            confirmBtn.disabled = !valid;
            confirmBtn.style.opacity = valid ? '1' : '0.4';
        });
    }

    if (confirmBtn) {
        confirmBtn.addEventListener('click', () => {
            enableModal.style.display = 'none';
            confirmInput.value = '';
            confirmBtn.disabled = true;
            confirmBtn.style.opacity = '0.4';
            applyPartyMode(true);
        });
    }

    if (cancelBtn) {
        cancelBtn.addEventListener('click', () => {
            enableModal.style.display = 'none';
            confirmInput.value = '';
            confirmBtn.disabled = true;
            confirmBtn.style.opacity = '0.4';
            checkbox.checked = currentlyEnabled;
        });
    }

    // Close modal on backdrop click
    if (enableModal) {
        enableModal.addEventListener('click', (e) => {
            if (e.target === enableModal) cancelBtn.click();
        });
    }

    saveBtn.addEventListener('click', () => {
        const wantEnabled = checkbox.checked;
        if (wantEnabled === currentlyEnabled) return; // no change

        if (wantEnabled) {
            // Show type-to-confirm modal
            if (modalSource) modalSource.textContent = document.querySelector('#party-mode-checkbox')
                ?.closest('section')?.querySelector('.form-input[disabled]')?.value || 'current album';
            enableModal.style.display = 'flex';
            confirmInput.value = '';
            confirmBtn.disabled = true;
            confirmBtn.style.opacity = '0.4';
            setTimeout(() => confirmInput.focus(), 50);
        } else {
            // Two-click native confirm for disable
            if (!confirm('This will re-enable cloud sync and WiFi recovery. Continue?')) {
                checkbox.checked = true;
                return;
            }
            applyPartyMode(false);
        }
    });
})();


// =============================================================================
// Demo Mode (PL-015)
// =============================================================================

function plural(n, word) {
    return `${n} ${word}${n === 1 ? '' : 's'}`;
}

/** Show or hide the SD-card-moved and taken-over banners from /dashboard/status. */
function updateRegistryBanners(registry) {
    if (!registry) return;
    const swap = document.getElementById('swap-banner');
    const replaced = document.getElementById('replaced-banner');
    if (swap) {
        swap.style.display = registry.pending_swap ? '' : 'none';
        document.getElementById('swap-banner-old').textContent = registry.pending_swap || '';
    }
    if (replaced) {
        replaced.style.display = registry.replaced_by ? '' : 'none';
        document.getElementById('replaced-banner-by').textContent = registry.replaced_by || '';
        const at = document.getElementById('replaced-banner-at');
        at.textContent = registry.replaced_at ? ` on ${new Date(registry.replaced_at).toLocaleDateString()}` : '';
    }
}

(function initRegistryBanners() {
    const at = document.getElementById('replaced-banner-at');
    if (at && at.dataset.at) at.textContent = ` on ${new Date(at.dataset.at).toLocaleDateString()}`;

    async function post(url, body, okMessage) {
        try {
            const data = await apiFetch(url, {
                method: 'POST', headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(body || {}),
            });
            if (!data.ok) { alert(data.error); return; }
            alert(okMessage(data));
            location.reload();
        } catch (e) {
            alert(`Error: ${e.message}`);
        }
    }

    const moved = document.getElementById('btn-swap-moved');
    const copied = document.getElementById('btn-swap-copied');
    const undo = document.getElementById('btn-undo-takeover');
    if (moved) moved.addEventListener('click', () => {
        if (!confirm('Keep this frame\'s albums on this Pi?\n\nThe old Pi\'s cloud record is marked as replaced by this one.')) return;
        post('/api/albums/frame-swap', { moved: true }, d => 'Done: this Pi now owns the frame\'s albums.'
            + (d.cloud_updated ? '' : ' The cloud record will be updated when the cloud is reachable.'));
    });
    if (copied) copied.addEventListener('click', () => {
        if (!confirm('Start this Pi as a new frame?\n\nIt keeps the albums on this card. The original frame keeps its deleted albums.')) return;
        post('/api/albums/frame-swap', { moved: false }, () => 'Done: this Pi is now a separate frame.');
    });
    if (undo) undo.addEventListener('click', () => {
        if (!confirm('Undo the takeover? This frame\'s cloud record is marked as its own again.')) return;
        post('/api/albums/undo-takeover', {}, () => 'Takeover undone.');
    });
})();

/** Keep the demo banner in step with /dashboard/status (days left, expiry while open). */
function updateDemoBanner(demo) {
    const banner = document.getElementById('demo-banner');
    const text = document.getElementById('demo-banner-text');
    if (!banner || !demo) return;
    const on = demo.allowed && demo.enabled;
    banner.style.display = on ? '' : 'none';
    if (on && text) {
        text.textContent = `${plural(demo.days_left, 'day')} left · ${plural(demo.demo_devices, 'demo device')}`;
    }
}

(function initDemoMode() {
    const onBtn    = document.getElementById('btn-demo-on');
    const offBtn   = document.getElementById('btn-demo-off');
    const regenBtn = document.getElementById('btn-demo-regenerate');
    const statusEl = document.getElementById('demo-mode-status');
    const expires  = document.getElementById('demo-expires');

    if (expires && expires.dataset.expires) {
        expires.textContent = new Date(expires.dataset.expires).toLocaleString();
    }

    function showStatus(msg, type) {
        statusEl.textContent = msg;
        statusEl.className = 'status-message ' + type;
        statusEl.style.display = 'block';
    }

    async function post(url, body, busyMsg) {
        [onBtn, offBtn, regenBtn].forEach(b => { if (b) b.disabled = true; });
        showStatus(busyMsg, 'info');
        try {
            const resp = await fetch(url, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: body ? JSON.stringify(body) : undefined,
            });
            const data = await resp.json();
            if (data.ok) {
                location.reload();
                return;
            }
            showStatus('Error: ' + (data.error || 'Unknown failure'), 'error');
        } catch (err) {
            showStatus('Network error. Please try again.', 'error');
        }
        [onBtn, offBtn, regenBtn].forEach(b => { if (b) b.disabled = false; });
    }

    if (onBtn) {
        onBtn.addEventListener('click', () => {
            if (!confirm('Turn on demo mode for 14 days? Anyone with a demo code can pair with this frame from the internet.')) return;
            post('/api/settings/demo', { enabled: true }, 'Turning on demo mode…');
        });
    }
    if (offBtn) {
        offBtn.addEventListener('click', () => {
            const n = parseInt(offBtn.dataset.devices || '0', 10);
            if (!confirm(`Turn off demo mode? This revokes ${plural(n, 'demo device')}.`)) return;
            post('/api/settings/demo', { enabled: false }, 'Turning off demo mode…');
        });
    }
    if (regenBtn) {
        regenBtn.addEventListener('click', () => {
            if (!confirm('Generate new demo codes? The current codes stop working and the 14 days restart. Phones already paired stay paired.')) return;
            post('/api/settings/demo/regenerate', null, 'Generating new codes…');
        });
    }
})();

/** Demo frame reset (PL-151): Save as Baseline and Reset to Baseline on the Demo Mode card. */
(function initDemoReset() {
    const saveBtn  = document.getElementById('btn-demo-baseline');
    const resetBtn = document.getElementById('btn-demo-reset');
    const statusEl = document.getElementById('demo-reset-status');
    const saved    = document.getElementById('demo-baseline-saved');
    if (!saveBtn) return;
    if (saved && saved.dataset.saved) saved.textContent = new Date(saved.dataset.saved).toLocaleString();

    function showStatus(msg, type) {
        statusEl.textContent = msg;
        statusEl.className = 'status-message ' + type;
        statusEl.style.display = 'block';
    }

    function resetSummary(d) {
        const albums = d.albums.map(a => `${a.name} (${plural(a.photos, 'photo')}${a.synced ? '' : ', sync failed'})`).join(', ');
        const parts = [
            `Restored: ${albums}.`,
            `Removed ${plural(d.phones_removed, 'phone')}, ${plural(d.invites_removed, 'invite')}, ${plural(d.upload_links_removed, 'upload link')}.`,
            `Deleted ${plural(d.albums_deleted, 'album')} and ${plural(d.cloud_folders_deleted, 'cloud folder')}.`,
        ];
        if (d.settings_restored.length) parts.push(`Settings put back: ${d.settings_restored.join(', ')}.`);
        parts.push(`Demo mode on, ${plural(d.demo.days_left, 'day')} left.`);
        return parts.join('\n');
    }

    async function run(url, busyMsg, done) {
        [saveBtn, resetBtn].forEach(b => { b.disabled = true; });
        showStatus(busyMsg, 'info');
        try {
            const resp = await fetch(url, { method: 'POST' });
            const data = await resp.json();
            if (data.ok) {
                alert(done(data));
                location.reload();
                return;
            }
            showStatus('Error: ' + (data.error || 'Unknown failure'), 'error');
        } catch (err) {
            showStatus('Network error. Please try again.', 'error');
        }
        saveBtn.disabled = false;
        resetBtn.disabled = !saved;
    }

    saveBtn.addEventListener('click', () => {
        if (!confirm('Save the albums, photos, showing album and settings as they are now as the demo baseline?'
            + (saved ? '\n\nThis replaces the current baseline.' : ''))) return;
        run('/api/settings/demo/baseline', 'Saving the baseline…',
            d => `Baseline saved: ${plural(d.baseline.albums.length, 'album')}, ${plural(d.baseline.photos, 'photo')}.`);
    });
    resetBtn.addEventListener('click', () => {
        if (!confirm('Reset the demo frame to the baseline?\n\nDeletes other albums and every other cloud folder on this Koofr account, '
            + 'removes demo and Share phones, invites and upload links. Your Manager pairing stays.')) return;
        run('/api/settings/demo/reset', 'Resetting the demo frame… this can take a few minutes.', resetSummary);
    });
})();


// =============================================================================
// RECOVER ALBUMS (PL-147 follow-up)
// =============================================================================

let recoverAlbums = [];

function showRecoverStatus(type, message) {
    const el = document.getElementById('recover-status');
    if (!el) return;
    el.className = `status-message ${type}`;
    el.textContent = message;
    el.style.display = 'block';
}

function restoreSummary(data) {
    if (data.kind === 'frame') return frameRestoreSummary(data);
    const parts = [`${data.restored} file${data.restored === 1 ? '' : 's'} added to "${data.album}"`];
    if (data.already_there) parts.push(`${data.already_there} already there`);
    if (data.renamed) parts.push(`${data.renamed} renamed to avoid overwriting`);
    if (data.skipped) parts.push(`${data.skipped} skipped (not photos/videos)`);
    parts.push(data.uploaded_to_cloud ? 'uploaded to its cloud folder' : 'this album has no cloud folder, so they are on the frame only');
    return parts.join(', ') + '.';
}

const FRAME_RESTORE_ACTIONS = { merged: 'on this frame', recovered: 'deleted album re-added', created: 'new album' };

/** One line per album of a whole-frame restore. */
function frameRestoreSummary(data) {
    const lines = (data.albums || []).map(a =>
        `"${a.name}" (${FRAME_RESTORE_ACTIONS[a.action] || a.action}): ${a.restored} added`
        + (a.already_there ? `, ${a.already_there} already there` : '')
        + (a.renamed ? `, ${a.renamed} renamed` : ''));
    return `Restored ${plural(lines.length, 'album')}${data.frame_name ? ` from ${data.frame_name}` : ''}. ` + lines.join('; ') + '.';
}

/** Restore every album in a whole-frame backup, in one go. */
async function restoreFrameBackup(filename, albumCount) {
    if (!confirm(`Restore all ${plural(albumCount, 'album')} from ${filename}?\n\nAlbums on this frame get only the photos they're missing (nothing is duplicated). Deleted or missing albums are created again. Photos are uploaded to each album's cloud folder.`)) return;
    showRecoverStatus('info', 'Restoring the whole frame… this can take a while for a large backup.');
    const status = document.getElementById('backup-create-status');
    if (status) { status.textContent = 'Restoring the whole frame…'; status.style.color = '#94a3b8'; }
    try {
        const data = await apiFetch('/api/albums/restore-backup', {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ filename }),
        });
        const msg = data.ok ? frameRestoreSummary(data) : data.error;
        showRecoverStatus(data.ok ? 'success' : 'error', msg);
        if (status) { status.textContent = msg; status.style.color = data.ok ? '#4ade80' : '#f87171'; }
        if (data.ok) {
            if (typeof loadSources === 'function') loadSources();
            loadBackupSources();
            loadRecoverable();
        }
    } catch (e) {
        showRecoverStatus('error', `Error: ${e.message}`);
        if (status) { status.textContent = `Error: ${e.message}`; status.style.color = '#f87171'; }
    }
}

/** Ask where to restore to: an existing album id, or {newName}. Returns null if cancelled. */
function askNewAlbumName(suggested) {
    const name = prompt('Name for the new album:', suggested || '');
    if (name === null) return null;
    if (!name.trim()) { alert('The album needs a name.'); return null; }
    return { newName: name.trim() };
}

async function loadRecoverable() {
    const cloudEl = document.getElementById('recover-cloud');
    cloudEl.textContent = 'Checking cloud storage…';
    try {
        const [rec, albums] = await Promise.all([apiFetch('/api/albums/recoverable'), apiFetch('/api/sources')]);
        recoverAlbums = albums.sources || [];
        renderRecoverCloud(rec);
        renderRecoverUploadTargets();
    } catch (e) {
        cloudEl.textContent = `Error: ${e.message}`;
    }
}

/** A table of recoverable cloud folders; `kind` is 'own' or 'unclaimed' (needs the shared-account warning). */
function recoverCloudTable(folders, kind) {
    return `<table class="sources-table"><thead><tr><th>Cloud folder</th><th>Deleted</th><th>Photos</th><th>Album name</th><th></th></tr></thead><tbody>${
        folders.map((f, i) => `<tr>
            <td><code>${escapeHtml(f.folder)}</code></td>
            <td>${f.deleted_at ? new Date(f.deleted_at).toLocaleDateString() : (kind === 'own' ? '' : 'unknown')}</td>
            <td>${f.photo_count < 0 ? '?' : f.photo_count}</td>
            <td><input class="form-input" id="recover-name-${kind}-${i}" value="${escapeHtml(f.suggested_name)}" maxlength="50"></td>
            <td><button class="btn-small" onclick="recoverFromCloud('${escapeHtml(f.folder)}', '${kind}', ${i}, ${f.photo_count})">Recover</button></td>
        </tr>`).join('')
    }</tbody></table>`;
}

function renderRecoverCloud(rec) {
    const el = document.getElementById('recover-cloud');
    const wrap = document.getElementById('recover-unclaimed-wrap');
    const framesPart = document.getElementById('recover-frames-part');
    wrap.style.display = 'none';
    framesPart.style.display = 'none';
    if (rec.cloud_error) { el.textContent = rec.cloud_error; return; }

    // On an account only this frame uses, unclaimed folders are this frame's too: list them with its own
    const own = rec.unclaimed_needs_confirm ? (rec.cloud || []) : (rec.cloud || []).concat(rec.unclaimed || []);
    el.innerHTML = own.length ? recoverCloudTable(own, 'own') : 'No deleted albums to recover from cloud storage.';

    const unclaimed = rec.unclaimed_needs_confirm ? (rec.unclaimed || []) : [];
    if (unclaimed.length) {
        const list = document.getElementById('recover-unclaimed');
        const check = document.getElementById('recover-show-unclaimed');
        document.getElementById('recover-unclaimed-count').textContent = unclaimed.length;
        list.innerHTML = recoverCloudTable(unclaimed, 'unclaimed');
        list.style.display = check.checked ? 'block' : 'none';
        check.onchange = () => { list.style.display = check.checked ? 'block' : 'none'; };
        wrap.style.display = 'block';
    }
    renderRecoverFrames(rec.frames || []);
}

let recoverFrames = [];

function renderRecoverFrames(frames) {
    const part = document.getElementById('recover-frames-part');
    recoverFrames = frames;
    if (frames.length === 0) return;
    document.getElementById('recover-frames').innerHTML = `<table class="sources-table"><thead><tr><th>Frame</th><th>Last seen</th><th>Albums</th><th></th></tr></thead><tbody>${
        frames.map((f, i) => `<tr>
            <td>${escapeHtml(f.frame_name)} <span class="form-hint">${escapeHtml(f.short)}</span></td>
            <td>${f.last_seen ? new Date(f.last_seen).toLocaleString() : 'never'}${f.recent ? ' <span class="source-status-badge disabled">recent</span>' : ''}</td>
            <td>${f.albums}${f.deleted ? ` (${f.deleted} deleted)` : ''}</td>
            <td><button class="btn-small" onclick="takeOverFrame(${i})">Take over</button></td>
        </tr>`).join('')
    }</tbody></table>`;
    part.style.display = 'block';
}

async function takeOverFrame(index) {
    const { serial, frame_name: name, recent, albums } = recoverFrames[index];
    let confirmName = '';
    if (recent) {
        const typed = prompt(`${name} checked in within the last 24 hours, so it may still be running.\n\nTaking it over lets this frame recover its ${plural(albums, 'album')}. Type ${name} to confirm:`);
        if (typed === null) return;
        if (typed.trim().toLowerCase() !== name.trim().toLowerCase()) { alert(`That doesn't match "${name}". Nothing was changed.`); return; }
        confirmName = typed;
    } else if (!confirm(`Take over ${name}'s albums?\n\nThis frame will be able to recover its ${plural(albums, 'album')}, and ${name}'s cloud record is marked as replaced by this Pi. Nothing is deleted.`)) {
        return;
    }
    showRecoverStatus('info', `Taking over ${name}…`);
    try {
        const data = await apiFetch('/api/albums/take-over', {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ serial, confirm_name: confirmName }),
        });
        if (!data.ok) { showRecoverStatus('error', data.error); return; }
        showRecoverStatus('success', `Took over ${data.frame_name}: ${plural(data.albums_added, 'album')} added to this frame's list.`
            + (data.cloud_updated ? '' : ' The cloud record will be updated when the cloud is reachable.'));
        loadRecoverable();
    } catch (e) {
        showRecoverStatus('error', `Error: ${e.message}`);
    }
}

function renderRecoverUploadTargets() {
    const sel = document.getElementById('recover-upload-target');
    sel.innerHTML = recoverAlbums.map(a => `<option value="${escapeHtml(a.id)}">${escapeHtml(a.label)}</option>`).join('')
        + '<option value="__new__">➕ New album…</option>';
}

async function recoverFromCloud(folder, kind, index, count) {
    const name = document.getElementById(`recover-name-${kind}-${index}`).value.trim();
    if (!name) { alert('The album needs a name.'); return; }
    const photos = count < 0 ? 'its photos' : `${count} photo${count === 1 ? '' : 's'}`;
    const warning = kind === 'unclaimed'
        ? `\n\n⚠️ No frame has recorded ${folder}, and this cloud account is shared. If it's another frame's album, photos added here will show up on that frame too.`
        : '';
    if (!confirm(`Add album "${name}" using cloud folder ${folder}?\n\n${photos} will sync to the frame.${warning}`)) return;
    showRecoverStatus('info', `Recovering "${name}"…`);
    try {
        const data = await apiFetch('/api/albums/recover-cloud', {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ folder, name, allow_unclaimed: kind === 'unclaimed' }),
        });
        if (!data.ok) { showRecoverStatus('error', data.error); return; }
        showRecoverStatus('success', `"${data.name}": ${data.message}`);
        if (typeof loadSources === 'function') loadSources();
        loadRecoverable();
    } catch (e) {
        showRecoverStatus('error', `Error: ${e.message}`);
    }
}

/**
 * Restore a backup. `albumId` is the album to restore into, or null to ask for a new album name
 * (suggested from the backup). Used by Backups → Photo Backups.
 */
async function restoreBackupInto(filename, albumId, suggestedName) {
    let target = albumId ? { targetId: albumId } : askNewAlbumName((suggestedName || '').replace(/_/g, ' '));
    if (!target) return;
    const where = target.targetId ? `album "${target.targetId}"` : `a new album "${target.newName}"`;
    if (!confirm(`Restore ${filename} into ${where}?\n\nIts photos are added (existing photos are kept; same-name files are renamed) and uploaded to the album's cloud folder.`)) return;
    showRecoverStatus('info', 'Restoring… this can take a few minutes for a large backup.');
    try {
        const data = await apiFetch('/api/albums/restore-backup', {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ filename, target_id: target.targetId || null, new_name: target.newName || null }),
        });
        const msg = data.ok ? restoreSummary(data) : data.error;
        showRecoverStatus(data.ok ? 'success' : 'error', msg);
        if (!document.getElementById('recover-section') || document.getElementById('recover-section').style.display === 'none') {
            alert(data.ok ? `Restored: ${msg}` : `Restore failed: ${msg}`);
        }
        if (data.ok) {
            if (typeof loadSources === 'function') loadSources();
            loadBackupSources();
            loadRecoverable();
        }
    } catch (e) {
        showRecoverStatus('error', `Error: ${e.message}`);
    }
}

function uploadRecoverArchive() {
    const file = document.getElementById('recover-file').files[0];
    if (!file) { alert('Choose a .zip or .tar.gz file first.'); return; }
    const sel = document.getElementById('recover-upload-target');
    let target = sel.value === '__new__' ? askNewAlbumName(file.name.replace(/\.(zip|tar\.gz|tgz)$/i, '')) : { targetId: sel.value };
    if (!target) return;
    const where = target.targetId ? `album "${sel.options[sel.selectedIndex].text}"` : `a new album "${target.newName}"`;
    if (!confirm(`Upload ${file.name} (${fmtBytes(file.size)}) into ${where}?\n\nIts photos are added and uploaded to the album's cloud folder. A whole-frame backup restores all its albums instead.`)) return;

    const params = new URLSearchParams(target.targetId ? { target_id: target.targetId } : { new_name: target.newName });
    const progress = document.getElementById('recover-upload-progress');
    const btn = document.getElementById('btn-recover-upload');
    progress.style.display = 'block';
    progress.value = 0;
    btn.disabled = true;
    showRecoverStatus('info', `Uploading ${file.name}…`);

    const xhr = new XMLHttpRequest();
    xhr.open('POST', `/api/albums/upload-archive?${params}`);
    xhr.upload.onprogress = (e) => {
        if (e.lengthComputable) progress.value = Math.round((e.loaded / e.total) * 100);
        if (e.loaded === e.total) showRecoverStatus('info', 'Uploaded. Unpacking and copying to the cloud folder…');
    };
    xhr.onload = () => {
        btn.disabled = false;
        progress.style.display = 'none';
        let data;
        try { data = JSON.parse(xhr.responseText); } catch (e) { data = { ok: false, error: `HTTP ${xhr.status}` }; }
        if (xhr.status === 413) data = { ok: false, error: 'The file is too big (limit 16 GB).' };
        showRecoverStatus(data.ok ? 'success' : 'error', data.ok ? restoreSummary(data) : (data.error || data.detail));
        if (data.ok) {
            document.getElementById('recover-file').value = '';
            if (typeof loadSources === 'function') loadSources();
            loadRecoverable();
        }
    };
    xhr.onerror = () => {
        btn.disabled = false;
        progress.style.display = 'none';
        showRecoverStatus('error', 'Upload failed (network error).');
    };
    xhr.send(file);
}

(function initRecoverAlbums() {
    const toggle = document.getElementById('recover-toggle');
    const section = document.getElementById('recover-section');
    if (!toggle || !section) return;
    const setOpen = (open) => {
        section.style.display = open ? 'block' : 'none';
        toggle.textContent = open ? 'Hide' : 'Show';
        header.style.cursor = open ? 'default' : 'pointer';
        if (open) loadRecoverable();
    };
    const header = toggle.closest('.card-header');
    toggle.addEventListener('click', (e) => {
        e.stopPropagation();
        setOpen(section.style.display === 'none');
    });
    // Like the other Tools cards: clicking the header of a closed card opens it
    header.addEventListener('click', () => {
        if (section.style.display === 'none') setOpen(true);
    });
    header.style.cursor = 'pointer';
    const btn = document.getElementById('btn-recover-upload');
    if (btn) btn.addEventListener('click', uploadRecoverArchive);
})();

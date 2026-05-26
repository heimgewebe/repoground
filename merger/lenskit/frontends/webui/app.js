// repoLens UI Logic

// Single Source of Truth from index.html (fallback to dev if missing)
const RLENS_UI_VERSION = window.__RLENS_UI_VERSION__ || "dev";
console.info(`[rLens] UI Version: ${RLENS_UI_VERSION}`);

// --- State Migration & Cache Busting ---
try {
    const storedVersion = localStorage.getItem('rlens_state_version');
    if (storedVersion !== RLENS_UI_VERSION) {
        // RELOAD LOOP GUARD: Check if we just reset this version in this session
        if (sessionStorage.getItem('rlens_reset_once') === RLENS_UI_VERSION) {
            console.warn(`[rLens] Reload loop detected for version ${RLENS_UI_VERSION}. Aborting automatic reset/reload.`);
            // Show a non-blocking UI warning after DOM load
            window.addEventListener('DOMContentLoaded', () => {
                const warn = document.createElement('div');
                warn.className = "fixed bottom-0 left-0 right-0 bg-red-600 text-white text-center p-2 z-50 text-xs font-bold";
                warn.innerHTML = "Warning: State reset failed or blocked. UI may be unstable. <button onclick='localStorage.clear();location.reload()' class='underline ml-2'>Force Reset</button>";
                document.body.appendChild(warn);
            });
        } else {
            console.warn(`[rLens] Version mismatch (Stored: ${storedVersion} != Current: ${RLENS_UI_VERSION}). Performing hard reset.`);

            // Set guard flag BEFORE actions
            sessionStorage.setItem('rlens_reset_once', RLENS_UI_VERSION);

            // 1. Clear LocalStorage
            localStorage.clear();

            // 2. Clear IndexedDB (Safer: rlens_ prefix only)
            if (window.indexedDB && window.indexedDB.databases) {
                window.indexedDB.databases().then(dbs => {
                    dbs.forEach(db => {
                        if (db.name && db.name.startsWith('rlens_')) {
                            console.log(`Deleting DB: ${db.name}`);
                            window.indexedDB.deleteDatabase(db.name);
                        }
                    });
                });
            } else if (window.indexedDB) {
                console.warn("[rLens] indexedDB.databases() not available; skipping IndexedDB cleanup.");
            }

            // 3. Unregister potentially stale Service Workers
            if ('serviceWorker' in navigator) {
                navigator.serviceWorker.getRegistrations().then(function(registrations) {
                    for(let registration of registrations) {
                        console.info("Unregistering Service Worker:", registration);
                        registration.unregister();
                    }
                });
            }

            // 4. Update Version
            localStorage.setItem('rlens_state_version', RLENS_UI_VERSION);

            // 5. Force Reload (to ensure clean slate)
            setTimeout(() => {
                window.location.reload();
            }, 300);
        }
    }
} catch (e) {
    console.error("State migration failed", e);
}

const API_BASE = '/api';

// Guard: Ensure materialize.js is loaded
if (typeof materializeRawFromCompressed !== 'function' || typeof normalizePath !== 'function') {
    window.__RLENS_MATERIALIZE_MISSING__ = true;
    const errorMsg = "CRITICAL: materialize.js not loaded. Application logic will fail.";
    console.error(errorMsg);
    // Attempt to show UI error if DOM is ready, otherwise wait
    const showErr = () => {
        const div = document.createElement('div');
        div.className = "fixed top-0 left-0 right-0 bg-red-600 text-white text-center p-4 z-50 font-bold";
        div.innerText = errorMsg;
        document.body.prepend(div);
    };
    if (document.body) showErr();
    else window.addEventListener('DOMContentLoaded', showErr);
}

// Token handling
const TOKEN_KEY = 'rlens_token';
const SETS_KEY = 'rlens_sets';
const CONFIG_KEY = 'rlens_config';
const ATLAS_CONFIG_KEY = 'rlens_atlas_config_v2';
const ATLAS_CONFIG_LEGACY_KEY = 'rlens_atlas_config';
const PRESCAN_SAVED_KEY = "lenskit.prescan.savedSelections.v1";

// Global State
let currentPickerTarget = null;
let currentPickerPath = null;
let currentPickerToken = null; // For token-based navigation

// Guard: strictly prevent merge when prescan is open
window.__prescanOpen = false;

let prescanCurrentTree = null;
// prescanSelection is Tri-State:
// null = ALL selected
// Set() = Partial/None (empty set = none)
let prescanSelection = new Set();
let prescanExpandedPaths = new Set(); // Stores paths of expanded directories (root expanded by default)
let savedPrescanSelections = loadSavedPrescanSelections(); // repoName -> { raw: Set|null, compressed: Array|null }

// Conditional Test Hook (explicit flag instead of heuristic)
if (window.__RLENS_TEST__) {
    window.__rlens_pool_ready = true;
}

// DOCS: savedPrescanSelections acts as the "Selection Pool".
// It is strictly separated from the active "Merge Targets" (which are built in startJob).
// Prescan operations only modify this pool, never the Merge Targets directly.

// Available Extras
const EXTRAS_OPTIONS = [
    'health',
    'augment_sidecar',
    'organism_index',
    'fleet_panorama',
    'json_sidecar',
    'heatmap'
];

// Default selected extras (based on existing logic/user preference)
const DEFAULT_EXTRAS = [
    'augment_sidecar',
    'json_sidecar'
];

// --- Invariant State Wrappers ---

function selectionIsAll() {
    return prescanSelection === null;
}

function selectionIsNone() {
    return prescanSelection !== null && prescanSelection.size === 0;
}

function selectionResetNone() {
    // NONE state is represented by an empty Set (not null), distinct from ALL which uses null
    prescanSelection = new Set();
}

function selectionSetAll() {
    prescanSelection = null;
}

// --- Utilities ---

// normalizePath and materializeRawFromCompressed are loaded from materialize.js

// Helper to collect all file paths from the current tree for materialization
function getAllPathsInTree(treeNode) {
    const paths = new Set();
    function visit(node) {
        if (node.type === 'file') {
             const p = normalizePath(node.path);
             if (p) paths.add(p);
        }
        if (node.children) node.children.forEach(visit);
    }
    visit(treeNode);
    return paths;
}


// Ensures prescanSelection is a Set for mutations when currently in ALL state
// Returns true if materialization succeeded, false if failed
function selectionEnsureSetForMutation() {
    if (prescanSelection !== null) {
        return true; // Already a Set
    }
    
    // Need to materialize ALL state
    if (prescanCurrentTree && prescanCurrentTree.tree) {
        prescanSelection = getAllPathsInTree(prescanCurrentTree.tree);
        return true;
    }
    
    // Unable to materialize - log warning and keep ALL state
    console.warn('prescanCurrentTree is not available; cannot materialize ALL state for mutation. Keeping ALL state.');
    return false;
}

function setSelectionState(path, isSelected) {
    const p = normalizePath(path);
    if (p === null) return;

    // Fix 1: Null-Guard for ALL state
    if (prescanSelection === null) {
        // Current state is ALL
        if (isSelected) return; // Already selected

        // Deselecting one item from ALL -> Materialize
        if (!selectionEnsureSetForMutation()) {
            // Cannot materialize - keep ALL state
            return;
        }
        prescanSelection.delete(p);
        return;
    }

    // Current state is Partial (Set)
    if (isSelected) prescanSelection.add(p);
    else prescanSelection.delete(p);
}

function isPathSelected(path) {
    const p = normalizePath(path);
    if (p === null) return false;

    // If selection is null, it means EVERYTHING is selected
    if (selectionIsAll()) return true;

    return prescanSelection.has(p);
}

function setExpansionState(path, isExpanded) {
    const p = normalizePath(path);
    if (p === null) return;
    if (isExpanded) prescanExpandedPaths.add(p);
    else prescanExpandedPaths.delete(p);
}

function isPathExpanded(path) {
    const p = normalizePath(path);
    if (p === null) return false;
    return prescanExpandedPaths.has(p);
}

function clearGlobalFilters(payload) {
    payload.path_filter = null;
    payload.extensions = null;
}

// --- Prescan saved selections persistence ---
function loadSavedPrescanSelections() {
    try {
        const raw = JSON.parse(localStorage.getItem(PRESCAN_SAVED_KEY) || "{}");
        const m = new Map();
        for (const [repo, obj] of Object.entries(raw)) {
            // Invariant Check: raw must be rehydrated to Set or null
            let rawSet = null;
            if (obj.raw !== null) { // null = ALL
                const rawList = Array.isArray(obj.raw) ? obj.raw : [];
                // Filter out non-strings to prevent corruption
                rawSet = new Set(rawList.filter(x => typeof x === 'string').map(normalizePath).filter(p => p !== null));
            }

            // compressed can be null (ALL) or array
            let compressed = null;
            if (obj.compressed !== null) {
                compressed = Array.isArray(obj.compressed) ? obj.compressed.map(normalizePath).filter(p => p !== null) : [];
            }

            m.set(repo, { raw: rawSet, compressed });
        }
        return m;
    } catch {
        return new Map();
    }
}

function persistSavedPrescanSelections() {
    const obj = {};
    for (const [repo, sel] of savedPrescanSelections.entries()) {
        obj[repo] = {
            raw: sel.raw ? Array.from(sel.raw) : null,
            compressed: sel.compressed
        };
    }
    localStorage.setItem(PRESCAN_SAVED_KEY, JSON.stringify(obj));
}

// Simple notification system for user feedback
function showNotification(message, type = 'info') {
    // Create notification element
    const notification = document.createElement('div');
    notification.className = `fixed top-4 right-4 px-4 py-3 rounded shadow-lg z-50 transition-opacity duration-300 ${
        type === 'success' ? 'bg-green-600 text-white' :
        type === 'warning' ? 'bg-yellow-600 text-white' :
        type === 'error' ? 'bg-red-600 text-white' :
        'bg-blue-600 text-white'
    }`;
    notification.textContent = message;
    notification.style.opacity = '0';
    
    document.body.appendChild(notification);
    
    // Fade in
    setTimeout(() => {
        notification.style.opacity = '1';
    }, 10);
    
    // Fade out and remove after 3 seconds
    setTimeout(() => {
        notification.style.opacity = '0';
        setTimeout(() => {
            document.body.removeChild(notification);
        }, 300);
    }, 3000);
}

function getToken() {
    return document.getElementById('authToken').value || localStorage.getItem(TOKEN_KEY) || '';
}

function setToken(token) {
    if (token) {
        localStorage.setItem(TOKEN_KEY, token);
    } else {
        localStorage.removeItem(TOKEN_KEY);
    }
}

// Wrapper for fetch with auth
async function apiFetch(url, options = {}) {
    const token = getToken();
    const headers = options.headers || {};

    if (token) {
        headers['Authorization'] = `Bearer ${token}`;
    }

    options.headers = headers;
    return fetch(url, options);
}

async function fetchHealth() {
    try {
        // Health check endpoint is open, but we use it to check connectivity
        const res = await apiFetch(`${API_BASE}/health`);
        const data = await res.json();
        const authStatus = data.auth_enabled ? '🔒 Auth' : '🔓 Open';
        document.getElementById('status').innerText = `v${data.version} (UI: ${RLENS_UI_VERSION}) • ${authStatus} • Hub: ${data.hub}`;

        // Only set values if empty (respect user changes or saved config)
        if (!document.getElementById('hubPath').value) {
            document.getElementById('hubPath').value = data.hub || '';
        }
        if (!document.getElementById('mergesPath').value && data.merges_dir) {
            document.getElementById('mergesPath').value = data.merges_dir || '';
        }

        return data.hub;
    } catch (e) {
        document.getElementById('status').innerText = 'Offline';
        return null;
    }
}

async function fetchRepos(hub, options = {}) {
    const preserveSelection = options.preserveSelection !== false;
    // Preserve checked repos only for normal refreshes; reset flow can disable this.
    const previouslyChecked = preserveSelection
        ? new Set(Array.from(document.querySelectorAll('input[name="repos"]:checked')).map(cb => cb.value))
        : new Set();

    const list = document.getElementById('repoList');
    list.innerHTML = '<div class="text-gray-500 italic">Loading repos...</div>';

    try {
        // Construct query string properly
        let url = `${API_BASE}/repos`;
        if (hub) {
            url += `?hub=${encodeURIComponent(hub)}`;
        }

        const res = await apiFetch(url);
        if (res.status === 401) {
             list.innerHTML = '<div class="text-red-400">Access Denied (Check Token)</div>';
             return;
        }
        if (res.status === 403) {
             list.innerHTML = '<div class="text-red-400">Hub path restricted</div>';
             return;
        }

        if (!res.ok) {
             list.innerHTML = '<div class="text-red-400">Error fetching repos</div>';
             return;
        }

        const repos = await res.json();

        list.innerHTML = '';
        if (repos.length === 0) {
            list.innerHTML = '<div class="text-gray-500 italic">No repos found in hub.</div>';
            return;
        }

        repos.forEach(repo => {
            const div = document.createElement('div');
            div.className = "flex items-center space-x-2 p-1 hover:bg-gray-800 rounded cursor-pointer relative group";
            div.onclick = (e) => {
                if (e.target.type !== 'checkbox') {
                    const box = div.querySelector('input[type="checkbox"]');
                    box.checked = !box.checked;
                }
            };

            // Badge check
            let badgeHtml = '';
            if (savedPrescanSelections.has(repo)) {
                const sel = savedPrescanSelections.get(repo);
                let title = "";
                let label = "POOL";
                let colorClass = "bg-blue-900 text-blue-200";

                if (sel.compressed === null) {
                    title = "POOL: ALL included (Full Repo)";
                    label = "POOL: ALL";
                    colorClass = "bg-green-900 text-green-200";
                } else {
                    const compressedCount = sel.compressed.length;
                    const rawCount = sel.raw ? sel.raw.size : 0;
                    title = `${rawCount} selected items (compressed to ${compressedCount} path rules)`;
                    label = `POOL: ${compressedCount} paths`;
                }

                badgeHtml = `<span class="ml-auto text-[10px] ${colorClass} px-1 rounded font-mono" title="${title}">${label}</span>`;
            }

            div.innerHTML = `
                <input type="checkbox" name="repos" value="${repo}" class="form-checkbox text-blue-500 bg-gray-900 border-gray-700">
                <span class="font-bold text-gray-300 select-none">${repo}</span>
                ${badgeHtml}
            `;
            list.appendChild(div);

            // Restore checked state after rerender
            const cb = div.querySelector('input[type="checkbox"]');
            if (previouslyChecked.has(repo)) cb.checked = true;
        });
    } catch (e) {
        list.innerHTML = '<div class="text-red-500">Error loading repos: ' + e.message + '</div>';
    }
}

function selectAllRepos() {
    const boxes = document.querySelectorAll('input[name="repos"]');
    if (boxes.length === 0) return;

    // Check if all are currently checked
    const allChecked = Array.from(boxes).every(b => b.checked);
    // Toggle
    boxes.forEach(b => b.checked = !allChecked);
}

// --- Sets Management ---

function getSets() {
    try {
        return JSON.parse(localStorage.getItem(SETS_KEY) || '{}');
    } catch { return {}; }
}

function saveSet() {
    const name = document.getElementById('setName').value.trim();
    if (!name) return alert("Please enter a name");

    const selected = Array.from(document.querySelectorAll('input[name="repos"]:checked')).map(cb => cb.value);
    if (selected.length === 0) return alert("No repos selected");

    const sets = getSets();
    sets[name] = selected;
    localStorage.setItem(SETS_KEY, JSON.stringify(sets));
    document.getElementById('setName').value = '';
    renderSets();
}

function deleteSet(name) {
    if (!confirm(`Delete set "${name}"?`)) return;
    const sets = getSets();
    delete sets[name];
    localStorage.setItem(SETS_KEY, JSON.stringify(sets));
    renderSets();
}

function loadSet(name) {
    const sets = getSets();
    const repos = sets[name];
    if (!repos) return;

    const boxes = document.querySelectorAll('input[name="repos"]');
    boxes.forEach(b => {
        b.checked = repos.includes(b.value);
    });
}

function renderSets() {
    const div = document.getElementById('setsList');
    const sets = getSets();
    div.innerHTML = '';

    Object.keys(sets).sort().forEach(name => {
        const badge = document.createElement('div');
        badge.className = "flex items-center bg-gray-700 hover:bg-gray-600 rounded px-2 py-1 text-xs cursor-pointer";
        badge.onclick = () => loadSet(name);

        const span = document.createElement('span');
        span.innerText = name;
        span.className = "mr-2 text-blue-300 font-bold";

        const del = document.createElement('span');
        del.innerHTML = '&times;';
        del.className = "text-gray-400 hover:text-red-400 font-bold";
        del.onclick = (e) => {
            e.stopPropagation();
            deleteSet(name);
        };

        badge.appendChild(span);
        badge.appendChild(del);
        div.appendChild(badge);
    });
}

// --- Selection Pool Management (New) ---

function togglePoolPanel() {
    const container = document.getElementById('selectionPool');
    if (!container) return;

    // Toggle hidden class
    if (container.classList.contains('hidden')) {
        container.classList.remove('hidden');
        // Render if empty just to show it's empty
        if (savedPrescanSelections.size === 0) {
            container.innerHTML = '<div class="text-gray-500 text-xs italic p-1">Pool is empty</div>';
        } else {
            renderSelectionPool();
        }
    } else {
        container.classList.add('hidden');
    }
}

function renderSelectionPool() {
    const container = document.getElementById('selectionPool');
    if (!container) return; // Guard if element missing

    container.innerHTML = '';
    const pool = savedPrescanSelections;

    if (pool.size === 0) {
        container.classList.add('hidden');
        return;
    }
    container.classList.remove('hidden');

    // Header
    const header = document.createElement('div');
    header.className = "font-bold text-blue-300 text-xs mb-2 flex justify-between items-center border-b border-gray-700 pb-1";
    header.innerHTML = `<span>Active Pool (${pool.size})</span> <button onclick="clearPool()" class="text-red-400 hover:text-white text-[10px]">Clear</button>`;
    container.appendChild(header);

    // List
    pool.forEach((val, repo) => {
        const div = document.createElement('div');
        div.className = "flex justify-between items-center text-xs bg-gray-700 p-1 rounded mb-1";

        let info = "";
        if (val.compressed === null) info = "ALL";
        else info = `${val.compressed.length} rules`;

        div.innerHTML = `
            <span class="font-mono truncate w-24 font-bold text-gray-300">${repo}</span>
            <span class="text-gray-400">${info}</span>
            <button onclick="removeFromPool('${repo}')" class="text-red-400 hover:text-white ml-2">×</button>
        `;
        container.appendChild(div);
    });
}

function clearPool() {
    if(confirm("Clear the entire selection pool?")) {
        savedPrescanSelections.clear();
        persistSavedPrescanSelections();
        renderSelectionPool();
        fetchRepos(document.getElementById('hubPath').value);
    }
}

function removeFromPool(repo) {
    savedPrescanSelections.delete(repo);
    persistSavedPrescanSelections();
    renderSelectionPool();
    fetchRepos(document.getElementById('hubPath').value);
}

// --- Config Management ---

function saveConfig() {
    const config = {
        profile: document.getElementById('profile').value,
        mode: document.getElementById('mode').value,
        splitSize: document.getElementById('splitSize').value,
        maxBytes: document.getElementById('maxBytes').value,
        planOnly: document.getElementById('planOnly').checked,
        codeOnly: document.getElementById('codeOnly').checked,
        metaDensity: document.getElementById('metaDensity').value,
        pathFilter: document.getElementById('pathFilter').value,
        extFilter: document.getElementById('extFilter').value,
        extras: Array.from(document.querySelectorAll('input[name="extras"]:checked')).map(cb => cb.value),
        // Persist paths too if desired
        hubPath: document.getElementById('hubPath').value,
        mergesPath: document.getElementById('mergesPath').value
    };
    localStorage.setItem(CONFIG_KEY, JSON.stringify(config));

    const btn = document.querySelector('button[onclick="saveConfig()"]');
    const oldText = btn.innerText;
    btn.innerText = "Saved!";
    setTimeout(() => btn.innerText = oldText, 1000);
}

function getEffectiveMergeFormDefaults() {
    const factoryDefaults = {
        profile: 'max',
        mode: 'gesamt',
        splitSize: '25MB',
        maxBytes: '0',
        metaDensity: 'auto',
        pathFilter: '',
        extFilter: '',
        planOnly: false,
        codeOnly: false,
        extras: [...DEFAULT_EXTRAS]
    };

    try {
        const raw = localStorage.getItem(CONFIG_KEY);
        const saved = raw ? JSON.parse(raw) : {};
        if (saved && typeof saved === 'object') {
            return {
                ...factoryDefaults,
                profile: saved.profile ?? factoryDefaults.profile,
                mode: saved.mode ?? factoryDefaults.mode,
                splitSize: saved.splitSize ?? factoryDefaults.splitSize,
                maxBytes: saved.maxBytes ?? factoryDefaults.maxBytes,
                metaDensity: saved.metaDensity ?? factoryDefaults.metaDensity,
                pathFilter: saved.pathFilter ?? factoryDefaults.pathFilter,
                extFilter: saved.extFilter ?? factoryDefaults.extFilter,
                planOnly: saved.planOnly ?? factoryDefaults.planOnly,
                codeOnly: saved.codeOnly ?? factoryDefaults.codeOnly,
                extras: Array.isArray(saved.extras) ? saved.extras : factoryDefaults.extras
            };
        }
    } catch (e) {
        console.warn('Failed to read saved merge defaults', e);
    }

    return factoryDefaults;
}

async function resetMergeFormToDefaultsAfterSuccessfulSubmit() {
    const defaults = getEffectiveMergeFormDefaults();

    document.querySelectorAll('input[name="repos"]').forEach(cb => {
        cb.checked = false;
    });

    const hubPathEl = document.getElementById('hubPath');
    const mergesPathEl = document.getElementById('mergesPath');

    savedPrescanSelections.clear();
    persistSavedPrescanSelections();
    renderSelectionPool();

    await fetchRepos((hubPathEl && hubPathEl.value) || '', { preserveSelection: false });
    document.querySelectorAll('input[name="repos"]').forEach(cb => {
        cb.checked = false;
    });

    const profileEl = document.getElementById('profile');
    const modeEl = document.getElementById('mode');
    const splitSizeEl = document.getElementById('splitSize');
    const maxBytesEl = document.getElementById('maxBytes');
    const metaDensityEl = document.getElementById('metaDensity');
    const pathFilterEl = document.getElementById('pathFilter');
    const extFilterEl = document.getElementById('extFilter');
    const planOnlyEl = document.getElementById('planOnly');
    const codeOnlyEl = document.getElementById('codeOnly');

    if (profileEl) profileEl.value = defaults.profile;
    if (modeEl) modeEl.value = defaults.mode;
    if (splitSizeEl) splitSizeEl.value = defaults.splitSize;
    if (maxBytesEl) maxBytesEl.value = defaults.maxBytes;
    if (metaDensityEl) metaDensityEl.value = defaults.metaDensity;
    if (pathFilterEl) pathFilterEl.value = defaults.pathFilter;
    if (extFilterEl) extFilterEl.value = defaults.extFilter;
    if (planOnlyEl) planOnlyEl.checked = defaults.planOnly;
    if (codeOnlyEl) codeOnlyEl.checked = defaults.codeOnly;

    const defaultExtras = new Set(defaults.extras);
    document.querySelectorAll('input[name="extras"]').forEach(cb => {
        cb.checked = defaultExtras.has(cb.value);
    });

    showNotification('Job submitted; form reset to defaults', 'info');
}

function restoreConfig() {
    try {
        const config = JSON.parse(localStorage.getItem(CONFIG_KEY));
        if (config) {
            if (config.profile) document.getElementById('profile').value = config.profile;
            if (config.mode) document.getElementById('mode').value = config.mode;
            if (config.splitSize) document.getElementById('splitSize').value = config.splitSize;
            if (config.maxBytes) document.getElementById('maxBytes').value = config.maxBytes;
            if (config.planOnly !== undefined) document.getElementById('planOnly').checked = config.planOnly;
            if (config.codeOnly !== undefined) document.getElementById('codeOnly').checked = config.codeOnly;
            if (config.metaDensity !== undefined) document.getElementById('metaDensity').value = config.metaDensity;
            if (config.pathFilter !== undefined) document.getElementById('pathFilter').value = config.pathFilter;
            if (config.extFilter !== undefined) document.getElementById('extFilter').value = config.extFilter;

            if (config.hubPath) document.getElementById('hubPath').value = config.hubPath;
            if (config.mergesPath) document.getElementById('mergesPath').value = config.mergesPath;

            // Extras need to be handled carefully as they are rendered async or statically
            if (config.extras) {
                 const boxes = document.querySelectorAll('input[name="extras"]');
                 boxes.forEach(b => {
                     b.checked = config.extras.includes(b.value);
                 });
            }
        }

        // Restore Atlas Config (Versioned & Migrated)
        let atlasConfig = null;
        try {
            const rawV2 = localStorage.getItem(ATLAS_CONFIG_KEY);
            if (rawV2) {
                atlasConfig = JSON.parse(rawV2);
                // Version Check (Soft Reset if future version or invalid)
                if (typeof atlasConfig.version !== 'number' || atlasConfig.version !== 2) {
                    console.warn("[Atlas] Unknown config version. Resetting.");
                    atlasConfig = null;
                }
            } else {
                // Migration V1 -> V2
                const rawV1 = localStorage.getItem(ATLAS_CONFIG_LEGACY_KEY);
                if (rawV1) {
                    console.info("[Atlas] Migrating config v1 -> v2");
                    let v1;
                    try { v1 = JSON.parse(rawV1); } catch(e) {}
                    const safeV1 = (v1 && typeof v1 === 'object') ? v1 : {};

                    atlasConfig = {
                        version: 2,
                        root: typeof safeV1.root === 'string' ? safeV1.root : '',
                        token: typeof safeV1.token === 'string' ? safeV1.token : null,
                        depth: parseInt(safeV1.depth, 10) || null,
                        limit: parseInt(safeV1.limit, 10) || null,
                        excludes: typeof safeV1.excludes === 'string' ? safeV1.excludes : ''
                    };
                    // Save immediately
                    localStorage.setItem(ATLAS_CONFIG_KEY, JSON.stringify(atlasConfig));
                    // Cleanup
                    localStorage.removeItem(ATLAS_CONFIG_LEGACY_KEY);
                }
            }
        } catch (e) {
            console.error("Atlas config load error", e);
        }

        if (atlasConfig) {
             const rootEl = document.getElementById('atlasRoot');
             if (atlasConfig.root) rootEl.value = atlasConfig.root;
             if (atlasConfig.token) rootEl.setAttribute('data-token', atlasConfig.token);

             if (atlasConfig.depth) document.getElementById('atlasDepth').value = atlasConfig.depth;
             if (atlasConfig.limit) document.getElementById('atlasLimit').value = atlasConfig.limit;
             if (atlasConfig.excludes) document.getElementById('atlasExcludes').value = atlasConfig.excludes;
             if (atlasConfig.scanMode) {
                 const modeEl = document.getElementById('atlasMode');
                 if (modeEl) modeEl.value = atlasConfig.scanMode;
             }
        }

    } catch (e) { console.error("Error restoring config", e); }
}

function renderExtras() {
    const container = document.getElementById('extras-container');
    container.innerHTML = '';

    EXTRAS_OPTIONS.forEach(opt => {
        const isChecked = DEFAULT_EXTRAS.includes(opt);
        const label = document.createElement('label');
        label.className = "flex items-center space-x-2 cursor-pointer text-xs";
        label.innerHTML = `
            <input type="checkbox" name="extras" value="${opt}" ${isChecked ? 'checked' : ''} class="form-checkbox text-blue-500 bg-gray-900 border-gray-700">
            <span>${opt}</span>
        `;
        container.appendChild(label);
    });
}

// --- Folder Picker ---

async function openPicker(targetId) {
    currentPickerTarget = targetId;
    document.getElementById('pickerModal').classList.remove('hidden');
    await loadPickerRoots();
}

function closePicker() {
    document.getElementById('pickerModal').classList.add('hidden');
    currentPickerTarget = null;
    currentPickerPath = null;
    currentPickerToken = null;
}

function applyPickerSelection() {
    if (!currentPickerTarget || !currentPickerPath) return;

    // Store token (opaque) in data attribute if target supports it (e.g. Atlas),
    // or value if appropriate.
    // For Atlas, we need to send the token.
    // For Hub (Legacy/JobRequest), we typically send the path string.
    // BUT: The goal is to satisfy CodeQL. Hub config is less dynamic.
    // Let's adopt a hybrid approach:
    // 1. Set visible value to path (for user confirmation/display)
    // 2. Set 'data-token' attribute on the input to the token.
    // Consumers (startAtlasJob) will check for data-token.

    const el = document.getElementById(currentPickerTarget);
    if (el) {
        el.value = currentPickerPath || '';
        el.dataset.token = currentPickerToken || '';
    }

    // If hub changed, reload repos
    if (currentPickerTarget === 'hubPath') {
        fetchRepos(currentPickerPath);
    }

    closePicker();
}

async function loadPickerRoots() {
    const list = document.getElementById('pickerList');
    const pathDisplay = document.getElementById('pickerCurrentPath');
    pathDisplay.value = "Select Root";
    list.innerHTML = '<div class="text-gray-500 italic">Loading roots...</div>';

    try {
        const res = await apiFetch(`${API_BASE}/fs/roots`);
        if (!res.ok) throw new Error("Fetch roots failed");
        const data = await res.json();

        list.innerHTML = '';
        data.roots.forEach(r => {
            const div = document.createElement('div');
            div.className = "flex items-center cursor-pointer hover:bg-gray-700 p-1 rounded";
            div.onclick = () => loadPickerToken(r.token);

            let label = r.id.toUpperCase();
            let desc = r.path;

            div.innerHTML = `<span class="mr-2">🏠</span> <span class="font-bold text-blue-300 mr-2">${label}</span> <span class="text-gray-500 text-xs truncate">${desc}</span>`;
            list.appendChild(div);
        });
    } catch (e) {
        list.innerHTML = `<div class="text-red-400">Error: ${e.message}</div>`;
    }
}

async function loadPickerToken(token) {
    const list = document.getElementById('pickerList');
    const pathDisplay = document.getElementById('pickerCurrentPath');
    list.innerHTML = '<div class="text-gray-500 italic">Loading...</div>';

    try {
        // Use token navigation
        const url = `${API_BASE}/fs/list?token=${encodeURIComponent(token)}`;
        const res = await apiFetch(url);

        if (res.status === 403) throw new Error("Access Denied (Path restricted)");
        if (!res.ok) throw new Error("Fetch failed");

        const data = await res.json();

        // Update state
        currentPickerPath = data.abs;
        currentPickerToken = token;
        pathDisplay.value = data.abs;

        // Add "Use This Folder" button at the top
        list.innerHTML = `
            <div class="p-2 border-b border-gray-700 flex justify-between items-center bg-gray-800 sticky top-0">
                <span class="text-xs text-gray-400 font-mono truncate mr-2">${data.abs}</span>
                <button onclick="applyPickerSelection()" class="bg-green-600 hover:bg-green-500 text-white px-3 py-1 rounded text-xs font-bold">Use This Folder</button>
            </div>
        `;

        // Add "Up" button if parent_token exists
        if (data.parent_token) {
            const upDiv = document.createElement('div');
            upDiv.className = "flex items-center cursor-pointer hover:bg-gray-700 p-1 rounded mb-1 border-b border-gray-700";
            upDiv.onclick = () => loadPickerToken(data.parent_token);
            upDiv.innerHTML = `<span class="mr-2">⬆️</span> <span>..</span>`;
            list.appendChild(upDiv);
        } else {
            // "Up" to Roots list
            const upDiv = document.createElement('div');
            upDiv.className = "flex items-center cursor-pointer hover:bg-gray-700 p-1 rounded mb-1 border-b border-gray-700";
            upDiv.onclick = () => loadPickerRoots();
            upDiv.innerHTML = `<span class="mr-2">🏠</span> <span>Roots</span>`;
            list.appendChild(upDiv);
        }

        data.entries.forEach(entry => {
            const div = document.createElement('div');
            div.className = "flex items-center cursor-pointer hover:bg-gray-700 p-1 rounded";

            if (entry.type === 'dir') {
                // Directory: Click to navigate
                div.onclick = () => loadPickerToken(entry.token);
                div.innerHTML = `<span class="mr-2">📁</span> <span>${entry.name}</span>`;
            } else {
                // File: Non-clickable in folder picker mode (or select?)
                div.className += " text-gray-500 cursor-default";
                div.innerHTML = `<span class="mr-2">📄</span> <span>${entry.name}</span>`;
            }
            list.appendChild(div);
        });

    } catch (e) {
        list.innerHTML = `<div class="text-red-400">Error: ${e.message}</div>`;
    }
}

function pickerSelect() {
    applyPickerSelection();
}

function createArtifactDownloadButton({ url, filename, label, className }) {
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = className;
    btn.textContent = label;
    btn.dataset.dl = url;
    if (filename) btn.dataset.name = filename;
    btn.addEventListener('click', () => downloadWithAuth(btn.dataset.dl, btn.dataset.name || 'artifact'));
    return btn;
}

function formatArtifactFallbackLabel(key) {
    return key.replace(/_/g, ' ').replace(/^\w/, c => c.toUpperCase());
}

const ARTIFACT_LABELS = {
    chunk_index: { label: "Chunks", color: "text-yellow-400" },
    dump_index: { label: "Dump Index", color: "text-purple-400" },
    sqlite_index: { label: "SQLite", color: "text-cyan-400" },
    retrieval_eval: { label: "Eval", color: "text-orange-400" },
    derived_manifest: { label: "Derived Manifest", color: "text-teal-400" },
    bundle_manifest: { label: "Bundle Manifest", color: "text-pink-400" }
};

async function loadArtifacts() {
    const list = document.getElementById('artifactList');
    list.innerHTML = '<div class="text-gray-500 italic">Loading...</div>';
    try {
        const res = await apiFetch(`${API_BASE}/artifacts`);
        if (res.status === 401) {
             list.innerHTML = '<div class="text-red-400">Auth Required</div>';
             return;
        }
        const arts = await res.json();

        list.innerHTML = '';
        if (arts.length === 0) {
            list.innerHTML = '<div class="text-gray-500 italic">No artifacts yet.</div>';
            return;
        }

        arts.forEach(art => {
            const div = document.createElement('div');
            div.className = "bg-gray-900 p-2 rounded border border-gray-700 flex flex-col";

            const date = new Date(art.created_at).toLocaleString();
            const repos = art.repos.length > 3 ? `${art.repos.slice(0,3).join(', ')} +${art.repos.length-3}` : art.repos.join(', ');

            let linkElements = [];

            // Primary JSON (fallback to legacy index_json)
            const primaryJsonPath = art.paths.json || art.paths.index_json;
            const primaryJsonKey = art.paths.json ? 'json' : 'index_json';
            if (primaryJsonPath) {
                linkElements.push(createArtifactDownloadButton({
                    url: `${API_BASE}/artifacts/${art.id}/download?key=${encodeURIComponent(primaryJsonKey)}`,
                    filename: primaryJsonPath,
                    label: 'JSON',
                    className: 'text-green-400 hover:underline'
                }));
            }

            // Canonical MD (fallback to legacy canonical_md)
            const primaryMdPath = art.paths.md || art.paths.canonical_md;
            const primaryMdKey = art.paths.md ? 'md' : 'canonical_md';
            if (primaryMdPath) {
                linkElements.push(createArtifactDownloadButton({
                    url: `${API_BASE}/artifacts/${art.id}/download?key=${encodeURIComponent(primaryMdKey)}`,
                    filename: primaryMdPath,
                    label: 'Markdown',
                    className: 'text-blue-400 hover:underline'
                }));
            }

            // Other parts
            for (const [key, val] of Object.entries(art.paths)) {
                if (key !== 'json' && key !== 'md' && key !== 'canonical_md' && key !== 'index_json') {
                    if (ARTIFACT_LABELS[key]) {
                        const { label, color } = ARTIFACT_LABELS[key];
                        linkElements.push(createArtifactDownloadButton({
                            url: `${API_BASE}/artifacts/${art.id}/download?key=${encodeURIComponent(key)}`,
                            filename: val,
                            label: label,
                            className: `${color} hover:underline text-xs`
                        }));
                    } else if (key.startsWith('md_part')) {
                         linkElements.push(createArtifactDownloadButton({
                             url: `${API_BASE}/artifacts/${art.id}/download?key=${encodeURIComponent(key)}`,
                             filename: val,
                             label: `Part ${key.split('_').pop()}`,
                             className: 'text-gray-400 hover:underline text-xs'
                         }));
                    } else if (key.startsWith('other_')) {
                         linkElements.push(createArtifactDownloadButton({
                             url: `${API_BASE}/artifacts/${art.id}/download?key=${encodeURIComponent(key)}`,
                             filename: val,
                             label: `Extra ${key.split('_').pop()}`,
                             className: 'text-gray-300 hover:underline text-xs'
                         }));
                    } else {
                         // Fallback for any other key not explicitly modeled, so users can still download it
                         linkElements.push(createArtifactDownloadButton({
                             url: `${API_BASE}/artifacts/${art.id}/download?key=${encodeURIComponent(key)}`,
                             filename: val,
                             label: formatArtifactFallbackLabel(key),
                             className: 'text-gray-200 hover:underline text-xs'
                         }));
                    }
                }
            }

            div.innerHTML = `
                <div class="flex justify-between items-start">
                    <span class="font-bold text-blue-300">${art.params.level} / ${art.params.mode}</span>
                    <span class="text-xs text-gray-500">${date}</span>
                </div>
                <div class="text-xs text-gray-400 truncate mb-1" title="${art.repos.join(', ')}">${repos || 'All Repos'}</div>
                <div class="links-container flex flex-wrap gap-2 text-xs mt-1"></div>
            `;

            const linksContainer = div.querySelector('.links-container');
            linkElements.forEach((btn, index) => {
                linksContainer.appendChild(btn);
                if (index < linkElements.length - 1) {
                    const separator = document.createElement('span');
                    separator.className = 'text-gray-600';
                    separator.textContent = '|';
                    linksContainer.appendChild(separator);
                }
            });

            list.appendChild(div);
        });

    } catch (e) {
        list.innerHTML = '<div class="text-red-500">Error loading artifacts.</div>';
    }
}

async function startJob(e) {
    e.preventDefault();
    if (window.__prescanOpen) {
        alert("Prescan ist offen. Bitte schließen und dann Merge starten.");
        return; // HARD GUARD
    }

    // Robust button selection (submitter or fallback)
    const btn = (e && e.submitter) || document.querySelector("#jobForm button[type='submit']");
    if (btn) {
        btn.disabled = true;
        btn.innerText = "Starting...";
    }

    // Dynamically query selected repos from the DOM
    const selectedRepos = Array.from(document.querySelectorAll('input[name="repos"]:checked')).map(cb => cb.value);

    // Security: Validate Repo Keys (Strict Regex Allowlist)
    // MUST remain consistent with backend logic in merger/lenskit/adapters/security.py
    // Allowed: A-Z, a-z, 0-9, ., _, -
    // Blocked: everything else (including /, \, ..)
    // Specific block: "." and ".." strictly, and any sequence containing ".."
    const isValidKey = (k) =>
        /^[A-Za-z0-9._-]+$/.test(k) &&
        k !== "." &&
        k !== ".." &&
        !k.includes("..");

    const dirtyKeys = selectedRepos.filter(k => !isValidKey(k));
    if (dirtyKeys.length > 0) {
        alert(`Security: Invalid repository names detected: ${dirtyKeys.join(", ")}. Only alphanumeric, dot, underscore, and dash are allowed (no '..').`);
        if (btn) {
            btn.disabled = false;
            btn.innerText = "Start Job";
        }
        return;
    }

    // Extensions
    const extRaw = document.getElementById('extFilter').value.trim();
    const extensions = extRaw ? extRaw.split(',').map(s => s.trim()) : null;

    // Extras
    const checkedExtras = Array.from(document.querySelectorAll('input[name="extras"]:checked')).map(cb => cb.value);
    const extrasCsv = checkedExtras.join(',');

    // JSON Sidecar legacy logic
    const jsonSidecar = checkedExtras.includes('json_sidecar');

    const planOnlyChecked = document.getElementById('planOnly').checked;
    const commonPayload = {
        hub: document.getElementById('hubPath').value,
        merges_dir: document.getElementById('mergesPath').value || null,
        level: document.getElementById('profile').value,
        mode: document.getElementById('mode').value,
        max_bytes: document.getElementById('maxBytes').value,
        split_size: document.getElementById('splitSize').value,
        plan_only: document.getElementById('planOnly').checked,
        code_only: document.getElementById('codeOnly').checked,
        meta_density: document.getElementById('metaDensity').value,
        json_sidecar: jsonSidecar,
        path_filter: document.getElementById('pathFilter').value.trim() || null,
        extensions: extensions,
        extras: extrasCsv
    };

    if (!planOnlyChecked) {
        commonPayload.force_new = true;
    }

    try {
        // Run Merge Strategy: STRICTLY Batch / Single based on checkboxes.
        // Ignores Pool (Pool is run via Run Merge from Pool).
        // This ensures clear separation of intent.

        const jobsToStart = [];

        if (selectedRepos.length === 0) {
             throw new Error("No repos selected.");
        }

        // Handle Mode: "pro-repo" implies individual job submission for deterministic behavior.
        // "gesamt" (Combined) implies a single batch job.
        const mode = document.getElementById('mode').value;

        // Helper to get include_paths from Pool if available
        const getIncludePaths = (repoName) => {
            if (savedPrescanSelections.has(repoName)) {
                const sel = savedPrescanSelections.get(repoName);
                // null means ALL, array means partial
                return sel.compressed;
            }
            // Not in pool -> Global filters apply (path_filter/extensions in commonPayload)
            // returning null here means "use global default" which is null in payload (ALL)
            return null;
        };

        // Helper to check if repo has a pool override (Any selection in pool).
        // A saved pool entry means this repo is explicitly pool-controlled.
        // This includes ALL/null selections, not only partial subsets.
        const hasPoolOverride = (repo) => {
            return savedPrescanSelections.has(repo);
        };

        // Determine if any pool override is active.
        // If pool selection is active for any repo, we MUST clear global filters
        // because explicit pool intent supersedes downstream path/extensions filtering.
        const anyPoolOverride = selectedRepos.some(hasPoolOverride);

        if (mode === 'pro-repo') {
            // Explicit Split Mode: Submit separate jobs per repo
            selectedRepos.forEach(repo => {
                const paths = getIncludePaths(repo);
                const hasOverride = hasPoolOverride(repo);

                const payload = {
                    ...commonPayload,
                    repos: [repo]
                };

                // Explicit selection from pool supersedes global filters
                if (hasOverride) {
                    payload.include_paths = paths;
                    clearGlobalFilters(payload);
                }

                jobsToStart.push(payload);
            });
        } else {
            // Combined Mode (Default): Submit one job with mapping
            // If pool selections exist, we MUST use include_paths_by_repo + strict mode
            // and clear global filters to prevent silent drops.

            if (anyPoolOverride) {
                const pathMap = {};
                selectedRepos.forEach(repo => {
                    pathMap[repo] = getIncludePaths(repo);
                });

                const payload = {
                    ...commonPayload,
                    repos: selectedRepos,
                    include_paths_by_repo: pathMap,
                    strict_include_paths_by_repo: true
                };
                clearGlobalFilters(payload);
                jobsToStart.push(payload);
            } else {
                // Standard Batch (No mapping needed)
                jobsToStart.push({ ...commonPayload, repos: selectedRepos });
            }
        }

        // Sequential launch
        for (const payload of jobsToStart) {
             const res = await apiFetch(`${API_BASE}/jobs`, {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify(payload)
            });

            if (res.status === 401) throw new Error("Unauthorized.");
            if (!res.ok) throw new Error(`HTTP Error ${res.status}`);

            const job = await res.json();
            streamLogs(job.id); // This will connect to the last one, acceptable for now
        }

        await resetMergeFormToDefaultsAfterSuccessfulSubmit();

        btn.disabled = false;
        btn.innerText = "Start Job";

    } catch (e) {
        alert("Failed to start job: " + e.message);
        btn.disabled = false;
        btn.innerText = "Start Job";
    }
}

let activeEventSource = null;

function streamLogs(jobId) {
    // Close existing stream if any
    if (activeEventSource) {
        activeEventSource.close();
        activeEventSource = null;
    }

    const pre = document.getElementById('logs');
    pre.innerText = `Connecting to logs for job ${jobId}...\n`;

    const token = getToken();
    const url = `${API_BASE}/jobs/${jobId}/logs` + (token ? `?token=${encodeURIComponent(token)}` : '');
    const es = new EventSource(url);
    activeEventSource = es;

    let streamClosed = false;

    function closeStream(reason) {
        if (streamClosed) return;
        streamClosed = true;
        es.close();
        activeEventSource = null;
        pre.innerText += `\n${reason}\n`;
        pre.scrollTop = pre.scrollHeight;
    }

    // Named SSE event "end" — sent by backend as "event: end\ndata: end\n\n"
    // onmessage does NOT receive named events; addEventListener is required.
    es.addEventListener("end", () => {
        closeStream("[Job Finished]");
        loadArtifacts();
    });

    es.onmessage = (event) => {
        pre.innerText += event.data + "\n";
        pre.scrollTop = pre.scrollHeight;
    };

    es.onerror = () => {
        closeStream("[Connection Lost]");
    };
}

// Init
document.addEventListener('DOMContentLoaded', async () => {
    fetchVersion(); // Added: Fetch server version on startup

    // Global ESC handler for modals
    document.addEventListener('keydown', (e) => {
        if (e.key === "Escape") {
            const prescan = document.getElementById('prescanModal');
            if (prescan && !prescan.classList.contains('hidden')) {
                closePrescan();
                return;
            }
            const picker = document.getElementById('pickerModal');
            if (picker && !picker.classList.contains('hidden')) {
                closePicker();
            }
        }
    });

    // Render extras immediately
    renderExtras();
    renderSets();
    renderSelectionPool(); // New
    restoreConfig();

    // Optional: accept token from URL once, then scrub it from the address bar.
    // Enables local wrapper to open UI already authenticated.
    try {
        const url = new URL(window.location.href);
        const urlToken = url.searchParams.get('token');
        if (urlToken) {
            document.getElementById('authToken').value = urlToken;
            setToken(urlToken);
            url.searchParams.delete('token');
            window.history.replaceState({}, document.title, url.pathname + url.search);
        }
    } catch (e) {
        /* non-fatal */
    }

    // Restore token
    const savedToken = localStorage.getItem(TOKEN_KEY);
    if (savedToken) {
        document.getElementById('authToken').value = savedToken;
    }

    // Listen for token changes
    document.getElementById('authToken').addEventListener('input', (e) => {
        setToken(e.target.value);
        // Retry loading data
        loadArtifacts();
        fetchHealth().then(hub => {
            if (hub) fetchRepos(hub);
        });
    });

    // Also listen for manual hub changes (blur)
    document.getElementById('hubPath').addEventListener('blur', (e) => {
        fetchRepos(e.target.value);
    });

    const hub = await fetchHealth();
    if (hub) {
        // If persisted hub is different from server hub, use persisted if available
        const persisted = document.getElementById('hubPath').value;
        fetchRepos(persisted || hub);
        loadArtifacts();
    } else {
        // Try fetch repos with whatever we have
        const persisted = document.getElementById('hubPath').value;
        if(persisted) fetchRepos(persisted);
        loadArtifacts();
    }

    // Load Atlas artifacts too if tab is visible? Or just always.
    // loadAtlasArtifacts();

    document.getElementById('jobForm').addEventListener('submit', startJob);
    document.getElementById('atlasForm').addEventListener('submit', startAtlasJob);

    // Bind query form submission logic
    const qf = document.getElementById('queryForm');
    if (qf) {
        qf.addEventListener('submit', executeQuery);
    }

    // Clear token if user manually edits the root path
    const atlasRootEl = document.getElementById('atlasRoot');
    if (atlasRootEl) {
        atlasRootEl.addEventListener('input', (e) => {
            delete e.target.dataset.token;
        });
    }
});

// --- Tabs ---
function switchTab(tabId) {
    document.querySelectorAll('.layout-view').forEach(el => el.classList.add('hidden'));
    const layoutEl = document.getElementById(`layout-${tabId}`);
    if (layoutEl) {
        layoutEl.classList.remove('hidden');
    }

    // Toggle active state dynamically for all tabs
    const allTabs = ['job', 'atlas', 'query'];
    allTabs.forEach(id => {
        const tabEl = document.getElementById(`tab-${id}`);
        if (tabEl) {
            tabEl.className = tabId === id
                ? "px-3 py-1 rounded bg-blue-600 text-white font-bold text-sm"
                : "px-3 py-1 rounded bg-gray-700 text-gray-300 hover:text-white text-sm";
        }
    });

    if (tabId === 'atlas') {
        loadAtlasArtifacts();
    }
}

// --- Query Logic ---
async function executeQuery(e) {
    if (e && e.preventDefault) {
        e.preventDefault();
    }
    // Default to a query selector if e.target is missing or mock in tests
    const btn = (e && e.target && e.target.querySelector) ? e.target.querySelector('button[type="submit"]') : document.querySelector('#queryForm button[type="submit"]');
    const prevText = btn ? btn.innerText : "Execute Query";
    if (btn) {
        btn.disabled = true;
        btn.innerText = "Querying...";
    }

    const resultsContainer = document.getElementById('queryResults');
    resultsContainer.innerHTML = '<div class="text-gray-400 italic">Searching...</div>';

    const kVal = parseInt(document.getElementById('queryK').value, 10);
    const windowLinesVal = parseInt(document.getElementById('queryWindowLines').value, 10);

    if (Number.isNaN(kVal) || kVal < 1) {
        resultsContainer.innerHTML = '';
        const errDiv = document.createElement('div');
        errDiv.className = "text-red-500 bg-red-900/20 p-4 rounded border border-red-800";
        errDiv.textContent = "Query Failed: Top-K must be a valid number >= 1";
        resultsContainer.appendChild(errDiv);
        if (btn) { btn.disabled = false; btn.innerText = prevText; }
        return;
    }

    if (Number.isNaN(windowLinesVal) || windowLinesVal < 0) {
        resultsContainer.innerHTML = '';
        const errDiv = document.createElement('div');
        errDiv.className = "text-red-500 bg-red-900/20 p-4 rounded border border-red-800";
        errDiv.textContent = "Query Failed: Window lines must be a valid number >= 0";
        resultsContainer.appendChild(errDiv);
        if (btn) { btn.disabled = false; btn.innerText = prevText; }
        return;
    }

    const payload = {
        index_id: document.getElementById('queryIndexId').value.trim(),
        q: document.getElementById('queryText').value.trim(),
        k: kVal,
        context_mode: document.getElementById('queryContextMode').value,
        context_window_lines: windowLinesVal,
        explain: document.getElementById('queryExplain').checked,
        trace: document.getElementById('queryTrace').checked,
        output_profile: "ui_navigation"
    };

    try {
        const response = await apiFetch(`${API_BASE}/query`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify(payload)
        });

        if (!response.ok) {
            const err = await response.json();
            throw new Error(err.detail || `HTTP Error ${response.status}`);
        }

        const data = await response.json();
        renderQueryResults(data);
    } catch (err) {
        resultsContainer.innerHTML = '';
        const errDiv = document.createElement('div');
        errDiv.className = "text-red-500 bg-red-900/20 p-4 rounded border border-red-800";
        errDiv.textContent = `Query Failed: ${err.message}`;
        resultsContainer.appendChild(errDiv);
    } finally {
        if (btn) {
            btn.disabled = false;
            btn.innerText = prevText;
        }
    }
}


function renderQueryResults(data) {
    const resultsContainer = document.getElementById('queryResults');
    resultsContainer.textContent = ''; // Clear container cleanly

    const bundle = data.context_bundle || data;
    const hits = bundle.hits || [];

    if (hits.length === 0) {
        const noRes = document.createElement('div');
        noRes.className = "text-gray-400 italic";
        noRes.textContent = "No results found.";
        resultsContainer.appendChild(noRes);
        return;
    }

    hits.forEach((hit) => {
        const score = typeof hit.score === 'number' ? hit.score.toFixed(3) : "0.000";

        const div = document.createElement('div');
        div.className = "bg-gray-800 p-4 rounded border border-gray-700 mt-4";

        // Header: Path and Score
        const headerDiv = document.createElement('div');
        headerDiv.className = "flex justify-between items-start mb-2";

        const pathDiv = document.createElement('div');
        pathDiv.className = "font-mono text-sm text-blue-400 break-all";
        pathDiv.textContent = hit.file || 'unknown';
        const rangeSpan = document.createElement('span');
        rangeSpan.className = "text-gray-500 ml-1";
        rangeSpan.textContent = `:${hit.range || ''}`;
        pathDiv.appendChild(rangeSpan);

        const scoreDiv = document.createElement('div');
        scoreDiv.className = "text-xs font-bold text-green-400 bg-green-900/30 px-2 py-1 rounded";
        scoreDiv.textContent = `Score: ${score}`;

        headerDiv.appendChild(pathDiv);
        headerDiv.appendChild(scoreDiv);
        div.appendChild(headerDiv);

        // Metadata: Provenance and Graph Badge
        const metaDiv = document.createElement('div');
        metaDiv.className = "flex items-center text-xs mb-2";

        const provLabel = document.createElement('span');
        provLabel.className = "text-gray-400";
        provLabel.textContent = "Provenance:";
        metaDiv.appendChild(provLabel);

        const provBadge = document.createElement('span');
        provBadge.className = "bg-gray-700 text-gray-300 text-[10px] px-1 rounded ml-2";
        provBadge.textContent = hit.provenance_type || 'unknown';
        metaDiv.appendChild(provBadge);

        if (hit.graph_context && hit.graph_context.graph_used) {
            const graphBadge = document.createElement('span');
            graphBadge.className = "bg-purple-900 text-purple-200 text-[10px] px-1 rounded ml-2";
            graphBadge.title = `Graph Distance: ${hit.graph_context.distance}`;
            graphBadge.textContent = "Graph";
            metaDiv.appendChild(graphBadge);
        }
        div.appendChild(metaDiv);

        // Context / Snippet
        if (hit.surrounding_context || hit.resolved_code_snippet) {
            const ctxWrap = document.createElement('div');
            ctxWrap.className = "mt-2 text-xs";

            const ctxLabel = document.createElement('div');
            ctxLabel.className = "text-gray-500 mb-1 uppercase font-bold";
            ctxLabel.textContent = hit.surrounding_context ? "Context Preview" : "Exact Match";
            ctxWrap.appendChild(ctxLabel);

            const ctxPre = document.createElement('pre');
            ctxPre.className = "bg-gray-900 p-2 rounded border border-gray-700 text-gray-300 overflow-x-auto max-h-40";
            ctxPre.textContent = hit.surrounding_context || hit.resolved_code_snippet;
            ctxWrap.appendChild(ctxPre);

            div.appendChild(ctxWrap);
        }

        // Explain
        if (hit.explain && Object.keys(hit.explain).length > 0) {
            const expDetails = document.createElement('details');
            expDetails.className = "mt-2 text-xs";

            const expSummary = document.createElement('summary');
            expSummary.className = "cursor-pointer text-gray-400 hover:text-gray-200";
            expSummary.textContent = "Explain";
            expDetails.appendChild(expSummary);

            const expPre = document.createElement('pre');
            expPre.className = "bg-gray-900 p-2 mt-1 rounded border border-gray-700 text-gray-300 overflow-x-auto";
            expPre.textContent = JSON.stringify(hit.explain, null, 2);
            expDetails.appendChild(expPre);

            div.appendChild(expDetails);
        }

        resultsContainer.appendChild(div);
    });

    if (data.query_trace) {
        const traceDiv = document.createElement('div');
        traceDiv.className = "mt-6 border-t border-gray-700 pt-4";

        const traceDetails = document.createElement('details');
        traceDetails.className = "text-xs";

        const traceSummary = document.createElement('summary');
        traceSummary.className = "cursor-pointer text-yellow-500 hover:text-yellow-400 font-bold uppercase";
        traceSummary.textContent = "Query Trace (Diagnostics)";
        traceDetails.appendChild(traceSummary);

        const tracePre = document.createElement('pre');
        tracePre.className = "bg-gray-900 p-2 mt-2 rounded border border-gray-700 text-gray-300 overflow-x-auto";
        tracePre.textContent = JSON.stringify(data.query_trace, null, 2);
        traceDetails.appendChild(tracePre);

        traceDiv.appendChild(traceDetails);
        resultsContainer.appendChild(traceDiv);
    }
}

// --- Atlas Logic ---
async function startAtlasJob(e) {
    e.preventDefault();
    const btn = e.target.querySelector('button[type="submit"]');
    btn.disabled = true;
    btn.innerText = "Scanning...";

    const rootInput = document.getElementById('atlasRoot');
    const rootPath = rootInput.value.trim();
    const rootToken = rootInput.dataset.token; // Use token if available from picker

    // Save Atlas Config (include token for restoration)
    // NOTE: Persisting the token is a deliberate UX decision for this Localhost tool.
    // It allows the form to remain valid after a page reload.
    // In a multi-user environment, persisting capabilities in localStorage would be a risk.
    const config = {
        version: 2,
        root: rootPath,
        token: rootToken || null,
        depth: document.getElementById('atlasDepth').value,
        limit: document.getElementById('atlasLimit').value,
        excludes: document.getElementById('atlasExcludes').value,
        scanMode: document.getElementById('atlasMode') ? document.getElementById('atlasMode').value : 'inventory'
    };
    localStorage.setItem(ATLAS_CONFIG_KEY, JSON.stringify(config));

    if (typeof buildAtlasPayload !== 'function') {
        console.error("atlas_payload.js not loaded: buildAtlasPayload missing");
        alert("Internal error: atlas payload builder missing. Please hard-reload (Ctrl+Shift+R).");
        btn.disabled = false;
        btn.innerText = "Create Atlas";
        return;
    }

    const payload = buildAtlasPayload(
        config.root,
        config.token,
        config.depth,
        config.limit,
        config.excludes,
        config.scanMode
    );

    if (payload.root_kind === "invalid") {
         alert("Invalid Root. Please use the picker (folder icon) to select a directory, or type a valid preset ('hub', 'merges', 'system'), or provide an absolute path.");
         btn.disabled = false;
         btn.innerText = "Create Atlas";
         return;
    }

    try {
        const res = await apiFetch(`${API_BASE}/atlas`, {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify(payload)
        });

        if (res.status === 400) {
            let errMsg = "Bad Request";
            try {
                const errData = await res.json();
                if (errData.detail) errMsg = errData.detail;
            } catch(e) { /* ignore JSON parse error */ }

            // Heuristic detection of root/token issues
            const lowerErr = errMsg.toLowerCase();
            const isRootTokenIssue = lowerErr.includes("missing root directory") ||
                                     lowerErr.includes("missing atlas root") ||
                                     lowerErr.includes("invalid root directory identifier") ||
                                     lowerErr.includes("invalid atlas root_id") ||
                                     lowerErr.includes("invalid atlas token");

            if (isRootTokenIssue) {
                 console.warn("[Atlas] Invalid Root/Token detected. Auto-clearing.");

                 // Auto-Clear Token from Storage (Use local 'config' to avoid re-read)
                 if (config.token) {
                     delete config.token;
                     // Version is already 2 in 'config'
                     localStorage.setItem(ATLAS_CONFIG_KEY, JSON.stringify(config));
                 }

                 // UI Update
                 delete rootInput.dataset.token;

                 alert(`Invalid Root Token. Please re-select the root folder.\n\nServer: ${errMsg}`);
                 return;
            }

            throw new Error("Atlas scan failed: " + errMsg);
        }

        if (!res.ok) throw new Error("Atlas scan failed: " + res.statusText);

        const art = await res.json();
        alert(`Atlas scan started/completed: ${art.id}`);
        loadAtlasArtifacts();

    } catch (e) {
        alert(e.message);
    } finally {
        btn.disabled = false;
        btn.innerText = "Create Atlas";
    }
}

let _atlasPollingTimeout = null;

async function loadAtlasArtifacts() {
    const list = document.getElementById('atlasList');
    if (!list.innerHTML || list.innerHTML.includes('No atlas artifacts')) {
        list.innerHTML = '<div class="text-gray-500 italic">Loading...</div>';
    }

    try {
        const res = await apiFetch(`${API_BASE}/atlas`);
        if (res.status === 404) {
             list.innerHTML = '<div class="text-gray-500 italic">No atlas artifacts found.</div>';
             return;
        }
        if (!res.ok) throw new Error("Failed to load atlas");

        const artifacts = await res.json();

        if (artifacts.length === 0) {
            list.innerHTML = '<div class="text-gray-500 italic">No atlas artifacts found.</div>';
            return;
        }

        list.innerHTML = '';

        let anyRunning = false;

        artifacts.forEach(art => {
            const div = document.createElement('div');
            div.className = "bg-gray-900 p-2 rounded border border-gray-700 flex flex-col mb-2";

            const date = new Date(art.created_at).toLocaleString();

            const headerDiv = document.createElement('div');
            headerDiv.className = "flex justify-between items-start";

            const titleSpan = document.createElement('span');
            titleSpan.className = "font-bold text-green-400";
            titleSpan.textContent = art.id;

            if (art.status === 'running') {
                const badge = document.createElement('span');
                badge.className = "text-yellow-400 animate-pulse text-xs font-bold ml-2";
                badge.textContent = "RUNNING";
                titleSpan.appendChild(badge);
                anyRunning = true;
            } else if (art.status === 'failed') {
                const badge = document.createElement('span');
                badge.className = "text-red-500 text-xs font-bold ml-2";
                badge.textContent = "FAILED";
                titleSpan.appendChild(badge);
            }

            const dateSpan = document.createElement('span');
            dateSpan.className = "text-xs text-gray-500";
            dateSpan.textContent = date;

            headerDiv.appendChild(titleSpan);
            headerDiv.appendChild(dateSpan);
            div.appendChild(headerDiv);

            const rootDiv = document.createElement('div');
            rootDiv.className = "text-xs text-gray-300 font-mono bg-gray-800 p-1 rounded mt-1 truncate";
            rootDiv.title = art.root_scanned;
            rootDiv.textContent = `Root: ${art.root_scanned}`;
            div.appendChild(rootDiv);

            if (art.effective) {
                const limitsDiv = document.createElement('div');
                limitsDiv.className = "text-[10px] text-gray-500 mt-1";
                limitsDiv.textContent = `Limits: Depth=${art.effective.max_depth}, Cap=${art.effective.max_entries}`;
                div.appendChild(limitsDiv);
            }

            if (art.stats && art.stats.total_files !== undefined) {
                const mb = (art.stats.total_bytes / (1024*1024)).toFixed(2);
                const statsDiv = document.createElement('div');
                statsDiv.className = "mt-2 text-xs grid grid-cols-2 gap-2 text-gray-400";

                const filesDiv = document.createElement('div');
                filesDiv.textContent = 'Files: ';
                const filesSpan = document.createElement('span');
                filesSpan.className = "text-white";
                filesSpan.textContent = art.stats.total_files;
                filesDiv.appendChild(filesSpan);
                statsDiv.appendChild(filesDiv);

                const dirsDiv = document.createElement('div');
                dirsDiv.textContent = 'Dirs: ';
                const dirsSpan = document.createElement('span');
                dirsSpan.className = "text-white";
                dirsSpan.textContent = art.stats.total_dirs;
                dirsDiv.appendChild(dirsSpan);
                statsDiv.appendChild(dirsDiv);

                const sizeDiv = document.createElement('div');
                sizeDiv.textContent = 'Size: ';
                const sizeSpan = document.createElement('span');
                sizeSpan.className = "text-white";
                sizeSpan.textContent = `${mb} MB`;
                sizeDiv.appendChild(sizeSpan);
                statsDiv.appendChild(sizeDiv);

                const durationDiv = document.createElement('div');
                durationDiv.textContent = 'Duration: ';
                const durationSpan = document.createElement('span');
                durationSpan.className = "text-white";
                durationSpan.textContent = `${art.stats.duration_seconds.toFixed(2)}s`;
                durationDiv.appendChild(durationSpan);
                statsDiv.appendChild(durationDiv);

                div.appendChild(statsDiv);
            }

            if (art.status === 'complete') {
                const dlDiv = document.createElement('div');
                dlDiv.className = "flex flex-wrap gap-2 text-xs mt-3 border-t border-gray-800 pt-2";

                if (art.paths.json) {
                    dlDiv.appendChild(createArtifactDownloadButton({
                        url: `${API_BASE}/atlas/${art.id}/download?key=json`,
                        filename: art.paths.json,
                        label: 'Download JSON',
                        className: 'bg-gray-700 hover:bg-gray-600 px-2 py-1 rounded text-green-400'
                    }));
                }

                if (art.paths.md) {
                    dlDiv.appendChild(createArtifactDownloadButton({
                        url: `${API_BASE}/atlas/${art.id}/download?key=md`,
                        filename: art.paths.md,
                        label: 'Download Report',
                        className: 'bg-gray-700 hover:bg-gray-600 px-2 py-1 rounded text-blue-400'
                    }));
                }

                if (art.paths.inventory) {
                    dlDiv.appendChild(createArtifactDownloadButton({
                        url: `${API_BASE}/atlas/${art.id}/download?key=inventory`,
                        filename: art.paths.inventory,
                        label: 'Download Inventory',
                        className: 'bg-gray-700 hover:bg-gray-600 px-2 py-1 rounded text-yellow-400'
                    }));
                }

                if (art.paths.dirs_inventory) {
                    dlDiv.appendChild(createArtifactDownloadButton({
                        url: `${API_BASE}/atlas/${art.id}/download?key=dirs_inventory`,
                        filename: art.paths.dirs_inventory,
                        label: 'Download Dirs Inventory',
                        className: 'bg-gray-700 hover:bg-gray-600 px-2 py-1 rounded text-orange-400'
                    }));
                }

                if (art.paths.topology) {
                    dlDiv.appendChild(createArtifactDownloadButton({
                        url: `${API_BASE}/atlas/${art.id}/download?key=topology`,
                        filename: art.paths.topology,
                        label: 'Download Topology',
                        className: 'bg-gray-700 hover:bg-gray-600 px-2 py-1 rounded text-purple-400'
                    }));
                }

                if (art.paths.content) {
                    dlDiv.appendChild(createArtifactDownloadButton({
                        url: `${API_BASE}/atlas/${art.id}/download?key=content`,
                        filename: art.paths.content,
                        label: 'Download Content JSON',
                        className: 'bg-gray-700 hover:bg-gray-600 px-2 py-1 rounded text-teal-400'
                    }));
                }

                if (art.paths.workspaces) {
                    dlDiv.appendChild(createArtifactDownloadButton({
                        url: `${API_BASE}/atlas/${art.id}/download?key=workspaces`,
                        filename: art.paths.workspaces,
                        label: 'Download Workspaces',
                        className: 'bg-gray-700 hover:bg-gray-600 px-2 py-1 rounded text-indigo-400'
                    }));
                }

                if (art.paths.hotspots) {
                    dlDiv.appendChild(createArtifactDownloadButton({
                        url: `${API_BASE}/atlas/${art.id}/download?key=hotspots`,
                        filename: art.paths.hotspots,
                        label: 'Download Hotspots',
                        className: 'bg-gray-700 hover:bg-gray-600 px-2 py-1 rounded text-pink-400'
                    }));
                }

                div.appendChild(dlDiv);
            } else if (art.status === 'failed') {
                const errDiv = document.createElement('div');
                errDiv.className = "text-xs text-red-400 mt-2 p-2 bg-red-900/30 rounded border border-red-800/50 break-words";
                errDiv.textContent = art.error || "Atlas scan failed. See server logs for details.";
                div.appendChild(errDiv);
            }

            list.appendChild(div);
        });

        if (_atlasPollingTimeout) {
            clearTimeout(_atlasPollingTimeout);
            _atlasPollingTimeout = null;
        }

        if (anyRunning) {
            _atlasPollingTimeout = setTimeout(() => {
                // Only poll if tab is active to save resources
                if (!document.getElementById('layout-atlas').classList.contains('hidden')) {
                    loadAtlasArtifacts();
                } else {
                    // Will be fetched next time tab is switched to
                    _atlasPollingTimeout = null;
                }
            }, 3000);
        }

    } catch (e) {
        list.innerHTML = `<div class="text-gray-500 italic">Error: ${e.message}</div>`;
    }
}

async function startExport() {
    if (!confirm("Prepare export for webmaschine? This will overwrite files in exports/webmaschine.")) return;

    try {
        const res = await apiFetch(`${API_BASE}/export/webmaschine`, { method: 'POST' });
        if (!res.ok) throw new Error("Export failed");
        const data = await res.json();
        alert(`Export successful!\nPath: ${data.path}`);
    } catch (e) {
        alert(e.message);
    }
}

// Secure download via blob
async function downloadWithAuth(url, name) {
    try {
        const res = await apiFetch(url);

        if (!res.ok) {
            alert("Download failed: " + res.statusText);
            return;
        }

        const blob = await res.blob();
        const downloadUrl = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = downloadUrl;

        // Try to get filename from header
        // For blob downloads, the name passed in is usually better if available
        // But we can check Content-Disposition if needed.

        a.download = name;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        URL.revokeObjectURL(downloadUrl);

    } catch (e) {
        alert("Download error: " + e.message);
    }
}

// --- Prescan Logic ---
// ARCHITECTURE:
// - Prescan → Selection Pool (modify only, never triggers merge)
// - Merge → Explicit action from main view via job submission buttons
// - No implicit transition from prescan to merge execution

async function startPrescan() {
    window.__prescanOpen = true; // Engage Guard

    const repos = Array.from(document.querySelectorAll('input[name="repos"]:checked')).map(cb => cb.value);

    if (repos.length === 0) {
        alert("Please select at least one repository first.");
        window.__prescanOpen = false; // Disengage if early exit
        return;
    }
    if (repos.length > 1) {
        alert("Prescan currently supports single repo selection for editing. Please select only one.");
        window.__prescanOpen = false; // Disengage if early exit
        return;
    }

    const repo = repos[0];

    document.getElementById('prescanModal').classList.remove('hidden');
    document.getElementById('prescanTree').innerHTML = '<div class="text-gray-500 italic p-4">Scanning structure...</div>';
    document.getElementById('prescanStats').innerText = `Scanning ${repo}...`;

    // Reset or load selection
    if (savedPrescanSelections.has(repo)) {
        // Handle Tri-state load
        const saved = savedPrescanSelections.get(repo);
        if (saved.raw === null) {
            selectionSetAll();
        } else {
            prescanSelection = new Set(saved.raw);
        }
    } else {
        selectionResetNone();
    }
    prescanExpandedPaths.clear();

    try {
        const res = await apiFetch(`${API_BASE}/prescan`, {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({
                repo: repo,
                max_depth: 10
            })
        });

        if (!res.ok) throw new Error("Prescan failed: " + res.statusText);

        const data = await res.json();
        prescanCurrentTree = data;

        document.getElementById('prescanStats').innerText = `${data.root} • ${data.file_count} files • ${(data.total_bytes / 1024 / 1024).toFixed(2)} MB`;

        // Expand root by default - use internal path which is usually '.' for relative root
        if (data.tree && data.tree.path) {
            setExpansionState(data.tree.path, true);
        } else {
            // Fallback
            setExpansionState(".", true);
        }

        // Initial Selection: Recommended (instead of All) if empty
        // Only run recommendation if we started fresh (prescanSelection is empty set, not null/all)
        if (selectionIsNone()) {
            prescanRecommended();
        }

        renderPrescanTree();

    } catch (e) {
        document.getElementById('prescanTree').innerHTML = `<div class="text-red-400 p-4">Error: ${e.message}</div>`;
    }
}

function closePrescan() {
    document.getElementById('prescanModal').classList.add('hidden');
    prescanCurrentTree = null;
    prescanExpandedPaths.clear();
    window.__prescanOpen = false; // Disengage Guard
}

function renderPrescanTree() {
    if (!prescanCurrentTree) return;

    const container = document.getElementById('prescanTree');
    container.innerHTML = '';

    // Retry render logic: Pure DOM recursion
    function renderNodeTo(node, parentEl) {
        const div = document.createElement('div');
        div.className = "select-none";

        const row = document.createElement('div');
        row.className = "flex items-center hover:bg-gray-800 py-px cursor-pointer group";

        const path = node.path; // Normalization handled by wrappers/isPathSelected
        const isDir = node.type === 'dir';
        const isChecked = isDir ? isDirSelected(node) : isPathSelected(path);
        const isExpanded = isDir && isPathExpanded(path);

        // Determine indeterminate state for dirs
        let indeterminate = false;
        if (isDir && !isChecked) {
            indeterminate = isDirPartial(node);
        }

        const cb = document.createElement('input');
        cb.type = 'checkbox';
        cb.checked = isChecked;
        cb.indeterminate = indeterminate;
        cb.className = "mr-2 form-checkbox text-blue-500 bg-gray-900 border-gray-700";
        cb.onclick = (e) => {
            e.stopPropagation();
            togglePrescanNode(node, cb.checked);
            // Optimization: Don't full re-render, just update checkbox states if possible?
            // For now, re-render is safer for indeterminate states, but since we collapse, it's fast.
            renderPrescanTree();
        };

        // Click on row toggles expansion (for dirs)
        row.onclick = (e) => {
            if (e.target !== cb && isDir) {
                if (isPathExpanded(path)) {
                    setExpansionState(path, false);
                } else {
                    setExpansionState(path, true);
                }
                renderPrescanTree();
            } else if (e.target !== cb && !isDir) {
                // Toggle file
                cb.click();
            }
        };

        const icon = document.createElement('span');
        icon.className = "mr-2 text-xs w-4 text-center inline-block";
        if (isDir) {
            icon.innerText = isExpanded ? '📂' : '📁';
        } else {
            icon.innerText = '📄';
        }

        const label = document.createElement('span');
        label.className = isDir ? "text-blue-200 font-bold" : "text-gray-300";

        // UX Enhancement: Handle root/empty path labels gracefully
        const normalized = normalizePath(path);
        label.innerText = normalized ? (normalized.split('/').pop() || "/") : "n/a";

        row.appendChild(cb);
        row.appendChild(icon);
        row.appendChild(label);

        if (!isDir) {
             const sizeKb = (node.size / 1024).toFixed(1);
             const meta = document.createElement('span');
             meta.className = "text-gray-600 text-xs ml-2 opacity-0 group-hover:opacity-100";
             meta.innerText = `${sizeKb} KB`;
             row.appendChild(meta);
        }

        div.appendChild(row);

        // Render children only if expanded
        if (isDir && node.children && isExpanded) {
            const childrenContainer = document.createElement('div');
            childrenContainer.className = "pl-4 border-l border-gray-800 ml-2";

            const dirs = node.children.filter(c => c.type === 'dir').sort((a,b) => (normalizePath(a.path) || "").localeCompare(normalizePath(b.path) || ""));
            const files = node.children.filter(c => c.type === 'file').sort((a,b) => (normalizePath(a.path) || "").localeCompare(normalizePath(b.path) || ""));

            [...dirs, ...files].forEach(child => {
                renderNodeTo(child, childrenContainer);
            });
            div.appendChild(childrenContainer);
        }

        parentEl.appendChild(div);
    }

    // Start with root directly
    renderNodeTo(prescanCurrentTree.tree, container);
}

function isDirSelected(node) {
    // A dir is selected if all its children are selected
    if (!node.children || node.children.length === 0) return false;

    // If prescanSelection is null (ALL), then everything is selected
    if (selectionIsAll()) return true;

    return node.children.every(c => c.type === 'dir' ? isDirSelected(c) : isPathSelected(c.path));
}

function isDirPartial(node) {
    // True if some children selected
    if (!node.children || node.children.length === 0) return false;

    // If ALL, it's not partial, it's full
    if (selectionIsAll()) return false;

    return node.children.some(c => c.type === 'dir' ? (isDirSelected(c) || isDirPartial(c)) : isPathSelected(c.path));
}

function togglePrescanNode(rootNode, checked) {
    // If user clicked "Check" on root node while in "Partial" mode, it's effectively "Check All"
    // BUT this function is called for sub-nodes too.

    // Iterative approach to avoid call stack overflow on deep trees
    const stack = [rootNode];
    while (stack.length > 0) {
        const node = stack.pop();
        if (node.type === 'file') {
            setSelectionState(node.path, checked);
        } else if (node.children) {
            // Push children to stack
            for (let i = 0; i < node.children.length; i++) {
                stack.push(node.children[i]);
            }
        }
    }
}

function prescanToggleAll(checked) {
    if (!prescanCurrentTree) return;

    // No recursion, no iteration. Pure State Switch.
    if (checked) {
        selectionSetAll();
    } else {
        selectionResetNone();
    }

    renderPrescanTree();
}

function prescanDocs() {
    prescanToggleAll(false);
    // Traverse and select matches
    function visit(node) {
        if (node.type === 'file') {
            const path = normalizePath(node.path);
            if (path) { // Guard against null
                const lower = path.toLowerCase();
                if (lower.includes('readme') || lower.includes('docs/') || lower.endsWith('.md') || lower.includes('manual')) {
                    setSelectionState(path, true);
                }
            }
        } else if (node.children) {
            node.children.forEach(visit);
        }
    }
    visit(prescanCurrentTree.tree);
    renderPrescanTree();
}

function prescanRecommended() {
    // Default heuristic: src, README, docs, contracts, no tests
    prescanToggleAll(false);
    function visit(node) {
        if (node.type === 'file') {
            const path = normalizePath(node.path);
            if (path) { // Guard against null
                const lower = path.toLowerCase();
                // Critical
                if (lower.includes('readme') || lower.endsWith('.ai-context.yml')) {
                    setSelectionState(path, true);
                    return;
                }
                // Code
                const parts = lower.split('/');
                if (parts.includes('src') || parts.includes('contracts') || parts.includes('docs')) {
                    // Improved test exclusion heuristic (User request E)
                    // Added __tests__ as per cherry-pick #291
                    const isTest = parts.includes('tests') ||
                                   parts.includes('__tests__') ||
                                   parts.includes('test') ||
                                   lower.includes('_test.') ||
                                   lower.includes('.test.') ||
                                   lower.includes('.spec.');

                    if (!isTest) {
                         setSelectionState(path, true);
                    }
                }
            }
        } else if (node.children) {
            node.children.forEach(visit);
        }
    }
    visit(prescanCurrentTree.tree);
    renderPrescanTree();
}

async function storePrescanSelectionReplace() {
    await storePrescanSelectionInternal(false);
}

async function storePrescanSelectionAppend() {
    await storePrescanSelectionInternal(true);
}

// Deprecated aliases kept for compatibility if referenced in HTML
async function applyPrescanSelectionReplace() { await storePrescanSelectionReplace(); }
async function applyPrescanSelectionAppend() { await storePrescanSelectionAppend(); }

async function removePrescanSelection() {
    const repo = prescanCurrentTree.root;
    savedPrescanSelections.delete(repo);
    persistSavedPrescanSelections();
    closePrescan();
    
    // Update UI (Selection Pool + Badges)
    renderSelectionPool();
    await fetchRepos(document.getElementById('hubPath').value);
    
    // Show feedback
    showNotification(`Removed selection pool for ${repo}`, 'info');
}

async function storePrescanSelectionInternal(append) {
    // Semantics: "Store Selection" in Pool.
    // - empty selection means "remove manual override" (back to standard behavior)
    // - prescanSelection === null means "ALL" (explicitly select entire repo)
    // This function MUST NOT trigger any merge or job execution.

    const repo = prescanCurrentTree.root;
    const prev = savedPrescanSelections.get(repo) || null;

    if (selectionIsAll()) {
        // ALL selected
        // ALL overrides everything (Union with ALL is ALL).
        savedPrescanSelections.set(repo, { raw: null, compressed: null });
    } else {
        if (selectionIsNone()) {
             // Nothing selected in current view.
             // If Replace: Remove manual override (delete from pool).
             // If Append: Do nothing (keep previous state) but inform the user.
             if (!append) {
                 savedPrescanSelections.delete(repo);
             } else {
                 // Provide feedback so the user understands why no changes were applied.
                 showNotification('No changes were applied because no items are selected in append mode.', 'warning');
                 return; // Don't close the dialog
             }
        } else {
             // Partial selection in current view.
             // Calculate compressed paths for the *current* selection.
             const currentCompressed = [];
             function collectPaths(node) {
                 const path = normalizePath(node.path);

                 if (node.type === 'file') {
                     // Only add if path is valid AND selected
                     if (path !== null && isPathSelected(path)) {
                         currentCompressed.push(path);
                     }
                 } else if (node.type === 'dir') {
                     // If valid path AND fully selected, add dir
                     if (path !== null && isDirSelected(node)) {
                         currentCompressed.push(path);
                     } else {
                         // Otherwise descend (also descends if path is null/invalid but has children)
                         if (node.children) node.children.forEach(collectPaths);
                     }
                 }
             }
             collectPaths(prescanCurrentTree.tree);

             // Merge Logic
             if (prev && append) {
                 if (prev.compressed === null) {
                     // Previous was ALL. New is Partial. Result: ALL.
                     // Note: When merging ALL with Partial in append mode, the result is ALL.
                     // This may be counterintuitive if user intentionally deselected items.
                     // We keep ALL as union of ALL and anything is ALL.
                     savedPrescanSelections.set(repo, prev);
                 } else {
                     // Previous was Partial. New is Partial.
                     // 1. Merge Compressed Rules (for Backend)
                     const mergedCompressed = new Set([...(prev.compressed || []), ...currentCompressed]);

                     // 2. Merge Raw Sets (for UI consistency)
                     // If we don't merge raw, reloading the pool will show incomplete checkboxes.
                     let mergedRaw = null;
                     if (prev.raw && prescanSelection) {
                         // Union of both sets
                         mergedRaw = new Set([...prev.raw, ...prescanSelection]);
                     } else if (prescanSelection) {
                         // Prev raw missing? Use current.
                         mergedRaw = new Set(prescanSelection);
                     } else if (prev.raw instanceof Set) {
                         // Current selection is null but prev.raw exists as a Set.
                         // This could happen if previous had raw but current is ALL state.
                         // Create a new Set to avoid mutations to previous selection.
                         mergedRaw = new Set(prev.raw);
                     }
                     
                     // If both prev.raw and prescanSelection are falsy, mergedRaw would remain null,
                     // while mergedCompressed may still contain paths. To avoid losing the raw
                     // representation (and causing UI inconsistencies on reload), fall back to
                     // materializing raw from the tree using compressed rules.
                     if (!mergedRaw && mergedCompressed.size > 0) {
                         if (window.__RLENS_MATERIALIZE_MISSING__) {
                             if (!window.__RLENS_MATERIALIZE_WARNED__) {
                                 window.__RLENS_MATERIALIZE_WARNED__ = true;
                                 console.warn('Cannot materialize raw: materialize.js missing (degraded)');
                             }
                             mergedRaw = null;
                         } else if (prescanCurrentTree && prescanCurrentTree.tree) {
                             mergedRaw = materializeRawFromCompressed(prescanCurrentTree.tree, mergedCompressed);
                         } else {
                             // Cannot materialize raw without tree. Keep raw as null (degraded state).
                             // This maintains the files-only contract: raw is either null or contains only files.
                             // UI will need to handle this degraded state on reload (tree required for full restore).
                             console.warn('Cannot materialize raw from compressed without tree; raw will be null (degraded)');
                             mergedRaw = null;
                         }
                     }

                     savedPrescanSelections.set(repo, {
                         raw: mergedRaw,
                         compressed: Array.from(mergedCompressed)
                     });
                 }
             } else {
                 // Replace Mode or No Previous State
                 // prescanSelection contains only files (enforced by togglePrescanNode and helper functions)
                 savedPrescanSelections.set(repo, {
                     raw: new Set(prescanSelection),
                     compressed: currentCompressed
                 });
             }
        }
    }

    persistSavedPrescanSelections();
    closePrescan();

    // Update UI (Selection Pool + Badges)
    renderSelectionPool();
    await fetchRepos(document.getElementById('hubPath').value);
    
    // Show feedback
    const mode = append ? 'appended to' : 'replaced';
    showNotification(`Selection ${mode} pool for ${repo}`, 'success');
}

// Deprecated function name kept for backward compatibility
async function applyPrescanSelection() {
    // Default to replace mode for backward compatibility
    await storePrescanSelectionReplace();
}

// --- Version & Diagnostics ---

async function fetchVersion() {
    try {
        const res = await apiFetch('/api/version');
        if (res.ok) {
            const data = await res.json();
            const verEl = document.getElementById('verLabel');
            const originEl = document.getElementById('originLabel');

            // Format: S: <ver> | B: <build_ts>
            // Build ID format: ver-timestamp. We split and take last part.
            const buildTs = data.build_id ? data.build_id.split('-').pop() : '?';

            if (verEl) verEl.textContent = `S: ${data.version} | B: ${buildTs}`;
            if (originEl) originEl.textContent = `Origin: ${window.location.host}`; // user requested origin

            console.info(`[rLens] Server Version: ${data.version}, Build: ${data.build_id}`);
        }
    } catch (e) {
        console.error("Version check failed", e);
    }
}

async function hardRefresh() {
    if (!confirm("Clear all caches and reload?")) return;

    // 1. Unregister Service Workers (Critical for Brave/PWA)
    if ('serviceWorker' in navigator) {
        try {
            const registrations = await navigator.serviceWorker.getRegistrations();
            await Promise.all(registrations.map(r => r.unregister()));
            console.log(`[rLens] Unregistered ${registrations.length} service workers.`);
        } catch (e) {
            console.warn("[rLens] Service Worker cleanup failed", e);
        }
    }

    // 2. Clear Cache Storage (Hard await)
    if ('caches' in window) {
        try {
            const keys = await caches.keys();
            await Promise.all(keys.map(name => caches.delete(name)));
            console.log(`[rLens] Cleared ${keys.length} caches.`);
        } catch (e) {
            console.warn("[rLens] Cache clearing failed", e);
        }
    }

    // 3. Clear Storage
    localStorage.clear();
    sessionStorage.clear();

    // 4. Reload with timestamp to force network fetch of index.html
    const url = new URL(window.location.href);
    url.searchParams.set('t', Date.now());
    window.location.replace(url.toString());
}

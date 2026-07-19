// Tests for the RepoGround "Quelle" (source mode) dropdown and the legacy pre_pull
// payload it now drives.
//
// Loads app.js into a VM context with a mock DOM (same approach as
// test_artifact_fallback.js) and drives the real startJob() / saveConfig() /
// getEffectiveMergeFormDefaults() code paths, asserting:
//   - the source dropdown is the leading semantics; it derives the legacy
//     pre_pull flag (local_ff => true, local_current/remote_snapshot => false),
//   - remote_snapshot adds repo_source_mode / remote_ref_policy / remote_ref,
//   - plan-only forces pre_pull false,
//   - Save/Load Defaults round-trips the source mode (and legacy pre_pull),
//   - index.html ships the (hidden, derived) #prePull checkbox + #sourceMode,
//   - the Source Acquisition artifact link is wired in app.js.

const fs = require('fs');
const path = require('path');
const vm = require('vm');

let failed = 0;
function assert(condition, message) {
    if (!condition) {
        console.error('FAIL: ' + message);
        failed++;
    } else {
        console.log('PASS: ' + message);
    }
}

// --- Static checks on index.html / app.js -----------------------------------
const html = fs.readFileSync(path.join(__dirname, '..', 'index.html'), 'utf8');
const inputMatch = html.match(/<input[^>]*id="prePull"[^>]*>/);
assert(!!inputMatch, 'index.html contains an input with id="prePull"');
assert(!!inputMatch && /\schecked(\s|>|=)/.test(inputMatch[0]), 'pre_pull checkbox is checked by default in index.html');
assert(/id="sourceMode"/.test(html), 'index.html contains the #sourceMode dropdown');
assert(/id="remoteRefPolicy"/.test(html), 'index.html contains the #remoteRefPolicy dropdown');
assert(/id="remoteRef"/.test(html), 'index.html contains the #remoteRef input');

const appJsSrc = fs.readFileSync(path.join(__dirname, '..', 'app.js'), 'utf8');
assert(/source_acquisition_report/.test(appJsSrc), 'app.js wires a source_acquisition_report artifact link');

// --- Mock DOM + VM context --------------------------------------------------
function makeEl(overrides = {}) {
    const el = {
        value: '',
        checked: false,
        innerText: '',
        textContent: '',
        className: '',
        disabled: false,
        dataset: {},
        style: {},
        children: [],
        classList: { add() {}, remove() {}, contains() { return false; }, toggle() {} },
        appendChild(c) { this.children.push(c); },
        setAttribute() {},
        removeAttribute() {},
        addEventListener() {},
        querySelector() { return null; },
        querySelectorAll() { return []; }
    };
    Object.defineProperty(el, 'innerHTML', { get() { return this._h || ''; }, set(v) { this._h = v; } });
    return Object.assign(el, overrides);
}

function makeStorage(seed = {}) {
    const m = new Map(Object.entries(seed));
    return {
        getItem(k) { return m.has(k) ? m.get(k) : null; },
        setItem(k, v) { m.set(k, String(v)); },
        removeItem(k) { m.delete(k); },
        clear() { m.clear(); },
        _map: m
    };
}

// Element registry shared between Node and the VM so mutations are visible both ways.
const els = {
    prePull: makeEl({ checked: true }),
    sourceMode: makeEl({ value: 'local_ff' }),
    remoteRefPolicy: makeEl({ value: 'upstream' }),
    remoteRef: makeEl({ value: '' }),
    remoteSnapshotFields: makeEl(),
    planOnly: makeEl({ checked: false }),
    codeOnly: makeEl({ checked: false }),
    hubPath: makeEl({ value: '/hub' }),
    mergesPath: makeEl({ value: '' }),
    profile: makeEl({ value: 'max' }),
    mode: makeEl({ value: 'gesamt' }),
    maxBytes: makeEl({ value: '0' }),
    splitSize: makeEl({ value: '25MB' }),
    metaDensity: makeEl({ value: 'auto' }),
    pathFilter: makeEl({ value: '' }),
    extFilter: makeEl({ value: '' }),
    authToken: makeEl({ value: '' }),
    logs: makeEl(),
    repoList: makeEl()
};

// Controls + captures
const state = { selectedRepos: [{ value: 'repoA' }] };
const captured = {};
const alerts = [];

class FakeEventSource {
    constructor(url) { this.url = url; }
    addEventListener() {}
    close() {}
}

const localStorageMock = makeStorage({ repoground_state_version: 'test' });

const context = {
    window: {
        __REPOGROUND_UI_VERSION__: 'test',
        __prescanOpen: false,
        location: { href: 'http://localhost/', search: '', pathname: '/', reload() {} },
        history: { replaceState() {} },
        addEventListener() {},
        indexedDB: undefined
    },
    document: {
        body: { appendChild() {}, prepend() {} },
        createElement() { return makeEl(); },
        getElementById(id) {
            if (id === 'selectionPool') return null; // renderSelectionPool guards on null
            if (!els[id]) els[id] = makeEl();
            return els[id];
        },
        querySelector() { return makeEl(); },
        querySelectorAll(sel) {
            if (sel === 'input[name="repos"]:checked') return state.selectedRepos;
            return [];
        },
        addEventListener() {}
    },
    localStorage: localStorageMock,
    sessionStorage: makeStorage(),
    navigator: { serviceWorker: { getRegistrations: async () => [] } },
    console: { info() {}, warn() {}, log() {}, error: (...a) => console.error('VM ERROR:', ...a) },
    alert(msg) { alerts.push(msg); },
    setTimeout() {},
    EventSource: FakeEventSource,
    Date, Object, Array, Set, Map, JSON, URL, String, Promise, encodeURIComponent,
    materializeRawFromCompressed() {},
    normalizePath(p) { return p; },
    fetch: async (url, options = {}) => {
        if (url.includes('/api/jobs') && (options.method || 'GET') === 'POST') {
            captured.body = JSON.parse(options.body);
            return { ok: true, status: 200, json: async () => ({ id: 'job-x' }) };
        }
        if (url.includes('/api/repos')) {
            return { ok: true, status: 200, json: async () => [] };
        }
        return { ok: true, status: 200, json: async () => ({}) };
    }
};

vm.createContext(context);
vm.runInContext(appJsSrc, context);

const submitEvent = () => ({ preventDefault() {}, submitter: makeEl({ innerText: 'Start Job' }) });

async function run() {
    // 1. local_ff (default) → pre_pull true, repo_source_mode local_ff.
    els.sourceMode.value = 'local_ff';
    els.planOnly.checked = false;
    await context.startJob(submitEvent());
    assert(captured.body && captured.body.pre_pull === true, 'local_ff derives pre_pull === true');
    assert(captured.body.repo_source_mode === 'local_ff', 'local_ff sends repo_source_mode=local_ff');
    assert(captured.body.repos && captured.body.repos[0] === 'repoA', 'payload still carries the selected repo');

    // 2. Reset-after-submit restores the source mode to its default (local_ff).
    assert(els.sourceMode.value === 'local_ff', 'reset after submit restores sourceMode to local_ff');

    // 3. local_current → pre_pull false.
    captured.body = null;
    els.sourceMode.value = 'local_current';
    await context.startJob(submitEvent());
    assert(captured.body && captured.body.pre_pull === false, 'local_current derives pre_pull === false');
    assert(captured.body.repo_source_mode === 'local_current', 'local_current sends repo_source_mode=local_current');

    // 4. remote_snapshot → pre_pull false + ref policy; remote_ref sent when set.
    captured.body = null;
    els.sourceMode.value = 'remote_snapshot';
    context.syncSourceModeFields();
    els.remoteRef.value = '';
    await context.startJob(submitEvent());
    assert(captured.body && captured.body.pre_pull === false, 'remote_snapshot derives pre_pull === false');
    assert(captured.body.repo_source_mode === 'remote_snapshot', 'remote_snapshot sends repo_source_mode=remote_snapshot');
    assert(captured.body.remote_ref_policy === 'default_branch', 'remote_snapshot sends remote_ref_policy=default_branch');
    assert(!('remote_ref' in captured.body), 'remote_ref omitted when empty');

    captured.body = null;
    els.sourceMode.value = 'remote_snapshot';
    els.remoteRefPolicy.value = 'upstream';
    els.remoteRef.value = 'origin/main';
    await context.startJob(submitEvent());
    assert(captured.body.remote_ref === 'origin/main', 'remote_ref sent when set');

    // 5. Control plane: local_ff + plan-only is a conflict. The submit must be
    //    blocked (no /api/jobs request) and a visible error surfaced — never a
    //    silent coercion to local_current.
    captured.body = null;
    alerts.length = 0;
    els.sourceMode.value = 'local_ff';
    els.planOnly.checked = true;
    els.remoteRef.value = '';
    await context.startJob(submitEvent());
    assert(captured.body === null, 'local_ff + plan-only does NOT post an /api/jobs request');
    assert(alerts.length === 1 && /plan-only/i.test(alerts[0]), 'local_ff + plan-only surfaces a visible error');

    // 5b. plan-only with a non-mutating mode (local_current) still submits.
    captured.body = null;
    alerts.length = 0;
    els.sourceMode.value = 'local_current';
    els.planOnly.checked = true;
    await context.startJob(submitEvent());
    assert(captured.body && captured.body.pre_pull === false, 'plan-only + local_current posts pre_pull === false');
    assert(alerts.length === 0, 'plan-only + local_current does not raise an error');
    els.planOnly.checked = false;

    // 5c. remote_ref is blocked on a local source mode (no silent drop).
    captured.body = null;
    alerts.length = 0;
    els.sourceMode.value = 'local_current';
    els.remoteRef.value = 'origin/main';
    await context.startJob(submitEvent());
    assert(captured.body === null, 'remote_ref on a local mode does NOT post an /api/jobs request');
    assert(alerts.length === 1 && /remote_ref/i.test(alerts[0]), 'remote_ref on a local mode surfaces a visible error');
    els.remoteRef.value = '';

    // 6. Save/Load Defaults round-trips the source mode + legacy pre_pull.
    els.sourceMode.value = 'remote_snapshot';
    els.prePull.checked = false;
    context.saveConfig();
    const saved = JSON.parse(localStorageMock.getItem('repoground_config'));
    assert(saved.sourceMode === 'remote_snapshot', 'saveConfig persists sourceMode=remote_snapshot');
    assert(saved.prePull === false, 'saveConfig still persists legacy prePull=false');
    let defaults = context.getEffectiveMergeFormDefaults();
    assert(defaults.sourceMode === 'remote_snapshot', 'getEffectiveMergeFormDefaults loads sourceMode=remote_snapshot');

    // 7. Factory default sourceMode is local_ff when nothing is stored.
    localStorageMock.removeItem('repoground_config');
    defaults = context.getEffectiveMergeFormDefaults();
    assert(defaults.sourceMode === 'local_ff', 'factory default sourceMode is local_ff');
    assert(defaults.prePull === true, 'factory default prePull is true when no config stored');

    // 8. Legacy migration: a stored prePull=false (no sourceMode) maps to local_current.
    localStorageMock.setItem('repoground_config', JSON.stringify({ prePull: false }));
    defaults = context.getEffectiveMergeFormDefaults();
    assert(defaults.sourceMode === 'local_current', 'legacy prePull=false migrates to sourceMode=local_current');
    localStorageMock.removeItem('repoground_config');

    // 9. UI coupling: plan-only disables the pre_pull checkbox.
    if (typeof context.syncPrePullWithPlanOnly === 'function') {
        els.prePull.disabled = false;
        els.planOnly.checked = true;
        context.syncPrePullWithPlanOnly();
        assert(els.prePull.disabled === true, 'plan-only disables the pre_pull checkbox');
        els.planOnly.checked = false;
        context.syncPrePullWithPlanOnly();
        assert(els.prePull.disabled === false, 'clearing plan-only re-enables the pre_pull checkbox');
    } else {
        assert(false, 'syncPrePullWithPlanOnly should be defined');
    }

    // 10. UI coupling: remote-snapshot reveals the ref fields.
    if (typeof context.syncSourceModeFields === 'function') {
        let hidden = null;
        els.remoteSnapshotFields.classList = { toggle(_c, v) { hidden = v; }, add() {}, remove() {}, contains() { return false; } };
        els.sourceMode.value = 'remote_snapshot';
        context.syncSourceModeFields();
        assert(hidden === false, 'remote_snapshot reveals the remote ref fields');
        els.sourceMode.value = 'local_ff';
        context.syncSourceModeFields();
        assert(hidden === true, 'non-remote modes hide the remote ref fields');
    } else {
        assert(false, 'syncSourceModeFields should be defined');
    }

    if (failed > 0) {
        console.error(`\n${failed} test(s) failed!`);
        process.exit(1);
    }
    console.log('\nAll source-mode payload tests passed successfully!');
    process.exit(0);
}

run().catch((e) => { console.error('test crashed:', e); process.exit(1); });

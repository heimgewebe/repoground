// Tests for the "Repo vor Merge aktualisieren" (pre_pull) checkbox.
//
// Loads app.js into a VM context with a mock DOM (same approach as
// test_artifact_fallback.js) and drives the real startJob() / saveConfig() /
// getEffectiveMergeFormDefaults() code paths, asserting:
//   - the payload POSTed to /api/jobs carries pre_pull (true when checked,
//     false when unchecked),
//   - reset-after-submit restores the checkbox to checked,
//   - Save/Load Defaults round-trips the field,
//   - index.html ships the checkbox, checked by default.

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

// --- Static check: index.html ships a checked #prePull checkbox -------------
const html = fs.readFileSync(path.join(__dirname, '..', 'index.html'), 'utf8');
const inputMatch = html.match(/<input[^>]*id="prePull"[^>]*>/);
assert(!!inputMatch, 'index.html contains an input with id="prePull"');
assert(!!inputMatch && /\schecked(\s|>|=)/.test(inputMatch[0]), 'pre_pull checkbox is checked by default in index.html');

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

class FakeEventSource {
    constructor(url) { this.url = url; }
    addEventListener() {}
    close() {}
}

const localStorageMock = makeStorage({ rlens_state_version: 'test' });

const context = {
    window: {
        __RLENS_UI_VERSION__: 'test',
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
    alert() {},
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
vm.runInContext(fs.readFileSync(path.join(__dirname, '..', 'app.js'), 'utf8'), context);

const submitEvent = () => ({ preventDefault() {}, submitter: makeEl({ innerText: 'Start Job' }) });

async function run() {
    // 1. Checked → pre_pull true
    els.prePull.checked = true;
    await context.startJob(submitEvent());
    assert(captured.body && captured.body.pre_pull === true, 'commonPayload.pre_pull === true when checkbox checked');
    assert(captured.body.repos && captured.body.repos[0] === 'repoA', 'payload still carries the selected repo');

    // 2. Reset-after-submit restored the checkbox to its default (checked).
    assert(els.prePull.checked === true, 'reset after successful submit restores pre_pull to checked');

    // 3. Unchecked → pre_pull false
    captured.body = null;
    els.prePull.checked = false;
    await context.startJob(submitEvent());
    assert(captured.body && captured.body.pre_pull === false, 'commonPayload.pre_pull === false when checkbox unchecked');

    // 4. Save Defaults persists the field; Load Defaults reads it back.
    els.prePull.checked = false;
    context.saveConfig();
    const saved = JSON.parse(localStorageMock.getItem('rlens_config'));
    assert(saved.prePull === false, 'saveConfig persists prePull=false');
    let defaults = context.getEffectiveMergeFormDefaults();
    assert(defaults.prePull === false, 'getEffectiveMergeFormDefaults loads prePull=false');

    els.prePull.checked = true;
    context.saveConfig();
    defaults = context.getEffectiveMergeFormDefaults();
    assert(defaults.prePull === true, 'getEffectiveMergeFormDefaults loads prePull=true after re-save');

    // 5. Default when nothing is stored is true (factory default).
    localStorageMock.removeItem('rlens_config');
    defaults = context.getEffectiveMergeFormDefaults();
    assert(defaults.prePull === true, 'factory default prePull is true when no config stored');

    // 6. plan-only forces effective pre_pull === false even if checkbox is checked.
    captured.body = null;
    els.planOnly.checked = true;
    els.prePull.checked = true;
    await context.startJob(submitEvent());
    assert(captured.body && captured.body.pre_pull === false, 'plan-only forces pre_pull === false in payload');
    els.planOnly.checked = false;

    // 7. UI coupling: syncPrePullWithPlanOnly disables the checkbox under plan-only.
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

    if (failed > 0) {
        console.error(`\n${failed} test(s) failed!`);
        process.exit(1);
    }
    console.log('\nAll pre_pull payload tests passed successfully!');
    process.exit(0);
}

run().catch((e) => { console.error('test crashed:', e); process.exit(1); });

const fs = require('fs');
const path = require('path');
const vm = require('vm');

let failed = 0;

function assert(condition, message) {
    if (!condition) {
        console.error(`FAIL: ${message}`);
        failed++;
    } else {
        console.log(`PASS: ${message}`);
    }
}

function makeStorage(seed = {}) {
    const map = new Map(Object.entries(seed));
    return {
        getItem(key) { return map.has(key) ? map.get(key) : null; },
        setItem(key, value) { map.set(key, String(value)); },
        removeItem(key) { map.delete(key); },
        clear() { map.clear(); },
    };
}

function makeEl(overrides = {}) {
    const classes = new Set((overrides.className || '').split(/\s+/).filter(Boolean));
    return Object.assign({
        value: '',
        checked: false,
        disabled: false,
        innerText: '',
        textContent: '',
        dataset: {},
        style: {},
        children: [],
        classList: {
            add(name) { classes.add(name); },
            remove(name) { classes.delete(name); },
            contains(name) { return classes.has(name); },
            toggle(name, force) {
                if (force === undefined) {
                    if (classes.has(name)) classes.delete(name);
                    else classes.add(name);
                    return;
                }
                if (force) classes.add(name);
                else classes.delete(name);
            },
        },
        appendChild(child) { this.children.push(child); },
        removeChild() {},
        addEventListener() {},
        querySelector() { return null; },
        querySelectorAll() { return []; },
    }, overrides);
}

function makeResponse(status, payload) {
    return {
        ok: status >= 200 && status < 300,
        status,
        async json() { return payload; },
    };
}

const html = fs.readFileSync(path.join(__dirname, '..', 'index.html'), 'utf8');
assert(
    html.includes('Browser hard refresh only — does not restart RepoGround service'),
    'hard refresh button title explicitly says it does not restart RepoGround'
);
assert(
    html.includes('id="restartServiceBtn"') && html.includes('Restart RepoGround'),
    'index.html contains a separate Restart RepoGround admin button'
);
assert(
    html.includes('onclick="hardRefresh()"') && html.includes('onclick="restartService()"'),
    'hard refresh and service restart are separate controls'
);

const appJsSrc = fs.readFileSync(path.join(__dirname, '..', 'app.js'), 'utf8');

function createContext(options = {}) {
    const fetchLog = [];
    const notifications = [];
    let confirmMessage = null;
    let fetchImpl = async () => makeResponse(404, {});

    const elements = {
        authToken: makeEl({ value: 'test-token' }),
        status: makeEl(),
        restartServiceBtn: makeEl({ textContent: 'Restart RepoGround', className: 'hidden' }),
        hubPath: makeEl({ value: '/hub' }),
        logs: makeEl(),
        repoList: makeEl(),
        prePull: makeEl({ checked: true }),
        sourceMode: makeEl({ value: 'local_ff' }),
        remoteRefPolicy: makeEl({ value: 'default_branch' }),
        remoteRef: makeEl({ value: '' }),
        planOnly: makeEl({ checked: false }),
        codeOnly: makeEl({ checked: false }),
        profile: makeEl({ value: 'max' }),
        mode: makeEl({ value: 'gesamt' }),
        splitSize: makeEl({ value: '25MB' }),
        maxBytes: makeEl({ value: '0' }),
        metaDensity: makeEl({ value: 'auto' }),
        pathFilter: makeEl({ value: '' }),
        extFilter: makeEl({ value: '' }),
        verLabel: makeEl(),
        originLabel: makeEl(),
    };

    if (Object.prototype.hasOwnProperty.call(options, 'statusElement')) {
        elements.status = options.statusElement;
    }

    const context = {
        window: {
            __RLENS_UI_VERSION__: 'test',
            location: { href: 'http://localhost/', host: 'localhost', search: '', pathname: '/', replace() {}, reload() {} },
            history: { replaceState() {} },
            addEventListener() {},
            __prescanOpen: false,
            indexedDB: undefined,
        },
        document: {
            body: { appendChild() {}, removeChild() {}, prepend() {} },
            createElement() { return makeEl(); },
            getElementById(id) {
                if (options.nullElementIds && options.nullElementIds.has(id)) {
                    return null;
                }
                if (!elements[id]) elements[id] = makeEl();
                return elements[id];
            },
            querySelector() { return null; },
            querySelectorAll() { return []; },
            addEventListener() {},
        },
        localStorage: makeStorage({ repoground_state_version: 'test' }),
        sessionStorage: makeStorage(),
        navigator: { serviceWorker: { getRegistrations: async () => [] } },
        console: { info() {}, warn() {}, log() {}, error() {} },
        materializeRawFromCompressed() {},
        normalizePath(value) { return value; },
        fetch: async (url, options = {}) => {
            fetchLog.push({ url, options });
            return fetchImpl(url, options);
        },
        confirm(message) {
            confirmMessage = message;
            return true;
        },
        setTimeout(fn) {
            if (typeof fn === 'function') fn();
            return 0;
        },
        clearTimeout() {},
        URL,
        Promise,
        Date,
        Map,
        Set,
        JSON,
    };

    vm.createContext(context);
    vm.runInContext(appJsSrc, context);

    context.showNotification = (message, type) => notifications.push({ message, type });

    return {
        context,
        elements,
        notifications,
        fetchLog,
        setFetchImpl(fn) { fetchImpl = fn; },
        getConfirmMessage() { return confirmMessage; },
    };
}

async function run() {
    {
        const ctx = createContext();
        ctx.context.confirm = (message) => {
            ctx.confirmMessage = message;
            return false;
        };
        await ctx.context.hardRefresh();
        assert(
            ctx.confirmMessage === 'Clear browser cache/storage and reload the UI? This does not restart the RepoGround service.',
            'hardRefresh confirm text explicitly excludes service restart'
        );
    }

    {
        const ctx = createContext();
        ctx.setFetchImpl(async (url) => {
            if (url.includes('/api/admin/capabilities')) {
                return makeResponse(200, { service_restart_enabled: true });
            }
            return makeResponse(404, {});
        });
        await ctx.context.fetchAdminCapabilities();
        assert(!ctx.elements.restartServiceBtn.classList.contains('hidden'), 'restart button is shown when backend capability is enabled');
        assert(ctx.elements.restartServiceBtn.disabled === false, 'restart button is enabled when capability is true');
    }

    {
        const ctx = createContext();
        let versionCalls = 0;
        ctx.setFetchImpl(async (url) => {
            if (url.includes('/api/version')) {
                versionCalls += 1;
                return makeResponse(200, { version: 'abc', build_id: 'abc', started_at: 'after' });
            }
            return makeResponse(404, {});
        });

        const restarted = await ctx.context.waitForServiceRestart(null, 1, 0, 0);

        assert(restarted === false, 'waitForServiceRestart(null, ...) does not report a successful restart');
        assert(versionCalls === 0, 'waitForServiceRestart(null, ...) returns before polling');
    }

    {
        const ctx = createContext();
        const observed = {};
        ctx.setFetchImpl(async (url, options = {}) => {
            if (url.includes('/api/admin/capabilities')) {
                return makeResponse(200, { service_restart_enabled: true });
            }
            if (url.includes('/api/version')) {
                return makeResponse(200, { version: 'abc', build_id: 'abc', started_at: 'before' });
            }
            if (url.includes('/api/admin/restart')) {
                observed.method = options.method || 'GET';
                return makeResponse(202, { status: 'scheduled' });
            }
            return makeResponse(404, {});
        });
        await ctx.context.fetchAdminCapabilities();
        ctx.context.waitForServiceRestart = async (startedAt) => {
            observed.startedAt = startedAt;
            return true;
        };
        ctx.context.fetchVersion = async () => {
            observed.fetchVersionCalled = true;
            return { started_at: 'after' };
        };
        ctx.context.fetchHealth = async () => {
            observed.fetchHealthCalled = true;
            return '/hub';
        };
        ctx.context.fetchRepos = (hub) => {
            observed.fetchReposHub = hub;
        };
        ctx.context.loadArtifacts = () => {
            observed.loadArtifactsCalled = true;
        };

        await ctx.context.restartService();

        assert(observed.method === 'POST', 'restart button posts to /api/admin/restart');
        assert(ctx.elements.status.innerText === 'Restart scheduled. Reconnecting...', '202 response moves the UI into reconnect state');
        assert(observed.startedAt === 'before', 'restart reconnect waits for a newer server start timestamp');
        assert(observed.fetchVersionCalled === true, 'restart success refreshes version info');
        assert(observed.fetchHealthCalled === true, 'restart success refreshes health info');
        assert(observed.loadArtifactsCalled === true, 'restart success reloads artifacts');
    }

    {
        const ctx = createContext();
        const observed = { method: null };
        ctx.setFetchImpl(async (url, options = {}) => {
            if (url.includes('/api/admin/capabilities')) {
                return makeResponse(200, { service_restart_enabled: true });
            }
            if (url.includes('/api/version')) {
                return makeResponse(200, { version: 'abc', build_id: 'abc' });
            }
            if (url.includes('/api/admin/restart')) {
                observed.method = options.method || 'GET';
                return makeResponse(202, { status: 'scheduled' });
            }
            return makeResponse(404, {});
        });
        await ctx.context.fetchAdminCapabilities();
        await ctx.context.restartService();

        assert(observed.method === null, 'restartService without started_at does not post /api/admin/restart');
        assert(
            ctx.notifications.some(n => n.message.includes('did not provide started_at') && n.type === 'error'),
            'restartService without started_at surfaces a verification error'
        );
        assert(ctx.elements.restartServiceBtn.textContent === 'Restart RepoGround', 'restart button text is restored after verification failure');
        assert(ctx.elements.restartServiceBtn.disabled === false, 'restart button is re-enabled after verification failure');
    }

    {
        const ctx = createContext();
        ctx.setFetchImpl(async (url) => {
            if (url.includes('/api/admin/capabilities')) {
                return makeResponse(200, { service_restart_enabled: true });
            }
            if (url.includes('/api/version')) {
                return makeResponse(200, { version: 'abc', build_id: 'abc', started_at: 'before' });
            }
            if (url.includes('/api/admin/restart')) {
                return makeResponse(403, { detail: 'Service restart is disabled' });
            }
            return makeResponse(404, {});
        });
        await ctx.context.fetchAdminCapabilities();
        await ctx.context.restartService();
        assert(
            ctx.notifications.some(n => n.message.includes('disabled on this host') && n.type === 'warning'),
            '403 restart response is surfaced as a disabled warning'
        );
    }

    {
        const ctx = createContext();
        ctx.setFetchImpl(async (url) => {
            if (url.includes('/api/admin/capabilities')) {
                return makeResponse(200, { service_restart_enabled: true });
            }
            if (url.includes('/api/version')) {
                return makeResponse(200, { version: 'abc', build_id: 'abc', started_at: 'before' });
            }
            if (url.includes('/api/admin/restart')) {
                return makeResponse(409, { status: 'blocked', reason: 'jobs_running' });
            }
            return makeResponse(404, {});
        });
        await ctx.context.fetchAdminCapabilities();
        await ctx.context.restartService();
        assert(
            ctx.notifications.some(n => n.message.includes('jobs are still running') && n.type === 'warning'),
            '409 restart response is surfaced as a jobs-running warning'
        );
    }

    {
        const ctx = createContext({ nullElementIds: new Set(['status']) });
        const observed = {};
        ctx.setFetchImpl(async (url, options = {}) => {
            if (url.includes('/api/admin/capabilities')) {
                return makeResponse(200, { service_restart_enabled: true });
            }
            if (url.includes('/api/version')) {
                return makeResponse(200, { version: 'abc', build_id: 'abc', started_at: 'before' });
            }
            if (url.includes('/api/admin/restart')) {
                observed.method = options.method || 'GET';
                return makeResponse(202, { status: 'scheduled' });
            }
            return makeResponse(404, {});
        });
        await ctx.context.fetchAdminCapabilities();
        ctx.context.waitForServiceRestart = async (startedAt) => {
            observed.startedAt = startedAt;
            return true;
        };
        ctx.context.fetchVersion = async () => {
            observed.fetchVersionCalled = true;
            return { started_at: 'after' };
        };
        ctx.context.fetchHealth = async () => {
            observed.fetchHealthCalled = true;
            return '/hub';
        };
        ctx.context.fetchRepos = () => {
            observed.fetchReposCalled = true;
        };
        ctx.context.loadArtifacts = () => {
            observed.loadArtifactsCalled = true;
        };

        await ctx.context.restartService();

        assert(observed.method === 'POST', 'missing status element does not block restart POST');
        assert(observed.startedAt === 'before', 'missing status element still passes the previous started_at into polling');
        assert(observed.fetchVersionCalled === true, 'missing status element still allows restart success flow');
        assert(observed.loadArtifactsCalled === true, 'missing status element still reaches artifact reload');
    }

    if (failed > 0) {
        console.error(`\n${failed} test(s) failed.`);
        process.exit(1);
    }

    console.log('\nAll admin restart button tests passed.');
}

run().catch((error) => {
    console.error('test crashed:', error);
    process.exit(1);
});

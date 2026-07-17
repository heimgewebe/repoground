const fs = require('fs');
const path = require('path');
const vm = require('vm');

const code = fs.readFileSync(path.join(__dirname, '..', 'app.js'), 'utf8');

global.artifactListEl = {
    innerHTML: '',
    children: [],
    appendChild: function(c) { this.children.push(c); },
    querySelectorAll: function() { return []; }
};

const context = {
    window: {
        __RLENS_UI_VERSION__: 'test',
        location: { href: 'http://localhost' },
        addEventListener: () => {}
    },
    document: {
        body: { appendChild: () => {}, prepend: () => {} },
        createElement: (tag) => {
            const el = {
                tagName: tag,
                className: '',
                dataset: {},
                children: [],
                textContent: '',
                appendChild: function(c) { this.children.push(c); },
                addEventListener: () => {},
                querySelectorAll: () => [],
                querySelector: function(selector) {
                    if (selector === '.links-container' && this.className.includes('links-container')) {
                        return this;
                    }
                    for (const child of this.children) {
                        if (child.className && child.className.includes('links-container') && selector === '.links-container') {
                            return child;
                        }
                    }
                    return null;
                }
            };
            Object.defineProperty(el, 'innerHTML', {
                set: function(val) {
                    this._innerHTML = val;
                    // very naive parser to mock the links-container for querySelector
                    if (val.includes('links-container')) {
                        const linksContainer = context.document.createElement('div');
                        linksContainer.className = 'links-container flex flex-wrap gap-2 text-xs mt-1';
                        this.children.push(linksContainer);
                    }
                },
                get: function() {
                    return this._innerHTML || '';
                }
            });
            Object.defineProperty(el, 'outerHTML', {
                get: function() {
                    const attrs = Object.entries(this.dataset).map(([k, v]) => `data-${k}="${String(v).replace(/"/g, '&quot;')}"`).join(' ');
                    // Important: Simulate the browser's DOM escaping for textContent
                    const text = (this.textContent || '')
                        .replace(/&/g, '&amp;')
                        .replace(/</g, '&lt;')
                        .replace(/>/g, '&gt;');

                    let inner = text;
                    if (this.children.length > 0) {
                         inner += this.children.map(c => c.outerHTML).join('');
                    }

                    return `<${this.tagName} class="${this.className}" ${attrs}>${inner}</${this.tagName}>`;
                }
            });
            return el;
        },
        getElementById: (id) => {
            if (id === 'artifactList') return global.artifactListEl;
            if (id === 'authToken') return { value: '' };
            return { value: '', innerText: '', addEventListener: () => {} };
        },
        querySelectorAll: () => [],
        addEventListener: () => {}
    },
    localStorage: {
        getItem: (key) => key === 'rlens_state_version' ? 'test' : null,
        setItem: () => {},
        clear: () => {}
    },
    sessionStorage: {
        getItem: (key) => key === 'rlens_state_version' ? 'test' : null,
        setItem: () => {},
        clear: () => {}
    },
    navigator: { serviceWorker: { getRegistrations: async () => [] } },
    console: {
        info: () => {},
        warn: () => {},
        error: (...args) => console.error("VM ERROR:", ...args),
        log: (...args) => console.log("VM LOG:", ...args)
    },
    alert: () => {},
    setTimeout: () => {},
    Date: Date,
    Object: Object,
    Array: Array,
    Set: Set,
    Map: Map,
    JSON: JSON,
    URL: URL,
    String: String,
    Promise: Promise,
    encodeURIComponent: encodeURIComponent,
    materializeRawFromCompressed: () => {},
    normalizePath: () => {},
    fetch: async (url, options) => {
        if (url.includes('/api/artifacts')) {
            return {
                ok: true, status: 200, json: async () => [{
                    id: '1', created_at: new Date().toISOString(), repos: ['repo1'], params: { level: 'l', mode: 'm' },
                    paths: {
                        json: 'a.json',
                        md: 'a.md',
                        chunk_index: 'chunk.json',
                        foo_bar: 'b.bin',
                        custom_bundle_x: 'c.zip',
                        '<script>alert(1)</script>': 'malicious.bin',
                        'foo&bar': 'amp.bin',
                        'foo"bar': 'quote.bin',
                        "foo'bar": 'squote.bin'
                    }
                }]
            };
        }
        return { ok: true, status: 200, json: async () => ({}) };
    }
};

vm.createContext(context);

vm.runInContext(code, context);

async function runTest() {
    // 1. Test unit function formatArtifactFallbackLabel directly
    if (typeof context.formatArtifactFallbackLabel !== 'function') {
        console.error("FAIL: formatArtifactFallbackLabel is not defined in context");
        process.exit(1);
    }

    const t1 = context.formatArtifactFallbackLabel('foo_bar_baz');
    if (t1 !== 'Foo bar baz') {
        console.error("FAIL: expected 'Foo bar baz', got", t1);
        process.exit(1);
    }

    console.log("PASS: formatArtifactFallbackLabel unit checks");

    // 2. Test UI behavior
    await context.loadArtifacts();

    if (global.artifactListEl.children.length === 0) {
        console.error("FAIL: No children added to artifact list");
        process.exit(1);
    }

    const containerDiv = global.artifactListEl.children[0];
    const linksContainer = containerDiv.children.find(c => c.className.includes('links-container'));

    if (!linksContainer) {
         console.error("FAIL: Links container not found");
         process.exit(1);
    }

    const html = linksContainer.outerHTML;

    if (!html.includes('data-dl="/api/artifacts/1/download?key=foo_bar"')) {
        console.error("FAIL: Should render foo_bar button correctly in links container");
        process.exit(1);
    }

    // Check escaping logic in mock
    if (html.includes('<script>')) {
        console.error("FAIL: Unescaped malicious key found in HTML!");
        console.error(html);
        process.exit(1);
    }

    // Check ampersand
    if (html.includes('data-dl="/api/artifacts/1/download?key=foo%26bar"')) {
        // It correctly URI encoded the key
    } else {
         console.error("FAIL: Ampersand key not correctly rendered");
         process.exit(1);
    }

    // Check quotes
    if (html.includes('data-dl="/api/artifacts/1/download?key=foo%22bar"')) {
        // Correct
    } else {
         console.error("FAIL: Double quote key not correctly rendered");
         process.exit(1);
    }

    // Check single quotes
    if (html.includes('data-dl="/api/artifacts/1/download?key=foo\'bar"')) {
        // Correct (encodeURIComponent does not encode single quotes natively, so it stays raw or is structurally fine since HTML attributes are wrapped in double quotes)
    } else {
         console.error("FAIL: Single quote key not correctly rendered in URL");
         console.error(html);
         process.exit(1);
    }

    // Check script tags (angle brackets) in URL
    if (html.includes('data-dl="/api/artifacts/1/download?key=%3Cscript%3Ealert(1)%3C%2Fscript%3E"')) {
        // Correctly encoded
    } else {
         console.error("FAIL: Script tag key not correctly encoded in URL");
         process.exit(1);
    }

    console.log("PASS: loadArtifacts fallback rendering works perfectly and safely!");
    process.exit(0);
}

runTest().catch(e => {
    console.error("test failed:", e);
    process.exit(1);
});

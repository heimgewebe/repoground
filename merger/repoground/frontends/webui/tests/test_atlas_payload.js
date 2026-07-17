const { buildAtlasPayload } = require('../atlas_payload.js');

let failed = 0;

function assert(condition, message) {
    if (!condition) {
        console.error("FAIL: " + message);
        failed++;
    } else {
        console.log("PASS: " + message);
    }
}

// Test 1: "hub" without token
let payload = buildAtlasPayload("hub", undefined, "6", "200000", "");
assert(payload.root_kind === "preset", "root_kind should be 'preset'");
assert(payload.root_value === "hub", "root_value should be 'hub'");
assert(payload.root_token === null, "root_token should be null");

// Test 2: "HUB " (case insensitive and trim)
payload = buildAtlasPayload("HUB ", null, 6, 200000, "");
assert(payload.root_kind === "preset", "root_kind should be 'preset' after trim and lowercase");
assert(payload.root_value === "hub", "root_value should be 'hub'");

// Test 3: "home" without leading slash is considered invalid manual text
payload = buildAtlasPayload("home", null, 6, 200000, "");
assert(payload.root_kind === "invalid", "root_kind should be 'invalid' for unknown non-absolute text");
assert(payload.root_value === "home", "root_value should be 'home'");

// Test 4: absolute path "/home" maps to abs_path
payload = buildAtlasPayload("/home", null, 6, 200000, "");
assert(payload.root_kind === "abs_path", "root_kind should be 'abs_path' for absolute paths");
assert(payload.root_value === "/home", "root_value should be '/home'");

// Test 5: raw path with token (picker)
payload = buildAtlasPayload("/path/to/my/folder", "abc-123-token", 6, 200000, "");
assert(payload.root_kind === "token", "root_kind should be 'token' for picker paths");
assert(payload.root_value === null, "root_value should be null for token");
assert(payload.root_token === "abc-123-token", "root_token should be preserved");

// Test 6: raw path without token (manual typing supported as abs_path)
payload = buildAtlasPayload("/path/to/my/folder", null, 6, 200000, "");
assert(payload.root_kind === "abs_path", "root_kind should be 'abs_path' for manual absolute paths");
assert(payload.root_value === "/path/to/my/folder", "root_value should be the path");
assert(payload.root_token === null, "root_token should be null");

// Test 6: limit and depth parses correctly
payload = buildAtlasPayload("hub", null, "10", "50000", "glob1, glob2");
assert(payload.max_depth === 10, "max_depth parsed correctly");
assert(payload.max_entries === 50000, "max_entries parsed correctly");
assert(payload.exclude_globs.length === 2, "exclude_globs parsed correctly");
assert(payload.exclude_globs[0] === "glob1" && payload.exclude_globs[1] === "glob2", "exclude_globs trimmed correctly");
assert(payload.inventory_strict === true, "inventory_strict should be true");
assert(payload.scan_mode === "inventory", "scan_mode defaults to inventory");

// Test 7: scan_mode passes through
payload = buildAtlasPayload("hub", null, "10", "50000", "", "workspace");
assert(payload.scan_mode === "workspace", "scan_mode correctly assigned to workspace");

if (failed > 0) {
    console.error(`\n${failed} tests failed!`);
    process.exit(1);
} else {
    console.log(`\nAll tests passed successfully!`);
}

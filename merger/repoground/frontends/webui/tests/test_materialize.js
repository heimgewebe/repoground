
const assert = require('assert');
// Static require - much cleaner!
const { materializeRawFromCompressed } = require('../materialize.js');

// --- Tests ---

console.log("Running materializeRawFromCompressed tests...");

const tree = {
    path: 'src/utils',
    type: 'dir',
    children: [
        { path: 'src/utils/a.js', type: 'file' },
        { path: 'src/utils/b.js', type: 'file' },
        { path: 'src/utils/sub', type: 'dir', children: [
             { path: 'src/utils/sub/c.js', type: 'file' },
        ]},
    ],
};

// Helper for assertions
function assertSetEqual(actualSet, expectedArray, message) {
    const actual = Array.from(actualSet).sort();
    const expected = expectedArray.sort();
    assert.deepStrictEqual(actual, expected, message);
    console.log(`[PASS] ${message}`);
}

try {
    // 1. Subtree Root Implicit Include
    // compressedSet = ['src'] -> should include all files under src/utils
    assertSetEqual(
        materializeRawFromCompressed(tree, new Set(['src'])),
        ['src/utils/a.js', 'src/utils/b.js', 'src/utils/sub/c.js'],
        "Subtree Root Implicit Include"
    );

    // 2. Directory Rule Include
    // compressedSet = ['src/utils'] -> should include all files
    assertSetEqual(
        materializeRawFromCompressed(tree, new Set(['src/utils'])),
        ['src/utils/a.js', 'src/utils/b.js', 'src/utils/sub/c.js'],
        "Directory Rule Include"
    );

    // 3. File Rule Only
    // compressedSet = ['src/utils/a.js'] -> only a.js
    assertSetEqual(
        materializeRawFromCompressed(tree, new Set(['src/utils/a.js'])),
        ['src/utils/a.js'],
        "File Rule Only"
    );

    // 4. Mixed Rule
    // compressedSet = ['src/utils/sub', 'src/utils/a.js'] -> a.js and c.js (from sub)
    assertSetEqual(
        materializeRawFromCompressed(tree, new Set(['src/utils/sub', 'src/utils/a.js'])),
        ['src/utils/a.js', 'src/utils/sub/c.js'],
        "Mixed Rule (File + Subdir)"
    );

    // 5. Trailing Slash Robustness (Normalized Internally)
    // compressedSet = ['src/'] -> should be treated same as 'src'
    assertSetEqual(
        materializeRawFromCompressed(tree, new Set(['src/'])),
        ['src/utils/a.js', 'src/utils/b.js', 'src/utils/sub/c.js'],
        "Trailing Slash Robustness (src/ -> src)"
    );

    // 6. Explicit Subdir Slash
    // compressedSet = ['src/utils/'] -> should match 'src/utils'
    assertSetEqual(
        materializeRawFromCompressed(tree, new Set(['src/utils/'])),
        ['src/utils/a.js', 'src/utils/b.js', 'src/utils/sub/c.js'],
        "Trailing Slash Robustness (src/utils/ -> src/utils)"
    );

    // 7. Empty Set
    assertSetEqual(
        materializeRawFromCompressed(tree, new Set([])),
        [],
        "Empty Set"
    );

    // 8. Backslash Normalization
    // compressedSet = ['src\\utils\\a.js'] -> should match 'src/utils/a.js'
    assertSetEqual(
        materializeRawFromCompressed(tree, new Set(['src\\utils\\a.js'])),
        ['src/utils/a.js'],
        "Backslash Normalization (src\\utils\\a.js -> src/utils/a.js)"
    );

    // 9. Traversal Rejection
    // compressedSet = ['../secret'] -> should be ignored (null)
    assertSetEqual(
        materializeRawFromCompressed(tree, new Set(['../secret'])),
        [],
        "Traversal Rejection (../secret -> null)"
    );

    // 10. Multiple Slash Collapse
    // compressedSet = ['src//utils'] -> should match 'src/utils'
    assertSetEqual(
        materializeRawFromCompressed(tree, new Set(['src//utils'])),
        ['src/utils/a.js', 'src/utils/b.js', 'src/utils/sub/c.js'],
        "Multiple Slash Collapse (src//utils -> src/utils)"
    );

} catch (e) {
    console.error("Test Failed:", e);
    process.exit(1);
}

console.log("All tests passed.");

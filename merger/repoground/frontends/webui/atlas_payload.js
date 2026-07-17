/**
 * Utility for building the Atlas API payload.
 * Isolated here for safer testability without DOM dependencies.
 */

function buildAtlasPayload(rootPath, rootToken, depth, limit, excludes, scanMode = 'inventory') {
    let payloadToken = rootToken || null;
    let payloadValue = null;
    let rootKind = "abs_path";

    const cleanPath = (rootPath || "").trim();
    const lower = cleanPath.toLowerCase();

    if (['hub', 'merges', 'system'].includes(lower)) {
        rootKind = "preset";
        payloadValue = lower;
        payloadToken = null; // Presets ignore tokens
    } else if (payloadToken) {
        rootKind = "token";
        // payloadToken is already set
        payloadValue = null; // Use token only
    } else if (cleanPath.startsWith('/') || /^[a-zA-Z]:[\\/]/.test(cleanPath)) {
        rootKind = "abs_path";
        payloadValue = cleanPath;
        payloadToken = null;
    } else {
        // Purely frontend UI state. The API does not accept "invalid".
        // The app.js layer must catch this and display a user error before submitting.
        rootKind = "invalid";
        payloadValue = cleanPath;
        payloadToken = null;
    }

    return {
        root_kind: rootKind,
        root_value: payloadValue,
        root_token: payloadToken,
        max_depth: parseInt(depth, 10) || 6,
        max_entries: parseInt(limit, 10) || 200000,
        exclude_globs: excludes ? excludes.split(',').map(s => s.trim()).filter(Boolean) : [],
        inventory_strict: true,
        scan_mode: scanMode
    };
}

// Export for Node.js test environment
if (typeof module !== 'undefined' && module.exports) {
    module.exports = { buildAtlasPayload };
}

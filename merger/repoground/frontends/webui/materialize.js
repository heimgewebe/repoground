// RepoGround materialization logic
// Shared logic for both Node.js tests and Browser runtime (UMD-like pattern)

(function(root, factory) {
    if (typeof module === 'object' && module.exports) {
        // Node.js
        module.exports = factory();
    } else {
        // Browser globals
        const exported = factory();
        root.normalizePath = exported.normalizePath;
        root.materializeRawFromCompressed = exported.materializeRawFromCompressed;
    }
}(typeof self !== 'undefined' ? self : this, function() {

    function normalizePath(p) {
        // Return null for invalid input.
        // Empty string becomes "." (current directory/root of tree).
        if (typeof p !== 'string') return null;

        p = p.trim();

        // Normalize backslashes
        p = p.replace(/\\/g, '/');
        // Collapse multiple slashes
        p = p.replace(/\/{2,}/g, '/');

        // Absolute root protection
        if (p === "/") return "/";

        // Security: Reject traversal
        if (p === '..' || p.startsWith('../') || p.includes('/../') || p.endsWith('/..')) {
            return null;
        }

        if (p.startsWith("./")) {
            p = p.substring(2);
        }

        // Remove trailing slash only if not root "/" (guarded above)
        if (p.length > 1 && p.endsWith("/")) {
            p = p.substring(0, p.length - 1);
        }

        if (p === "") return ".";
        return p;
    }

    // Materialize raw file paths from tree using compressed rules
    // This reconstructs the UI truth from compressed backend rules
    // OPTIMIZED: Uses state propagation (parentIncluded) to avoid O(n*m) prefix scans.
    // ROBUSTNESS: Normalizes compressedSet entries to handle trailing slashes gracefully.
    function materializeRawFromCompressed(treeNode, compressedSet) {
        const paths = new Set();

        // Normalize the set once to ensure consistency (O(m))
        // Handles trailing slashes (e.g., "src/" -> "src")
        const normalizedSet = new Set();
        for (const entry of compressedSet) {
            const norm = normalizePath(entry);
            if (norm) normalizedSet.add(norm);
        }

        // Check if the root itself is implicitly included by an ancestor in compressedSet
        // This handles cases where treeNode is a subtree (e.g. 'src/utils') but compressedSet contains a parent (e.g. 'src')
        // This is the only O(m) check needed, and it's done once per call.
        let rootImplicitlyIncluded = false;
        const rootPath = normalizePath(treeNode.path);

        if (rootPath && !normalizedSet.has(rootPath)) {
             for (const compressedPath of normalizedSet) {
                 if (rootPath.startsWith(compressedPath + '/')) {
                     rootImplicitlyIncluded = true;
                     break;
                 }
             }
        }

        function visit(node, parentIncluded) {
            const normalizedPath = normalizePath(node.path);
            if (!normalizedPath) return;

            let included = parentIncluded;

            // If not inherited from parent, check if this specific node is selected
            if (!included && normalizedSet.has(normalizedPath)) {
                included = true;
            }

            if (node.type === 'file') {
                if (included) {
                    paths.add(normalizedPath);
                }
            } else if (node.children) {
                // Recurse for directories
                node.children.forEach(child => visit(child, included));
            }
        }

        visit(treeNode, rootImplicitlyIncluded);
        return paths;
    }

    return {
        normalizePath: normalizePath,
        materializeRawFromCompressed: materializeRawFromCompressed
    };
}));

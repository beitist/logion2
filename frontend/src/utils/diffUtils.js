import DiffMatchPatch from 'diff-match-patch';

/**
 * Escapes HTML special characters to prevent XSS in rendered diff output.
 */
function escapeHtml(text) {
    return text
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;');
}

/**
 * Creates an inline word-level diff as HTML between original and final text.
 *
 * Deleted words: red + strikethrough
 * Inserted words: green + underlined
 * Unchanged: plain text
 *
 * @param {string} originalText - Text before changes (plain, no tags)
 * @param {string} finalText - Text after changes (plain, no tags)
 * @returns {string|null} HTML diff string, or null if texts are identical
 */
export function createInlineDiff(originalText, finalText) {
    if (!originalText && !finalText) return null;
    if (originalText === finalText) return null;

    const dmp = new DiffMatchPatch();
    const diffs = dmp.diff_main(originalText || '', finalText || '');
    dmp.diff_cleanupSemantic(diffs);

    let html = '';
    for (const [op, text] of diffs) {
        const escaped = escapeHtml(text);
        if (op === -1) {
            // Deletion (was in original, not in final)
            html += `<span class="tc-deleted">${escaped}</span>`;
        } else if (op === 1) {
            // Insertion (not in original, is in final)
            html += `<span class="tc-inserted">${escaped}</span>`;
        } else {
            // Unchanged
            html += escaped;
        }
    }
    return html;
}

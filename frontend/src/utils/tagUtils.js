
/**
 * Utility functions for Tag Management in TiptapEditor and SplitView.
 * Centralizes logic for "Combo Tags" (Merging adjacent tags) and Label Formatting.
 */

/**
 * Generates a human-readable label for a tag ID sequence.
 * Handles single IDs ("1") and ranges ("1,2,3" -> "1-3").
 * @param {string} idString - Comma-separated IDs (e.g. "1" or "1,2,3")
 * @returns {string} - Short label (e.g. "1" or "1-3")
 */
export const getTagLabel = (idString) => {
    if (!idString) return "?";

    // Check for comma
    if (!String(idString).includes(',')) {
        return String(idString);
    }

    const parts = String(idString).split(',').map(s => s.trim()).filter(s => s);
    if (parts.length === 0) return "";
    if (parts.length === 1) return parts[0];

    // Range Logic: First-Last
    // We assume the sequence reflects the order.
    // "1,2,3" -> "1-3"
    // "3,2,1" -> "3-1" (for end tags)
    return `${parts[0]}-${parts[parts.length - 1]}`;
};

/**
 * Merges adjacent tag spans in the hydrated HTML.
 * Used by both TiptapEditor (hydrateContent) and SplitView (formatSourceContent).
 * 
 * Replaces:
 * <span ... data-id="1"></span><span ... data-id="2"></span>
 * With:
 * <span ... data-id="1,2"></span>
 * 
 * @param {string} html - The HTML string with individual tag spans.
 * @returns {string} - HTML with merged spans.
 */
export const mergeAdjacentTags = (html) => {
    let merged = html;
    let hasChanges = true;

    // Regex Explanation:
    // Matches two adjacent <span data-type="tag-node"> elements.
    // Captures ID and Label from both.
    const regex = /<span data-type="tag-node" data-id="([^"]+)" data-label="[^"]+"><\/span>(?:<span class="[^"]+"><\/span>)?<span data-type="tag-node" data-id="([^"]+)" data-label="[^"]+"><\/span>/g;
    // Note: The middle (?:...) handles potential invisible characters if any? 
    // Actually, stick to strict adjacency for now like previous logic.

    // Strict Regex used previously:
    const strictRegex = /<span data-type="tag-node" data-id="([^"]+)" data-label="([^"]+)"><\/span>(<span data-type="tag-node" data-id="([^"]+)" data-label="([^"]+)"><\/span>)/g;

    while (hasChanges) {
        hasChanges = false;
        merged = merged.replace(strictRegex, (match, id1, label1, secondSpan, id2, label2) => {
            hasChanges = true;
            const newId = `${id1},${id2}`;
            // We don't calculate label here, renderer does it. But we must put something.
            // We put newId as label placeholder, the Renderer calls getTagLabel(id).
            // Actually Tiptap stores label in attrs.
            const newLabel = getTagLabel(newId);
            return `<span data-type="tag-node" data-id="${newId}" data-label="${newLabel}"></span>`;
        });
    }
    return merged;
};

/**
 * Merges adjacent XML-like tags for the Static View (Sidebar).
 * Replaces <1><2> with <1,2>.
 * @param {string} text 
 * @returns {string}
 */
export const mergeXmlTags = (text) => {
    let formatted = text;
    let mergeChanged = true;
    while (mergeChanged) {
        mergeChanged = false;
        // Start Tags
        formatted = formatted.replace(/<(\d+)>(?:\s*)<(\d+)>/g, (m, id1, id2) => {
            mergeChanged = true;
            return `<${id1},${id2}>`;
        });
        // End Tags
        formatted = formatted.replace(/<\/(\d+)>(?:\s*)<\/(\d+)>/g, (m, id1, id2) => {
            mergeChanged = true;
            return `</${id1},${id2}>`;
        });
    }
    return formatted;
};

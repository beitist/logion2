import { mergeXmlTags, getTagLabel } from './tagUtils';

/**
 * Hydrates custom XML <N> tags into Tiptap-friendly HTML spans.
 * Handles tab wrappers and legacy comment tags.
 */
export const hydrateContent = (htmlContent, tags) => {
    if (!htmlContent) return "";
    let hydrated = htmlContent;

    // 1. Pre-Pass: Iteratively Handle Wrapper Tags around TABs
    // Example: <2><4>[TAB]</4></2> -> <2>\t</2> -> \t
    let changed = true;
    while (changed) {
        changed = false;
        // Match <N> [TAB] or \t </N> with optional spaces
        hydrated = hydrated.replace(/<(\d+)>\s*(?:\[TAB\]|\t)\s*<\/\1>/g, (match, id) => {
            changed = true;
            return "\t";
        });
    }

    // 2. Standard Match <(\d+)> OR </(\d+)>
    hydrated = hydrated.replace(/<(\d+)>|<\/(\d+)>/g, (match, openId, closeId) => {
        const id = openId || closeId;
        const tagInfo = tags ? tags[id] : null;
        let label = id;
        let finalId = id;

        if (tagInfo) {
            if (tagInfo.type === 'tab') {
                // Start/End tag for a specific TAB (if not caught by pre-pass)
                return "";
            }
        }
        const tagType = tagInfo?.type || 'unknown';
        return `<span data-type="tag-node" data-id="${finalId}" data-label="${label}" data-tag-type="${tagType}" class="tag-node tag-node-${finalId}" style="--tag-label: '${label}'"></span>`;
    });

    // Post-Pass: Merge Combo Tags
    let mergeChanged = true;
    while (mergeChanged) {
        mergeChanged = false;
        const regex = /<span data-type="tag-node" data-id="([^"]+)" data-label="([^"]+)" data-tag-type="([^"]+)"><\/span>(<span data-type="tag-node" data-id="([^"]+)" data-label="([^"]+)" data-tag-type="([^"]+)"><\/span>)/g;
        hydrated = hydrated.replace(regex, (match, id1, label1, type1, secondSpan, id2, label2, type2) => {
            mergeChanged = true;
            const newId = `${id1},${id2}`;
            const newLabel = `${label1},${label2}`;
            const newType = type1 === type2 ? type1 : `${type1},${type2}`;
            return `<span data-type="tag-node" data-id="${newId}" data-label="${newLabel}" data-tag-type="${newType}" class="tag-node tag-node-${newId}" style="--tag-label: '${newLabel}'"></span>`;
        });
    }

    return hydrated;
};

/**
 * Serializes Tiptap HTML content back to custom XML notation.
 * Reconstructs tabs and handles tag ordering.
 */
export const serializeContent = (htmlContent, tags) => {
    // 1. Prepare Smart Mapping for Generic Tabs
    const tabIds = [];
    if (tags) {
        Object.keys(tags).forEach(k => {
            if (tags[k].type === 'tab') tabIds.push(parseInt(k));
        });
        tabIds.sort((a, b) => a - b);
    }

    // 2. Serialize
    const openTags = new Set();
    let serialized = htmlContent;
    let tabIndex = 0;

    // Replace <span ... data-id="X"></span> with <X> or </X>
    serialized = serialized.replace(/<span([^>]+)><\/span>/g, (match, attrs) => {
        // Check if it is a tag node
        if (!attrs.includes('data-type="tag-node"')) return match;

        // Extract ID
        const idMatch = attrs.match(/data-id="([^"]+)"/);
        if (!idMatch) return match;

        const fullNodeId = idMatch[1];
        const ids = fullNodeId.split(',').map(s => s.trim());
        let replacement = "";

        for (let i = 0; i < ids.length; i++) {
            let realId = ids[i];

            // Handle Generic TAB
            if (realId === 'TAB') {
                if (tabIndex < tabIds.length) {
                    realId = String(tabIds[tabIndex]);
                    tabIndex++;
                    replacement += `<${realId}>[TAB]</${realId}>`;
                    continue;
                } else {
                    replacement += "[TAB]";
                    continue;
                }
            }

            // Standard Logic
            if (openTags.has(realId)) {
                openTags.delete(realId);
                replacement += `</${realId}>`;
            } else {
                openTags.add(realId);
                replacement += `<${realId}>`;
            }
        }
        return replacement;
    });

    return serialized;
};

/**
 * Visualizes tags as badges & applies smart hiding for source content display.
 */
export const formatSourceContent = (htmlContent, tags, forTiptap = false) => {
    if (!htmlContent) return "";

    let contentToRender = htmlContent;
    let wrapperStyle = ""; // CSS class or style

    // Iteratively strip formatting tags that wrap the whole content
    while (true) {
        const wrapMatch = contentToRender.match(/^<(\d+)>(.*?)<\/\1>$/);
        if (!wrapMatch) break;

        const tid = wrapMatch[1];
        const innerText = wrapMatch[2];
        const tagInfo = tags ? tags[tid] : null;

        if (tagInfo && ['bold', 'italic', 'underline'].includes(tagInfo.type)) {
            contentToRender = innerText;
        } else if (tagInfo && tagInfo.type === 'comment') {
            if (!forTiptap) {
                wrapperStyle += " bg-yellow-100 border-b-2 border-yellow-300 cursor-help";
            }
            contentToRender = innerText;
        } else {
            break;
        }
    }

    if (forTiptap) {
        let hydrated = hydrateContent(contentToRender, tags);
        hydrated = hydrated.replace(/\[TAB\]/g, '\t');
        if (wrapperStyle) {
            return `<span class="${wrapperStyle}">${hydrated}</span>`;
        }
        return hydrated;
    }

    // For Sidebar / HTML View
    let visibleContent = contentToRender.replace(/\[TAB\]/g, '\t');
    visibleContent = visibleContent.replace(/\t/g, '<span class="Tiptap-invisible-character Tiptap-invisible-character--tab"></span>');

    // Badge Replacement
    const createBadge = (id, isClose) => {
        const t = tags ? tags[id] : null;
        if (t && (t.type === 'tab' || t.type === 'comment')) return "";

        const colorClass = isClose ? "bg-orange-100 text-orange-800" : "bg-blue-100 text-blue-800";
        const title = isClose ? "End Tag" : "Start Tag";
        const label = isClose ? `/${id}` : id;
        return `<span class="inline-flex items-center justify-center ${colorClass} text-[10px] font-mono h-4 min-w-[16px] rounded mx-0.5 select-none" title="${title}">${label}</span>`;
    };

    let formatted = mergeXmlTags(visibleContent);

    formatted = formatted.replace(/<([0-9,]+)>/g, (match, ids) => {
        if (ids.includes(',')) {
            const label = getTagLabel(ids);
            return `<span class="inline-flex items-center justify-center bg-blue-100 text-blue-800 text-[10px] font-mono h-4 min-w-[24px] rounded mx-0.5 select-none" title="Start Tags ${ids}">${label}</span>`;
        }
        return createBadge(ids, false);
    });

    formatted = formatted.replace(/<\/([0-9,]+)>/g, (match, ids) => {
        if (ids.includes(',')) {
            const label = `/${getTagLabel(ids)}`;
            return `<span class="inline-flex items-center justify-center bg-orange-100 text-orange-800 text-[10px] font-mono h-4 min-w-[24px] rounded mx-0.5 select-none" title="End Tags ${ids}">${label}</span>`;
        }
        return createBadge(ids, true);
    });

    formatted = formatted.replace(/\t|\[TAB\]/g, '<span class="text-gray-400 font-mono select-none">⇥</span>');
    formatted = formatted.replace(/\[COMMENT\]/g, '<span class="cursor-help bg-yellow-200 text-yellow-800 text-[10px] px-1 rounded mx-0.5 align-middle">💬</span>');
    formatted = formatted.replace(/<br\s*\/?>/gi, '<span class="bg-purple-50 text-purple-400 text-[10px] px-1 rounded mx-0.5 select-none inline-block">↵</span><br/>');

    if (wrapperStyle) {
        return `<span class="${wrapperStyle}">${formatted}</span>`;
    }

    return formatted;
};

/**
 * Helper to extract comments for display from tags
 */
export const getSegmentComments = (tags) => {
    if (!tags) return [];
    const uniqueComments = new Map();

    Object.values(tags).forEach(t => {
        if (t.type === 'comment') {
            const key = t.ref_id || t.content;
            if (!uniqueComments.has(key)) {
                uniqueComments.set(key, t.content);
            }
        }
    });

    return Array.from(uniqueComments.values());
};

/**
 * Highlights glossary terms in HTML content by wrapping them with <mark> elements.
 * 
 * @param {string} htmlContent - The HTML content to process
 * @param {Array} glossaryMatches - Array of glossary matches [{source, target, note}]
 * @returns {string} HTML with glossary terms wrapped in highlighted marks
 * 
 * Example:
 *   Input: "Submit the Final Report by deadline."
 *   Glossary: [{source: "Final Report", target: "Verwendungsnachweis"}]
 *   Output: "Submit the <mark class="glossary-highlight" ...>Final Report</mark> by deadline."
 */
export const highlightGlossaryTerms = (htmlContent, glossaryMatches) => {
    if (!htmlContent || !glossaryMatches || glossaryMatches.length === 0) {
        return htmlContent;
    }

    let result = htmlContent;

    // Sort glossary terms by length (longest first) to avoid partial replacements
    // e.g., "Final Report" should be matched before "Report"
    const sortedMatches = [...glossaryMatches].sort(
        (a, b) => (b.source?.length || 0) - (a.source?.length || 0)
    );

    // Track which regions are already marked to avoid double-highlighting
    const markedRegions = [];

    for (const match of sortedMatches) {
        if (!match.source) continue;

        // Escape special regex characters in the source term
        const escapedSource = match.source.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');

        // Case-insensitive word boundary match
        // Using word boundaries to avoid partial word matches
        const regex = new RegExp(`\\b(${escapedSource})\\b`, 'gi');

        result = result.replace(regex, (fullMatch, capturedTerm, offset) => {
            // Check if this region overlaps with an already marked region
            for (const region of markedRegions) {
                if (offset >= region.start && offset < region.end) {
                    return fullMatch; // Skip - already highlighted
                }
            }

            // Mark this region as highlighted
            markedRegions.push({ start: offset, end: offset + fullMatch.length });

            // Create tooltip content
            const targetText = match.target || '';
            const noteText = match.note ? ` (${match.note})` : '';
            const tooltipContent = `→ ${targetText}${noteText}`;

            // Return the highlighted term with tooltip
            // Using data attributes for potential JS-based tooltip enhancement
            return `<mark class="glossary-highlight bg-yellow-100 border-b border-yellow-400 cursor-help rounded-sm px-0.5" 
                         title="${tooltipContent.replace(/"/g, '&quot;')}"
                         data-glossary-source="${match.source.replace(/"/g, '&quot;')}"
                         data-glossary-target="${targetText.replace(/"/g, '&quot;')}">${capturedTerm}</mark>`;
        });
    }

    return result;
};


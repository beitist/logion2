
import React, { useEffect, useState } from 'react';
import { getSegments, getProject, updateSegment, downloadProject, updateProject, deleteProject } from "../api/client";
import { TiptapEditor } from './TiptapEditor';

// GLOBAL DEBUG FLAG
const SHOW_DEBUG = true;

export function SplitView({ projectId }) {
    const [segments, setSegments] = useState([]);
    // ... (rest of imports/state)
    const [project, setProject] = useState(null);
    const [loading, setLoading] = useState(true);
    const [savingId, setSavingId] = useState(null); // ID of segment currently saving
    const [showSettings, setShowSettings] = useState(false);
    const [aiInstructions, setAiInstructions] = useState(["", "", ""]); // 3 fields

    useEffect(() => {
        const loadData = async () => {
            try {
                const p = await getProject(projectId);
                setProject(p);
                // Load AI Instructions from config if available
                if (p.config && p.config.ai_instructions) {
                    // Ensure 3 fields
                    const loaded = p.config.ai_instructions || [];
                    const filled = [loaded[0] || "", loaded[1] || "", loaded[2] || ""];
                    setAiInstructions(filled);
                }
                const s = await getSegments(projectId);
                setSegments(s);
            } catch (err) {
                console.error(err);
            } finally {
                setLoading(false);
            }
        };
        loadData();
    }, [projectId]);

    const handleEditorUpdate = (id, newContent) => {
        setSegments((prev) =>
            prev.map((seg) =>
                seg.id === id ? { ...seg, target_content: newContent } : seg
            )
        );
    };

    // Helper: Hydrate generic XML tags (<1>, </1>) into Tiptap TagNodes
    const hydrateContent = (content, tags) => {
        if (!content) return "";
        let hydrated = content;

        // 1. Pre-Pass: Handle Self-Contained Tabs <N>[TAB]</N>
        // We replace the whole sequence with a single Tab Chip to avoid duplication (Chip + Text + Chip).
        hydrated = hydrated.replace(/<(\d+)>\[TAB\]<\/\1>/g, (match, id) => {
            const tagInfo = tags ? tags[id] : null;
            if (tagInfo && tagInfo.type === 'tab') {
                // Return a SINGLE chip for the whole group
                return `<span data-type="tag-node" data-id="TAB" data-label="TAB"></span>`;
            }
            return match;
        });

        // 2. Standard Match <(\d+)> OR </(\d+)>
        hydrated = hydrated.replace(/<(\d+)>|<\/(\d+)>/g, (match, openId, closeId) => {
            const id = openId || closeId;
            const tagInfo = tags ? tags[id] : null;
            let label = id;
            let finalId = id;

            if (tagInfo) {
                if (tagInfo.type === 'tab') {
                    label = 'TAB';
                    finalId = 'TAB'; // Use generic ID so user can behave generically
                }
                else if (tagInfo.type === 'comment') label = '💬';
            }

            return `<span data-type="tag-node" data-id="${finalId}" data-label="${label}"></span>`;
        });

        return hydrated;
    };

    const handleSave = async (id, htmlContent) => {
        console.log("Saving segment", id);
        setSavingId(id);

        // Serialization: Convert TagNodes back to <1>...</1>

        // 1. Prepare Smart Mapping for Generic Tabs
        // We need the original segment to know available tab IDs
        const seg = segments.find(s => s.id === id);
        const tabIds = [];
        if (seg && seg.tags) {
            // Collect all IDs that are tabs, sorted numerically or by appearance order?
            // Usually keys are strings "1", "10". Numeric sort is safest.
            Object.keys(seg.tags).forEach(k => {
                if (seg.tags[k].type === 'tab') tabIds.push(parseInt(k));
            });
            tabIds.sort((a, b) => a - b);
        }

        // 2. Serialize
        const openTags = new Set();
        let serialized = htmlContent;
        let tabIndex = 0;

        // Replace <span ... data-id="X"></span> with <X> or </X>
        // CRITICAL FIX: Tiptap/Browser may reorder attributes (e.g. data-id before data-type).
        // Old Regex required specific order. New Regex matches SPAN tag and parses attributes manually.
        serialized = serialized.replace(/<span([^>]+)><\/span>/g, (match, attrs) => {
            // Check if it's our tag node
            if (!attrs.includes('data-type="tag-node"')) return match;

            // Extract ID
            const idMatch = attrs.match(/data-id="([^"]+)"/);
            if (!idMatch) return match;

            const nodeId = idMatch[1];
            let realId = nodeId;

            // Handle Generic TAB
            if (nodeId === 'TAB') {
                if (tabIndex < tabIds.length) {
                    realId = String(tabIds[tabIndex]);
                    tabIndex++;
                    return `<${realId}>[TAB]</${realId}>`;
                } else {
                    return "[TAB]";
                }
            }

            // Standard Logic for other IDs (1, 2, C...)
            if (openTags.has(realId)) {
                openTags.delete(realId);
                return `</${realId}>`;
            } else {
                openTags.add(realId);
                return `<${realId}>`;
            }
        });

        // Serialize Tabs/Comments Visuals back to markers
        // note: Generic Tabs logic above already injected [TAB] inside tags!
        // So we don't need to replace `[TAB]` visual unless it was manually typed? 
        // But `htmlContent` contains ` < span...> TAB</span > ` inside the node?
        // Wait, replace loop matched the WHOLE span. So inner content is GONE.
        // My return `< ${ realId }> [TAB]</${ realId }> ` REPLACES the whole chip.
        // So I don't need to clean up `⇥ TAB` span for Tabs.

        // But for Comments? Comments are standard nodes.
        // Standard logic returns `< ID > `. Inner content was consumed.
        // Does Tiptap node contain "💬"? Yes.
        // So `< ID > ` is returned. Content is GONE?
        // NO. `match` consumes the span. The return value replaces it.
        // For comments, we want `< ID > [COMMENT]</ID > `?
        // Or does the user wrap text? "Reference Comment".
        // If it's a range comment, user wraps text.
        // But `TagNode` is an ATOM. It cannot wrap text.
        // Wait. `TagNode` is an ATOM. It is a point.
        // So for COMMENTS (Ranges), using `TagNode` is wrong?
        // User changed plan to "Insert at Cursor".
        // Meaning: Click "C" -> Insert `[C]`. Move cursor -> Click "C" -> Insert `[C]`.
        // Result: `[C] text[C]`.
        // Serialization: `< C > text </C > `.
        // Perfect.
        // The inner content of the [C] chip (💬) doesn't matter. It's just a marker.
        // So standard logic works.

        // Only TAB is special because <1>[TAB]</1> is a single unit in strict sense?
        // Or is it <1>...tabs...</1>?
        // Logic says Tab tag wraps a [TAB] marker.
        // So inserting `< 1 > [TAB]</1 > ` for a single chip is correct.

        // Calculate Status
        // If content is empty or just an empty paragraph, it remains 'draft'.
        // Otherwise 'translated'.
        const isEmpty = !htmlContent || htmlContent.trim() === '' || htmlContent.trim() === '<p></p>';
        const newStatus = isEmpty ? 'draft' : 'translated';

        try {
            await updateSegment(id, serialized, newStatus);

            // Update local state to reflect status change immediately (e.g. for badges)
            setSegments(prev => prev.map(s =>
                s.id === id ? { ...s, target_content: serialized, status: newStatus } : s
            ));

        } catch (err) {
            console.error("Save failed", err);
            alert("Save failed!");
        } finally {
            setSavingId(null);
        }
    };

    const handleExport = async () => {
        if (!project) return;
        try {
            const blob = await downloadProject(projectId);
            // Create download link
            const url = window.URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = `translated_${project.filename}`;
            document.body.appendChild(a);
            a.click();
            a.remove();
        } catch (err) {
            console.error("Export failed", err);
            alert("Export failed!");
        }
    };

    const handleUpdateSettings = async (index, value) => {
        const newInstructions = [...aiInstructions];
        newInstructions[index] = value;
        setAiInstructions(newInstructions);
    };

    const saveSettings = async () => {
        if (!project) return;
        try {
            const config = { ...(project.config || {}), ai_instructions: aiInstructions };
            await updateProject(projectId, { config });
            // console.log("Settings saved");
            // Update local project state
            setProject(prev => ({ ...prev, config }));
        } catch (err) {
            console.error("Failed to save settings", err);
            alert("Failed to save settings");
        }
    };

    const handleDeleteProject = async () => {
        if (!window.confirm("Are you sure you want to delete this project? This cannot be undone.")) return;
        try {
            await deleteProject(projectId);
            window.location.href = "/"; // Force reload/redirect to home
        } catch (err) {
            console.error("Failed to delete project", err);
            alert("Failed to delete project");
        }
    };

    // Helper to visualize tags as badges & apply smart hiding
    const formatSourceContent = (htmlContent, tags) => {
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

            // Only strip standard formatting tags
            // USER REQUEST 1321: "Source bitte auch keine RTF-formatierungen sondern ausschliesslich tags"
            // We REMOVE the logic that strips tags and applies styles.
            // Now these tags will fall through and be rendered as numeric chips below.

            if (tagInfo && ['bold', 'italic', 'underline'].includes(tagInfo.type)) {
                // STRIP redundant specific styling tags that wrap the whole segment.
                // We do NOT apply the style (wrapperStyle) to keep the "Chip Mode" strict/clean look.
                // The tag simply disappears from view, reducing noise.
                contentToRender = innerText;
            } else
                if (tagInfo && tagInfo.type === 'comment') {
                    // COMMENT RANGE DETECTED!
                    // We unwrap it but apply a Highlight Style
                    wrapperStyle += " bg-yellow-100 border-b-2 border-yellow-300 cursor-help";
                    contentToRender = innerText;

                    // Note: We strip the tag, so the "Start Tag" chip logic below won't fire for this ID.
                    // This is perfect! We get highlight but no generic chip <N>.
                    // But wait, the loop continues. If we unwrapped, regex below won't find <ID> anymore.
                    // We need to ensure we don't break the loop logic if we want to strip INNER tags too.
                    // Yes, continue unwrapping.
                } else {
                    // If it's a Link or Comment, stop stripping so the chip remains visible
                    break;
                }
        }

        // 2. Badge Replacement (Smart)
        // We use a callback to check tag type before rendering a Blue/Orange chip.

        // Start Tags <n>
        let formatted = contentToRender.replace(/<(\d+)>/g, (match, id) => {
            const t = tags ? tags[id] : null;
            // If it's a TAB or COMMENT or LINK, we might want to hide the generic numeric chip 
            // because we render the content specially (or want to avoid double-visuals).

            // Tab: Logic change - We ALWAYS want to show [TAB] badge, but not the numeric wrapper.
            // Since [TAB] marker is inside, we hide the wrapper.
            if (t && (t.type === 'tab' || t.type === 'comment')) {
                return ""; // Hide start tag wrapper, content ([TAB]) will be styled below
            }
            return `<span class="inline-flex items-center justify-center bg-blue-100 text-blue-800 text-[10px] font-mono h-4 min-w-[16px] rounded mx-0.5 select-none" title="Start Tag">${id}</span>`;
        });

        // End Tags </n>
        formatted = formatted.replace(/<\/(\d+)>/g, (match, id) => {
            const t = tags ? tags[id] : null;
            if (t && (t.type === 'tab' || t.type === 'comment')) {
                return ""; // Hide end tag
            }
            return `<span class="inline-flex items-center justify-center bg-orange-100 text-orange-800 text-[10px] font-mono h-4 min-w-[16px] rounded mx-0.5 select-none" title="End Tag">/${id}</span>`;
        });

        // Replace [TAB] -> [TAB] Badge
        formatted = formatted.replace(/\[TAB\]/g,
            '<span class="bg-gray-100 text-gray-800 text-[10px] font-bold px-1 rounded mx-0.5 border border-gray-300">⇥ TAB</span>');

        // Replace [COMMENT] -> [💬] Badge
        formatted = formatted.replace(/\[COMMENT\]/g,
            '<span class="cursor-help bg-yellow-200 text-yellow-800 text-[10px] px-1 rounded mx-0.5 align-middle">💬</span>');

        // Replace <br/> -> [↵] Badge
        // Regex for <br/> or <br> or <br />
        formatted = formatted.replace(/<br\s*\/?>/gi,
            '<span class="bg-purple-50 text-purple-400 text-[10px] px-1 rounded mx-0.5 select-none inline-block">↵</span><br/>');
        // We append real <br/> so it breaks line visually too? 
        // User said "nicht erahnen wo welche sind".
        // If I keep real <br/>, it breaks. If I remove it, it becomes one line with badges.
        // Usually keeping the break IS desired, but the badge makes it EXPLICIT.
        // Let's keep both. Badge + Break.


        // Replace <br/> (already HTML, but ensure it's safe? dangerouslySetInnerHTML handles it)

        // 3. Wrap result if we stripped a wrapper
        if (wrapperStyle) {
            return `<span class="${wrapperStyle}">${formatted}</span>`;
        }

        return formatted;
    };

    // Helper to check if content is ONLY a comment (to potentially hide it if desired)
    // But currently we always show chip.

    // Helper to extract comments for display
    const getSegmentComments = (tags) => {
        if (!tags) return [];
        const uniqueComments = new Map(); // ref_id -> content

        Object.values(tags).forEach(t => {
            if (t.type === 'comment') {
                // Use ref_id for uniqueness if available, else content
                const key = t.ref_id || t.content;
                if (!uniqueComments.has(key)) {
                    uniqueComments.set(key, t.content);
                }
            }
        });

        return Array.from(uniqueComments.values());
    };

    if (loading) return <div className="p-8 text-center">Loading...</div>;

    return (
        <div className="h-screen flex flex-col">
            <header className="p-4 bg-gray-100 border-b flex justify-between items-center">
                <h1 className="font-bold">Project: {project?.filename}</h1>
                <div className="flex gap-2">
                    <button
                        onClick={() => setShowSettings(true)}
                        className="bg-gray-200 text-gray-700 px-3 py-2 rounded hover:bg-gray-300"
                        title="Project Settings"
                    >
                        ⚙️ Settings
                    </button>
                    <button
                        onClick={handleExport}
                        className="bg-green-600 text-white px-4 py-2 rounded hover:bg-green-700">
                        Export DOCX
                    </button>
                </div>

                {/* Settings Modal */}
                {showSettings && (
                    <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50">
                        <div className="bg-white p-6 rounded-lg shadow-xl w-full max-w-4xl h-[80vh] flex flex-col">
                            <h2 className="text-xl font-bold mb-4">Project Files</h2>

                            <div className="flex-1 overflow-hidden grid grid-cols-3 gap-4">
                                {/* Window 1: Source Files */}
                                <div className="border rounded-lg bg-gray-50 flex flex-col">
                                    <h3 className="p-3 bg-white border-b font-medium text-gray-700 flex items-center gap-2">
                                        📄 Source Files
                                    </h3>
                                    <div className="p-3 overflow-y-auto flex-1 space-y-2">
                                        {project.files && project.files.filter(f => f.category === 'source').length > 0 ? (
                                            project.files.filter(f => f.category === 'source').map(f => (
                                                <div key={f.id} className="text-sm bg-white p-2 rounded shadow-sm border border-gray-200 truncate" title={f.filename}>
                                                    {f.filename}
                                                </div>
                                            ))
                                        ) : (
                                            <p className="text-gray-400 text-sm italic">No source files</p>
                                        )}
                                    </div>
                                </div>

                                {/* Window 2: Legal/Reference Files */}
                                <div className="border rounded-lg bg-indigo-50 flex flex-col">
                                    <h3 className="p-3 bg-white border-b font-medium text-indigo-700 flex items-center gap-2">
                                        ⚖️ Legal / Reference
                                    </h3>
                                    <div className="p-3 overflow-y-auto flex-1 space-y-2">
                                        {project.files && project.files.filter(f => f.category === 'legal').length > 0 ? (
                                            project.files.filter(f => f.category === 'legal').map(f => (
                                                <div key={f.id} className="text-sm bg-white p-2 rounded shadow-sm border border-indigo-100 truncate text-indigo-700" title={f.filename}>
                                                    {f.filename}
                                                </div>
                                            ))
                                        ) : (
                                            <p className="text-indigo-300 text-sm italic">No legal files</p>
                                        )}
                                    </div>
                                </div>

                                {/* Window 3: Background Files */}
                                <div className="border rounded-lg bg-blue-50 flex flex-col">
                                    <h3 className="p-3 bg-white border-b font-medium text-blue-700 flex items-center gap-2">
                                        📚 Background / Context
                                    </h3>
                                    <div className="p-3 overflow-y-auto flex-1 space-y-2">
                                        {project.files && project.files.filter(f => f.category === 'background').length > 0 ? (
                                            project.files.filter(f => f.category === 'background').map(f => (
                                                <div key={f.id} className="text-sm bg-white p-2 rounded shadow-sm border border-blue-100 truncate text-blue-700" title={f.filename}>
                                                    {f.filename}
                                                </div>
                                            ))
                                        ) : (
                                            <p className="text-blue-300 text-sm italic">No background files</p>
                                        )}
                                    </div>
                                </div>
                            </div>

                            <div className="border-t pt-4 mt-4 flex justify-between items-center">
                                <button
                                    onClick={handleDeleteProject}
                                    className="text-red-500 text-sm hover:underline"
                                >
                                    🗑️ Delete Project
                                </button>
                                <button
                                    onClick={() => setShowSettings(false)}
                                    className="bg-blue-600 text-white px-4 py-2 rounded hover:bg-blue-700"
                                >
                                    Close
                                </button>
                            </div>
                        </div>
                    </div>
                )}
            </header>

            <div className="flex-1 overflow-auto p-4">
                <div className="max-w-6xl mx-auto space-y-4">
                    {segments.map((seg) => {
                        const comments = getSegmentComments(seg.tags);
                        return (
                            <div key={seg.id} className="grid grid-cols-2 gap-4 bg-white rounded-lg shadow-sm border border-gray-200 overflow-hidden">
                                {/* Source Column */}
                                <div className="w-1/2 p-4 bg-gray-50 rounded text-sm leading-relaxed border-r border-gray-100 flex flex-col">
                                    {/* Source Text */}
                                    <div className="flex-grow" dangerouslySetInnerHTML={{ __html: formatSourceContent(seg.source_content, seg.tags) }} />

                                    {/* Comments Section */}
                                    {comments.length > 0 && (
                                        <div className="mt-4 pt-3 border-t border-gray-200 text-xs text-gray-600 bg-yellow-50 -mx-4 -mb-4 p-4">
                                            <div className="font-semibold mb-1 flex items-center gap-2">
                                                <span>💬 Comments ({comments.length})</span>
                                            </div>
                                            <ul className="space-y-1 list-disc list-inside">
                                                {comments.map((c, i) => (
                                                    <li key={i}>{c}</li>
                                                ))}
                                            </ul>
                                        </div>
                                    )}

                                    {/* DEBUG: Show raw source content */}
                                    {SHOW_DEBUG && (
                                        <div className="mt-4 p-1 bg-red-50 text-[10px] font-mono text-red-500 border border-red-200 rounded break-all">
                                            DEBUG Source-DB: {seg.source_content}
                                        </div>
                                    )}
                                </div>

                                {/* Target Column */}
                                <div className="p-4 bg-white relative group">
                                    <div className="text-xs text-gray-400 font-mono mb-1 uppercase tracking-wider flex justify-between items-center">
                                        <div className="flex items-center gap-2">
                                            <span>Target (DE)</span>
                                            {/* Context Badges */}
                                            {seg.metadata && (
                                                <>
                                                    {seg.metadata.type === 'header' && (
                                                        <span className="bg-purple-100 text-purple-700 px-1.5 py-0.5 rounded text-[10px] font-bold border border-purple-200">
                                                            HEADER {seg.metadata.section_index !== undefined ? `#${seg.metadata.section_index} ` : ''}
                                                        </span>
                                                    )}
                                                    {seg.metadata.type === 'footer' && (
                                                        <span className="bg-purple-100 text-purple-700 px-1.5 py-0.5 rounded text-[10px] font-bold border border-purple-200">
                                                            FOOTER {seg.metadata.section_index !== undefined ? `#${seg.metadata.section_index} ` : ''}
                                                        </span>
                                                    )}
                                                    {(seg.metadata.type === 'table' || seg.metadata.child_type === 'table_cell') && (
                                                        <span className="bg-blue-100 text-blue-700 px-1.5 py-0.5 rounded text-[10px] font-bold border border-blue-200">
                                                            TABLE [{seg.metadata.table_index},{seg.metadata.row_index},{seg.metadata.cell_index}]
                                                        </span>
                                                    )}
                                                </>
                                            )}
                                        </div>
                                        <span className={`px-2 py-0.5 rounded-full text-[10px] ${seg.status === 'draft' ? 'bg-yellow-100 text-yellow-700' :
                                            seg.status === 'translated' ? 'bg-green-100 text-green-700' : 'bg-gray-100'
                                            }`}>
                                            {seg.status}
                                        </span>
                                    </div>
                                    <TiptapEditor
                                        content={hydrateContent(seg.target_content, seg.tags)}
                                        segmentId={seg.id}
                                        availableTags={seg.tags}
                                        onSave={handleSave}
                                    />

                                    {/* DEBUG: Show raw target content sent to backend */}
                                    {SHOW_DEBUG && (
                                        <div className="mt-1 p-1 bg-slate-100 text-[10px] font-mono text-slate-500 border border-slate-200 rounded break-all">
                                            DEBUG Target-DB: {seg.target_content}
                                        </div>
                                    )}
                                </div>
                            </div>
                        )
                    })}
                </div>
            </div>
        </div>
    );
}

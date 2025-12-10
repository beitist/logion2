import React, { useEffect, useState } from 'react';
import { getSegments, getProject, updateSegment, downloadProject } from "../api/client";
import { TiptapEditor } from './TiptapEditor';

export function SplitView({ projectId }) {
    const [segments, setSegments] = useState([]);
    const [project, setProject] = useState(null);
    const [loading, setLoading] = useState(true);
    const [savingId, setSavingId] = useState(null); // ID of segment currently saving

    useEffect(() => {
        const loadData = async () => {
            try {
                const p = await getProject(projectId);
                setProject(p);
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

    const handleSave = async (id, content) => {
        console.log("Saving segment", id);
        setSavingId(id);
        try {
            await updateSegment(id, content);
            // Maybe show a toast?
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
            if (tagInfo && ['bold', 'italic', 'underline'].includes(tagInfo.type)) {
                if (tagInfo.type === 'bold') wrapperStyle += " font-bold";
                if (tagInfo.type === 'italic') wrapperStyle += " italic";
                if (tagInfo.type === 'underline') wrapperStyle += " underline";

                contentToRender = innerText;
            } else if (tagInfo && tagInfo.type === 'comment') {
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
            // Link: We WANT the chip (user needs to know where link starts).
            // Tab/Comment: The content is [TAB]/[COMMENT] which we style distinctively. Hiding the wrapper is cleaner.
            if (t && (t.type === 'tab' || t.type === 'comment')) {
                return ""; // Hide start tag
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

        // Replace [TAB]
        formatted = formatted.replace(/\[TAB\]/g,
            '<span class="bg-gray-100 text-gray-500 text-[10px] px-1 rounded mx-0.5 border border-gray-300">⇥ TAB</span>');

        // Replace [COMMENT] - Show inline chip
        formatted = formatted.replace(/\[COMMENT\]/g,
            '<span class="cursor-help bg-yellow-200 text-yellow-800 text-[10px] px-1 rounded mx-0.5 align-middle">💬</span>');

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
        return Object.values(tags)
            .filter(t => t.type === 'comment')
            .map(t => t.content);
    };

    if (loading) return <div className="p-8 text-center">Loading...</div>;

    return (
        <div className="h-screen flex flex-col">
            <header className="p-4 bg-gray-100 border-b flex justify-between items-center">
                <h1 className="font-bold">Project: {project?.filename}</h1>
                <button
                    onClick={handleExport}
                    className="bg-green-600 text-white px-4 py-2 rounded hover:bg-green-700">
                    Export DOCX
                </button>
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
                                </div>

                                {/* Target Column */}
                                <div className="p-4 bg-white relative group">
                                    <div className="text-xs text-gray-400 font-mono mb-1 uppercase tracking-wider flex justify-between">
                                        <span>Target (DE)</span>
                                        <span className={`px-2 py-0.5 rounded-full text-[10px] ${seg.status === 'draft' ? 'bg-yellow-100 text-yellow-700' :
                                            seg.status === 'translated' ? 'bg-green-100 text-green-700' : 'bg-gray-100'
                                            }`}>
                                            {seg.status}
                                        </span>
                                    </div>
                                    <TiptapEditor
                                        content={seg.target_content || ""}
                                        segmentId={seg.id}
                                        onSave={handleSave}
                                        isReadOnly={false}
                                    />
                                </div>
                            </div>
                        )
                    })}
                </div>
            </div>
        </div>
    );
}

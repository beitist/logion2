import React, { useEffect, useState } from 'react';
import { getSegments, getProject, updateSegment, downloadProject, downloadProjectTMX, updateProject, deleteProject, generateDraft, getGlossaryTerms, reingestProject } from "../api/client";
import { TiptapEditor } from './TiptapEditor';
import { mergeXmlTags, getTagLabel } from '../utils/tagUtils';

// GLOBAL DEBUG FLAG
// GLOBAL DEBUG FLAG REMOVED - now strict state controlled

import { RAGSettingsTab } from './settings/RAGSettingsTab';
import { AISettingsTab } from './settings/AISettingsTab';
import { GlossarySettingsTab } from './settings/GlossarySettingsTab';
import { StatisticsSettingsTab } from './settings/StatisticsSettingsTab';
import { WorkflowsTab } from './settings/WorkflowsTab';
import { ProjectSettingsTab } from './settings/ProjectSettingsTab';
import { GlossaryAddModal } from './GlossaryAddModal';

import { Terminal, Bug, Keyboard, Trash2, Save, MoreVertical, FileText, Check, Copy, ArrowLeft, Download, ChevronDown } from 'lucide-react';
import './TiptapStyles.css'; // Ensure invisible character styles are available
import { LogConsole } from './LogConsole';
import { ShortcutsPanel } from './ShortcutsPanel';

export function SplitView({ projectId, onBack }) {
    // ... existing state ...
    const [segments, setSegments] = useState([]);
    const [project, setProject] = useState(null);
    const [loading, setLoading] = useState(true);
    const [savingId, setSavingId] = useState(null);
    const [showSettings, setShowSettings] = useState(false);
    const [showShortcuts, setShowShortcuts] = useState(false);
    const [activeSettingsTab, setActiveSettingsTab] = useState('files'); // 'files', 'ai', 'glossary'
    const [activeSegmentId, setActiveSegmentId] = useState(null); // Track active segment for sidebar & AI logic

    // Glossary Modal State
    const [showGlossaryModal, setShowGlossaryModal] = useState(false);
    const [glossarySelection, setGlossarySelection] = useState("");
    const [glossaryTerms, setGlossaryTerms] = useState([]); // Cache for display

    // Flash State for MT Updates
    const [flashingSegments, setFlashingSegments] = useState({});

    // Export UI
    const [showExportMenu, setShowExportMenu] = useState(false);

    // Re-initialization State
    const [isReinitializing, setIsReinitializing] = useState(false);
    const [reinitStatus, setReinitStatus] = useState("idle"); // idle, ingesting, ready, error
    const [reinitLogs, setReinitLogs] = useState([]);

    // Polling for Re-initialization
    useEffect(() => {
        let interval;
        if (isReinitializing) {
            interval = setInterval(async () => {
                try {
                    const p = await getProject(projectId);
                    if (p) {
                        setReinitStatus(p.rag_status);
                        setReinitLogs(p.ingestion_logs || []);

                        if (p.rag_status === 'ready' || p.rag_status === 'error') {
                            // Keep interval running? user might want to see logs?
                            // No, stop polling to save bandwidth, but keep modal open.
                            clearInterval(interval);
                        }
                    }
                } catch (e) {
                    console.error("Polling failed", e);
                }
            }, 1000);
        }
        return () => clearInterval(interval);
    }, [isReinitializing, projectId]);



    useEffect(() => {
        if (projectId) {
            getGlossaryTerms(projectId).then(setGlossaryTerms).catch(err => console.warn("Glossary load failed", err));
        }
    }, [projectId, showGlossaryModal]); // Reload if modal closes (term added)

    // Console & Debug State
    const [showConsole, setShowConsole] = useState(false);
    // ... (rest of code)

    // ... (rest of code)

    const [showDebug, setShowDebug] = useState(false); // Toggle for per-segment debug info
    const [logs, setLogs] = useState([]);

    const log = (message, type = 'info', details = null) => {
        setLogs(prev => [...prev, {
            time: new Date().toLocaleTimeString(),
            message,
            type,
            details
        }]);
        // Auto-open console on error? Or just let user see notification?
        // Let's keep it manual for now to not be annoying.
    };

    // ... useEffect loadData ...
    // AI Auto-Drafting Queue System
    const draftQueue = React.useRef([]);
    const isProcessingQueue = React.useRef(false);
    const segmentsRef = React.useRef(segments); // Keep latest state for async queue

    // Update ref whenever segments change
    useEffect(() => {
        segmentsRef.current = segments;
    }, [segments]);

    // Helper to add to queue safely
    const queueSegments = (ids, mode = "translate", isWorkflow = false) => {
        let added = false;
        ids.forEach(id => {
            // Check if already in queue (compare IDs)
            if (draftQueue.current.find(item => item.id === id)) return;

            // Check if already done (using Ref for latest)
            const seg = segmentsRef.current.find(s => s.id === id);
            if (!seg) return;

            // Mode Logic:
            const hasContent = seg.target_content && seg.target_content.trim() !== '' && seg.target_content !== '<p></p>';

            if (mode === "translate" && hasContent) return;
            if (seg.locked) return;

            draftQueue.current.push({ id, mode, isWorkflow });
            added = true;
        });

        if (added) {
            processQueue();
        }
    };

    // Main Queue Processor
    const processQueue = async () => {
        if (isProcessingQueue.current) return;
        isProcessingQueue.current = true;

        const CONCURRENCY = 3;

        while (draftQueue.current.length > 0) {
            // Take up to CONCURRENCY items
            const batch = draftQueue.current.splice(0, CONCURRENCY);

            // Process batch in parallel
            await Promise.all(batch.map(async (item) => {
                const { id: nextId, mode, isWorkflow } = item;

                // Double-check just before execution
                const seg = segmentsRef.current.find(s => s.id === nextId);

                // Re-check conditions as state might have changed
                const hasContent = seg && seg.target_content && seg.target_content.trim() !== '' && seg.target_content !== '<p></p>';

                if (!seg || seg.locked) return;
                if (mode === "translate" && hasContent) return;

                try {
                    await handleAiDraft(nextId, true, mode, isWorkflow); // true = isAuto
                } catch (e) {
                    console.warn("Queue item failed", nextId, e);
                }
            }));

            // Minimal delay between batches to breath
            await new Promise(r => setTimeout(r, 50));
        }

        isProcessingQueue.current = false;
    };

    const handleReingest = async () => {
        if (!confirm("This will clear all existing context vectors and re-process all files. Continue?")) return;

        try {
            await reingestProject(projectId);
            setIsReinitializing(true);
            setReinitStatus("started");
            setReinitLogs(["Request sent..."]);
        } catch (e) {
            alert("Failed to trigger re-ingest: " + e.message);
        }
    };


    useEffect(() => {
        const loadData = async () => {
            try {
                setLoading(true);
                const p = await getProject(projectId);
                setProject(p);
                const s = await getSegments(projectId);
                setSegments(s);
                segmentsRef.current = s;

                // Trigger Initial Lookahead
                const config = p.config || {};
                const aiSettings = config.ai_settings || {};
                const preTranslateCount = parseInt(aiSettings.pre_translate_count) || 0;

                if (preTranslateCount > 0 && s.length > 0) {
                    // Start from 0, queue N segments
                    const initialIds = s.slice(0, preTranslateCount).map(seg => seg.id);
                    // Defer to ensure refs/state are settled? 
                    // Direct call is fine as we set segmentsRef above.
                    // But queueSegments uses segmentsRef.
                    setTimeout(() => queueSegments(initialIds), 100);
                }

                // Auto-Focus First Draft Segment
                if (s.length > 0) {
                    const firstDraft = s.find(seg => seg.status === 'draft');
                    if (firstDraft) {
                        setTimeout(() => {
                            const el = document.getElementById(`editor-${firstDraft.id}`);
                            if (el) {
                                el.scrollIntoView({ behavior: 'smooth', block: 'center' });
                                // Also set as active for AI/Shortcuts context
                                setActiveSegmentId(firstDraft.id);
                            }
                        }, 500); // Slight delay for rendering
                    }
                }
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

    // Helper to hydrate Tiptap tags from custom XML <N> format
    const hydrateContent = (htmlContent, tags) => {
        if (!htmlContent) return "";
        let hydrated = htmlContent;

        // 1. Pre-Pass: Iteratively Handle Wrapper Tags around TABs
        // Example: <2><4>[TAB]</4></2> -> <2>\t</2> -> \t
        // We do this in a loop to handle arbitrary nesting depth.
        let changed = true;
        while (changed) {
            changed = false;
            // Match <N> [TAB] or \t </N> with optional spaces
            hydrated = hydrated.replace(/<(\d+)>\s*(?:\[TAB\]|\t)\s*<\/\1>/g, (match, id) => {
                // We don't strictly care about tag type here. 
                // If a tag wraps ONLY a tab, it's structurally irrelevant for the Editor view 
                // and causes visual "Chips" (e.g. bold tabs). We strip the wrapper.
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
                    // Start/End tag for a specific TAB (if not caught by pre-pass for some reason)
                    return "";
                }
                // REMOVED: Speechbubble override for comments (User Request 1)
                // else if (tagInfo.type === 'comment') label = '💬';
            }
            return `<span data-type="tag-node" data-id="${finalId}" data-label="${label}" class="tag-node tag-node-${finalId}" style="--tag-label: '${label}'"></span>`;
        });

        // Post-Pass: Merge Combo Tags (Like in TiptapEditor)
        let mergeChanged = true;
        while (mergeChanged) {
            mergeChanged = false;
            const regex = /<span data-type="tag-node" data-id="([^"]+)" data-label="([^"]+)"><\/span>(<span data-type="tag-node" data-id="([^"]+)" data-label="([^"]+)"><\/span>)/g;
            hydrated = hydrated.replace(regex, (match, id1, label1, secondSpan, id2, label2) => {
                mergeChanged = true;
                const newId = `${id1},${id2}`;
                const newLabel = `${label1},${label2}`;
                return `<span data-type="tag-node" data-id="${newId}" data-label="${newLabel}" class="tag-node tag-node-${newId}" style="--tag-label: '${newLabel}'"></span>`;
            });
        }

        return hydrated;
    };



    const handleSave = async (id, htmlContent) => {
        // console.log("Saving segment", id); // Debug removed
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

                // Standard Logic for other IDs (1, 2, C...)
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
            const start = performance.now();
            await updateSegment(id, serialized, newStatus);
            const duration = Math.round(performance.now() - start);

            // Update local state to reflect status change immediately (e.g. for badges)
            setSegments(prev => prev.map(s =>
                s.id === id ? { ...s, target_content: serialized, status: newStatus } : s
            ));

            log(`Segment saved in ${duration}ms`, 'success');

        } catch (err) {
            log(`Save failed: ${err.message}`, 'error');
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

    const handleTmXExport = async () => {
        if (!project) return;
        try {
            const blob = await downloadProjectTMX(projectId);
            const url = window.URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = `${project.filename}.tmx`;
            document.body.appendChild(a);
            a.click();
            a.remove();
        } catch (err) {
            console.error("TMX Export failed", err);
            alert("TMX Export failed!");
        }
    };

    const handleUpdateSettings = async (index, value) => {
        // This function is not used anymore as AISettingsTab handles its own state and updates
        // Keeping it for now in case it's re-purposed.
        // const newInstructions = [...aiInstructions];
        // newInstructions[index] = value;
        // setAiInstructions(newInstructions);
    };

    const saveSettings = async () => {
        // This function is not used anymore as AISettingsTab handles its own state and updates
        // if (!project) return;
        // try {
        //     const config = { ...(project.config || {}), ai_instructions: aiInstructions };
        //     await updateProject(projectId, { config });
        //     // console.log("Settings saved");
        //     // Update local project state
        //     setProject(prev => ({ ...prev, config }));
        // } catch (err) {
        //     console.error("Failed to save settings", err);
        //     alert("Failed to save settings");
        // }
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
    const formatSourceContent = (htmlContent, tags, forTiptap = false) => {
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
            } else
                if (tagInfo && tagInfo.type === 'comment') {
                    if (!forTiptap) {
                        wrapperStyle += " bg-yellow-100 border-b-2 border-yellow-300 cursor-help";
                    }
                    contentToRender = innerText;
                } else {
                    break;
                }
        }

        if (forTiptap) {
            // For Tiptap, we need to Hydrate the XML tags into Tiptap-friendly spans
            // AND we must ensure that [TAB] is converted to real \t character for the InvisibleCharacters extension to pick it up.
            let hydrated = hydrateContent(contentToRender, tags);

            // Explicitly handle any remaining generic [TAB] or known tab contents
            // If hydrateContent returned [TAB] because regex failed, we fix it here.
            hydrated = hydrated.replace(/\[TAB\]/g, '\t');

            if (wrapperStyle) {
                return `<span class="${wrapperStyle}">${hydrated}</span>`;
            }
            return hydrated;
        }

        // For Sidebar / HTML View: Render VISIBLE TAB
        // We replace [TAB] or \t with the exact HTML structure used by Tiptap CSS (roughly)
        // so it looks the same.
        let visibleContent = contentToRender.replace(/\[TAB\]/g, '\t');
        visibleContent = visibleContent.replace(/\t/g, '<span class="Tiptap-invisible-character Tiptap-invisible-character--tab"></span>');

        // 2. Badge Replacement (Smart) for Raw HTML View (Legacy/Fallback)
        // User Request 2: Combo Tags for Source/Sidebar

        // Helper to build badge HTML
        const createBadge = (id, isClose) => {
            const t = tags ? tags[id] : null;
            if (t && (t.type === 'tab' || t.type === 'comment')) return "";

            const colorClass = isClose ? "bg-orange-100 text-orange-800" : "bg-blue-100 text-blue-800";
            const title = isClose ? "End Tag" : "Start Tag";
            const label = isClose ? `/${id}` : id;
            return `<span class="inline-flex items-center justify-center ${colorClass} text-[10px] font-mono h-4 min-w-[16px] rounded mx-0.5 select-none" title="${title}">${label}</span>`;
        };

        // Pre-Pass: Merge IDs in the string or just handling the replacement?
        // Replacing iteratively is safer for string manipulation.

        // Merge adjacent tags in XML format first? e.g. <1><2> -> <1,2>
        // Start Tags
        // Pre-Pass: Merge adjacent tags in XML format
        // Refactored to Utils
        let formatted = mergeXmlTags(visibleContent);

        // Now render badges for (comma-separated) IDs
        // Matches <1,2,3... > or </1,2,3... >
        formatted = formatted.replace(/<([0-9,]+)>/g, (match, ids) => {
            if (ids.includes(',')) {
                // Combo Start: Show Range (1-3)
                const label = getTagLabel(ids);
                return `<span class="inline-flex items-center justify-center bg-blue-100 text-blue-800 text-[10px] font-mono h-4 min-w-[24px] rounded mx-0.5 select-none" title="Start Tags ${ids}">${label}</span>`;
            }
            return createBadge(ids, false);
        });

        formatted = formatted.replace(/<\/([0-9,]+)>/g, (match, ids) => {
            if (ids.includes(',')) {
                // Combo End: Show Range per utility
                const label = `/${getTagLabel(ids)}`;
                return `<span class="inline-flex items-center justify-center bg-orange-100 text-orange-800 text-[10px] font-mono h-4 min-w-[24px] rounded mx-0.5 select-none" title="End Tags ${ids}">${label}</span>`;
            }
            return createBadge(ids, true);
        });


        // Replace [TAB] -> Visible Arrow [⇥] for sidebar/raw view
        formatted = formatted.replace(/\t|\[TAB\]/g, '<span class="text-gray-400 font-mono select-none">⇥</span>');

        // Replace [COMMENT] -> [💬] Badge
        formatted = formatted.replace(/\[COMMENT\]/g,
            '<span class="cursor-help bg-yellow-200 text-yellow-800 text-[10px] px-1 rounded mx-0.5 align-middle">💬</span>');

        // Replace <br/> -> [↵] Badge
        formatted = formatted.replace(/<br\s*\/?>/gi,
            '<span class="bg-purple-50 text-purple-400 text-[10px] px-1 rounded mx-0.5 select-none inline-block">↵</span><br/>');

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

    // Editor Instances Registry
    const editorRefs = React.useRef({});

    // Navigation Helper
    const handleNavigation = (currentId, direction) => {
        // finding current index
        const currentIndex = segments.findIndex(s => s.id === currentId);
        if (currentIndex === -1) return;

        let nextIndex = direction === 'next' ? currentIndex + 1 : currentIndex - 1;

        // Boundaries
        if (nextIndex < 0) nextIndex = 0; // or loop? usually stop
        if (nextIndex >= segments.length) nextIndex = segments.length - 1;

        if (nextIndex !== currentIndex) {
            const nextSeg = segments[nextIndex];

            // Try Tiptap Method first (Cleanest)
            const editor = editorRefs.current[nextSeg.id];
            if (editor) {
                editor.commands.focus('end'); // Focus at end of text
                handleSegmentFocus(nextSeg.id);
                // Ensure scroll
                setTimeout(() => {
                    const el = document.getElementById(`editor-${nextSeg.id}`);
                    if (el) el.scrollIntoView({ behavior: 'smooth', block: 'center' });
                }, 50);
                return;
            }

            // Fallback to DOM (Old way)
            setTimeout(() => {
                const editorEl = document.querySelector(`#editor-${nextSeg.id} .ProseMirror`);
                if (editorEl) {
                    editorEl.focus();
                    handleSegmentFocus(nextSeg.id); // Sync state
                }
            }, 10);
        }
    };

    const handleContextMenu = (e) => {
        // Check if text is selected
        const selection = window.getSelection();
        const selectedText = selection.toString().trim();

        if (selectedText) {
            e.preventDefault(); // Prevent browser menu
            setGlossarySelection(selectedText);
            setShowGlossaryModal(true);
        }
    };



    // Handler for manual AI Draft triggers
    const handleAiDraft = async (segmentId, isAuto = false, mode = "translate", isWorkflow = false) => {
        const seg = segmentsRef.current.find(s => s.id === segmentId); // Use Ref for safety
        if (!isAuto) {
            log(`Generating draft (${mode}) for segment #${seg?.index + 1}...`, 'info', { segmentId });
        }

        try {
            const start = performance.now();
            const updated = await generateDraft(segmentId, mode, isWorkflow);
            const duration = Math.round(performance.now() - start);

            if (!isAuto) {
                log(`Draft generated in ${duration}ms`, 'success', {
                    target_len: updated.target_content?.length,
                    matches: updated.context_matches?.length || 0
                });

                // Trigger Flash
                setFlashingSegments(prev => ({ ...prev, [segmentId]: Date.now() }));
                // Cleanup after animation (2s)
                setTimeout(() => {
                    setFlashingSegments(prev => {
                        const next = { ...prev };
                        delete next[segmentId];
                        return next;
                    });
                }, 2000);
            }

            // Update State
            setSegments(prev => prev.map(s => {
                if (s.id !== segmentId) return s;

                // Mode-based update override
                // "analyze": Only context_matches
                // "draft": ai_draft + context_matches (backend handles field populating, we just merge)
                // "translate": target_content + context_matches

                // Since `updated` comes from backend with correct fields set/unset based on mode:
                // We can just merge everything relevant.

                // NOTE: If mode is "analyze", target_content in `updated` might be OLD or EMPTY depending on backend response.
                // Backend `generate_draft_endpoint`:
                // returns `segment.__dict__` copy.
                // If mode="analyze", target_content is untouched on DB.
                // So `updated` has the CURRENT DB state.

                return { ...s, ...updated };
            }));

            return updated; // Return full object so caller can use target_content
        } catch (err) {
            if (!isAuto) {
                log("AI Draft failed", 'error', err.message);
                console.error("AI Draft failed", err);
                alert("AI Draft creation failed");
            }
            throw err;
        }
    };

    // Focus Handler
    const handleSegmentFocus = async (id) => {
        if (id === activeSegmentId) return;
        setActiveSegmentId(id);

        // Auto-Generate Draft on Focus (if configured)
        const aiSettings = project?.config?.ai_settings || {};
        const isPreloadMode = aiSettings.preload_mode === true;

        // "Iterative way... loaded after the next"
        const preTranslateCount = parseInt(aiSettings.pre_translate_count) || 0;

        if (!isPreloadMode && preTranslateCount > 0) {
            // Find current index
            const currentIndex = segmentsRef.current.findIndex(s => s.id === id);
            if (currentIndex !== -1) {
                // Queue Next N
                const nextSegments = segmentsRef.current.slice(currentIndex, currentIndex + preTranslateCount + 1); // +1 because slice is exclusive? No, we want Current + N ahead?
                // User said "while I am working on one", "segment is loaded after the next"
                // Usually means: Current (if empty) + Next 1 + Next 2...
                const idsToQueue = nextSegments.map(s => s.id);
                queueSegments(idsToQueue);
            }
        }
    };

    if (loading) return <div className="p-8 text-center text-gray-500 animate-pulse">Loading Workspace...</div>;

    // Derive aiSettings from project config for TiptapEditor
    const aiSettings = project?.config?.ai_settings || {};

    return (
        <div className="h-screen flex flex-col">
            <header className="p-4 bg-gray-100 border-b flex justify-between items-center">
                <div className="flex items-center gap-3 w-1/3">
                    <button
                        onClick={onBack}
                        className="p-1.5 rounded-full hover:bg-gray-200 text-gray-500 hover:text-gray-900 transition-colors"
                        title="Back to Projects"
                    >
                        <ArrowLeft size={20} />
                    </button>
                    <h1 className="font-bold text-lg text-gray-800 flex items-center gap-2">
                        <span className="opacity-50">Project:</span> {project?.name || project?.filename}
                    </h1>
                </div>

                {/* Progress Bar */}
                <div className="flex flex-col items-center justify-center w-1/3 max-w-xs mx-4">
                    <div className="flex justify-between w-full text-[10px] text-gray-500 mb-1 uppercase tracking-wider font-semibold">
                        <span>Progress</span>
                        <span>{segments.filter(s => s.status === 'translated').length} / {segments.length}</span>
                    </div>
                    <div className="w-full bg-gray-200 rounded-full h-1.5 overflow-hidden">
                        <div
                            className="bg-green-500 h-full rounded-full transition-all duration-500 ease-out"
                            style={{ width: `${segments.length > 0 ? (segments.filter(s => s.status === 'translated').length / segments.length) * 100 : 0}%` }}
                        ></div>
                    </div>
                </div>

                <div className="flex gap-2 w-1/3 justify-end">
                    <button
                        onClick={() => setShowConsole(!showConsole)}
                        className={`p-2 rounded hover:bg-gray-200 transition-colors ${showConsole ? 'bg-gray-800 text-green-400' : 'text-gray-600'}`}
                        title="Toggle Hacker Console"
                    >
                        <Terminal size={18} />
                    </button>
                    <button
                        onClick={() => setShowDebug(!showDebug)}
                        className={`p-2 rounded hover:bg-gray-200 transition-colors ${showDebug ? 'bg-red-100 text-red-600' : 'text-gray-400'}`}
                        title="Toggle Debug Info"
                    >
                        <Bug size={18} />
                    </button>

                    <button
                        onClick={() => setShowShortcuts(!showShortcuts)}
                        className={`p-2 rounded hover:bg-gray-200 transition-colors ${showShortcuts ? 'bg-indigo-100 text-indigo-600' : 'text-gray-600'}`}
                        title="Keyboard Shortcuts"
                    >
                        <Keyboard size={18} />
                    </button>
                    <div className="w-px h-6 bg-gray-300 mx-1 self-center"></div>

                    <button
                        onClick={() => setShowSettings(true)}
                        className="bg-gray-200 text-gray-700 px-3 py-2 rounded hover:bg-gray-300 flex items-center gap-2"
                        title="Project Settings"
                    >
                        ⚙️ Settings
                    </button>
                    {/* Export Dropdown */}
                    <div className="relative">
                        <div className="inline-flex rounded-md shadow-sm">
                            <button
                                onClick={handleExport}
                                className="bg-green-600 text-white px-4 py-2 rounded-l hover:bg-green-700 font-medium transition-colors flex items-center gap-2"
                            >
                                <Download size={16} /> Export DOCX
                            </button>
                            <button
                                onClick={() => setShowExportMenu(!showExportMenu)}
                                className="bg-green-700 text-white px-2 py-2 rounded-r hover:bg-green-800 transition-colors border-l border-green-600"
                            >
                                <ChevronDown size={16} />
                            </button>
                        </div>
                        {showExportMenu && (
                            <div className="absolute right-0 mt-2 w-48 bg-white rounded-md shadow-lg z-50 border border-gray-100 py-1">
                                <button
                                    onClick={() => { handleExport(); setShowExportMenu(false); }}
                                    className="block w-full text-left px-4 py-2 text-sm text-gray-700 hover:bg-gray-50 bg-green-50/50"
                                >
                                    Download Export (DOCX)
                                </button>
                                <button
                                    onClick={() => { handleTmXExport(); setShowExportMenu(false); }}
                                    className="block w-full text-left px-4 py-2 text-sm text-gray-700 hover:bg-gray-50"
                                >
                                    Download TMX Memory
                                </button>
                            </div>
                        )}
                    </div>
                </div>

                {/* Settings Modal */}
                {showSettings && (
                    <div className="fixed inset-0 bg-black/60 backdrop-blur-sm flex items-center justify-center z-50 p-4">
                        <div className="bg-white rounded-xl shadow-2xl w-full max-w-4xl h-[85vh] flex flex-col overflow-hidden">
                            <div className="p-4 border-b border-gray-100 flex justify-between items-center bg-gray-50">
                                <h2 className="text-xl font-bold text-gray-800">Project Settings</h2>
                                <div className="flex gap-1 bg-gray-200 p-1 rounded-lg">
                                    <button
                                        onClick={() => setActiveSettingsTab('workflows')}
                                        className={`px-4 py-1.5 rounded-md text-sm font-medium transition-all ${activeSettingsTab === 'workflows' ? 'bg-white shadow text-pink-600' : 'text-gray-500 hover:text-gray-700'}`}
                                    >
                                        ⚡ Workflows
                                    </button>
                                    <button
                                        onClick={() => setActiveSettingsTab('files')}
                                        className={`px-4 py-1.5 rounded-md text-sm font-medium transition-all ${activeSettingsTab === 'files' ? 'bg-white shadow text-gray-900' : 'text-gray-500 hover:text-gray-700'}`}
                                    >
                                        Files
                                    </button>
                                    <button
                                        onClick={() => setActiveSettingsTab('rag')}
                                        className={`px-4 py-1.5 rounded-md text-sm font-medium transition-all ${activeSettingsTab === 'rag' ? 'bg-white shadow text-indigo-600' : 'text-gray-500 hover:text-gray-700'}`}
                                    >
                                        RAG & Context
                                    </button>
                                    <button
                                        onClick={() => setActiveSettingsTab('ai')}
                                        className={`px-4 py-1.5 rounded-md text-sm font-medium transition-all ${activeSettingsTab === 'ai' ? 'bg-white shadow text-purple-600' : 'text-gray-500 hover:text-gray-700'}`}
                                    >
                                        AI & Model
                                    </button>
                                    <button
                                        onClick={() => setActiveSettingsTab('glossary')}
                                        className={`px-4 py-1.5 rounded-md text-sm font-medium transition-all ${activeSettingsTab === 'glossary' ? 'bg-white shadow text-green-600' : 'text-gray-500 hover:text-gray-700'}`}
                                    >
                                        📚 Glossary
                                    </button>
                                    <button
                                        onClick={() => setActiveSettingsTab('project')}
                                        className={`px-4 py-1.5 rounded-md text-sm font-medium transition-all ${activeSettingsTab === 'project' ? 'bg-white shadow text-gray-800' : 'text-gray-500 hover:text-gray-700'}`}
                                    >
                                        ⚙️ Project
                                    </button>
                                    <button
                                        onClick={() => setActiveSettingsTab('stats')}
                                        className={`px-4 py-1.5 rounded-md text-sm font-medium transition-all ${activeSettingsTab === 'stats' ? 'bg-white shadow text-blue-600' : 'text-gray-500 hover:text-gray-700'}`}
                                    >
                                        📊 Stats
                                    </button>
                                </div>
                            </div>

                            <div className="flex-1 overflow-hidden p-6 bg-white">
                                {activeSettingsTab === 'files' ? (
                                    <div className="grid grid-cols-1 md:grid-cols-3 gap-6 h-full">
                                        {/* Window 1: Source Files */}
                                        <div className="border border-gray-200 rounded-xl bg-gray-50/50 flex flex-col overflow-hidden">
                                            <h3 className="p-3 bg-white border-b border-gray-100 font-medium text-gray-700 flex items-center gap-2 text-sm uppercase tracking-wide">
                                                📄 Source Files
                                            </h3>
                                            <div className="p-3 overflow-y-auto flex-1 space-y-2">
                                                {project.files && project.files.filter(f => f.category === 'source').length > 0 ? (
                                                    project.files.filter(f => f.category === 'source').map(f => (
                                                        <div key={f.id} className="text-sm bg-white p-2.5 rounded border border-gray-200 shadow-sm truncate text-gray-700 font-mono" title={f.filename}>
                                                            {f.filename}
                                                        </div>
                                                    ))
                                                ) : (
                                                    <p className="text-gray-400 text-sm italic p-2">No source files</p>
                                                )}
                                            </div>
                                        </div>

                                        {/* Window 2: Legal/Reference Files */}
                                        <div className="border border-indigo-100 rounded-xl bg-indigo-50/30 flex flex-col overflow-hidden">
                                            <h3 className="p-3 bg-white border-b border-indigo-50 font-medium text-indigo-700 flex items-center gap-2 text-sm uppercase tracking-wide">
                                                ⚖️ Legal / Reference
                                            </h3>
                                            <div className="p-3 overflow-y-auto flex-1 space-y-2">
                                                {project.files && project.files.filter(f => f.category === 'legal').length > 0 ? (
                                                    project.files.filter(f => f.category === 'legal').map(f => (
                                                        <div key={f.id} className="text-sm bg-white p-2.5 rounded border border-indigo-100 shadow-sm truncate text-indigo-700 font-mono" title={f.filename}>
                                                            {f.filename}
                                                        </div>
                                                    ))
                                                ) : (
                                                    <p className="text-indigo-300 text-sm italic p-2">No legal files</p>
                                                )}
                                            </div>
                                        </div>

                                        {/* Window 3: Background Files */}
                                        <div className="border border-blue-100 rounded-xl bg-blue-50/30 flex flex-col overflow-hidden">
                                            <h3 className="p-3 bg-white border-b border-blue-50 font-medium text-blue-700 flex items-center gap-2 text-sm uppercase tracking-wide">
                                                📚 Background
                                            </h3>
                                            <div className="p-3 overflow-y-auto flex-1 space-y-2">
                                                {project.files && project.files.filter(f => f.category === 'background').length > 0 ? (
                                                    project.files.filter(f => f.category === 'background').map(f => (
                                                        <div key={f.id} className="text-sm bg-white p-2.5 rounded border border-blue-100 shadow-sm truncate text-blue-700 font-mono" title={f.filename}>
                                                            {f.filename}
                                                        </div>
                                                    ))
                                                ) : (
                                                    <p className="text-blue-300 text-sm italic p-2">No background files</p>
                                                )}
                                            </div>
                                        </div>
                                    </div>
                                ) : activeSettingsTab === 'rag' ? (
                                    <RAGSettingsTab project={project} onUpdate={setProject} />
                                ) : activeSettingsTab === 'ai' ? (
                                    <AISettingsTab
                                        project={project}
                                        onUpdate={setProject}
                                        onQueueAll={() => queueSegments(segments.map(s => s.id))}
                                    />
                                ) : activeSettingsTab === 'glossary' ? (
                                    <GlossarySettingsTab project={project} onUpdate={setProject} />
                                ) : activeSettingsTab === 'stats' ? (
                                    <StatisticsSettingsTab project={{ ...project, segments: segments }} />
                                ) : activeSettingsTab === 'workflows' ? (
                                    <WorkflowsTab
                                        project={project}
                                        segments={segments}
                                        onQueueAll={queueSegments}
                                        onReingest={handleReingest}
                                    />
                                ) : activeSettingsTab === 'project' ? (
                                    <ProjectSettingsTab project={project} onUpdate={setProject} />
                                ) : null}
                            </div>

                            <div className="p-4 border-t border-gray-100 bg-gray-50 flex justify-between items-center">
                                <button
                                    onClick={handleDeleteProject}
                                    className="text-red-500 text-sm hover:text-red-700 font-medium px-2 py-1 rounded hover:bg-red-50 transition-colors"
                                >
                                    🗑️ Delete Project
                                </button>
                                <button
                                    onClick={() => setShowSettings(false)}
                                    className="bg-gray-800 text-white px-6 py-2 rounded-lg hover:bg-black transition-all shadow-sm font-medium"
                                >
                                    Close
                                </button>
                            </div>
                        </div>
                    </div>
                )}
            </header>

            {/* Glossary Add Modal */}
            {showGlossaryModal && (
                <GlossaryAddModal
                    projectId={projectId}
                    initialSource={glossarySelection}
                    onClose={() => setShowGlossaryModal(false)}
                    onSuccess={() => {
                        // Optional: Show toast or just close
                        // alert("Term added!");
                    }}
                />
            )}

            <div className="flex-1 overflow-auto p-4 bg-gray-50/50">
                <div className="max-w-7xl mx-auto space-y-4">
                    {segments.map((seg) => {
                        const comments = getSegmentComments(seg.tags);
                        const hasContext = (seg.context_matches?.length > 0 || seg.metadata?.context_matches?.length > 0);

                        // Logic for UI Highlight:
                        // User wants to see "light red" background if 100% Mandatory Match exists (and likely pre-filled).
                        const allMatches = seg.context_matches || seg.metadata?.context_matches || [];
                        const mandatoryMatch = allMatches.find(m => m.type === 'mandatory' && m.score >= 98);
                        const isMandatoryContext = !!mandatoryMatch;

                        return (
                            <div key={seg.id} className="grid grid-cols-1 lg:grid-cols-2 gap-4 bg-white rounded-xl shadow-sm border border-gray-200 overflow-hidden group hover:shadow-md transition-shadow">
                                {/* Source Column */}
                                <div className="p-5 bg-gray-50/80 rounded-l-xl text-sm leading-relaxed border-r border-gray-100 flex flex-col relative">
                                    <div className="absolute top-2 right-2 opacity-0 group-hover:opacity-100 transition-opacity text-xs text-gray-300 font-mono pointer-events-none">#{seg.index + 1}</div>

                                    {/* Source Text (Tiptap ReadOnly with Invisible Chars) */}
                                    <div className="flex-grow">
                                        <TiptapEditor
                                            content={formatSourceContent(seg.source_content, seg.tags, true)}
                                            isReadOnly={true}
                                            chromeless={true}
                                            availableTags={seg.tags}
                                            // Pass ID mostly for hydration or future keys
                                            segmentId={`source-${seg.id}`}
                                        />
                                    </div>

                                    {/* Comments Section */}
                                    {comments.length > 0 && (
                                        <div className="mt-4 pt-3 border-t border-gray-200 text-xs text-gray-600 bg-yellow-50 -mx-5 -mb-5 p-4">
                                            <div className="font-semibold mb-1 flex items-center gap-2 text-yellow-700">
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
                                    {showDebug && (
                                        <div className="mt-4 p-1 bg-red-50 text-[10px] font-mono text-red-500 border border-red-200 rounded break-all opacity-50 hover:opacity-100 transition-opacity">
                                            DEBUG Source-DB: {seg.tags ? "HAS TAGS" : "NO TAGS"}
                                        </div>
                                    )}

                                    {/* Context Panel (Matches) */}
                                    {/* Context Panel (Matches) */}
                                    {hasContext && (
                                        <div className="mt-6 border-t border-gray-200 pt-4">
                                            <div className="flex justify-between items-center mb-3">
                                                <h4 className="text-[10px] font-bold text-gray-400 uppercase tracking-widest flex items-center gap-2">
                                                    <span className="w-1 h-1 bg-gray-400 rounded-full"></span> Translation Memory / Context
                                                </h4>
                                                <button
                                                    onClick={() => handleAiDraft(seg.id)}
                                                    className="text-gray-400 hover:text-indigo-600 transition-colors"
                                                    title="Refresh Context (Cmd+Alt+ß / Cmd+Alt+?)"
                                                >
                                                    <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15"></path></svg>
                                                </button>
                                            </div>
                                            <div className="space-y-2">
                                                {(() => {
                                                    const sortedMatches = (seg.context_matches || seg.metadata.context_matches || [])
                                                        .sort((a, b) => (b.score || 0) - (a.score || 0));

                                                    const tmMatches = sortedMatches.filter(m => m.type !== 'mt');

                                                    return sortedMatches.map((match, idx) => {
                                                        const isMandatory = match.type === 'mandatory';
                                                        const isMT = match.type === 'mt';
                                                        const isGlossary = match.type === 'glossary';

                                                        // FILTERING: Check Thresholds
                                                        const aiConfig = project?.config?.ai_settings || {};
                                                        const tMandatory = aiConfig.threshold_mandatory !== undefined ? aiConfig.threshold_mandatory : 60;
                                                        const tOptional = aiConfig.threshold_optional !== undefined ? aiConfig.threshold_optional : 40;

                                                        const score = match.score || 0;

                                                        // Apply Filter
                                                        if (isGlossary) {
                                                            // Always show glossary
                                                        } else if (isMandatory) {
                                                            if (score < tMandatory) return null;
                                                        } else if (!isMT) {
                                                            // Optional / Archive
                                                            if (score < tOptional) return null;
                                                        }

                                                        // Determine shortcut label index
                                                        let shortcutLabel = '';
                                                        if (isMT) {
                                                            shortcutLabel = 'Cmd+Opt+0';
                                                        } else if (isGlossary) {
                                                            // Provide a shortcut? Maybe not for now, or use first slot
                                                        } else {
                                                            const tmIdx = tmMatches.indexOf(match);
                                                            if (tmIdx === 0) shortcutLabel = 'Cmd+Opt+9';
                                                            else if (tmIdx === 1) shortcutLabel = 'Cmd+Opt+8';
                                                            else if (tmIdx === 2) shortcutLabel = 'Cmd+Opt+7';
                                                        }

                                                        // Styles
                                                        let borderClass = isMandatory ? 'border-l-red-500' : 'border-l-blue-400';
                                                        let bgClass = 'bg-white';
                                                        let textClass = isMandatory ? 'text-red-700' : 'text-blue-700';
                                                        let label = isMandatory ? '⚖️ Vorgabe' : '💡 Vorschlag aus Archiv';

                                                        if (isMT) {
                                                            borderClass = 'border-l-purple-500';
                                                            bgClass = 'bg-purple-50';
                                                            textClass = 'text-purple-700';
                                                            label = '🤖 Machine Translation';

                                                            // Apply Flash if needed
                                                            if (flashingSegments[seg.id]) {
                                                                bgClass = 'animate-flash-purple';
                                                                // Note: keyframes handle bg color. 
                                                                // If we want it to stay purple-50 after, the keyframe 100% matches it.
                                                            }
                                                        } else if (isGlossary) {
                                                            borderClass = 'border-l-teal-500';
                                                            bgClass = 'bg-teal-50';
                                                            textClass = 'text-teal-700';
                                                            label = '📚 Glossary Term';
                                                        }

                                                        return (
                                                            <div key={idx} className={`p-2.5 rounded border transition-all hover:shadow-sm ${bgClass} ${borderClass} border-gray-200`}>
                                                                <div className="flex justify-between items-start mb-1">
                                                                    <div className="flex items-center gap-2">
                                                                        <span className={`text-[10px] font-bold uppercase tracking-wider flex items-center gap-1 ${textClass}`}>
                                                                            {label}
                                                                        </span>
                                                                        {match.score !== undefined && !isMT && (
                                                                            <span className={`text-[9px] font-bold px-1.5 rounded-full ${match.score > 85 ? 'bg-green-100 text-green-700' : 'bg-gray-100 text-gray-600'}`}>
                                                                                {match.score}%
                                                                            </span>
                                                                        )}
                                                                        {/* Shortcut Hint */}
                                                                        <span className="text-[9px] font-mono text-gray-400 bg-white/50 px-1 rounded border border-gray-100 opacity-0 group-hover:opacity-100 transition-opacity">
                                                                            {shortcutLabel}
                                                                        </span>
                                                                    </div>
                                                                    <div className="flex items-center gap-1 text-[9px] text-gray-400 font-mono" title={match.filename}>
                                                                        <span className="truncate max-w-[100px]">
                                                                            {isMT ? (project?.config?.ai_settings?.model || match.filename) : match.filename}
                                                                        </span>
                                                                    </div>
                                                                </div>

                                                                {/* Content - Smart Sentence Display */}
                                                                <div
                                                                    className="text-gray-800 text-[13px] leading-snug font-source selection:bg-yellow-100"
                                                                    dangerouslySetInnerHTML={{ __html: formatSourceContent(match.content, null, false) }}
                                                                />
                                                                {/* Note info */}
                                                                {match.note && (
                                                                    <div className="mt-1 text-[10px] text-gray-500 italic border-t border-gray-200/50 pt-1">
                                                                        Note: {match.note}
                                                                    </div>
                                                                )}
                                                            </div>
                                                        )
                                                    })
                                                })()}
                                            </div>
                                        </div>
                                    )}
                                </div>

                                {/* Target Column */}
                                <div className={`p-5 rounded-r-xl flex flex-col relative group ${isMandatoryContext ? 'bg-red-50/80 border-l border-red-200' : 'bg-white'}`}>
                                    <div className="text-xs text-gray-400 font-mono mb-2 uppercase tracking-wider flex justify-between items-center select-none">
                                        <div className="flex items-center gap-2">
                                            <span className={`font-bold transition-colors ${isMandatoryContext ? 'text-red-800' : 'text-gray-300 group-hover:text-indigo-400'}`}>
                                                {isMandatoryContext ? '⚠️ Mandatory Target' : 'Target (DE)'}
                                            </span>
                                            {/* Context Badges */}
                                            {seg.metadata && (
                                                <div className="flex gap-1">
                                                    {seg.metadata.type === 'header' && (
                                                        <span className="bg-purple-50 text-purple-600 px-1.5 py-0.5 rounded text-[9px] font-bold border border-purple-100">H</span>
                                                    )}
                                                    {(seg.metadata.type === 'table' || seg.metadata.child_type === 'table_cell') && (
                                                        <span className="bg-blue-50 text-blue-600 px-1.5 py-0.5 rounded text-[9px] font-bold border border-blue-100">Tb</span>
                                                    )}
                                                </div>
                                            )}
                                        </div>
                                        <span className={`px-2 py-0.5 rounded-full text-[9px] font-bold border ${seg.status === 'draft' ? 'bg-yellow-50 text-yellow-600 border-yellow-100' :
                                            seg.status === 'translated' ? 'bg-green-50 text-green-600 border-green-100' : 'bg-gray-50 border-gray-100'
                                            }`}>
                                            {seg.status}
                                        </span>
                                    </div>

                                    <div className="flex-grow">
                                        <TiptapEditor
                                            content={hydrateContent(seg.target_content || seg.context_matches?.find(m => m.type === 'mt')?.content, seg.tags)}
                                            segmentId={seg.id}
                                            availableTags={seg.tags}
                                            contextMatches={seg.context_matches || (seg.metadata && seg.metadata.context_matches)}
                                            onSave={handleSave}
                                            aiSettings={aiSettings}
                                            onAiDraft={handleAiDraft}
                                            onFocus={() => handleSegmentFocus(seg.id)}
                                            onNavigate={(dir) => handleNavigation(seg.id, dir)}
                                            onEditorReady={(ed) => editorRefs.current[seg.id] = ed}
                                        />
                                    </div>

                                    {/* DEBUG: Show raw target content sent to backend */}
                                    {showDebug && (
                                        <div className="mt-2 text-[9px] text-gray-300 font-mono break-all opacity-0 group-hover:opacity-50 transition-opacity">
                                            DB: {seg.target_content || '(empty)'}
                                        </div>
                                    )}
                                </div>
                            </div>
                        )
                    })}
                </div>
            </div>

            {/* Hacker Console */}
            <LogConsole
                logs={logs}
                isOpen={showConsole}
                onClose={() => setShowConsole(false)}
                onClear={() => setLogs([])}
            />

            <ShortcutsPanel isOpen={showShortcuts} onClose={() => setShowShortcuts(false)} />

            {/* Reinit Modal */}
            {isReinitializing && (
                <div className="fixed inset-0 bg-black/70 backdrop-blur-sm flex items-center justify-center z-[100] p-4">
                    <div className="bg-white rounded-xl shadow-2xl w-full max-w-lg p-6 flex flex-col gap-4">
                        <div className="flex items-center gap-3">
                            <div className={`p-3 rounded-full ${reinitStatus === 'ready' ? 'bg-green-100 text-green-600' : 'bg-blue-50 text-blue-600'}`}>
                                {reinitStatus === 'ready' ? <Check size={24} /> : (
                                    <div className="animate-spin rounded-full h-6 w-6 border-b-2 border-blue-600"></div>
                                )}
                            </div>
                            <div>
                                <h3 className="text-lg font-bold text-gray-800">
                                    {reinitStatus === 'ready' ? "Re-initialization Complete" : "Re-initializing Project..."}
                                </h3>
                                <p className="text-sm text-gray-500">
                                    {reinitStatus === 'ready' ? "You can now reload the project." : "Parsing files and generating vectors..."}
                                </p>
                            </div>
                        </div>

                        {/* Progress Bar */}
                        <div className="w-full bg-gray-100 rounded-full h-2 overflow-hidden relative">
                            {reinitStatus === 'ready' ? (
                                <div className="bg-green-500 h-full w-full transition-all duration-500"></div>
                            ) : (
                                <div className="bg-blue-500 h-full w-1/3 absolute top-0 left-0 bottom-0 animate-ping" style={{ animationDuration: '2s', width: '100%', opacity: 0.3 }}></div>
                            )}
                            {reinitStatus !== 'ready' && (
                                <div className="bg-blue-600 h-full w-1/3 absolute top-0 animate-pulse"></div>
                            )}
                        </div>

                        {/* Logs */}
                        <div className="bg-gray-900 rounded-lg p-3 h-48 overflow-y-auto font-mono text-[10px] text-green-400 flex flex-col-reverse">
                            {reinitLogs && reinitLogs.length > 0 ? reinitLogs.slice().reverse().map((l, i) => (
                                <div key={i} className="border-b border-gray-800/50 pb-0.5 mb-0.5 last:border-0">{l}</div>
                            )) : <div className="text-gray-500 italic">Waiting for logs...</div>}
                        </div>

                        <div className="flex justify-end gap-2 mt-2">
                            {reinitStatus === 'ready' ? (
                                <div className="flex gap-2">
                                    <button
                                        onClick={() => window.location.reload()}
                                        className="px-4 py-2 bg-green-600 text-white rounded hover:bg-green-700 font-medium shadow-sm"
                                    >
                                        Reload Project
                                    </button>
                                    <button
                                        onClick={() => setIsReinitializing(false)}
                                        className="px-4 py-2 bg-gray-200 text-gray-700 rounded hover:bg-gray-300"
                                    >
                                        Close
                                    </button>
                                </div>
                            ) : (
                                <button
                                    disabled
                                    className="px-4 py-2 bg-gray-100 text-gray-400 rounded cursor-not-allowed border border-gray-200"
                                >
                                    Processing...
                                </button>
                            )}
                        </div>
                    </div>
                </div>
            )}

        </div>
    );
};

import { useState, useRef, useEffect } from 'react';
import { generateDraft, reingestProject, reinitializeProject, getProject, batchTranslate, tcBatchTranslate, sequentialTranslate, resetWorkflowStatus } from "../api/client";

export function useBlockingTask(projectId, { segmentsRef, setSegments, projectRef, activeFileId, onRefresh, clearAIQueue }) {
    const [blockingTask, setBlockingTask] = useState({
        isOpen: false,
        type: null,
        status: 'idle',
        logs: [],
        title: "",
        progress: -1
    });

    const stopRef = useRef(false);

    // Ref to avoid stale closure for activeFileId
    const activeFileIdRef = useRef(activeFileId);
    activeFileIdRef.current = activeFileId;

    // Helper: filter segments by active file dropdown (null = all files)
    const getFilteredSegments = () => {
        const fid = activeFileIdRef.current;
        if (!fid) return segmentsRef.current;
        return segmentsRef.current.filter(s => s.file_id === fid);
    };

    const getFileLabel = () => {
        const fid = activeFileIdRef.current;
        if (!fid) return null;
        const seg = segmentsRef.current.find(s => s.file_id === fid);
        return seg?.filename || 'selected file';
    };

    // Polling Logic
    useEffect(() => {
        let interval;
        if (blockingTask.isOpen && blockingTask.type === 'reinit' && blockingTask.status === 'running') {
            interval = setInterval(async () => {
                try {
                    const p = await getProject(projectId);
                    setBlockingTask(prev => {
                        const newLogs = p.ingestion_logs || [];
                        if (newLogs.length > prev.logs.length) {
                            return { ...prev, logs: newLogs };
                        }
                        return prev;
                    });

                    if (p.rag_status === 'ready') {
                        setBlockingTask(prev => ({ ...prev, status: 'done', logs: [...(p.ingestion_logs || []), "Ingestion Complete."], progress: 1 }));
                        if (clearAIQueue) clearAIQueue();
                        if (onRefresh) onRefresh();
                        clearInterval(interval);
                    } else if (p.rag_status === 'error') {
                        setBlockingTask(prev => ({ ...prev, status: 'error', logs: [...(p.ingestion_logs || []), "Ingestion Failed."], progress: 1 }));
                        clearInterval(interval);
                    } else {
                        // Update Progress (Backend sends 0-100 int, Frontend expects 0-1 float)
                        if (p.rag_progress !== undefined) {
                            setBlockingTask(prev => ({ ...prev, progress: p.rag_progress / 100 }));
                        }
                    }
                } catch (e) { console.error(e); }
            }, 1000);
        }
        return () => clearInterval(interval);
    }, [blockingTask.isOpen, blockingTask.type, blockingTask.status, projectId]);

    const handleAutoTranslate = async () => {
        const aiSettings = projectRef.current?.config?.ai_settings || {};
        const modelName = aiSettings.model || "Default";
        const fileLabel = getFileLabel();
        const scope = fileLabel ? `for '${fileLabel}'` : '';

        if (!confirm(`Start Auto-Translate (High Quality) ${scope}?\n\nModel: ${modelName}`)) return;

        const candidates = getFilteredSegments().filter(s => s.status !== 'translated' && s.status !== 'approved');
        if (candidates.length === 0) {
            alert("No untranslated segments found!");
            return;
        }

        stopRef.current = false;
        setBlockingTask({
            isOpen: true,
            type: 'autotranslate',
            status: 'running',
            title: `Auto-Translating (${candidates.length} segments)`,
            logs: [`Starting batch job...`],
            progress: 0
        });

        let processed = 0;
        let errors = 0;

        for (const seg of candidates) {
            if (stopRef.current) {
                setBlockingTask(prev => ({ ...prev, status: 'error', logs: [...prev.logs, "Stopped."] }));
                return;
            }

            try {
                document.getElementById(`segment-${seg.id}`)?.scrollIntoView({ block: "center", behavior: "smooth" });
                setBlockingTask(prev => ({
                    ...prev,
                    logs: [...prev.logs.slice(-4), `Translating #${seg.index + 1}...`],
                    progress: processed / candidates.length
                }));
                const res = await generateDraft(seg.id, "translate", false);
                setSegments(prev => prev.map(s => s.id === seg.id ? { ...s, ...res.segment } : s));
            } catch (err) {
                console.error(err);
                errors++;
                setBlockingTask(prev => ({ ...prev, logs: [...prev.logs, `Error #${seg.index + 1}: ${err.message}`] }));
            }
            processed++;
        }

        setBlockingTask(prev => ({
            ...prev,
            status: 'done',
            title: "Translation Complete",
            progress: 1,
            logs: [...prev.logs, `Finished. Processed: ${processed}, Errors: ${errors}`]
        }));
    };

    const handleFullReinit = async (file = null) => {
        // Confirmation is handled by Modal now if file is involved, 
        // but if called directly we might want confirmation?
        // Let's assume Modal checks.
        // But if file is null, we should confirm if not already confirmed?
        // The modal confirms action.

        if (clearAIQueue) clearAIQueue(); // Stop any pending lookaheads immediately

        setBlockingTask({
            isOpen: true,
            type: 'reinit',
            status: 'running',
            title: file ? "Replacing Source & Re-initializing..." : "Re-initializing Project...",
            logs: ["Starting backend process..."],
            progress: -1
        });
        try {
            await reinitializeProject(projectId, file);
            setBlockingTask(prev => ({ ...prev, logs: [...prev.logs, "Processing source file..."] }));
        } catch (err) {
            setBlockingTask(prev => ({ ...prev, status: 'error', logs: [...prev.logs, `Error: ${err.message}`] }));
        }
    };

    const handleReingest = async () => {
        if (!confirm("Clear vectors and re-process?")) return;
        try {
            await reingestProject(projectId);
            setBlockingTask({
                isOpen: true,
                type: 'reinit',
                status: 'running',
                title: "Re-ingesting Context...",
                logs: ["Request sent..."],
                progress: -1
            });
        } catch (e) { alert("Failed: " + e.message); }
    };

    const handleBatchProcess = async (mode) => {
        const aiSettings = projectRef.current?.config?.ai_settings || {};
        const workflowModel = aiSettings.workflow_model || "Fast Model";
        const fileLabel = getFileLabel();
        const scope = fileLabel ? ` for '${fileLabel}'` : '';

        const modeLabel = mode === 'analyze' ? "Pre-Analysis" : mode === 'draft' ? "Pre-Translate" : "Machine Translation";

        // Filter Candidates (respect file dropdown)
        // analyze + draft = all segments; translate = only empty
        const base = getFilteredSegments();
        let candidates = mode === 'translate' ? base.filter(s => !s.target_content) : base;

        if (candidates.length === 0) {
            alert("No applicable segments found.");
            return;
        }

        const modelInfo = mode === 'analyze' ? 'Retrieval only (no LLM)' : `Model: ${workflowModel}`;
        if (!confirm(`Start ${modeLabel}${scope}?\n\nSegments: ${candidates.length}\n${modelInfo}`)) return;

        stopRef.current = false;
        setBlockingTask({
            isOpen: false,
            type: 'batch',
            status: 'running',
            title: `${modeLabel} (${candidates.length} segments)`,
            logs: [],
            progress: 0
        });

        try {
            // Fire-and-forget: send ALL IDs, backend handles internal batching
            const candidateIds = candidates.map(s => s.id);
            await batchTranslate(projectId, candidateIds, mode);
            if (onRefresh) onRefresh();
        } catch (err) {
            setBlockingTask(prev => ({
                ...prev,
                status: 'error',
                logs: [`Error: ${err.message}`]
            }));
        }
    };

    const handleTCBatch = async () => {
        const aiSettings = projectRef.current?.config?.ai_settings || {};
        const workflowModel = aiSettings.workflow_model || "Fast Model";

        // Count TC segments
        const tcSegments = segmentsRef.current.filter(s => s.metadata?.has_track_changes);
        if (tcSegments.length === 0) {
            alert("No Track Changes segments found in this project.");
            return;
        }

        if (!confirm(`Start TC Step-by-Step Translation?\n\nTC Segments: ${tcSegments.length}\nModel: ${workflowModel}\n\nThis translates each revision stage and generates TC markup.`)) return;

        stopRef.current = false;
        setBlockingTask({
            isOpen: false,
            type: 'tc_batch',
            status: 'running',
            title: `TC Step-by-Step (${tcSegments.length} segments)`,
            logs: [],
            progress: 0
        });

        try {
            // Fire-and-forget: backend handles everything, auto-poll tracks progress
            await tcBatchTranslate(projectId);
            if (onRefresh) onRefresh();
        } catch (err) {
            setBlockingTask(prev => ({
                ...prev,
                status: 'error',
                logs: [`Error: ${err.message}`]
            }));
        }
    };

    const handleSequentialTranslate = async () => {
        const aiSettings = projectRef.current?.config?.ai_settings || {};
        const workflowModel = aiSettings.workflow_model || "Fast Model";
        const fileLabel = getFileLabel();
        const scope = fileLabel ? ` for '${fileLabel}'` : '';

        // Count empty segments (respect file filter)
        const emptySegments = getFilteredSegments().filter(s => !s.target_content);
        if (emptySegments.length === 0) {
            alert("No empty segments to translate.");
            return;
        }

        if (!confirm(`Start Sequential Translation${scope} (1-by-1 with Auto-Glossary)?\n\nEmpty Segments: ${emptySegments.length}\nModel: ${workflowModel}\n\nThis is slower but builds terminology as it goes.`)) return;

        stopRef.current = false;
        setBlockingTask({
            isOpen: false,
            type: 'sequential',
            status: 'running',
            title: `Sequential Translation${scope} (${emptySegments.length} segments)`,
            logs: [],
            progress: 0
        });

        try {
            // Fire-and-forget: backend handles everything, auto-poll tracks progress
            const segmentIds = activeFileIdRef.current ? emptySegments.map(s => s.id) : null;
            await sequentialTranslate(projectId, segmentIds);
            // Refresh project state so auto-poll + WorkflowIndicator activate immediately
            if (onRefresh) onRefresh();
        } catch (err) {
            setBlockingTask(prev => ({
                ...prev,
                status: 'error',
                logs: [`Error: ${err.message}`]
            }));
        }
    };

    const cancelWorkflow = async () => {
        stopRef.current = true;
        try {
            await resetWorkflowStatus(projectId);
            setBlockingTask(prev => ({ ...prev, status: 'idle', isOpen: false }));
            if (onRefresh) onRefresh();
        } catch (err) {
            console.error('Cancel failed:', err);
        }
    };

    return {
        blockingTask, setBlockingTask,
        stopRef,
        cancelWorkflow,
        handleAutoTranslate,
        handleFullReinit,
        handleReingest,
        handleBatchProcess,
        handleTCBatch,
        handleSequentialTranslate
    };
}

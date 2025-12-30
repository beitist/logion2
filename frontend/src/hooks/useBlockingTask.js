import { useState, useRef, useEffect } from 'react';
import { generateDraft, reingestProject, reinitializeProject, getProject, batchTranslate, getSegments } from "../api/client";

export function useBlockingTask(projectId, { segmentsRef, setSegments, projectRef }) {
    const [blockingTask, setBlockingTask] = useState({
        isOpen: false,
        type: null,
        status: 'idle',
        logs: [],
        title: "",
        progress: -1
    });

    const stopRef = useRef(false);

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

        if (!confirm(`Start Auto-Translate (High Quality)?\n\nModel: ${modelName}`)) return;

        const candidates = segmentsRef.current.filter(s => s.status !== 'translated' && s.status !== 'approved');
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

    const handleFullReinit = async () => {
        if (!confirm("Re-initialize Project? Translations preserved.")) return;
        setBlockingTask({
            isOpen: true,
            type: 'reinit',
            status: 'running',
            title: "Re-initializing Project...",
            logs: ["Starting..."],
            progress: -1
        });
        try {
            await reinitializeProject(projectId);
            setBlockingTask(prev => ({ ...prev, logs: [...prev.logs, "Backend process started..."] }));
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
                title: "Re-ingesting Project...",
                logs: ["Request sent..."],
                progress: -1
            });
        } catch (e) { alert("Failed: " + e.message); }
    };

    // Generic Batch Processor
    const handleBatchProcess = async (mode) => {
        const aiSettings = projectRef.current?.config?.ai_settings || {};
        const batchSize = aiSettings.batch_size || 10;
        const workflowModel = aiSettings.workflow_model || "Fast Model";

        const modeLabel = mode === 'draft' ? "Pre-Translate" : "Machine Translation";
        if (!confirm(`Start ${modeLabel}?\n\nModel: ${workflowModel}\nBatch Size: ${batchSize}`)) return;

        // Filter Candidates
        let candidates = [];
        if (mode === 'draft') {
            // Pre-Translate: Process ALL segments (update drafts)
            candidates = segmentsRef.current;
        } else {
            // Machine Translation: Process only EMPTY targets (fill gaps)
            candidates = segmentsRef.current.filter(s => !s.target_content);
        }

        if (candidates.length === 0) {
            alert("No applicable segments found.");
            return;
        }

        stopRef.current = false;
        setBlockingTask({
            isOpen: true,
            type: 'batch',
            status: 'running',
            title: `${modeLabel} (${candidates.length})`,
            logs: [`Starting ${modeLabel}...`, `Batch Size: ${batchSize}`],
            progress: 0
        });

        let processed = 0;
        let errors = 0;

        // Chunking
        for (let i = 0; i < candidates.length; i += batchSize) {
            if (stopRef.current) {
                setBlockingTask(prev => ({ ...prev, status: 'error', logs: [...prev.logs, "Stopped by user."] }));
                break;
            }

            const batch = candidates.slice(i, i + batchSize);
            const batchIds = batch.map(s => s.id);

            try {
                setBlockingTask(prev => ({
                    ...prev,
                    logs: [...prev.logs.slice(-4), `Processing batch ${Math.floor(i / batchSize) + 1}...`],
                    progress: processed / candidates.length
                }));

                // Call Batch API
                await batchTranslate(projectId, batchIds, mode);

                // Refresh Frontend State (Naive: Fetch all segments to ensure consistency)
                // Optimization: Be optimistic? No, safer to fetch or we miss side-effects.
                // Or better: The API returns list of updated segments? 
                // Currently API returns success status. Implementation Plan says "Bulk update DB".
                // We should re-fetch segments for the updated range or all.
                // Fetching all is safest for now.

                // Partially update memory for smoothness?
                // Real: Fetch only updated? We don't have endpoint for "get segments by ids".
                // Let's silent re-fetch all for sync.
                const updatedSegments = await getSegments(projectId);
                setSegments(updatedSegments.segments || updatedSegments); // Handle if wrapper used

            } catch (err) {
                console.error(err);
                errors += batch.length; // Assume whole batch failed
                setBlockingTask(prev => ({ ...prev, logs: [...prev.logs, `Batch Error: ${err.message}`] }));
            }

            processed += batch.length;
        }

        setBlockingTask(prev => ({
            ...prev,
            status: 'done',
            title: "Workflow Complete",
            progress: 1,
            logs: [...prev.logs, `Done. Processed: ${processed}, Errors: ${errors}`]
        }));
    };

    return {
        blockingTask, setBlockingTask,
        stopRef,
        handleAutoTranslate, // Legacy (Sequential)
        handleFullReinit,
        handleReingest,
        handleBatchProcess // New
    };
}

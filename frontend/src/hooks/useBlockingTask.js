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

    const handleFullReinit = async (file = null) => {
        // Confirmation is handled by Modal now if file is involved, 
        // but if called directly we might want confirmation?
        // Let's assume Modal checks.
        // But if file is null, we should confirm if not already confirmed?
        // The modal confirms action.

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
                title: "Re-ingesting Project...",
                logs: ["Request sent..."],
                progress: -1
            });
        } catch (e) { alert("Failed: " + e.message); }
    };

    // State Tracking Helper
    const updateWorkflowState = async (status, mode = null) => {
        if (!projectRef.current) return;
        const currentConfig = projectRef.current.config || {};
        const workflowState = status === 'idle' ? null : {
            status,
            active_mode: mode,
            timestamp: Date.now()
        };

        // Optimistic update? No, rely on refetch for safety or local ref
        // deep merge config
        const newConfig = { ...currentConfig, workflow: workflowState };

        try {
            // We use the client directly to avoid circular hook dependency if possible
            // But we need to import updateProject
            const { updateProject } = require("../api/client");
            await updateProject(projectId, { config: newConfig });
        } catch (e) {
            console.error("Failed to update workflow state in DB", e);
        }
    };

    const handleBatchProcess = async (mode, options = {}) => {
        const { resume = false } = options;
        const aiSettings = projectRef.current?.config?.ai_settings || {};
        const batchSize = aiSettings.batch_size || 10;
        const workflowModel = aiSettings.workflow_model || "Fast Model";

        const modeLabel = mode === 'draft' ? "Pre-Translate" : "Machine Translation";

        // Confirmation (Skip if resuming autonomously, but usually user triggers resume)
        if (!resume && !confirm(`Start ${modeLabel}?\n\nModel: ${workflowModel}\nBatch Size: ${batchSize}`)) return;

        // Filter Candidates
        let candidates = [];
        if (mode === 'draft') {
            // Pre-Translate: Process ALL segments (update drafts)
            // If Resuming, skip those that already have ai_draft and match the model
            candidates = segmentsRef.current;
            if (resume) {
                candidates = candidates.filter(s => !s.metadata?.ai_draft);
            }
        } else {
            // Machine Translation: Process only EMPTY targets (fill gaps)
            candidates = segmentsRef.current.filter(s => !s.target_content);
            // Resume for Translate is implicit as we filter fulfilled ones
        }

        if (candidates.length === 0) {
            alert("No applicable segments found.");
            // Clear state if we were trying to resume
            if (resume) updateWorkflowState('idle');
            return;
        }

        stopRef.current = false;
        setBlockingTask({
            isOpen: true,
            type: 'batch',
            status: 'running',
            title: `${modeLabel} ${resume ? '(Resuming)' : ''} (${candidates.length})`,
            logs: [`Starting ${modeLabel}...`, `Batch Size: ${batchSize}`],
            progress: 0
        });

        // Track Start in DB
        await updateWorkflowState('running', mode);

        let processed = 0;
        let errors = 0;

        // Chunking
        for (let i = 0; i < candidates.length; i += batchSize) {
            if (stopRef.current) {
                setBlockingTask(prev => ({ ...prev, status: 'error', logs: [...prev.logs, "Stopped by user."] }));
                // Track Paused (or Idle if strict stop)
                // User said "erase ephemeral data" if they say NO to resume. 
                // But here we just stop. We should leave it as 'running' or set to 'paused' so on reload we ask?
                // Let's set to 'running' (idempotent) or 'paused'.
                // If we set 'idle', we lose progress tracking.
                // Let's leave it as is (so on reload it detects 'running' and asks).
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

                // Refresh Frontend State (Sync)
                // fetch full validation
                const updatedSegments = await getSegments(projectId);
                setSegments(updatedSegments.segments || updatedSegments);

            } catch (err) {
                console.error(err);
                errors += batch.length;
                setBlockingTask(prev => ({ ...prev, logs: [...prev.logs, `Batch Error: ${err.message}`] }));
            }

            processed += batch.length;
        }

        if (!stopRef.current) {
            setBlockingTask(prev => ({
                ...prev,
                status: 'done',
                title: "Workflow Complete",
                progress: 1,
                logs: [...prev.logs, `Done. Processed: ${processed}, Errors: ${errors}`]
            }));
            // Clear DB State
            await updateWorkflowState('idle');
        }
    };

    const checkResumableWorkflow = async () => {
        if (!projectRef.current) return;
        const wf = projectRef.current.config?.workflow;
        if (wf && wf.status === 'running' && wf.active_mode) {
            if (confirm(`Uncompleted workflow detected (${wf.active_mode}).\nDo you want to continue?`)) {
                handleBatchProcess(wf.active_mode, { resume: true });
            } else {
                // Erase ephemeral data
                await updateWorkflowState('idle');
            }
        }
    };

    return {
        blockingTask, setBlockingTask,
        stopRef,
        handleAutoTranslate,
        handleFullReinit,
        handleReingest,
        handleBatchProcess,
        checkResumableWorkflow
    };
}

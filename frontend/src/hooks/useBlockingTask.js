import { useState, useRef, useEffect } from 'react';
import { generateDraft, reingestProject, reinitializeProject, getProject } from "../api/client";

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
                        setBlockingTask(prev => ({ ...prev, status: 'done', logs: [...(p.ingestion_logs || []), "Ingestion Complete."] }));
                        clearInterval(interval);
                    } else if (p.rag_status === 'error') {
                        setBlockingTask(prev => ({ ...prev, status: 'error', logs: [...(p.ingestion_logs || []), "Ingestion Failed."] }));
                        clearInterval(interval);
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

    return {
        blockingTask, setBlockingTask,
        stopRef,
        handleAutoTranslate,
        handleFullReinit,
        handleReingest
    };
}

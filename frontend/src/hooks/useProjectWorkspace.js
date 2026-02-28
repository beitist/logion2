import { useEffect } from 'react';
import { useUIState } from './useUIState';
import { useProjectData } from './useProjectData';
import { useAIQueue } from './useAIQueue';
import { useBlockingTask } from './useBlockingTask';

export function useProjectWorkspace(projectId) {
    // 1. UI State (Janitor)
    const ui = useUIState(projectId);

    // 2. Project Data (Archivist) - Depends on Logger
    // We pass a 'queueSegments' stub initially? 
    // No, React Hoisting is fine, but we need to declare variables.
    // However, ProjectData needs 'queueSegments' for the "Load Data -> Trigger PreTranslate" flow.
    // Circle dependency! 
    // Solution: ProjectData accepts a `onLoad` effect or we move the pre-translate trigger to AIQueue?
    // Better: ProjectData exposes `segments` and AIQueue observes them?
    // Or ProjectData returns `segments` and we use a separate useEffect in the Facade to trigger initial queue?
    // Let's pass `queueSegments` as a lazy ref or forward declared function? No.
    // Let's remove the queueing logic from ProjectData's load effect and put it here in the Facade.

    // We will separate the initial pre-translate trigger from Data Loading.

    const data = useProjectData(projectId, {
        log: ui.log,
        setActiveSegmentId: ui.setActiveSegmentId,
        // queueSegments: passed later? No, we perform initial queueing in Facade effect.
        queueSegments: null
    });

    // 3. AI Queue (Coordinator) - Depends on Data & UI
    const ai = useAIQueue({
        segmentsRef: data.segmentsRef,
        projectRef: data.projectRef,
        setSegments: data.setSegments,
        log: ui.log,
        setFlashingSegments: ui.setFlashingSegments,
        activeSegmentId: ui.activeSegmentId,
        setActiveSegmentId: ui.setActiveSegmentId,
        editorRefs: data.editorRefs
    });

    // 4. Blocking Tasks (Ceremony) - Depends on Data & Logs
    const blocking = useBlockingTask(projectId, {
        segmentsRef: data.segmentsRef,
        projectRef: data.projectRef,
        setSegments: data.setSegments,
        onRefresh: data.refreshProject,
        clearAIQueue: ai.clearQueue
    });

    // --- Glue Logic (Facade Effects) ---

    // Initial Pre-Translate Trigger (Moved out of useProjectData to avoid cyclic dep on ai.queueSegments)
    useEffect(() => {
        if (data.segments.length > 0 && data.project?.config?.ai_settings?.pre_translate_count) {
            // Ensure we only do this once or when project loads?
            // Simple check: This runs when segments change.
            // We need a ref to track if we've already queued for this project load.
            // BUT `useProjectData` was doing it on load.

            // Simplification: We rely on the user manually queueing, OR we just add a small check here.
            // Actually, to respect the "Clean Code" request:
            // Let's keep hooks strict. `useProjectData` loads data.
            // Here we say:
            // "If data loaded and configured, queue it."

            // Implementation:
            // Just relying on user is safer, but feature parity requires it.
            // Let's leave it for now. The previous implementation had it.
            // We can use a ref here.
        }
    }, [data.segments, data.project]);

    // Actually, let's just pass `ai.queueSegments` to `useProjectData`? 
    // We can't because `useAIQueue` needs `segments`.
    // Classic Hook composition issue.
    // FIX: logic inside `useProjectData` that calls `queueSegments` should be extracted to `useEffect` here.

    const triggerPreTranslate = () => {
        const count = parseInt(data.project?.config?.ai_settings?.pre_translate_count) || 0;
        if (count > 0 && data.segments.length > 0) {
            const initialIds = data.segments.slice(0, count).map(seg => seg.id);
            setTimeout(() => ai.queueSegments(initialIds), 100);
        }
    };

    // Trigger once when data becomes available
    useEffect(() => {
        if (!data.loading && data.segments.length > 0) {
            triggerPreTranslate();
        }
        if (!data.loading && data.project) {
            blocking.checkResumableWorkflow();
        }
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [data.loading]); // Run once when loading finishes


    // Glossary Sync
    useEffect(() => {
        ui.loadGlossary();
    }, [ui.showGlossaryModal]);


    // Return Unified API
    return {
        // ...ui
        ...ui,
        // ...data
        ...data,
        // ...ai
        ...ai,
        // ...blocking
        ...blocking,
        handleBatchProcess: blocking.handleBatchProcess, // Explicitly expose new method
        handleTCBatch: blocking.handleTCBatch, // TC Step-by-Step batch translation
        handleSequentialTranslate: blocking.handleSequentialTranslate, // Sequential 1-by-1 with auto-glossary

        // Manual Overrides or Composition
        // e.g. handleSave uses data.handleSave
    };
}

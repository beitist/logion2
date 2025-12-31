import { useState, useRef, useEffect } from 'react';
import { generateDraft } from "../api/client";

export function useAIQueue({ segmentsRef, projectRef, setSegments, log, setFlashingSegments, activeSegmentId, setActiveSegmentId, editorRefs }) {
    const [generatingSegments, setGeneratingSegments] = useState({});

    const generatingSegmentsRef = useRef({});
    const draftQueue = useRef([]);
    const isProcessingQueue = useRef(false);
    const lookaheadRef = useRef({ queue: [], processing: false });
    const circuitRef = useRef({ failures: 0, isBroken: false });
    const activeRequestsRef = useRef({});

    // --- Core Generators ---

    const analyzeSegment = async (seg, mode = 'analyze') => {
        const reqKey = `${seg.id}:${mode}`;
        if (activeRequestsRef.current[reqKey]) return activeRequestsRef.current[reqKey];

        const requestPromise = (async () => {
            try {
                const updated = await generateDraft(seg.id, mode);
                setSegments(prev => prev.map(s => s.id !== seg.id ? s : { ...s, ...updated }));
                circuitRef.current.failures = 0;
                circuitRef.current.isBroken = false;
                return updated;
            } catch (e) {
                console.error("Analyze failed", e);
                circuitRef.current.failures += 1;
                if (circuitRef.current.failures >= 3) {
                    console.warn("Lookahead Circuit Broken");
                    circuitRef.current.isBroken = true;
                }
                throw e;
            } finally {
                delete activeRequestsRef.current[reqKey];
            }
        })();

        activeRequestsRef.current[reqKey] = requestPromise;
        return requestPromise;
    };

    const handleAiDraft = async (segmentId, isAuto = false, mode = "translate", isWorkflow = false, forceRefresh = false) => {
        if (!isWorkflow) mode = "draft";
        if (generatingSegmentsRef.current[segmentId]) return;

        generatingSegmentsRef.current[segmentId] = true;
        setGeneratingSegments(prev => ({ ...prev, [segmentId]: true }));

        const seg = segmentsRef.current.find(s => s.id === segmentId);
        if (!isAuto) log(`Generating draft (${mode}) for segment #${seg?.index + 1}...`, 'info', { segmentId });

        try {
            const start = performance.now();
            const updated = await generateDraft(segmentId, mode, isWorkflow, forceRefresh);
            const duration = Math.round(performance.now() - start);

            if (!isAuto) {
                log(`Draft generated in ${duration}ms`, 'success', { target_len: updated.target_content?.length });
                if (setFlashingSegments) {
                    setFlashingSegments(prev => ({ ...prev, [segmentId]: Date.now() }));
                    setTimeout(() => {
                        setFlashingSegments(prev => {
                            const next = { ...prev };
                            delete next[segmentId];
                            return next;
                        });
                    }, 2000);
                }
            }

            setSegments(prev => prev.map(s => s.id !== segmentId ? s : { ...s, ...updated }));
            return updated;
        } catch (err) {
            if (!isAuto) {
                log("AI Draft failed", 'error', err.message);
                alert("AI Draft creation failed");
            }
            throw err;
        } finally {
            generatingSegmentsRef.current[segmentId] = false;
            setGeneratingSegments(prev => {
                const next = { ...prev };
                delete next[segmentId];
                return next;
            });
        }
    };

    // --- Queue & Lookahead Mechanics ---

    const processLookaheadItem = async (segId) => {
        const seg = segmentsRef.current.find(s => s.id === segId);
        if (!seg) return;

        // SKIP if already has matches (Optimization & Anti-Flicker)
        if (seg.context_matches && seg.context_matches.length > 0) {
            // Still check if we need to draft (if configured)
            // But don't re-analyze
        } else {
            await analyzeSegment(seg, 'analyze');
        }

        // Refresh seg ref after potential await
        const currentSeg = segmentsRef.current.find(s => s.id === segId);
        if (!currentSeg) return;

        const isTranslated = currentSeg.status === 'translated' || currentSeg.status === 'approved';
        const hasContent = currentSeg.target_content && currentSeg.target_content.trim().length > 0;

        if (projectRef.current?.use_ai && !isTranslated && !hasContent) {
            await generateDraft(currentSeg.id, 'draft');
        }
    };

    // Loop Effect
    useEffect(() => {
        const runLoop = async () => {
            // Lookahead Queue
            if (!lookaheadRef.current.processing && !circuitRef.current.isBroken && lookaheadRef.current.queue.length > 0) {
                lookaheadRef.current.processing = true;
                const nextId = lookaheadRef.current.queue.shift();
                try {
                    await processLookaheadItem(nextId);
                } catch (e) {
                    console.error("Lookahead error:", e);
                    await new Promise(r => setTimeout(r, 1000));
                } finally {
                    lookaheadRef.current.processing = false;
                }
            }
            // Re-schedule
            if (!stopLoopRef.current) setTimeout(runLoop, 500);
        };
        const stopLoopRef = { current: false };
        setTimeout(runLoop, 500);
        return () => { stopLoopRef.current = true; };
    }, []);

    const processQueue = async () => {
        if (isProcessingQueue.current) return;
        isProcessingQueue.current = true;
        const CONCURRENCY = 3;

        while (draftQueue.current.length > 0) {
            const batch = draftQueue.current.splice(0, CONCURRENCY);
            await Promise.all(batch.map(async (item) => {
                const { id: nextId, mode, isWorkflow } = item;
                const seg = segmentsRef.current.find(s => s.id === nextId);
                const hasContent = seg && seg.target_content && seg.target_content.trim() !== '' && seg.target_content !== '<p></p>';

                if (!seg || seg.locked) return;
                if (mode === "translate" && hasContent) return;

                try {
                    await handleAiDraft(nextId, true, mode, isWorkflow);
                } catch (e) {
                    // Ignore 404 (Segment not found) - likely stale queue item
                    if (e.message.includes('404')) {
                        // console.debug("Queue item skipped (404)", nextId);
                    } else {
                        console.warn("Queue item failed", nextId, e);
                    }
                }
            }));
            await new Promise(r => setTimeout(r, 50));
        }
        isProcessingQueue.current = false;
    };

    const queueSegments = (ids, mode = "translate", isWorkflow = false) => {
        let added = false;
        ids.forEach(id => {
            if (draftQueue.current.find(item => item.id === id)) return;
            const seg = segmentsRef.current.find(s => s.id === id);
            if (!seg) return;
            const hasContent = seg.target_content && seg.target_content.trim() !== '' && seg.target_content !== '<p></p>';
            if (mode === "translate" && hasContent) return;
            if (seg.locked) return;

            draftQueue.current.push({ id, mode, isWorkflow });
            added = true;
        });
        if (added) processQueue();
    };

    // --- Interaction Handlers ---

    const handleSegmentFocus = async (segmentId) => {
        if (setActiveSegmentId) setActiveSegmentId(segmentId);

        const seg = segmentsRef.current.find(s => s.id === segmentId);
        if (seg) {
            let analyzedSeg = seg;
            if (!seg.context_matches || seg.context_matches.length === 0) {
                const updatedFields = await analyzeSegment(seg, 'analyze');
                analyzedSeg = { ...seg, ...updatedFields };
            }

            const isTranslated = analyzedSeg.status === 'translated' || analyzedSeg.status === 'approved';
            const hasDraft = analyzedSeg.context_matches?.some(m => m.type === 'mt') || !!analyzedSeg.metadata?.ai_draft;
            const hasContent = analyzedSeg.target_content && analyzedSeg.target_content.trim().length > 0;

            if (projectRef.current?.use_ai && !isTranslated && !hasDraft && !hasContent) {
                handleAiDraft(analyzedSeg.id, true);
            }
        }

        const currentIndex = segmentsRef.current.findIndex(s => s.id === segmentId);
        if (currentIndex !== -1) {
            const nextSegments = segmentsRef.current.slice(currentIndex + 1, currentIndex + 6);
            lookaheadRef.current.queue = nextSegments.map(s => s.id);
        }
    };

    const handleNavigation = (currentId, direction) => {
        const segments = segmentsRef.current; // Use Ref for reliable index
        const currentIndex = segments.findIndex(s => s.id === currentId);
        if (currentIndex === -1) return;

        let nextIndex = direction === 'next' ? currentIndex + 1 : currentIndex - 1;
        if (nextIndex < 0) nextIndex = 0;
        if (nextIndex >= segments.length) nextIndex = segments.length - 1;

        if (nextIndex !== currentIndex) {
            const nextSeg = segments[nextIndex];
            const editor = editorRefs.current[nextSeg.id];
            if (editor) {
                editor.commands.focus('end');
                handleSegmentFocus(nextSeg.id);
                setTimeout(() => {
                    const el = document.getElementById(`editor-${nextSeg.id}`);
                    if (el) el.scrollIntoView({ behavior: 'smooth', block: 'center' });
                }, 50);
            } else {
                setTimeout(() => {
                    const editorEl = document.querySelector(`#editor-${nextSeg.id} .ProseMirror`);
                    if (editorEl) {
                        editorEl.focus();
                        handleSegmentFocus(nextSeg.id);
                    }
                }, 10);
            }
        }
    };

    const clearQueue = () => {
        draftQueue.current = [];
        lookaheadRef.current.queue = [];
        setGeneratingSegments({});
        generatingSegmentsRef.current = {};
        isProcessingQueue.current = false;
        activeRequestsRef.current = {};
    };

    return {
        generatingSegments,
        handleAiDraft,
        handleSegmentFocus,
        handleNavigation,
        queueSegments,
        clearQueue,
        activeRequestsRef
    };
}

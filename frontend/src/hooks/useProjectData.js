import { useState, useRef, useEffect } from 'react';
import {
    getSegments, getProject, updateSegment, downloadProject, downloadProjectTMX,
    deleteProject
} from "../api/client";
import { serializeContent } from '../utils/editorTransforms';

export function useProjectData(projectId, { log, setActiveSegmentId, queueSegments }) {
    const [segments, setSegments] = useState([]);
    const [project, setProject] = useState(null);
    const [loading, setLoading] = useState(true);
    const [savingId, setSavingId] = useState(null);

    const segmentsRef = useRef([]);
    const projectRef = useRef(null);
    const editorRefs = useRef({});

    // Sync Refs
    useEffect(() => { segmentsRef.current = segments; }, [segments]);
    useEffect(() => { projectRef.current = project; }, [project]);

    // Load Data
    const loadData = async (isInitial = false) => {
        // Avoid double loading if ID didn't change (strict mode protection?)
        // But we want to reload if projectId changes.
        if (!projectId) return;

        try {
            setLoading(true);
            const p = await getProject(projectId);
            setProject(p);
            const s = await getSegments(projectId);
            setSegments(s);
            segmentsRef.current = s;

            if (isInitial) {
                // Initial Lookahead Trigger (Delegate to Queue via callback if provided)
                if (queueSegments && p.config?.ai_settings?.pre_translate_count) {
                    const count = parseInt(p.config.ai_settings.pre_translate_count) || 0;
                    if (count > 0 && s.length > 0) {
                        const initialIds = s.slice(0, count).map(seg => seg.id);
                        setTimeout(() => queueSegments(initialIds), 100);
                    }
                }

                // Initial Focus: Scroll to first unconfirmed segment
                // Priority: 1) First empty target, 2) First draft/mt_draft status
                if (s.length > 0) {
                    // Find first segment that needs work
                    const firstUnconfirmed = s.find(seg =>
                        // Empty target content
                        (!seg.target_content || seg.target_content.trim() === '') ||
                        // Or has draft/mt_draft status (not yet confirmed by user)
                        ['draft', 'mt_draft', 'error'].includes(seg.status)
                    );

                    const targetSegment = firstUnconfirmed || s[0]; // Fallback to first segment

                    setTimeout(() => {
                        const el = document.getElementById(`editor-${targetSegment.id}`);
                        if (el) {
                            el.scrollIntoView({ behavior: 'smooth', block: 'center' });
                            if (setActiveSegmentId) setActiveSegmentId(targetSegment.id);
                        }
                    }, 500);
                }
            }
        } catch (err) {
            console.error(err);
        } finally {
            setLoading(false);
        }
    };

    useEffect(() => {
        loadData(true);
    }, [projectId]);

    const refreshProject = () => loadData(false);

    const handleSave = async (id, htmlContent) => {
        setSavingId(id);
        const seg = segmentsRef.current.find(s => s.id === id);
        if (!seg) return;

        const serialized = serializeContent(htmlContent, seg.tags);
        const isEmpty = !htmlContent || htmlContent.trim() === '' || htmlContent.trim() === '<p></p>';
        const newStatus = isEmpty ? 'draft' : 'translated';

        try {
            const start = performance.now();
            await updateSegment(id, serialized, newStatus);
            const duration = Math.round(performance.now() - start);
            setSegments(prev => prev.map(s => s.id === id ? { ...s, target_content: serialized, status: newStatus } : s));
            log(`Segment saved in ${duration}ms`, 'success');
        } catch (err) {
            log(`Save failed: ${err.message}`, 'error');
            console.error("Save failed", err);
            alert("Save failed!");
        } finally {
            setSavingId(null);
        }
    };

    const handleToggleFlag = async (segmentId, currentFlag) => {
        const newFlag = !currentFlag;
        setSegments(prev => prev.map(s => s.id === segmentId ? { ...s, metadata: { ...(s.metadata || {}), flagged: newFlag } } : s));
        try {
            await updateSegment(segmentId, undefined, undefined, { flagged: newFlag });
        } catch (err) {
            console.error("Failed to toggle flag", err);
            setSegments(prev => prev.map(s => s.id === segmentId ? { ...s, metadata: { ...(s.metadata || {}), flagged: currentFlag } } : s));
            alert("Failed to update flag");
        }
    };

    const handleEditorUpdate = (id, newContent) => {
        setSegments((prev) => prev.map((seg) => seg.id === id ? { ...seg, target_content: newContent } : seg));
    };

    const handleExport = async () => {
        if (!project) return;
        try {
            const blob = await downloadProject(projectId);
            const url = window.URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = `translated_${project.filename}`;
            document.body.appendChild(a);
            a.click();
            a.remove();
        } catch (err) { alert("Export failed!"); }
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
        } catch (err) { alert("TMX Export failed!"); }
    };

    const handleDeleteProject = async () => {
        if (!window.confirm("Delete project?")) return;
        try {
            await deleteProject(projectId);
            window.location.href = "/";
        } catch (err) { alert("Failed to delete project"); }
    };

    return {
        segments, setSegments,
        project, setProject,
        loading,
        savingId,
        segmentsRef,
        projectRef,
        editorRefs,
        handleSave,
        handleToggleFlag,
        handleEditorUpdate,
        handleExport,
        handleTmXExport,
        handleDeleteProject,
        refreshProject
    };
}

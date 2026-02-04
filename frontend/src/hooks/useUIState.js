import { useState } from 'react';
import { getGlossaryTerms } from "../api/client";

export function useUIState(projectId) {
    // Toggles
    const [showSettings, setShowSettings] = useState(false);
    const [showShortcuts, setShowShortcuts] = useState(false);
    const [activeSettingsTab, setActiveSettingsTab] = useState('project');
    const [activeSegmentId, setActiveSegmentId] = useState(null);
    const [showExportMenu, setShowExportMenu] = useState(false);
    const [showConsole, setShowConsole] = useState(false);
    const [showDebug, setShowDebug] = useState(false);

    // Multi-File Filter: null = all files, otherwise file_id
    const [activeFileId, setActiveFileId] = useState(null);

    // Comment Filter: 'all' = show all, 'none' = hide comments
    const [commentFilter, setCommentFilter] = useState('all');

    // Feature UI
    const [showGlossaryModal, setShowGlossaryModal] = useState(false);
    const [glossarySelection, setGlossarySelection] = useState("");
    const [glossaryTerms, setGlossaryTerms] = useState([]);;
    const [flashingSegments, setFlashingSegments] = useState({});
    const [logs, setLogs] = useState([]);

    // Helpers
    const log = (message, type = 'info', details = null) => {
        setLogs(prev => [...prev, {
            time: new Date().toLocaleTimeString(),
            message,
            type,
            details
        }]);
    };

    const handleContextMenu = (e) => {
        const selection = window.getSelection();
        const selectedText = selection.toString().trim();
        if (selectedText) {
            e.preventDefault();
            setGlossarySelection(selectedText);
            setShowGlossaryModal(true);
        }
    };

    const loadGlossary = async () => {
        if (projectId) {
            try {
                const terms = await getGlossaryTerms(projectId);
                setGlossaryTerms(terms);
            } catch (err) {
                console.warn("Glossary load failed", err);
            }
        }
    };

    return {
        // State
        showSettings, setShowSettings,
        showShortcuts, setShowShortcuts,
        activeSettingsTab, setActiveSettingsTab,
        activeSegmentId, setActiveSegmentId,
        showExportMenu, setShowExportMenu,
        showConsole, setShowConsole,
        showDebug, setShowDebug,
        activeFileId, setActiveFileId,  // Multi-File Filter
        commentFilter, setCommentFilter,  // Comment Filter
        showGlossaryModal, setShowGlossaryModal,
        glossarySelection, setGlossarySelection,
        glossaryTerms, setGlossaryTerms,
        flashingSegments, setFlashingSegments,
        logs, setLogs,

        // Handlers
        log,
        handleContextMenu,
        loadGlossary
    };
}

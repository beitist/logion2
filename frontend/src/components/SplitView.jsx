import React, { useRef, useEffect, useState } from 'react';
import { Terminal, Keyboard, X, Trash2, Save, MoreVertical, FileText, Check, Copy, ArrowLeft, Download, ChevronDown, Zap, Database, BookOpen, BarChart3, RefreshCw, FolderOpen, Settings, GitCompareArrows, MessageSquare } from 'lucide-react';
import './TiptapStyles.css';

import { RAGSettingsTab } from './settings/RAGSettingsTab';
import { AISettingsTab } from './settings/AISettingsTab';
import { GlossarySettingsTab } from './settings/GlossarySettingsTab';
import { StatisticsSettingsTab } from './settings/StatisticsSettingsTab';
import { WorkflowsTab } from './settings/WorkflowsTab';
import { ProjectSettingsTab } from './settings/ProjectSettingsTab';
import { FilesSettingsTab } from './settings/FilesSettingsTab';  // Multi-File Management
import { TCSettingsTab } from './settings/TCSettingsTab';

import { GlossaryAddModal } from './GlossaryAddModal';
import { LogConsole } from './LogConsole';
import { ShortcutsPanel } from './ShortcutsPanel';
import { BlockingModal } from './BlockingModal';
import { WorkflowIndicator } from './WorkflowIndicator';
import { ChatPanel } from './ChatPanel';
import { QACheck, QAExportWarning } from './QACheck';

import { useProjectWorkspace } from '../hooks/useProjectWorkspace';
import { useSegmentChat } from '../hooks/useSegmentChat';
import { updateGlossaryTerm } from '../api/client';
import { SegmentRow } from './segment';
import { useVirtualizer } from '@tanstack/react-virtual';

export function SplitView({ projectId, onBack }) {
    const {
        // State
        segments, project, loading, savingId,
        showSettings, setShowSettings,
        showShortcuts, setShowShortcuts,
        activeSettingsTab, setActiveSettingsTab,
        activeSegmentId, setActiveSegmentId,
        showExportMenu, setShowExportMenu,
        showConsole, setShowConsole,
        showDebug, setShowDebug,
        showChat, setShowChat,
        activeFileId, setActiveFileId,  // Multi-File Filter
        commentFilter, setCommentFilter,  // Comment Filter
        showGlossaryModal, setShowGlossaryModal,
        glossarySelection, setGlossarySelection,
        glossaryTerms, setGlossaryTerms,
        flashingSegments,
        logs, setLogs,
        generatingSegments,
        blockingTask, setBlockingTask,

        // Refs
        editorRefs,
        stopRef,

        // Handlers
        handleToggleFlag,
        handleToggleLock,
        handleToggleSkip,
        handlePropagate,
        handleFullReinit,
        handleAutoTranslate,
        handleBatchProcess,
        handleTCBatch,
        handleSequentialTranslate,
        handleOptimize,
        cancelWorkflow,
        handleReingest,
        handleEditorUpdate,
        handleSave,
        handleExport,
        handleTmXExport,
        handleDeleteProject,
        handleNavigation,
        handleSegmentFocus,
        handleContextMenu,
        handleAiDraft,
        queueSegments,
        refreshProject,
        setProject // Destructure setProject to allow updates
    } = useProjectWorkspace(projectId);

    const chat = useSegmentChat(projectId);

    // Glossary inline edit handler
    const handleGlossaryUpdate = async (entryId, updates) => {
        try {
            await updateGlossaryTerm(projectId, entryId, {
                target_term: updates.target_term,
                context_note: updates.context_note,
            });
        } catch (err) {
            console.error('Glossary update failed:', err);
        }
    };

    // QA Export Warning state
    const [showQAWarning, setShowQAWarning] = useState(false);
    const pendingExportRef = useRef(null);

    // Navigate to a specific segment by ID (for QA check)
    const handleNavigateToSegment = (segId) => {
        setActiveSegmentId(segId);
        handleSegmentFocus(segId);
    };

    // Wrap export to show QA warning
    const handleExportWithQA = () => {
        setShowExportMenu(false);
        // Check for QA issues
        let hasIssues = false;
        for (const seg of segments) {
            const meta = seg.metadata || {};
            if (meta.type === 'comment' || meta.skip) continue;
            const hasTarget = seg.target_content && seg.target_content.trim();
            if ((!hasTarget && seg.status !== 'translated') || seg.status === 'mt_draft' || seg.status === 'draft') {
                hasIssues = true;
                break;
            }
        }
        if (hasIssues) {
            pendingExportRef.current = 'docx';
            setShowQAWarning(true);
        } else {
            handleExport();
        }
    };

    const handleTmxExportWithQA = () => {
        setShowExportMenu(false);
        pendingExportRef.current = 'tmx';
        // TMX export without warning (only translations are included anyway)
        handleTmXExport();
    };

    const handleQAExportProceed = () => {
        setShowQAWarning(false);
        if (pendingExportRef.current === 'docx') handleExport();
        else if (pendingExportRef.current === 'tmx') handleTmXExport();
        pendingExportRef.current = null;
    };

    // Virtualization ref for scrollable container
    const parentRef = useRef(null);

    // Get unique source files from project (safe for loading state)
    const sourceFiles = (project?.files || []).filter(f => f.category === 'source');

    // Filter segments by activeFileId (null = show all)
    let filteredSegments = activeFileId
        ? segments.filter(s => s.file_id === activeFileId)
        : segments;

    // Filter comments based on commentFilter ('all', 'active', or 'none')
    if (commentFilter === 'none') {
        filteredSegments = filteredSegments.filter(s => s.metadata?.type !== 'comment');
    } else if (commentFilter === 'active') {
        filteredSegments = filteredSegments.filter(s => {
            if (s.metadata?.type === 'comment') return !s.metadata?.is_done;
            return true;
        });
    }

    // Virtualizer MUST be called before any early returns (Rules of Hooks)
    const rowVirtualizer = useVirtualizer({
        count: filteredSegments.length,
        getScrollElement: () => parentRef.current,
        estimateSize: () => 180,
        overscan: 5,
    });

    // Scroll to active segment when it changes (works with virtualizer)
    const prevActiveRef = useRef(null);
    useEffect(() => {
        if (!activeSegmentId || activeSegmentId === prevActiveRef.current) return;
        prevActiveRef.current = activeSegmentId;
        const idx = filteredSegments.findIndex(s => s.id === activeSegmentId);
        if (idx >= 0) {
            // First: tell virtualizer to render the row (it may be off-screen)
            rowVirtualizer.scrollToIndex(idx, { align: 'center' });
            // Then: use DOM anchor for pixel-accurate scroll after render
            requestAnimationFrame(() => {
                const el = document.getElementById(`segment-${activeSegmentId}`);
                if (el) el.scrollIntoView({ behavior: 'smooth', block: 'center' });
            });
        }
    }, [activeSegmentId, filteredSegments, rowVirtualizer]);

    // Global keyboard shortcut: Cmd+Shift+/ to toggle chat panel
    useEffect(() => {
        const handler = (e) => {
            if ((e.metaKey || e.ctrlKey) && e.shiftKey && e.key === '/') {
                e.preventDefault();
                setShowChat(prev => !prev);
            }
        };
        window.addEventListener('keydown', handler);
        return () => window.removeEventListener('keydown', handler);
    }, []);

    // Early return for loading state - AFTER all hooks
    if (loading) return <div className="p-8 text-center text-gray-500 animate-pulse">Loading Workspace...</div>;

    const aiSettings = project?.config?.ai_settings || {};

    // Get active file name for display
    const activeFileName = activeFileId
        ? sourceFiles.find(f => f.id === activeFileId)?.filename || 'Unknown'
        : 'All Files';


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

                {/* File Filter + Progress */}
                <div className="flex items-center justify-center gap-4 w-1/3 mx-4">
                    {/* File Dropdown - only show if multiple source files */}
                    {sourceFiles.length > 1 && (
                        <div className="relative">
                            <select
                                value={activeFileId || ''}
                                onChange={(e) => setActiveFileId(e.target.value || null)}
                                className="text-xs bg-white border border-gray-200 rounded-lg px-2 py-1.5 pr-6 text-gray-600 hover:border-gray-300 focus:outline-none focus:ring-2 focus:ring-indigo-200 appearance-none cursor-pointer"
                            >
                                <option value="">All Files ({segments.length})</option>
                                {sourceFiles.map(f => (
                                    <option key={f.id} value={f.id}>
                                        {f.filename} ({segments.filter(s => s.file_id === f.id).length})
                                    </option>
                                ))}
                            </select>
                            <ChevronDown size={12} className="absolute right-2 top-1/2 -translate-y-1/2 text-gray-400 pointer-events-none" />
                        </div>
                    )}

                    {/* Comment Filter Toggle (3-way: all → active → none) */}
                    {segments.some(s => s.metadata?.type === 'comment') && (
                        <button
                            onClick={() => {
                                const cycle = { all: 'active', active: 'none', none: 'all' };
                                setCommentFilter(cycle[commentFilter] || 'all');
                            }}
                            className={`text-xs px-2 py-1.5 rounded-lg border transition-colors flex items-center gap-1.5 ${commentFilter === 'all'
                                ? 'bg-amber-50 border-amber-200 text-amber-700 hover:bg-amber-100'
                                : commentFilter === 'active'
                                    ? 'bg-blue-50 border-blue-200 text-blue-700 hover:bg-blue-100'
                                    : 'bg-gray-50 border-gray-200 text-gray-400 hover:bg-gray-100'
                                }`}
                            title={
                                commentFilter === 'all' ? 'Showing all comments. Click to show only active.'
                                    : commentFilter === 'active' ? 'Showing active comments. Click to hide all.'
                                        : 'Comments hidden. Click to show all.'
                            }
                        >
                            💬 {commentFilter === 'all' ? 'All' : commentFilter === 'active' ? 'Active' : 'Hidden'}
                        </button>
                    )}

                    {/* Progress Bar */}
                    <div className="flex flex-col items-center justify-center flex-1 max-w-xs">
                        <div className="flex justify-between w-full text-[10px] text-gray-500 mb-1 uppercase tracking-wider font-semibold">
                            <span>Progress</span>
                            <span>{Math.round((filteredSegments.filter(s => s.status === 'translated' || s.status === 'approved').length / filteredSegments.length) * 100) || 0}%</span>
                        </div>
                        <div className="w-full bg-gray-200 rounded-full h-1.5 overflow-hidden">
                            <div
                                className="bg-indigo-500 h-full transition-all duration-500 ease-out"
                                style={{ width: `${(filteredSegments.filter(s => s.status === 'translated' || s.status === 'approved').length / filteredSegments.length) * 100 || 0}%` }}
                            />
                        </div>
                    </div>
                </div>

                <div className="flex items-center gap-2 w-1/3 justify-end">
                    {/* Console Toggle */}
                    <button
                        onClick={() => setShowConsole(!showConsole)}
                        className={`p-2 rounded-lg transition-colors relative ${showConsole ? 'bg-gray-800 text-white' : 'hover:bg-gray-200 text-gray-600'}`}
                        title="Toggle Log Console"
                    >
                        <Terminal size={18} />
                        {logs.some(l => l.type === 'error') && (
                            <span className="absolute top-0 right-0 w-2.5 h-2.5 bg-red-500 rounded-full border-2 border-white"></span>
                        )}
                    </button>

                    {/* Shortcuts Toggle */}
                    <button
                        onClick={() => setShowShortcuts(!showShortcuts)}
                        className={`p-2 rounded-lg transition-colors ${showShortcuts ? 'bg-indigo-100 text-indigo-700' : 'hover:bg-gray-200 text-gray-600'}`}
                        title="Keyboard Shortcuts"
                    >
                        <Keyboard size={18} />
                    </button>

                    {/* Chat Toggle */}
                    <button
                        onClick={() => setShowChat(!showChat)}
                        className={`p-2 rounded-lg transition-colors ${showChat ? 'bg-indigo-100 text-indigo-700' : 'hover:bg-gray-200 text-gray-600'}`}
                        title="Chat with Segment (⌘⇧/)"
                    >
                        <MessageSquare size={18} />
                    </button>

                    {/* Workflow Indicator */}
                    <WorkflowIndicator
                        project={project}
                        projectId={projectId}
                        blockingTask={blockingTask}
                        onCancel={cancelWorkflow}
                        onSegmentsRefresh={refreshProject}
                    />

                    <div className="h-6 w-px bg-gray-300 mx-2" />

                    {/* QA Check */}
                    <QACheck
                        segments={filteredSegments}
                        activeSegmentId={activeSegmentId}
                        onNavigateToSegment={handleNavigateToSegment}
                    />

                    {/* Export Menu */}
                    <div className="relative">
                        <button
                            onClick={() => setShowExportMenu(!showExportMenu)}
                            className="bg-gray-900 hover:bg-black text-white px-3 py-1.5 rounded-lg flex items-center gap-2 text-sm font-medium transition-colors shadow-sm"
                        >
                            <Download size={16} />
                            Export
                        </button>
                        {showExportMenu && (
                            <div className="absolute right-0 top-full mt-2 w-48 bg-white rounded-xl shadow-xl border border-gray-100 overflow-hidden z-20">
                                <div className="p-1">
                                    <button onClick={handleExportWithQA} className="flex items-center gap-2 w-full px-3 py-2 text-sm text-gray-700 hover:bg-gray-50 rounded-lg text-left">
                                        <FileText size={16} className="text-blue-500" />
                                        <span className="font-medium">Export Translation</span>
                                    </button>
                                    <button onClick={handleTmxExportWithQA} className="flex items-center gap-2 w-full px-3 py-2 text-sm text-gray-700 hover:bg-gray-50 rounded-lg text-left">
                                        <FileText size={16} className="text-green-500" />
                                        <span className="font-medium">Export TMX</span>
                                    </button>
                                </div>
                            </div>
                        )}
                    </div>

                    <button
                        onClick={() => setShowSettings(true)}
                        className="p-2 hover:bg-gray-200 rounded-lg text-gray-600 transition-colors ml-1"
                        title="Settings"
                    >
                        <MoreVertical size={20} />
                    </button>
                </div>
            </header>

            {/* Shortcuts Panel - Collapsible */}
            <div className={`border-b bg-white overflow-hidden transition-all duration-300 ease-in-out ${showShortcuts ? 'max-h-64 opacity-100' : 'max-h-0 opacity-0'}`}>
                <ShortcutsPanel onClose={() => setShowShortcuts(false)} />
            </div>

            {/* Main Workspace + Chat Panel */}
            <div className="flex-1 flex overflow-hidden">
                <main
                    ref={parentRef}
                    className="flex-1 overflow-auto bg-gray-50/50 p-4"
                >
                    <div
                        className="max-w-7xl mx-auto pb-24"
                        style={{
                            height: `${rowVirtualizer.getTotalSize()}px`,
                            width: '100%',
                            position: 'relative',
                        }}
                    >
                        {rowVirtualizer.getVirtualItems().map((virtualRow) => {
                            const seg = filteredSegments[virtualRow.index];
                            const idx = virtualRow.index;

                            // Check if we need a file separator (when showing all files)
                            const prevSeg = idx > 0 ? filteredSegments[idx - 1] : null;
                            const showFileSeparator = !activeFileId && sourceFiles.length > 1 &&
                                prevSeg && seg.file_id !== prevSeg.file_id;
                            const currentFile = sourceFiles.find(f => f.id === seg.file_id);

                            return (
                                <div
                                    key={seg.id}
                                    id={`segment-${seg.id}`}
                                    style={{
                                        position: 'absolute',
                                        top: 0,
                                        left: 0,
                                        width: '100%',
                                        transform: `translateY(${virtualRow.start}px)`,
                                    }}
                                    ref={rowVirtualizer.measureElement}
                                    data-index={virtualRow.index}
                                >
                                    {/* File Separator with filename */}
                                    {showFileSeparator && (
                                        <div className="flex items-center gap-3 py-2 my-2">
                                            <div className="flex-1 h-px bg-gray-300" />
                                            <span className="text-xs font-medium text-gray-500 uppercase tracking-wider">
                                                {currentFile?.filename || 'Unknown File'}
                                            </span>
                                            <div className="flex-1 h-px bg-gray-300" />
                                        </div>
                                    )}
                                    {/* First file header (only in all-files view) */}
                                    {!activeFileId && sourceFiles.length > 1 && idx === 0 && (
                                        <div className="flex items-center gap-3 py-2 mb-2">
                                            <span className="text-xs font-medium text-gray-500 uppercase tracking-wider">
                                                {currentFile?.filename || 'Unknown File'}
                                            </span>
                                            <div className="flex-1 h-px bg-gray-300" />
                                        </div>
                                    )}
                                    <SegmentRow
                                        segment={seg}
                                        project={project}
                                        generatingSegments={generatingSegments}
                                        flashingSegments={flashingSegments}
                                        showDebug={showDebug}
                                        onAiDraft={handleAiDraft}
                                        onToggleFlag={handleToggleFlag}
                                        onToggleLock={handleToggleLock}
                                        onToggleSkip={handleToggleSkip}
                                        onPropagate={handlePropagate}
                                        onSave={handleSave}
                                        onFocus={handleSegmentFocus}
                                        onNavigate={handleNavigation}
                                        onContextMenu={handleContextMenu}
                                        registerEditor={(id, ed) => editorRefs.current[id] = ed}
                                        onGlossaryUpdate={handleGlossaryUpdate}
                                    />
                                </div>
                            );
                        })}

                        {filteredSegments.length === 0 && !loading && (
                            <div className="text-center py-20 text-gray-400">
                                No segments found.
                            </div>
                        )}
                    </div>
                </main>

                {/* Chat Panel - Right Sidebar */}
                {showChat && (
                    <div className="w-80 border-l border-gray-200 flex-shrink-0 overflow-hidden">
                        <ChatPanel
                            segment={segments.find(s => s.id === activeSegmentId)}
                            messages={chat.getMessages(activeSegmentId)}
                            isLoading={chat.isLoading}
                            onSendMessage={chat.sendMessage}
                            onClearChat={chat.clearChat}
                            onClose={() => setShowChat(false)}
                        />
                    </div>
                )}
            </div>

            {/* Log Console Layer */}
            {showConsole && (
                <div className="h-64 border-t bg-gray-900 transition-all">
                    <LogConsole logs={logs} onClose={() => setShowConsole(false)} />
                </div>
            )}

            {/* Glossary Modal */}
            {showGlossaryModal && (
                <GlossaryAddModal
                    projectId={projectId}
                    initialSource={glossarySelection}
                    onClose={() => setShowGlossaryModal(false)}
                    onSuccess={() => {
                        // Optional: Refresh glossary terms via hook if needed, but they are fetched on modal open/close in hook
                    }}
                />
            )}

            {/* Settings Modal - Consider extracting to separate component "SettingsModal" */}
            {showSettings && (
                <div className="fixed inset-0 bg-black/40 backdrop-blur-[2px] flex items-center justify-center z-50 p-4">
                    <div className="bg-white rounded-lg shadow-2xl w-full max-w-4xl max-h-[85vh] flex flex-col overflow-hidden border border-gray-200">
                        {/* Header */}
                        <div className="flex items-center justify-between px-4 py-3 border-b border-gray-100 bg-white">
                            <div>
                                <h2 className="font-bold text-gray-800 text-sm">Project Settings</h2>
                                <p className="text-xs text-gray-500">Configure AI, Glossary, and Files</p>
                            </div>
                            <button
                                onClick={() => setShowSettings(false)}
                                className="p-1.5 hover:bg-gray-100 rounded-md text-gray-400 hover:text-gray-600 transition-colors"
                            >
                                <X size={16} />
                            </button>
                        </div>

                        <div className="flex flex-1 overflow-hidden">
                            {/* Sidebar - Sleek Pro Style */}
                            <div className="w-56 bg-gray-50/50 border-r border-gray-200 flex flex-col py-2">
                                {[
                                    { id: 'project', label: 'Project Settings', icon: Settings },
                                    { id: 'files', label: 'Files Manager', icon: FolderOpen },
                                    { id: 'ai', label: 'AI Configuration', icon: Zap },
                                    { id: 'rag', label: 'RAG / Context', icon: Database },
                                    { id: 'glossary', label: 'Glossary Manager', icon: BookOpen },
                                    { id: 'workflows', label: 'Workflows', icon: RefreshCw },
                                    { id: 'tc', label: 'Track Changes', icon: GitCompareArrows },
                                    { id: 'stats', label: 'Statistics', icon: BarChart3 },
                                ].map(tab => (
                                    <button
                                        key={tab.id}
                                        onClick={() => setActiveSettingsTab(tab.id)}
                                        className={`
                                                w-full text-left px-4 py-2 text-xs font-semibold transition-colors flex items-center gap-3 border-l-2
                                                ${activeSettingsTab === tab.id
                                                ? 'bg-white border-indigo-500 text-indigo-700 shadow-sm'
                                                : 'border-transparent text-gray-600 hover:bg-gray-100/80 hover:text-gray-900'
                                            }
                                            `}
                                    >
                                        <tab.icon size={14} className={activeSettingsTab === tab.id ? 'text-indigo-600' : 'text-gray-400'} />
                                        {tab.label}
                                    </button>
                                ))}
                                <div className="mt-auto border-t pt-4">
                                    <button
                                        onClick={handleDeleteProject}
                                        className="w-full text-left px-4 py-3 rounded-xl text-sm font-medium transition-all flex items-center gap-3 text-red-600 hover:bg-red-50"
                                    >
                                        <Trash2 size={16} />
                                        Delete Project
                                    </button>
                                </div>
                            </div>

                            {/* Content */}
                            <div className="flex-1 overflow-y-auto p-8">
                                <div className="max-w-2xl mx-auto">
                                    {activeSettingsTab === 'project' && (
                                        <ProjectSettingsTab
                                            project={project}
                                            onUpdate={setProject}
                                            onReingest={handleReingest}
                                            onFullReinit={handleFullReinit}
                                        />
                                    )}
                                    {activeSettingsTab === 'files' && (
                                        <FilesSettingsTab
                                            project={project}
                                            files={project?.files || []}
                                            onRefresh={refreshProject}
                                            onFullReinit={handleFullReinit}
                                        />
                                    )}
                                    {activeSettingsTab === 'ai' && (
                                        <AISettingsTab
                                            project={project}
                                            aiSettings={aiSettings}
                                            onUpdate={setProject}
                                        />
                                    )}
                                    {activeSettingsTab === 'rag' && (
                                        <RAGSettingsTab project={project} onUpdate={setProject} />
                                    )}
                                    {activeSettingsTab === 'glossary' && (
                                        <GlossarySettingsTab project={project} />
                                    )}
                                    {activeSettingsTab === 'workflows' && (
                                        <WorkflowsTab
                                            project={project}
                                            // Pass filteredSegments (already filtered by activeFileId dropdown)
                                            // so that batch workflows only process the currently visible file.
                                            segments={filteredSegments}
                                            // Provide file context so WorkflowsTab can show an info banner
                                            activeFileId={activeFileId}
                                            activeFileName={activeFileName}
                                            onQueueAll={queueSegments}
                                            onBatchProcess={handleBatchProcess} // Allow Blocking Workflows
                                            onTCBatch={handleTCBatch} // TC Step-by-Step
                                            onSequentialTranslate={handleSequentialTranslate} // Sequential 1-by-1
                                            onOptimize={handleOptimize} // Optimize via chat
                                            onReingest={handleReingest}
                                            onRefresh={refreshProject}
                                            onFullReinit={handleFullReinit}
                                        />
                                    )}
                                    {activeSettingsTab === 'tc' && (
                                        <TCSettingsTab project={project} onUpdate={setProject} />
                                    )}
                                    {activeSettingsTab === 'stats' && (
                                        <StatisticsSettingsTab project={project} />
                                    )}
                                </div>
                            </div>
                        </div>
                    </div>
                </div>
            )}

            {/* Blocking Task Modal */}
            <BlockingModal
                task={blockingTask}
                onComplete={() => setBlockingTask(prev => ({ ...prev, isOpen: false }))}
                onStop={() => stopRef.current = true}
            />

            {/* QA Export Warning */}
            {showQAWarning && (
                <QAExportWarning
                    segments={segments}
                    onProceed={handleQAExportProceed}
                    onCancel={() => { setShowQAWarning(false); pendingExportRef.current = null; }}
                />
            )}
        </div>
    );
}

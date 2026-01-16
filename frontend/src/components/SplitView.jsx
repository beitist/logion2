import React, { useState } from 'react';
import { Terminal, Bug, Keyboard, X, Trash2, Save, MoreVertical, FileText, Check, Copy, ArrowLeft, Download, ChevronDown, Zap, Database, BookOpen, BarChart3, RefreshCw } from 'lucide-react';
import './TiptapStyles.css';

import { RAGSettingsTab } from './settings/RAGSettingsTab';
import { AISettingsTab } from './settings/AISettingsTab';
import { GlossarySettingsTab } from './settings/GlossarySettingsTab';
import { StatisticsSettingsTab } from './settings/StatisticsSettingsTab';
import { WorkflowsTab } from './settings/WorkflowsTab';
import { ProjectSettingsTab } from './settings/ProjectSettingsTab';

import { GlossaryAddModal } from './GlossaryAddModal';
import { LogConsole } from './LogConsole';
import { ShortcutsPanel } from './ShortcutsPanel';
import { BlockingModal } from './BlockingModal';

import { useProjectWorkspace } from '../hooks/useProjectWorkspace';
import { SegmentRow } from './segment';

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
        handleFullReinit,
        handleAutoTranslate, // Keep for backward compatibility if needed, or remove if fully replaced
        handleBatchProcess, // New
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

    if (loading) return <div className="p-8 text-center text-gray-500 animate-pulse">Loading Workspace...</div>;

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
                        <span>{Math.round((segments.filter(s => s.status === 'translated' || s.status === 'approved').length / segments.length) * 100) || 0}%</span>
                    </div>
                    <div className="w-full bg-gray-200 rounded-full h-1.5 overflow-hidden">
                        <div
                            className="bg-indigo-500 h-full transition-all duration-500 ease-out"
                            style={{ width: `${(segments.filter(s => s.status === 'translated' || s.status === 'approved').length / segments.length) * 100 || 0}%` }}
                        />
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

                    {/* Debug Toggle */}
                    <button
                        onClick={() => setShowDebug(!showDebug)}
                        className={`p-2 rounded-lg transition-colors ${showDebug ? 'bg-red-100 text-red-700' : 'hover:bg-gray-200 text-gray-600'}`}
                        title="Toggle Debug View"
                    >
                        <Bug size={18} />
                    </button>

                    <div className="h-6 w-px bg-gray-300 mx-2" />

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
                                    <button onClick={handleExport} className="flex items-center gap-2 w-full px-3 py-2 text-sm text-gray-700 hover:bg-gray-50 rounded-lg text-left">
                                        <FileText size={16} className="text-blue-500" />
                                        <span className="font-medium">Export DOCX</span>
                                    </button>
                                    <button onClick={handleTmXExport} className="flex items-center gap-2 w-full px-3 py-2 text-sm text-gray-700 hover:bg-gray-50 rounded-lg text-left">
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
                <ShortcutsPanel />
            </div>

            {/* Main Workspace */}
            <main className="flex-1 overflow-auto bg-gray-50/50 p-4" onClick={(e) => {
                // Global click handler to handle some context logic if needed, currently moved to handlers
                // Check if clicking outside inputs to potentially close modals?
            }}>
                <div className="max-w-7xl mx-auto space-y-4 pb-24">
                    {segments.map(seg => (
                        <SegmentRow
                            key={seg.id}
                            segment={seg}
                            project={project}
                            generatingSegments={generatingSegments}
                            flashingSegments={flashingSegments}
                            showDebug={showDebug}
                            onAiDraft={handleAiDraft}
                            onToggleFlag={handleToggleFlag}
                            onSave={handleSave}
                            onFocus={handleSegmentFocus}
                            onNavigate={handleNavigation}
                            registerEditor={(id, ed) => editorRefs.current[id] = ed}
                        />
                    ))}

                    {segments.length === 0 && !loading && (
                        <div className="text-center py-20 text-gray-400">
                            No segments found.
                        </div>
                    )}
                </div>
            </main>

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
                                    { id: 'files', label: 'Project Settings', icon: FileText },
                                    { id: 'ai', label: 'AI Configuration', icon: Zap },
                                    { id: 'rag', label: 'RAG / Context', icon: Database },
                                    { id: 'glossary', label: 'Glossary Manager', icon: BookOpen },
                                    { id: 'workflows', label: 'Workflows', icon: RefreshCw },
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
                                    {activeSettingsTab === 'files' && (
                                        <ProjectSettingsTab
                                            project={project}
                                            onUpdate={setProject} // Fix: Pass setProject as onUpdate handler
                                            onReingest={handleReingest}
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
                                            segments={segments}
                                            onQueueAll={queueSegments}
                                            onBatchProcess={handleBatchProcess} // Allow Blocking Workflows
                                            onReingest={handleReingest}
                                            onRefresh={refreshProject}
                                            onFullReinit={handleFullReinit}
                                        />
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
        </div>
    );
}

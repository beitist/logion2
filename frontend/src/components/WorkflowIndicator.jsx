import React, { useState, useRef, useEffect } from 'react';
import { Settings, Check, AlertCircle, Square } from 'lucide-react';

/**
 * Workflow Indicator
 *
 * Gear icon in the header that shows workflow status:
 * - Spinning blue when a workflow is running
 * - Brief green flash on completion
 * - Red on error
 * - Gray when idle
 *
 * Click opens a popover with progress, logs, and cancel.
 */
export function WorkflowIndicator({ project, projectId, blockingTask, onCancel, onSegmentsRefresh }) {
    const [showPopover, setShowPopover] = useState(false);
    const [justCompleted, setJustCompleted] = useState(false);
    const prevStatusRef = useRef(project?.rag_status);
    const popoverRef = useRef(null);
    const buttonRef = useRef(null);

    const isActive = project?.rag_status === 'processing';
    const isError = project?.rag_status === 'error';

    // Detect completion: processing → ready
    useEffect(() => {
        const prev = prevStatusRef.current;
        const curr = project?.rag_status;
        prevStatusRef.current = curr;

        if (prev === 'processing' && curr === 'ready') {
            setJustCompleted(true);
            const timer = setTimeout(() => setJustCompleted(false), 5000);
            return () => clearTimeout(timer);
        }
    }, [project?.rag_status]);

    // Close popover on outside click
    useEffect(() => {
        if (!showPopover) return;
        const handleClick = (e) => {
            if (popoverRef.current && !popoverRef.current.contains(e.target) &&
                buttonRef.current && !buttonRef.current.contains(e.target)) {
                setShowPopover(false);
            }
        };
        document.addEventListener('mousedown', handleClick);
        return () => document.removeEventListener('mousedown', handleClick);
    }, [showPopover]);

    // Resolve workflow title
    const getWorkflowTitle = () => {
        if (blockingTask?.title && blockingTask?.status === 'running') return blockingTask.title;
        const mode = project?.config?.workflow?.active_mode;
        if (mode === 'draft') return 'Pre-Translate';
        if (mode === 'translate') return 'Machine Translation';
        if (mode === 'tc_batch') return 'TC Step-by-Step';
        if (mode === 'sequential') return 'Sequential Translation';
        return 'Background Workflow';
    };

    const progress = project?.rag_progress || 0;
    const logs = project?.ingestion_logs || [];
    const recentLogs = logs.slice(-5);

    // Icon styling
    const iconClass = isActive
        ? 'text-blue-600 bg-blue-50'
        : isError
            ? 'text-red-500 bg-red-50'
            : justCompleted
                ? 'text-emerald-600 bg-emerald-50'
                : 'hover:bg-gray-200 text-gray-600';

    return (
        <div className="relative">
            {/* Gear Button */}
            <button
                ref={buttonRef}
                onClick={() => setShowPopover(!showPopover)}
                className={`p-2 rounded-lg transition-colors relative ${iconClass}`}
                title="Workflow Status"
            >
                <Settings size={18} className={isActive ? 'animate-spin' : ''} />
                {/* Active indicator dot */}
                {isActive && (
                    <span className="absolute top-0 right-0 w-2.5 h-2.5 bg-blue-500 rounded-full border-2 border-white animate-pulse" />
                )}
                {justCompleted && (
                    <span className="absolute top-0 right-0 w-2.5 h-2.5 bg-emerald-500 rounded-full border-2 border-white" />
                )}
            </button>

            {/* Popover */}
            {showPopover && (
                <div
                    ref={popoverRef}
                    className="absolute right-0 top-full mt-2 w-80 bg-white rounded-xl shadow-xl border border-gray-100 overflow-hidden z-30"
                >
                    {isActive ? (
                        /* Running State */
                        <div className="p-4">
                            <div className="flex items-center gap-3 mb-3">
                                <div className="p-2 bg-blue-50 rounded-lg">
                                    <div className="animate-spin rounded-full h-4 w-4 border-2 border-blue-600 border-t-transparent" />
                                </div>
                                <div className="flex-1 min-w-0">
                                    <div className="text-sm font-semibold text-gray-800 truncate">
                                        {getWorkflowTitle()}
                                    </div>
                                    <div className="text-xs text-gray-500">
                                        {progress}% complete
                                    </div>
                                </div>
                            </div>

                            {/* Progress Bar */}
                            <div className="w-full bg-gray-100 rounded-full h-1.5 mb-3 overflow-hidden">
                                <div
                                    className="bg-blue-500 h-1.5 rounded-full transition-all duration-500 ease-out"
                                    style={{ width: `${Math.min(100, progress)}%` }}
                                />
                            </div>

                            {/* Recent Logs */}
                            {recentLogs.length > 0 && (
                                <div className="bg-gray-900 rounded-lg p-2.5 mb-3 max-h-32 overflow-y-auto">
                                    {recentLogs.map((log, i) => (
                                        <div key={i} className="text-[10px] font-mono text-green-400 leading-relaxed truncate">
                                            {log}
                                        </div>
                                    ))}
                                    <div className="animate-pulse text-green-600 text-xs mt-1">_</div>
                                </div>
                            )}

                            {/* Cancel Button */}
                            <button
                                onClick={async () => {
                                    if (onCancel) await onCancel();
                                    setShowPopover(false);
                                }}
                                className="w-full flex items-center justify-center gap-2 px-3 py-2 bg-red-50 text-red-600 rounded-lg text-xs font-medium hover:bg-red-100 transition-colors border border-red-100"
                            >
                                <Square size={12} />
                                Cancel Workflow
                            </button>
                        </div>
                    ) : justCompleted ? (
                        /* Just Completed State */
                        <div className="p-4 text-center">
                            <div className="p-3 bg-emerald-50 rounded-full inline-flex mb-2">
                                <Check size={20} className="text-emerald-600" />
                            </div>
                            <div className="text-sm font-semibold text-gray-800">Workflow Complete</div>
                            <div className="text-xs text-gray-500 mt-1">Segments have been refreshed.</div>
                        </div>
                    ) : isError ? (
                        /* Error State */
                        <div className="p-4">
                            <div className="flex items-center gap-3 mb-3">
                                <div className="p-2 bg-red-50 rounded-lg">
                                    <AlertCircle size={16} className="text-red-500" />
                                </div>
                                <div className="flex-1">
                                    <div className="text-sm font-semibold text-gray-800">Workflow Failed</div>
                                    <div className="text-xs text-gray-500">Check logs for details</div>
                                </div>
                            </div>
                            {recentLogs.length > 0 && (
                                <div className="bg-gray-900 rounded-lg p-2.5 mb-3 max-h-24 overflow-y-auto">
                                    {recentLogs.map((log, i) => (
                                        <div key={i} className="text-[10px] font-mono text-red-400 leading-relaxed truncate">
                                            {log}
                                        </div>
                                    ))}
                                </div>
                            )}
                            <button
                                onClick={() => setShowPopover(false)}
                                className="w-full px-3 py-2 bg-gray-100 text-gray-700 rounded-lg text-xs font-medium hover:bg-gray-200 transition-colors"
                            >
                                Dismiss
                            </button>
                        </div>
                    ) : (
                        /* Idle State */
                        <div className="p-4 text-center">
                            <div className="p-3 bg-gray-50 rounded-full inline-flex mb-2">
                                <Settings size={20} className="text-gray-400" />
                            </div>
                            <div className="text-sm font-medium text-gray-600">No Active Workflows</div>
                            <div className="text-xs text-gray-400 mt-1">
                                Start workflows from Settings &rarr; Workflows
                            </div>
                        </div>
                    )}
                </div>
            )}
        </div>
    );
}

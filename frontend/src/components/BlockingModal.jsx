import React from 'react';
import { Check, Bug } from 'lucide-react';

export function BlockingModal({ task, onStop, onComplete, onReload }) {
    if (!task.isOpen) return null;

    return (
        <div className="fixed inset-0 bg-black/80 backdrop-blur-md flex items-center justify-center z-[100] p-4">
            <div className="bg-white rounded-xl shadow-2xl w-full max-w-2xl p-8 flex flex-col gap-6 border border-gray-100">
                {/* Header */}
                <div className="flex items-center gap-4 border-b border-gray-100 pb-6">
                    <div className={`p-4 rounded-full ${task.status === 'done' ? 'bg-green-100 text-green-600' : task.status === 'error' ? 'bg-red-100 text-red-600' : 'bg-indigo-50 text-indigo-600'}`}>
                        {task.status === 'done' ? <Check size={32} /> : task.status === 'error' ? <Bug size={32} /> : (
                            <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-current"></div>
                        )}
                    </div>
                    <div className="flex-1">
                        <h3 className="text-xl font-bold text-gray-900">
                            {task.title}
                        </h3>
                        <div className="text-sm text-gray-500 mt-1">
                            {task.status === 'done' ? "Operation completed successfully." :
                                task.status === 'error' ? "Operation failed or cancelled." :
                                    "Please do not close this window."}
                        </div>
                    </div>
                </div>

                {/* Progress Bar */}
                {task.progress >= 0 && (
                    <div className="w-full bg-gray-100 rounded-full h-2.5 overflow-hidden">
                        <div
                            className="bg-indigo-600 h-2.5 rounded-full transition-all duration-300 ease-out"
                            style={{ width: `${Math.min(100, task.progress * 100)}%` }}
                        ></div>
                    </div>
                )}

                {/* Logs Console */}
                <div className="bg-gray-900 rounded-lg p-4 font-mono text-xs text-green-400 h-64 overflow-y-auto border border-gray-800 shadow-inner">
                    {task.logs.length > 0 ? (
                        <div className="flex flex-col">
                            {task.logs.map((log, i) => {
                                // Extract timestamp if log already contains one (format: [HH:MM:SS])
                                // Otherwise show log index
                                const hasTimestamp = log.match(/^\[[\d:]+\]/);
                                return (
                                    <div key={i} className="mb-1.5 border-l-2 border-transparent hover:border-green-600 pl-2 opacity-90 hover:opacity-100">
                                        {!hasTimestamp && (
                                            <span className="text-gray-500 mr-2">[{String(i + 1).padStart(2, '0')}]</span>
                                        )}
                                        {log}
                                    </div>
                                );
                            })}
                            {task.status === 'running' && (
                                <div className="animate-pulse mt-2 text-green-600">_</div>
                            )}
                        </div>
                    ) : (
                        <div className="text-gray-500 italic">Waiting...</div>
                    )}
                </div>

                {/* Actions */}
                <div className="flex justify-end pt-2 gap-3">
                    {task.status === 'running' && onStop && (
                        <button
                            onClick={onStop}
                            className="bg-red-50 text-red-600 hover:bg-red-100 px-6 py-3 rounded-lg transition-colors font-medium border border-red-100"
                        >
                            Stop / Cancel
                        </button>
                    )}

                    {task.status === 'done' || task.status === 'error' ? (
                        <button
                            onClick={onComplete || onReload || (() => window.location.reload())}
                            className="bg-gray-900 text-white px-6 py-3 rounded-lg hover:bg-black transition-colors font-medium flex items-center gap-2"
                        >
                            <Check size={18} />
                            {onReload ? "Reload Project" : "Continue"}
                        </button>
                    ) : (
                        <div className="text-xs text-gray-400 italic self-center">Processing...</div>
                    )}
                </div>
            </div>
        </div>
    );
}

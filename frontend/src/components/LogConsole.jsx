import React, { useEffect, useRef } from 'react';
import { Terminal, X, Trash2, Maximize2, Minimize2 } from 'lucide-react';

export function LogConsole({ logs, isOpen, onClose, onClear }) {
    const bottomRef = useRef(null);
    const [isExpanded, setIsExpanded] = React.useState(false);

    useEffect(() => {
        if (isOpen && bottomRef.current) {
            bottomRef.current.scrollIntoView({ behavior: 'smooth' });
        }
    }, [logs, isOpen]);

    if (!isOpen) return null;

    return (
        <div
            className={`fixed bottom-0 left-0 right-0 bg-gray-900 text-green-400 font-mono text-xs shadow-2xl transition-all duration-300 z-50 flex flex-col ${isExpanded ? 'h-[60vh]' : 'h-48'}`}
            style={{ boxShadow: '0 -4px 20px rgba(0,0,0,0.3)' }}
        >
            {/* Header */}
            <div className="flex justify-between items-center px-4 py-2 bg-gray-800 border-b border-gray-700 select-none">
                <div className="flex items-center gap-2">
                    <Terminal size={14} />
                    <span className="font-bold tracking-wider">HACKER_CONSOLE // AI_LOGS</span>
                    <span className="px-2 py-0.5 bg-green-900/30 text-green-300 rounded text-[10px] animate-pulse">LIVE</span>
                </div>
                <div className="flex items-center gap-2">
                    <button
                        onClick={onClear}
                        className="p-1 hover:bg-gray-700 rounded text-gray-400 hover:text-white transition-colors"
                        title="Clear Logs"
                    >
                        <Trash2 size={14} />
                    </button>
                    <button
                        onClick={() => setIsExpanded(!isExpanded)}
                        className="p-1 hover:bg-gray-700 rounded text-gray-400 hover:text-white transition-colors"
                        title={isExpanded ? "Collapse" : "Expand"}
                    >
                        {isExpanded ? <Minimize2 size={14} /> : <Maximize2 size={14} />}
                    </button>
                    <button
                        onClick={onClose}
                        className="p-1 hover:bg-red-900/50 rounded text-red-400 hover:text-red-200 transition-colors"
                        title="Close Console"
                    >
                        <X size={14} />
                    </button>
                </div>
            </div>

            {/* Content */}
            <div className="flex-1 overflow-y-auto p-4 space-y-1 scrollbar-thin scrollbar-thumb-gray-700 scrollbar-track-transparent">
                {logs.length === 0 ? (
                    <div className="text-gray-600 italic opacity-50 select-none">
                        &gt; System ready. Waiting for AI operations...
                    </div>
                ) : (
                    logs.map((log, idx) => (
                        <div key={idx} className="break-words font-mono">
                            <span className="text-gray-500 mr-2">[{log.time}]</span>
                            <span className={log.type === 'error' ? 'text-red-400 font-bold' : log.type === 'success' ? 'text-green-300' : 'text-gray-300'}>
                                {log.message}
                            </span>
                            {log.details && (
                                <pre className="mt-1 ml-10 text-[10px] text-gray-500 whitespace-pre-wrap border-l border-gray-700 pl-2">
                                    {typeof log.details === 'object' ? JSON.stringify(log.details, null, 2) : log.details}
                                </pre>
                            )}
                        </div>
                    ))
                )}
                <div ref={bottomRef} />
            </div>
        </div>
    );
}

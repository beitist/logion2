import React from 'react';
import { X, Keyboard } from 'lucide-react';

export function ShortcutsPanel({ isOpen, onClose }) {
    // Note: Visibility is now controlled by parent container CSS in SplitView
    // This component just renders the content

    const shortcuts = [
        // Navigation
        { keys: ["Cmd/Ctrl", "Enter"], desc: "Save & Next Segment", category: "Navigation" },
        { keys: ["Cmd/Ctrl", "Shift", "↓"], desc: "Next Segment", category: "Navigation" },
        { keys: ["Cmd/Ctrl", "Shift", "↑"], desc: "Prev Segment", category: "Navigation" },

        // AI & Context
        { keys: ["Ctrl", "Space"], desc: "Generate AI Draft", category: "AI" },
        { keys: ["Cmd/Ctrl", "Alt", "ß"], desc: "Generate AI Draft (Alt)", category: "AI" },
        { keys: ["Cmd/Ctrl", "Alt", "0"], desc: "Insert MT/Best Match", category: "Context" },
        { keys: ["Cmd/Ctrl", "Alt", "9"], desc: "Insert Reference 1", category: "Context" },
        { keys: ["Cmd/Ctrl", "Alt", "8"], desc: "Insert Reference 2", category: "Context" },
        { keys: ["Cmd/Ctrl", "Alt", "7"], desc: "Insert Reference 3", category: "Context" },

        // Formatting
        { keys: ["Tab"], desc: "Insert Tab Character", category: "Formatting" },
        { keys: ["Cmd/Ctrl", "Ctrl", "Alt", "Space"], desc: "Insert Non-Breaking Space", category: "Formatting" },
    ];

    return (
        <div className="fixed inset-y-0 right-0 w-80 bg-white shadow-2xl z-50 transform transition-transform duration-300 ease-in-out border-l border-gray-200 flex flex-col">
            <div className="p-4 border-b border-gray-100 flex justify-between items-center bg-gray-50">
                <h3 className="font-bold text-gray-800 flex items-center gap-2">
                    <Keyboard size={18} /> Shortcuts
                </h3>
                <button
                    onClick={onClose}
                    className="p-1 hover:bg-gray-200 rounded-full text-gray-500 transition-colors"
                >
                    <X size={18} />
                </button>
            </div>

            <div className="flex-1 overflow-y-auto p-4 space-y-6">
                {/* Group by Category is implicit or explicit? Let's generic list for now */}

                <div className="space-y-4">
                    {shortcuts.map((s, i) => (
                        <div key={i} className="flex justify-between items-center group">
                            <span className="text-sm text-gray-600 font-medium group-hover:text-gray-900">{s.desc}</span>
                            <div className="flex gap-1">
                                {s.keys.map((k, j) => (
                                    <span key={j} className="px-1.5 py-0.5 bg-gray-100 border border-gray-300 rounded text-xs font-mono text-gray-500 font-bold shadow-sm">
                                        {k}
                                    </span>
                                ))}
                            </div>
                        </div>
                    ))}
                </div>

                <div className="mt-8 p-4 bg-blue-50 rounded-lg text-xs text-blue-700 leading-relaxed border border-blue-100">
                    <strong>Tip:</strong> You can hover over the context matches in the editor to see their specific insertion shortcuts.
                </div>
            </div>
        </div>
    );
}

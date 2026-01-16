import React from 'react';
import { X, Keyboard } from 'lucide-react';

/**
 * ShortcutsPanel
 * 
 * Displays keyboard shortcuts for the editor.
 * Rendered as an embedded panel (not fixed sidebar).
 * Visibility is controlled by parent container in SplitView.
 */
export function ShortcutsPanel({ onClose }) {
    const shortcuts = [
        // Navigation
        { keys: ["⌘/Ctrl", "Enter"], desc: "Save & Next Segment", category: "Navigation" },
        { keys: ["⌘/Ctrl", "Shift", "↓"], desc: "Next Segment", category: "Navigation" },
        { keys: ["⌘/Ctrl", "Shift", "↑"], desc: "Prev Segment", category: "Navigation" },

        // AI & Context
        { keys: ["Ctrl", "Space"], desc: "Generate AI Draft", category: "AI" },
        { keys: ["⌘/Ctrl", "Alt", "0"], desc: "Insert MT/Best Match", category: "Context" },
        { keys: ["⌘/Ctrl", "Alt", "9"], desc: "Insert Reference 1", category: "Context" },
        { keys: ["⌘/Ctrl", "Alt", "8"], desc: "Insert Reference 2", category: "Context" },
        { keys: ["⌘/Ctrl", "Alt", "7"], desc: "Insert Reference 3", category: "Context" },

        // Formatting
        { keys: ["Tab"], desc: "Insert Tab Character", category: "Formatting" },
        { keys: ["⌘", "Ctrl", "Alt", "Space"], desc: "Insert NBSP", category: "Formatting" },
    ];

    return (
        <div className="p-4">
            {/* Header with Close Button */}
            <div className="flex justify-between items-center mb-4">
                <h3 className="font-bold text-gray-800 flex items-center gap-2 text-sm">
                    <Keyboard size={16} className="text-gray-500" />
                    Keyboard Shortcuts
                </h3>
                {onClose && (
                    <button
                        onClick={onClose}
                        className="p-1 hover:bg-gray-200 rounded-full text-gray-400 hover:text-gray-600 transition-colors"
                        title="Close Shortcuts"
                    >
                        <X size={16} />
                    </button>
                )}
            </div>

            {/* Grid of Shortcuts */}
            <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-x-6 gap-y-2">
                {shortcuts.map((s, i) => (
                    <div key={i} className="flex justify-between items-center gap-2 py-1">
                        <span className="text-xs text-gray-600 truncate">{s.desc}</span>
                        <div className="flex gap-0.5 flex-shrink-0">
                            {s.keys.map((k, j) => (
                                <span key={j} className="px-1.5 py-0.5 bg-gray-100 border border-gray-200 rounded text-[10px] font-mono text-gray-500 font-semibold">
                                    {k}
                                </span>
                            ))}
                        </div>
                    </div>
                ))}
            </div>
        </div>
    );
}

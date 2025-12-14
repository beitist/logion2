
import React, { useState, useEffect } from 'react';
import { addGlossaryTerm } from '../api/client';

export function GlossaryAddModal({ projectId, initialSource, onClose, onSuccess }) {
    const [source, setSource] = useState(initialSource || "");
    const [target, setTarget] = useState("");
    const [note, setNote] = useState("");
    const [isSaving, setIsSaving] = useState(false);

    // Auto-focus target input on mount
    const targetInputRef = React.useRef(null);

    useEffect(() => {
        if (targetInputRef.current) {
            targetInputRef.current.focus();
        }
    }, []);

    const handleSubmit = async (e) => {
        e.preventDefault();
        if (!source || !target) return;

        setIsSaving(true);
        try {
            await addGlossaryTerm(projectId, source, target, note);
            onSuccess();
            onClose();
        } catch (e) {
            alert("Failed to add term");
            console.error(e);
            setIsSaving(false);
        }
    };

    return (
        <div className="fixed inset-0 bg-black/50 backdrop-blur-sm flex items-center justify-center z-[100] p-4">
            <div className="bg-white rounded-xl shadow-2xl w-full max-w-md overflow-hidden animate-in fade-in zoom-in duration-200">
                <div className="p-4 bg-indigo-600 text-white flex justify-between items-center">
                    <h3 className="font-bold text-lg flex items-center gap-2">
                        📚 Add to Glossary
                    </h3>
                    <button onClick={onClose} className="text-white/80 hover:text-white">✕</button>
                </div>

                <form onSubmit={handleSubmit} className="p-6 flex flex-col gap-4">
                    <div>
                        <label className="block text-xs font-bold text-gray-500 uppercase tracking-wide mb-1">Source Term</label>
                        <input
                            className="w-full p-2 border border-gray-300 rounded bg-gray-50 font-medium text-gray-700 focus:outline-none"
                            value={source}
                            onChange={(e) => setSource(e.target.value)}
                        // Allow editing source if selection was imperfect
                        />
                        <p className="text-[10px] text-gray-400 mt-1">We'll automatically detect grammar variations (plurals, etc).</p>
                    </div>

                    <div>
                        <label className="block text-xs font-bold text-gray-500 uppercase tracking-wide mb-1">Target Translation</label>
                        <input
                            ref={targetInputRef}
                            className="w-full p-2 border border-blue-200 rounded focus:ring-2 focus:ring-blue-100 outline-none ring-offset-1"
                            placeholder="e.g. Verwendungsnachweis"
                            value={target}
                            onChange={(e) => setTarget(e.target.value)}
                            required
                        />
                    </div>

                    <div>
                        <label className="block text-xs font-bold text-gray-500 uppercase tracking-wide mb-1">Note (Optional)</label>
                        <input
                            className="w-full p-2 border border-gray-300 rounded focus:border-blue-300 outline-none"
                            placeholder="Context or Usage"
                            value={note}
                            onChange={(e) => setNote(e.target.value)}
                        />
                    </div>

                    <div className="flex justify-end gap-2 mt-2">
                        <button
                            type="button"
                            onClick={onClose}
                            className="px-4 py-2 text-gray-600 hover:bg-gray-100 rounded"
                        >
                            Cancel
                        </button>
                        <button
                            type="submit"
                            disabled={isSaving}
                            className="px-6 py-2 bg-indigo-600 text-white font-medium rounded hover:bg-indigo-700 shadow-md transition-all flex items-center gap-2"
                        >
                            {isSaving ? "Saving..." : "Save Term"}
                        </button>
                    </div>
                </form>
            </div>
        </div>
    );
}

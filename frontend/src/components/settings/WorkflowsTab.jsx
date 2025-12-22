import React, { useState } from 'react';
import { RefreshCw, Search, Calculator, Database, Copy } from 'lucide-react';
import { generateDraft, copySourceToTarget } from '../../api/client';

export function WorkflowsTab({ project, segments, onQueueAll, onReingest, onRefresh }) {
    const [copyLoading, setCopyLoading] = useState(false);

    const handleRun = (mode) => {
        if (!segments) return;
        const ids = segments.map(s => s.id);
        if (confirm(`Queue ${ids.length} segments for ${mode}?`)) {
            onQueueAll(ids, mode, true);
        }
    };

    const handleCopySource = async () => {
        if (!project) return;
        if (!confirm("This will overwrite target content for ALL segments with source content. Continue?")) return;

        try {
            setCopyLoading(true);
            await copySourceToTarget(project.id);
            if (onRefresh) onRefresh();
        } catch (err) {
            alert("Failed to copy source: " + err.message);
            console.error(err);
        } finally {
            setCopyLoading(false);
        }
    };

    return (
        <div className="space-y-6 py-4 h-full flex flex-col">
            <div className="flex items-center gap-2 text-indigo-800 bg-indigo-50 p-3 rounded-lg border border-indigo-100 mb-2">
                <RefreshCw size={18} />
                <span className="font-semibold text-sm">Workflows & Automation</span>
            </div>

            <div className="space-y-4 flex-1 overflow-y-auto pr-2">

                {/* 1. Pre-Analysis */}
                <div className="p-4 bg-white rounded-lg border border-gray-200 shadow-sm hover:border-gray-300 transition-all">
                    <div className="flex items-center gap-3 mb-2">
                        <div className="p-2 bg-blue-50 text-blue-600 rounded-md">
                            <Search size={20} />
                        </div>
                        <div>
                            <h3 className="text-sm font-bold text-gray-900">Pre-Analysis (Context Only)</h3>
                            <p className="text-xs text-gray-500">Retrieve TM/Glossary matches. Does NOT generate AI Drafts.</p>
                        </div>
                    </div>
                    <button
                        onClick={() => handleRun("analyze")}
                        className="w-full mt-2 flex items-center justify-center gap-2 px-3 py-2 bg-white border border-gray-300 text-gray-700 rounded hover:bg-gray-50 text-xs font-medium"
                    >
                        Analyze Context
                    </button>
                </div>

                {/* 2. Draft Suggestions */}
                <div className="p-4 bg-white rounded-lg border border-gray-200 shadow-sm hover:border-gray-300 transition-all">
                    <div className="flex items-center gap-3 mb-2">
                        <div className="p-2 bg-purple-50 text-purple-600 rounded-md">
                            <Calculator size={20} />
                        </div>
                        <div>
                            <h3 className="text-sm font-bold text-gray-900">Pre-Translate (Suggestions)</h3>
                            <p className="text-xs text-gray-500">Generates AI drafts in background for instant availability. Does NOT overwrite target.</p>
                        </div>
                    </div>
                    <button
                        onClick={() => handleRun("draft")}
                        className="w-full mt-2 flex items-center justify-center gap-2 px-3 py-2 bg-purple-50 border border-purple-200 text-purple-700 rounded hover:bg-purple-100 text-xs font-medium"
                    >
                        Generate Suggestions
                    </button>
                </div>

                {/* 3. Machine Translation */}
                <div className="p-4 bg-white rounded-lg border border-gray-200 shadow-sm hover:border-gray-300 transition-all">
                    <div className="flex items-center gap-3 mb-2">
                        <div className="p-2 bg-green-50 text-green-600 rounded-md">
                            <Database size={20} />
                        </div>
                        <div>
                            <h3 className="text-sm font-bold text-gray-900">Machine Translation</h3>
                            <p className="text-xs text-gray-500">Translate and fill all empty target segments immediately.</p>
                        </div>
                    </div>
                    <button
                        onClick={() => handleRun("translate")}
                        className="w-full mt-2 flex items-center justify-center gap-2 px-3 py-2 bg-green-600 text-white rounded hover:bg-green-700 shadow-sm text-xs font-medium"
                    >
                        Translate All Empty
                    </button>
                </div>

                {/* 4. Copy Source (Verification) */}
                <div className="p-4 bg-white rounded-lg border border-gray-200 shadow-sm hover:border-gray-300 transition-all">
                    <div className="flex items-center gap-3 mb-2">
                        <div className="p-2 bg-orange-50 text-orange-600 rounded-md">
                            <Copy size={20} />
                        </div>
                        <div>
                            <h3 className="text-sm font-bold text-gray-900">Copy Source to Target</h3>
                            <p className="text-xs text-gray-500">Verification Tool: Copies source text to target for all segments.</p>
                        </div>
                    </div>
                    <button
                        onClick={handleCopySource}
                        disabled={copyLoading}
                        className="w-full mt-2 flex items-center justify-center gap-2 px-3 py-2 bg-orange-50 border border-orange-200 text-orange-700 rounded hover:bg-orange-100 text-xs font-medium disabled:opacity-50"
                    >
                        {copyLoading ? "Copying..." : "Copy All Sources"}
                    </button>
                </div>

                {/* 5. Reingest */}
                <div className="p-4 bg-gray-50 rounded-lg border border-gray-200 mt-6 opacity-75 hover:opacity-100 transition-opacity">
                    <div className="flex items-center gap-3 mb-2">
                        <div className="p-2 bg-gray-200 text-gray-600 rounded-md">
                            <RefreshCw size={20} />
                        </div>
                        <div>
                            <h3 className="text-sm font-bold text-gray-900">Re-Ingest Documents</h3>
                            <p className="text-xs text-gray-500">Re-process source files for RAG.</p>
                        </div>
                    </div>
                    <button
                        onClick={onReingest}
                        className="w-full mt-2 flex items-center justify-center gap-2 px-3 py-2 bg-gray-200 border border-gray-300 text-gray-700 rounded hover:bg-gray-300 text-xs font-medium"
                    >
                        Re-Ingest
                    </button>
                </div>

            </div>
        </div>
    );
}

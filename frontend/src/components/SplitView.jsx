import React, { useEffect, useState } from 'react';
import { getSegments } from '../api/client';
import { TiptapEditor } from './TiptapEditor';

export function SplitView({ projectId }) {
    const [segments, setSegments] = useState([]);
    const [loading, setLoading] = useState(true);

    useEffect(() => {
        getSegments(projectId)
            .then(setSegments)
            .catch(console.error)
            .finally(() => setLoading(false));
    }, [projectId]);

    if (loading) return <div className="p-8 text-center">Loading segments...</div>;

    return (
        <div className="h-screen flex flex-col">
            <header className="bg-white border-b p-4 shadow-sm flex justify-between items-center">
                <h2 className="font-semibold text-gray-700">Project: {projectId}</h2>
                <button className="bg-green-600 text-white px-4 py-1 rounded text-sm hover:bg-green-700">Export</button>
            </header>

            <div className="flex-1 overflow-auto bg-gray-100 p-4">
                <div className="max-w-6xl mx-auto space-y-4">
                    {segments.map((seg) => (
                        <div key={seg.id} className="grid grid-cols-2 gap-4 bg-white rounded-lg shadow-sm border border-gray-200 overflow-hidden">
                            {/* Source Column */}
                            <div className="p-4 bg-gray-50 border-r border-gray-100">
                                <div className="text-xs text-gray-400 font-mono mb-1 uppercase tracking-wider">Source</div>
                                {/* We render source as ReadOnly Editor to show tags if we had them, or just text for now */}
                                <div className="text-gray-800 text-sm leading-relaxed whitespace-pre-wrap font-serif">
                                    {seg.source_content}
                                </div>
                            </div>

                            {/* Target Column */}
                            <div className="p-4 bg-white relative group">
                                <div className="text-xs text-gray-400 font-mono mb-1 uppercase tracking-wider flex justify-between">
                                    <span>Target (DE)</span>
                                    <span className={`px-2 py-0.5 rounded-full text-[10px] ${seg.status === 'draft' ? 'bg-yellow-100 text-yellow-700' :
                                            seg.status === 'translated' ? 'bg-green-100 text-green-700' : 'bg-gray-100'
                                        }`}>
                                        {seg.status}
                                    </span>
                                </div>
                                <TiptapEditor
                                    content={seg.target_content || ""}
                                    isReadOnly={false}
                                />
                            </div>
                        </div>
                    ))}
                </div>
            </div>
        </div>
    );
}

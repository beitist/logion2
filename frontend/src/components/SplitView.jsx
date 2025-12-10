import React, { useEffect, useState } from 'react';
import { getSegments, getProject, updateSegment, downloadProject } from "../api/client";
import { TiptapEditor } from './TiptapEditor';

export function SplitView({ projectId }) {
    const [segments, setSegments] = useState([]);
    const [project, setProject] = useState(null);
    const [loading, setLoading] = useState(true);
    const [savingId, setSavingId] = useState(null); // ID of segment currently saving

    useEffect(() => {
        const loadData = async () => {
            try {
                const p = await getProject(projectId);
                setProject(p);
                const s = await getSegments(projectId);
                setSegments(s);
            } catch (err) {
                console.error(err);
            } finally {
                setLoading(false);
            }
        };
        loadData();
    }, [projectId]);

    const handleEditorUpdate = (id, newContent) => {
        setSegments((prev) =>
            prev.map((seg) =>
                seg.id === id ? { ...seg, target_content: newContent } : seg
            )
        );
    };

    const handleSave = async (id, content) => {
        console.log("Saving segment", id);
        setSavingId(id);
        try {
            await updateSegment(id, content);
            // Maybe show a toast?
        } catch (err) {
            console.error("Save failed", err);
            alert("Save failed!");
        } finally {
            setSavingId(null);
        }
    };

    const handleExport = async () => {
        if (!project) return;
        try {
            const blob = await downloadProject(projectId);
            // Create download link
            const url = window.URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = `translated_${project.filename}`;
            document.body.appendChild(a);
            a.click();
            a.remove();
        } catch (err) {
            console.error("Export failed", err);
            alert("Export failed!");
        }
    };

    if (loading) return <div className="p-8 text-center">Loading...</div>;

    return (
        <div className="h-screen flex flex-col">
            <header className="p-4 bg-gray-100 border-b flex justify-between items-center">
                <h1 className="font-bold">Project: {project?.filename}</h1>
                <button
                    onClick={handleExport}
                    className="bg-green-600 text-white px-4 py-2 rounded hover:bg-green-700">
                    Export DOCX
                </button>
            </header>

            <div className="flex-1 overflow-auto p-4">
                <div className="max-w-6xl mx-auto space-y-4">
                    {segments.map((seg) => (
                        <div key={seg.id} className="grid grid-cols-2 gap-4 bg-white rounded-lg shadow-sm border border-gray-200 overflow-hidden">
                            {/* Source Column */}
                            <div className="w-1/2 p-2 bg-gray-50 rounded">
                                {/* Simulating ReadOnly for Source */}
                                <div dangerouslySetInnerHTML={{ __html: seg.source_content }} />
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

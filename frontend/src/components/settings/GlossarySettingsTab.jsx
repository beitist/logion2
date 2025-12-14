
import React, { useEffect, useState } from 'react';
import { getGlossaryTerms, addGlossaryTerm, uploadGlossary } from '../../api/client';

export function GlossarySettingsTab({ project }) {
    const [terms, setTerms] = useState([]);
    const [loading, setLoading] = useState(false);

    // Form State
    const [source, setSource] = useState("");
    const [target, setTarget] = useState("");
    const [note, setNote] = useState("");
    const [isSaving, setIsSaving] = useState(false);
    const [uploadFile, setUploadFile] = useState(null);

    useEffect(() => {
        if (project) loadTerms();
    }, [project]);

    const loadTerms = async () => {
        setLoading(true);
        try {
            const data = await getGlossaryTerms(project.id);
            setTerms(data);
        } catch (e) {
            console.error(e);
        } finally {
            setLoading(false);
        }
    };

    const handleAdd = async (e) => {
        e.preventDefault();
        if (!source || !target) return;

        setIsSaving(true);
        try {
            await addGlossaryTerm(project.id, source, target, note);
            setSource("");
            setTarget("");
            setNote("");
            loadTerms();
        } catch (e) {
            alert("Failed to add term");
        } finally {
            setIsSaving(false);
        }
    };

    const handleUpload = async () => {
        if (!uploadFile) return;
        try {
            await uploadGlossary(project.id, uploadFile);
            setUploadFile(null);
            loadTerms();
            alert("Uploaded successfully!");
        } catch (e) {
            alert("Upload failed");
            console.error(e);
        }
    };

    // CSV Download
    const handleDownload = () => {
        if (!terms.length) return;
        const header = "source,target,note\n";
        const rows = terms.map(t => `"${t.source}","${t.target}","${t.note || ''}"`).join("\n");
        const blob = new Blob([header + rows], { type: 'text/csv' });
        const url = window.URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `glossary_${project.filename || project.id}.csv`;
        document.body.appendChild(a);
        a.click();
        a.remove();
    }

    return (
        <div className="h-full flex flex-col gap-6">
            <div className="flex justify-between items-start">
                <div>
                    <h3 className="text-lg font-bold text-gray-800">Glossary & Terminology</h3>
                    <p className="text-sm text-gray-500">Manage terms that must be strictly translated.</p>
                </div>
                <div className="flex gap-2">
                    <button
                        onClick={handleDownload}
                        className="px-3 py-1 text-xs border rounded hover:bg-gray-50 text-gray-600"
                    >
                        Download CSV
                    </button>
                </div>
            </div>

            {/* Add Term Form */}
            <form onSubmit={handleAdd} className="bg-gray-50 p-4 rounded-lg border border-gray-200 flex flex-col sm:flex-row gap-3 items-end">
                <div className="flex-1 w-full">
                    <label className="block text-xs font-semibold text-gray-600 mb-1">Source Term</label>
                    <input
                        className="w-full text-sm p-2 border rounded focus:ring-2 focus:ring-blue-100 outline-none"
                        placeholder="e.g. Final Report"
                        value={source}
                        onChange={e => setSource(e.target.value)}
                        required
                    />
                </div>
                <div className="flex-1 w-full">
                    <label className="block text-xs font-semibold text-gray-600 mb-1">Target Term</label>
                    <input
                        className="w-full text-sm p-2 border rounded focus:ring-2 focus:ring-blue-100 outline-none"
                        placeholder="e.g. Verwendungsnachweis"
                        value={target}
                        onChange={e => setTarget(e.target.value)}
                        required
                    />
                </div>
                <div className="flex-1 w-full">
                    <label className="block text-xs font-semibold text-gray-600 mb-1">Context Note</label>
                    <input
                        className="w-full text-sm p-2 border rounded focus:ring-2 focus:ring-blue-100 outline-none"
                        placeholder="e.g. Official Term"
                        value={note}
                        onChange={e => setNote(e.target.value)}
                    />
                </div>
                <button
                    type="submit"
                    disabled={isSaving}
                    className="bg-blue-600 text-white px-4 py-2 rounded text-sm font-medium hover:bg-blue-700 transition disabled:opacity-50"
                >
                    {isSaving ? "Adding..." : "Add"}
                </button>
            </form>

            {/* Upload Area */}
            <div className="flex items-center gap-4 text-sm bg-white p-3 border rounded border-dashed border-gray-300">
                <span className="font-semibold text-gray-500">Bulk Upload (CSV):</span>
                <input type="file" accept=".csv" onChange={e => setUploadFile(e.target.files[0])} />
                <button
                    onClick={handleUpload}
                    disabled={!uploadFile}
                    className="px-3 py-1 bg-gray-100 text-gray-700 rounded hover:bg-gray-200 disabled:opacity-50"
                >
                    Upload
                </button>
                <div className="text-xs text-gray-400">CSV Headers: source, target, note</div>
            </div>

            {/* List */}
            <div className="flex-1 overflow-auto border rounded-lg">
                <table className="w-full text-sm text-left">
                    <thead className="bg-gray-100 text-gray-600 font-semibold sticky top-0">
                        <tr>
                            <th className="p-3">Source Term (Lemma)</th>
                            <th className="p-3">Target Term</th>
                            <th className="p-3">Note</th>
                        </tr>
                    </thead>
                    <tbody className="divide-y divide-gray-100">
                        {terms.map(t => (
                            <tr key={t.id} className="hover:bg-gray-50 group">
                                <td className="p-3">
                                    <div className="font-medium text-gray-800">{t.source}</div>
                                    <div className="text-xs text-gray-400 font-mono">{t.lemma}</div>
                                </td>
                                <td className="p-3 text-gray-700">{t.target}</td>
                                <td className="p-3 text-gray-500 italic">{t.note}</td>
                            </tr>
                        ))}
                        {!loading && terms.length === 0 && (
                            <tr><td colSpan="3" className="p-8 text-center text-gray-400 italic">No terms yet.</td></tr>
                        )}
                    </tbody>
                </table>
            </div>
        </div>
    );
}

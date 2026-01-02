import React, { useEffect, useState } from 'react';
import { getGlossaryTerms, addGlossaryTerm, uploadGlossary } from '../../api/client';
import { BookOpen, Plus, Upload, Download, Search } from 'lucide-react';
import { SettingsCard, SettingsSection } from './shared';

/**
 * Glossary Settings Tab
 * 
 * Manages terminology entries that enforce consistent translations.
 * Features:
 * - Add individual terms with source, target, and context note
 * - Bulk CSV upload/download
 * - Searchable term list
 */
export function GlossarySettingsTab({ project }) {
    const [terms, setTerms] = useState([]);
    const [loading, setLoading] = useState(false);
    const [searchQuery, setSearchQuery] = useState('');

    // Form State for adding new terms
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
        } catch (e) {
            alert("Upload failed");
            console.error(e);
        }
    };

    // CSV Download handler
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
    };

    // Filter terms by search query
    const filteredTerms = terms.filter(t =>
        t.source?.toLowerCase().includes(searchQuery.toLowerCase()) ||
        t.target?.toLowerCase().includes(searchQuery.toLowerCase()) ||
        t.note?.toLowerCase().includes(searchQuery.toLowerCase())
    );

    return (
        <div className="h-full flex flex-col gap-5">
            {/* Header Banner - Sleek */}
            <div className="flex items-center justify-between px-1 pb-2 border-b border-gray-100">
                <div className="flex items-center gap-3">
                    <div className="p-2 bg-gray-50 rounded-lg border border-gray-100 text-gray-400">
                        <BookOpen size={18} />
                    </div>
                    <div>
                        <h2 className="font-semibold text-gray-800 text-sm">Glossary & Terminology</h2>
                        <p className="text-xs text-gray-500">
                            {terms.length} term{terms.length !== 1 ? 's' : ''} defined
                        </p>
                    </div>
                </div>
                <button
                    onClick={handleDownload}
                    disabled={terms.length === 0}
                    className="flex items-center gap-2 px-3 py-1.5 text-xs border border-gray-200 
                               rounded-lg hover:bg-gray-50 text-gray-600 transition-colors
                               disabled:opacity-50 disabled:cursor-not-allowed"
                >
                    <Download size={14} />
                    Export CSV
                </button>
            </div>

            {/* Add Term Form */}
            <SettingsCard>
                <SettingsSection
                    icon={Plus}
                    title="Add New Term"
                    accentColor="text-emerald-500"
                >
                    <form onSubmit={handleAdd} className="flex flex-col sm:flex-row gap-3">
                        <div className="flex-1">
                            <input
                                className="w-full text-sm px-3 py-2.5 border border-gray-200 rounded-xl 
                                           focus:ring-2 focus:ring-emerald-500/20 focus:border-emerald-400
                                           shadow-sm transition-all placeholder:text-gray-400"
                                placeholder="Source term (e.g., Final Report)"
                                value={source}
                                onChange={e => setSource(e.target.value)}
                                required
                            />
                        </div>
                        <div className="flex-1">
                            <input
                                className="w-full text-sm px-3 py-2.5 border border-gray-200 rounded-xl 
                                           focus:ring-2 focus:ring-emerald-500/20 focus:border-emerald-400
                                           shadow-sm transition-all placeholder:text-gray-400"
                                placeholder="Target term (e.g., Verwendungsnachweis)"
                                value={target}
                                onChange={e => setTarget(e.target.value)}
                                required
                            />
                        </div>
                        <div className="flex-1">
                            <input
                                className="w-full text-sm px-3 py-2.5 border border-gray-200 rounded-xl 
                                           focus:ring-2 focus:ring-emerald-500/20 focus:border-emerald-400
                                           shadow-sm transition-all placeholder:text-gray-400"
                                placeholder="Context note (optional)"
                                value={note}
                                onChange={e => setNote(e.target.value)}
                            />
                        </div>
                        <button
                            type="submit"
                            disabled={isSaving}
                            className="px-4 py-2.5 bg-gray-900 text-white rounded-xl text-sm font-medium 
                                       hover:bg-black transition-colors shadow-sm
                                       disabled:opacity-50 disabled:cursor-not-allowed
                                       flex items-center gap-2"
                        >
                            <Plus size={16} />
                            {isSaving ? "Adding..." : "Add"}
                        </button>
                    </form>
                </SettingsSection>
            </SettingsCard>

            {/* Bulk Upload */}
            <div className="flex items-center gap-4 p-4 bg-white/50 border-2 border-dashed border-gray-200 rounded-xl">
                <Upload size={20} className="text-gray-400" />
                <div className="flex-1">
                    <input
                        type="file"
                        accept=".csv"
                        onChange={e => setUploadFile(e.target.files[0])}
                        className="text-sm text-gray-600 file:mr-3 file:py-1.5 file:px-3 
                                   file:rounded-lg file:border-0 file:text-sm file:font-medium
                                   file:bg-gray-100 file:text-gray-700 file:cursor-pointer
                                   hover:file:bg-gray-200"
                    />
                </div>
                <button
                    onClick={handleUpload}
                    disabled={!uploadFile}
                    className="px-4 py-1.5 bg-gray-100 text-gray-700 rounded-lg text-sm font-medium
                               hover:bg-gray-200 transition-colors
                               disabled:opacity-50 disabled:cursor-not-allowed"
                >
                    Upload CSV
                </button>
                <div className="text-xs text-gray-400">
                    Headers: source, target, note
                </div>
            </div>

            {/* Search */}
            <div className="relative">
                <Search size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400" />
                <input
                    type="text"
                    placeholder="Search terms..."
                    value={searchQuery}
                    onChange={(e) => setSearchQuery(e.target.value)}
                    className="w-full pl-10 pr-4 py-2.5 border border-gray-200 rounded-xl
                               focus:ring-2 focus:ring-amber-500/20 focus:border-amber-400
                               text-sm transition-all"
                />
            </div>

            {/* Terms Table */}
            <div className="flex-1 overflow-auto border border-gray-200 rounded-xl bg-white">
                <table className="w-full text-sm text-left">
                    <thead className="bg-gray-50 text-gray-600 font-medium sticky top-0">
                        <tr>
                            <th className="px-4 py-3 border-b border-gray-100">Source Term</th>
                            <th className="px-4 py-3 border-b border-gray-100">Target Term</th>
                            <th className="px-4 py-3 border-b border-gray-100">Note</th>
                        </tr>
                    </thead>
                    <tbody className="divide-y divide-gray-50">
                        {filteredTerms.map(t => (
                            <tr key={t.id} className="hover:bg-gray-50 transition-colors">
                                <td className="px-4 py-3">
                                    <div className="font-medium text-gray-800">{t.source}</div>
                                    <div className="text-xs text-gray-400 font-mono">{t.lemma}</div>
                                </td>
                                <td className="px-4 py-3 text-gray-700">{t.target}</td>
                                <td className="px-4 py-3 text-gray-500 italic text-xs">{t.note}</td>
                            </tr>
                        ))}
                        {!loading && filteredTerms.length === 0 && (
                            <tr>
                                <td colSpan="3" className="px-4 py-12 text-center text-gray-400 italic">
                                    {searchQuery ? 'No matching terms found' : 'No terms yet. Add your first term above.'}
                                </td>
                            </tr>
                        )}
                    </tbody>
                </table>
            </div>
        </div>
    );
}

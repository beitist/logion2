import React, { useState } from 'react';
import { createProject } from '../api/client';
import { X, Upload, Sparkles } from 'lucide-react';

export function NewProjectModal({ onClose, onCreated }) {
    const [formData, setFormData] = useState({
        name: '',
        source_lang: 'en',
        target_lang: 'de',
        use_ai: false
    });

    const [files, setFiles] = useState({
        source: [],
        legal: [],
        background: []
    });

    const [isSubmitting, setIsSubmitting] = useState(false);
    const [error, setError] = useState(null);

    const handleInputChange = (e) => {
        const { name, value, type, checked } = e.target;
        setFormData(prev => ({
            ...prev,
            [name]: type === 'checkbox' ? checked : value
        }));
    };

    const handleFileChange = (e, category) => {
        const selectedFiles = Array.from(e.target.files);
        setFiles(prev => ({
            ...prev,
            [category]: [...prev[category], ...selectedFiles]
        }));
    };

    const removeFile = (category, index) => {
        setFiles(prev => ({
            ...prev,
            [category]: prev[category].filter((_, i) => i !== index)
        }));
    };

    const handleSubmit = async (e) => {
        e.preventDefault();
        setError(null);

        if (files.source.length === 0) {
            setError("At least one source file is required.");
            return;
        }

        try {
            setIsSubmitting(true);
            const submission = new FormData();
            submission.append('name', formData.name);
            submission.append('source_lang', formData.source_lang);
            submission.append('target_lang', formData.target_lang);
            submission.append('use_ai', formData.use_ai);

            files.source.forEach(f => submission.append('source_files', f));
            files.legal.forEach(f => submission.append('legal_files', f));
            files.background.forEach(f => submission.append('background_files', f));

            const newProject = await createProject(submission);
            onCreated(newProject);
        } catch (err) {
            console.error(err);
            setError("Failed to create project: " + err.message);
        } finally {
            setIsSubmitting(false);
        }
    };

    const FileList = ({ category, list }) => (
        <div className="mt-2 space-y-2">
            {list.map((f, i) => (
                <div key={i} className="flex justify-between items-center bg-gray-50 px-3 py-2 rounded text-sm">
                    <span className="truncate max-w-[200px]">{f.name}</span>
                    <button
                        type="button"
                        onClick={() => removeFile(category, i)}
                        className="text-gray-400 hover:text-red-500"
                    >
                        <X size={14} />
                    </button>
                </div>
            ))}
        </div>
    );

    return (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm p-4">
            <div className="bg-white rounded-xl shadow-2xl w-full max-w-2xl overflow-hidden flex flex-col max-h-[90vh]">
                <div className="p-4 border-b border-gray-100 flex justify-between items-center">
                    <h2 className="text-xl font-semibold text-gray-800">New Project</h2>
                    <button onClick={onClose} className="text-gray-400 hover:text-gray-600">
                        <X size={24} />
                    </button>
                </div>

                <div className="p-6 overflow-y-auto flex-1">
                    {error && (
                        <div className="mb-4 p-3 bg-red-50 text-red-700 text-sm rounded border border-red-100">
                            {error}
                        </div>
                    )}

                    <form id="createProjectForm" onSubmit={handleSubmit} className="space-y-6">
                        {/* Basic Info */}
                        <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                            <div className="md:col-span-2">
                                <label className="block text-sm font-medium text-gray-700 mb-1">Project Name</label>
                                <input
                                    type="text"
                                    name="name"
                                    value={formData.name}
                                    onChange={handleInputChange}
                                    placeholder="e.g. Annual Report 2024"
                                    className="w-full px-3 py-2 border border-gray-300 rounded-md focus:ring-indigo-500 focus:border-indigo-500"
                                    required
                                />
                            </div>

                            <div>
                                <label className="block text-sm font-medium text-gray-700 mb-1">Source Language</label>
                                <select
                                    name="source_lang"
                                    value={formData.source_lang}
                                    onChange={handleInputChange}
                                    className="w-full px-3 py-2 border border-gray-300 rounded-md focus:ring-indigo-500 focus:border-indigo-500"
                                >
                                    <option value="en">English</option>
                                    <option value="de">German</option>
                                    <option value="fr">French</option>
                                    <option value="es">Spanish</option>
                                </select>
                            </div>

                            <div>
                                <label className="block text-sm font-medium text-gray-700 mb-1">Target Language</label>
                                <select
                                    name="target_lang"
                                    value={formData.target_lang}
                                    onChange={handleInputChange}
                                    className="w-full px-3 py-2 border border-gray-300 rounded-md focus:ring-indigo-500 focus:border-indigo-500"
                                >
                                    <option value="de">German</option>
                                    <option value="en">English</option>
                                    <option value="fr">French</option>
                                    <option value="es">Spanish</option>
                                </select>
                            </div>
                        </div>

                        {/* AI Toggle */}
                        <div className="flex items-center space-x-3 p-4 bg-indigo-50 rounded-lg border border-indigo-100">
                            <div className="flex items-center h-5">
                                <input
                                    id="use_ai"
                                    name="use_ai"
                                    type="checkbox"
                                    checked={formData.use_ai}
                                    onChange={handleInputChange}
                                    className="focus:ring-indigo-500 h-4 w-4 text-indigo-600 border-gray-300 rounded"
                                />
                            </div>
                            <div className="ml-3 text-sm">
                                <label htmlFor="use_ai" className="font-medium text-indigo-900 flex items-center gap-2">
                                    Enable AI Assistance <Sparkles size={14} className="text-indigo-500" />
                                </label>
                                <p className="text-gray-500">Uses generative AI for initial translation drafts and context.</p>
                            </div>
                        </div>

                        {/* File Uploads */}
                        <div className="space-y-4">
                            <h3 className="text-base font-medium text-gray-800 border-b pb-2">Files</h3>

                            {/* Source Files */}
                            <div>
                                <label className="block text-sm font-medium text-gray-700 mb-2">1) Source Files (docx, xlsx)</label>
                                <div className="mt-1 flex justify-center px-6 pt-5 pb-6 border-2 border-gray-300 border-dashed rounded-md hover:border-indigo-400 transition-colors">
                                    <div className="space-y-1 text-center">
                                        <Upload className="mx-auto h-8 w-8 text-gray-400" />
                                        <div className="flex text-sm text-gray-600">
                                            <label htmlFor="source-upload" className="relative cursor-pointer bg-white rounded-md font-medium text-indigo-600 hover:text-indigo-500 focus-within:outline-none">
                                                <span>Upload Source Files</span>
                                                <input id="source-upload" name="source-upload" type="file" className="sr-only" multiple onChange={(e) => handleFileChange(e, 'source')} accept=".docx,.xlsx" />
                                            </label>
                                        </div>
                                    </div>
                                </div>
                                <FileList category="source" list={files.source} />
                            </div>

                            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                                {/* Legal Files */}
                                <div>
                                    <label className="block text-sm font-medium text-gray-700 mb-1">2) Legal / Reference</label>
                                    <input type="file" multiple onChange={(e) => handleFileChange(e, 'legal')} className="block w-full text-sm text-gray-500 file:mr-4 file:py-2 file:px-4 file:rounded-full file:border-0 file:text-sm file:font-semibold file:bg-violet-50 file:text-violet-700 hover:file:bg-violet-100" />
                                    <FileList category="legal" list={files.legal} />
                                </div>

                                {/* Background Files */}
                                <div>
                                    <label className="block text-sm font-medium text-gray-700 mb-1">3) Background / Context</label>
                                    <input type="file" multiple onChange={(e) => handleFileChange(e, 'background')} className="block w-full text-sm text-gray-500 file:mr-4 file:py-2 file:px-4 file:rounded-full file:border-0 file:text-sm file:font-semibold file:bg-blue-50 file:text-blue-700 hover:file:bg-blue-100" />
                                    <FileList category="background" list={files.background} />
                                </div>
                            </div>

                        </div>
                    </form>
                </div>

                <div className="p-4 border-t border-gray-100 bg-gray-50 flex justify-end gap-3">
                    <button
                        type="button"
                        onClick={onClose}
                        className="px-4 py-2 text-sm font-medium text-gray-700 bg-white border border-gray-300 rounded-md hover:bg-gray-50"
                    >
                        Cancel
                    </button>
                    <button
                        form="createProjectForm"
                        type="submit"
                        disabled={isSubmitting}
                        className="px-4 py-2 text-sm font-medium text-white bg-indigo-600 rounded-md hover:bg-indigo-700 disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-2"
                    >
                        {isSubmitting ? 'Creating...' : 'Create Project'}
                    </button>
                </div>
            </div>
        </div>
    );
}

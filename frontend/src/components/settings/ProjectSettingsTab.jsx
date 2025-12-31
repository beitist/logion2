import React, { useState, useEffect } from 'react';
import { updateProject, reinitializeProject } from '../../api/client';
import { Settings, Save, Globe, RefreshCw } from 'lucide-react';

export function ProjectSettingsTab({ project, onUpdate, onReinit }) {
    const [formData, setFormData] = useState({
        name: '',
        source_lang: '',
        target_lang: '',
        use_ai: true
    });

    useEffect(() => {
        if (project) {
            setFormData({
                name: project.name || project.filename,
                source_lang: project.source_lang || 'en',
                target_lang: project.target_lang || 'de',
                use_ai: project.config?.use_ai !== false // Default true
            });
        }
    }, [project]);

    const handleSave = async () => {
        try {
            const currentConfig = project.config || {};
            const updatedProject = await updateProject(project.id, {
                // We don't have a direct name update in schema yet? 
                // Wait, ProjectUpdate schema has source_lang, target_lang. 
                // Name might be read-only or mapped to filename in some logic?
                // Let's assume we can update what schema allows.
                source_lang: formData.source_lang,
                target_lang: formData.target_lang,
                config: {
                    ...currentConfig,
                    use_ai: formData.use_ai
                }
            });
            onUpdate(updatedProject);
            alert("Project Settings saved!");
        } catch (e) {
            alert("Error saving settings: " + e.message);
        }
    };

    return (
        <div className="space-y-6 py-4 h-full flex flex-col">
            <div className="flex items-center gap-2 text-gray-800 bg-gray-50 p-3 rounded-lg border border-gray-200 mb-2">
                <Settings size={18} />
                <span className="font-semibold text-sm">Project Settings</span>
            </div>

            <div className="space-y-6 flex-1 overflow-y-auto pr-2">

                {/* 1. Project Identity */}
                <div>
                    <label className="block text-sm font-medium text-gray-700 mb-1">Project Name</label>
                    <input
                        type="text"
                        value={formData.name}
                        disabled // Name update might need backend support if it's filename based
                        className="w-full px-3 py-2 border border-gray-300 rounded-md bg-gray-100 text-gray-500 cursor-not-allowed"
                        title="Renaming not supported yet"
                    />
                </div>

                {/* 2. Languages */}
                <div className="grid grid-cols-2 gap-4">
                    <div>
                        <label className="block text-sm font-medium text-gray-700 mb-1">Source Language</label>
                        <div className="flex items-center gap-2">
                            <Globe size={14} className="text-gray-400" />
                            <input
                                type="text"
                                value={formData.source_lang}
                                onChange={(e) => setFormData({ ...formData, source_lang: e.target.value })}
                                className="w-full px-3 py-2 border border-gray-300 rounded-md"
                            />
                        </div>
                    </div>
                    <div>
                        <label className="block text-sm font-medium text-gray-700 mb-1">Target Language</label>
                        <div className="flex items-center gap-2">
                            <Globe size={14} className="text-gray-400" />
                            <input
                                type="text"
                                value={formData.target_lang}
                                onChange={(e) => setFormData({ ...formData, target_lang: e.target.value })}
                                className="w-full px-3 py-2 border border-gray-300 rounded-md"
                            />
                        </div>
                    </div>
                </div>

                {/* 3. Features */}
                <div className="p-4 bg-gray-50 rounded-lg border border-gray-200 flex items-center justify-between">
                    <div>
                        <label className="block text-sm font-bold text-gray-900">Enable AI Features</label>
                        <p className="text-xs text-gray-500">RAG, Machine Translation, Drafting</p>
                    </div>
                    <input
                        type="checkbox"
                        checked={formData.use_ai}
                        onChange={(e) => setFormData({ ...formData, use_ai: e.target.checked })}
                        className="h-4 w-4 text-indigo-600 focus:ring-indigo-500 border-gray-300 rounded"
                    />
                </div>

            </div>



            <div className="pt-4 border-t border-gray-100 flex justify-end">
                <button
                    onClick={handleSave}
                    className="flex items-center gap-2 px-6 py-2 bg-gray-900 text-white rounded hover:bg-black transition-colors shadow-sm font-medium"
                >
                    <Save size={16} /> Save Changes
                </button>
            </div>
        </div>
    );
}

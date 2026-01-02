import React, { useState, useEffect } from 'react';
import { updateProject } from '../../api/client';
import { Settings, Globe, Power, Save } from 'lucide-react';
import { SettingsCard, SettingsToggle, SettingsSection } from './shared';

/**
 * Project Settings Tab
 * 
 * Manages:
 * - Project name (read-only for now)
 * - Source and target languages
 * - AI feature toggle
 */
export function ProjectSettingsTab({ project, onUpdate, onReinit }) {
    const [formData, setFormData] = useState({
        name: '',
        source_lang: '',
        target_lang: '',
        use_ai: true
    });
    const [saving, setSaving] = useState(false);

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
        setSaving(true);
        try {
            const currentConfig = project.config || {};
            const updatedProject = await updateProject(project.id, {
                source_lang: formData.source_lang,
                target_lang: formData.target_lang,
                config: {
                    ...currentConfig,
                    use_ai: formData.use_ai
                }
            });
            onUpdate(updatedProject);
        } catch (e) {
            alert("Error saving settings: " + e.message);
        } finally {
            setSaving(false);
        }
    };

    return (
        <div className="space-y-6 py-2 h-full flex flex-col">
            {/* Header Banner */}
            <div className="flex items-center gap-3 bg-gradient-to-r from-gray-500/10 via-slate-500/10 to-zinc-500/10 p-4 rounded-xl border border-gray-200/50">
                <div className="p-2 bg-white rounded-lg shadow-sm">
                    <Settings size={20} className="text-gray-600" />
                </div>
                <div>
                    <h2 className="font-semibold text-gray-800">Project Settings</h2>
                    <p className="text-xs text-gray-500">Languages and core configuration</p>
                </div>
            </div>

            {/* Scrollable Content */}
            <div className="space-y-5 flex-1 overflow-y-auto pr-1">

                {/* Project Identity */}
                <SettingsCard>
                    <SettingsSection
                        icon={Settings}
                        title="Project Identity"
                        accentColor="text-gray-500"
                    >
                        <div>
                            <label className="block text-xs font-medium text-gray-600 mb-1.5">
                                Project Name
                            </label>
                            <input
                                type="text"
                                value={formData.name}
                                disabled
                                className="w-full px-3 py-2.5 border border-gray-200 rounded-xl 
                                           bg-gray-50 text-gray-500 cursor-not-allowed
                                           text-sm"
                                title="Renaming not supported yet"
                            />
                            <p className="text-xs text-gray-400 mt-1">
                                Project name is derived from the source file
                            </p>
                        </div>
                    </SettingsSection>
                </SettingsCard>

                {/* Language Settings */}
                <SettingsCard highlight>
                    <SettingsSection
                        icon={Globe}
                        title="Language Pair"
                        description="Source and target languages for translation"
                        accentColor="text-blue-500"
                    >
                        <div className="grid grid-cols-2 gap-4">
                            {/* Source Language */}
                            <div>
                                <label className="block text-xs font-medium text-gray-600 mb-1.5">
                                    Source Language
                                </label>
                                <div className="relative">
                                    <input
                                        type="text"
                                        value={formData.source_lang}
                                        onChange={(e) => setFormData({ ...formData, source_lang: e.target.value })}
                                        className="w-full px-3 py-2.5 pl-9 border border-gray-200 rounded-xl 
                                                   focus:ring-2 focus:ring-blue-500/20 focus:border-blue-400 
                                                   shadow-sm text-sm transition-all uppercase font-mono"
                                        maxLength={5}
                                    />
                                    <span className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400">
                                        🌐
                                    </span>
                                </div>
                            </div>

                            {/* Arrow indicator */}
                            <div className="hidden md:flex items-center justify-center absolute left-1/2 -translate-x-1/2 text-gray-300 text-2xl">
                                →
                            </div>

                            {/* Target Language */}
                            <div>
                                <label className="block text-xs font-medium text-gray-600 mb-1.5">
                                    Target Language
                                </label>
                                <div className="relative">
                                    <input
                                        type="text"
                                        value={formData.target_lang}
                                        onChange={(e) => setFormData({ ...formData, target_lang: e.target.value })}
                                        className="w-full px-3 py-2.5 pl-9 border border-gray-200 rounded-xl 
                                                   focus:ring-2 focus:ring-blue-500/20 focus:border-blue-400 
                                                   shadow-sm text-sm transition-all uppercase font-mono"
                                        maxLength={5}
                                    />
                                    <span className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400">
                                        🎯
                                    </span>
                                </div>
                            </div>
                        </div>
                    </SettingsSection>
                </SettingsCard>

                {/* Feature Toggles */}
                <SettingsCard>
                    <SettingsSection
                        icon={Power}
                        title="Features"
                        accentColor="text-emerald-500"
                    >
                        <div className="flex items-center justify-between p-3 bg-white rounded-xl border border-gray-100">
                            <div className="flex-1">
                                <div className="text-sm font-medium text-gray-800">
                                    Enable AI Features
                                </div>
                                <div className="text-xs text-gray-500 mt-0.5">
                                    RAG retrieval, Machine Translation, drafting
                                </div>
                            </div>
                            <SettingsToggle
                                checked={formData.use_ai}
                                onChange={(val) => setFormData({ ...formData, use_ai: val })}
                                accentColor="bg-emerald-500"
                            />
                        </div>
                    </SettingsSection>
                </SettingsCard>
            </div>

            {/* Save Button Footer */}
            <div className="pt-4 border-t border-gray-100 flex justify-end">
                <button
                    onClick={handleSave}
                    disabled={saving}
                    className="flex items-center gap-2 px-6 py-2.5 
                               bg-gradient-to-r from-gray-800 to-gray-900 
                               text-white rounded-xl 
                               hover:from-gray-900 hover:to-black 
                               transition-all shadow-sm font-medium
                               disabled:opacity-50 disabled:cursor-not-allowed"
                >
                    <Save size={16} />
                    {saving ? 'Saving...' : 'Save Changes'}
                </button>
            </div>
        </div>
    );
}

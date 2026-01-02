import React, { useState, useEffect } from 'react';
import { updateProject, getAiModels } from '../../api/client';
import { Zap, Command, Cpu, FileText, Sparkles, Eye, Save } from 'lucide-react';
import { SettingsCard, SettingsToggle, SettingsSection } from './shared';

/**
 * AI Configuration Settings Tab
 * 
 * Manages:
 * - Model selection (Editor vs Workflow models)
 * - Custom system prompt for translation style
 * - Batch processing settings
 * - Auto-fetch MT behavior (on focus vs preload mode)
 * - GUI display options (show match penalties)
 */
export function AISettingsTab({ project, onUpdate, onQueueAll }) {
    const [settings, setSettings] = useState({
        model: '',
        workflow_model: '',
        custom_prompt: '',
        pre_translate_count: 0,
        batch_size: 10,
        preload_mode: false  // If true, disables auto-fetch on focus
    });

    // GUI Settings (stored in project.config.gui_settings)
    const [guiSettings, setGuiSettings] = useState({
        show_match_penalties: false,
        auto_fetch_mt_on_focus: true  // Default: auto-fetch is enabled
    });

    const [availableModels, setAvailableModels] = useState([]);
    const [loadingModels, setLoadingModels] = useState(true);
    const [saving, setSaving] = useState(false);

    // Load Project Config
    useEffect(() => {
        if (project && project.config) {
            const ai = project.config.ai_settings || {};
            const gui = project.config.gui_settings || {};

            setSettings({
                model: ai.model || '',
                workflow_model: ai.workflow_model || '',
                custom_prompt: ai.custom_prompt || '',
                pre_translate_count: ai.pre_translate_count || 0,
                batch_size: ai.batch_size || 10,
                preload_mode: ai.preload_mode || false
            });

            setGuiSettings({
                show_match_penalties: gui.show_match_penalties || false,
                // Auto-fetch is the inverse of preload_mode for UX clarity
                auto_fetch_mt_on_focus: !ai.preload_mode
            });
        }
    }, [project]);

    // Load Available Models from backend
    useEffect(() => {
        const fetchModels = async () => {
            try {
                const data = await getAiModels();
                if (data.models) {
                    // Filter out background models (embedding/RAG) from selection
                    const mtModels = data.models.filter(m => m.usage !== 'bg');
                    setAvailableModels(mtModels);

                    // Set defaults if not configured
                    setSettings(s => {
                        const newS = { ...s };
                        if (!newS.model && data.models.length > 0) newS.model = data.models[0].id;
                        if (!newS.workflow_model && data.models.length > 0) newS.workflow_model = data.models[0].id;
                        return newS;
                    });
                }
            } catch (e) {
                console.error("Failed to load models", e);
                // Fallback to hardcoded default
                setAvailableModels([{ id: 'gemini-2.5-flash', name: 'Gemini 2.5 Flash (Fallback)' }]);
            } finally {
                setLoadingModels(false);
            }
        };
        fetchModels();
    }, []);

    const handleSave = async () => {
        setSaving(true);
        try {
            const currentConfig = project.config || {};

            // Convert auto_fetch toggle back to preload_mode for storage
            const updatedAiSettings = {
                ...(currentConfig.ai_settings || {}),
                ...settings,
                preload_mode: !guiSettings.auto_fetch_mt_on_focus
            };

            const updatedProject = await updateProject(project.id, {
                config: {
                    ...currentConfig,
                    ai_settings: updatedAiSettings,
                    gui_settings: {
                        ...(currentConfig.gui_settings || {}),
                        show_match_penalties: guiSettings.show_match_penalties
                    }
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
            <div className="flex items-center gap-3 bg-gradient-to-r from-purple-500/10 via-indigo-500/10 to-blue-500/10 p-4 rounded-xl border border-purple-200/50">
                <div className="p-2 bg-white rounded-lg shadow-sm">
                    <Zap size={20} className="text-purple-600" />
                </div>
                <div>
                    <h2 className="font-semibold text-gray-800">AI Configuration</h2>
                    <p className="text-xs text-gray-500">Models, prompts, and automation settings</p>
                </div>
            </div>

            {/* Scrollable Content Area */}
            <div className="space-y-5 flex-1 overflow-y-auto pr-1">

                {/* Model Selection Section */}
                <SettingsCard>
                    <SettingsSection
                        icon={Cpu}
                        title="Translation Models"
                        description="Choose AI models for different workflows"
                        accentColor="text-purple-500"
                    >
                        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                            {/* Editor Model */}
                            <div>
                                <label className="block text-xs font-medium text-gray-600 mb-1.5">
                                    Editor Model
                                    <span className="text-gray-400 font-normal ml-1">(Manual & Shortcuts)</span>
                                </label>
                                {loadingModels ? (
                                    <div className="h-10 bg-gray-100 rounded-lg animate-pulse" />
                                ) : (
                                    <select
                                        value={settings.model}
                                        onChange={(e) => setSettings({ ...settings, model: e.target.value })}
                                        className="w-full px-3 py-2.5 border border-gray-200 rounded-xl bg-white 
                                                   focus:ring-2 focus:ring-purple-500/20 focus:border-purple-400 
                                                   shadow-sm text-sm transition-all"
                                    >
                                        {availableModels.map(m => (
                                            <option key={m.id} value={m.id}>{m.name}</option>
                                        ))}
                                    </select>
                                )}
                            </div>

                            {/* Workflow Model */}
                            <div>
                                <label className="block text-xs font-medium text-gray-600 mb-1.5">
                                    Workflow Model
                                    <span className="text-gray-400 font-normal ml-1">(Batch Operations)</span>
                                </label>
                                {loadingModels ? (
                                    <div className="h-10 bg-gray-100 rounded-lg animate-pulse" />
                                ) : (
                                    <select
                                        value={settings.workflow_model}
                                        onChange={(e) => setSettings({ ...settings, workflow_model: e.target.value })}
                                        className="w-full px-3 py-2.5 border border-gray-200 rounded-xl bg-white 
                                                   focus:ring-2 focus:ring-purple-500/20 focus:border-purple-400 
                                                   shadow-sm text-sm transition-all"
                                    >
                                        {availableModels.map(m => (
                                            <option key={m.id} value={m.id}>{m.name}</option>
                                        ))}
                                    </select>
                                )}
                            </div>
                        </div>
                    </SettingsSection>
                </SettingsCard>

                {/* Custom Prompt Section */}
                <SettingsCard>
                    <SettingsSection
                        icon={FileText}
                        title="Custom Instructions"
                        description="System prompt injected into all translations"
                        accentColor="text-blue-500"
                    >
                        <textarea
                            value={settings.custom_prompt}
                            onChange={(e) => setSettings({ ...settings, custom_prompt: e.target.value })}
                            placeholder="e.g. 'Use formal bureaucratic German. Avoid anglicisms. Address experts.'"
                            className="w-full h-28 px-4 py-3 border border-gray-200 rounded-xl 
                                       focus:ring-2 focus:ring-blue-500/20 focus:border-blue-400 
                                       shadow-sm text-sm font-mono resize-none transition-all
                                       placeholder:text-gray-400"
                        />
                    </SettingsSection>
                </SettingsCard>

                {/* Automation Settings */}
                <SettingsCard highlight>
                    <SettingsSection
                        icon={Sparkles}
                        title="Automation Behavior"
                        description="Control how and when MT drafts are generated"
                        accentColor="text-indigo-500"
                    >
                        <div className="space-y-4">
                            {/* Auto-fetch on Focus Toggle */}
                            <div className="flex items-center justify-between p-3 bg-white rounded-xl border border-gray-100">
                                <div className="flex-1">
                                    <div className="text-sm font-medium text-gray-800">
                                        Auto-fetch MT on focus
                                    </div>
                                    <div className="text-xs text-gray-500 mt-0.5">
                                        When enabled, focusing an empty segment triggers MT generation
                                    </div>
                                </div>
                                <SettingsToggle
                                    checked={guiSettings.auto_fetch_mt_on_focus}
                                    onChange={(val) => setGuiSettings({ ...guiSettings, auto_fetch_mt_on_focus: val })}
                                    accentColor="bg-indigo-500"
                                />
                            </div>

                            {/* Batch Size */}
                            <div className="flex items-center justify-between p-3 bg-white rounded-xl border border-gray-100">
                                <div className="flex-1">
                                    <div className="text-sm font-medium text-gray-800">
                                        Batch Size
                                    </div>
                                    <div className="text-xs text-gray-500 mt-0.5">
                                        Segments per batch request (workflows)
                                    </div>
                                </div>
                                <input
                                    type="number"
                                    min="1"
                                    max="50"
                                    value={settings.batch_size}
                                    onChange={(e) => setSettings({ ...settings, batch_size: parseInt(e.target.value) || 10 })}
                                    className="w-20 px-3 py-1.5 text-center border border-gray-200 rounded-lg 
                                               focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-400 
                                               text-sm font-medium"
                                />
                            </div>

                            {/* Pre-translate Count */}
                            <div className="flex items-center justify-between p-3 bg-white rounded-xl border border-gray-100">
                                <div className="flex-1">
                                    <div className="text-sm font-medium text-gray-800">
                                        Pre-cache on Load
                                    </div>
                                    <div className="text-xs text-gray-500 mt-0.5">
                                        Number of segments to auto-draft when opening
                                    </div>
                                </div>
                                <input
                                    type="number"
                                    min="0"
                                    max="20"
                                    value={settings.pre_translate_count}
                                    onChange={(e) => setSettings({ ...settings, pre_translate_count: parseInt(e.target.value) || 0 })}
                                    className="w-20 px-3 py-1.5 text-center border border-gray-200 rounded-lg 
                                               focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-400 
                                               text-sm font-medium"
                                />
                            </div>
                        </div>
                    </SettingsSection>
                </SettingsCard>

                {/* Display Settings */}
                <SettingsCard>
                    <SettingsSection
                        icon={Eye}
                        title="Display Options"
                        description="Customize the translation interface"
                        accentColor="text-emerald-500"
                    >
                        <div className="flex items-center justify-between p-3 bg-white rounded-xl border border-gray-100">
                            <div className="flex-1">
                                <div className="text-sm font-medium text-gray-800">
                                    Show match quality explanations
                                </div>
                                <div className="text-xs text-gray-500 mt-0.5">
                                    Display penalty reasons on TM matches (numbers, length, etc.)
                                </div>
                            </div>
                            <SettingsToggle
                                checked={guiSettings.show_match_penalties}
                                onChange={(val) => setGuiSettings({ ...guiSettings, show_match_penalties: val })}
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
                    {saving ? 'Saving...' : 'Save AI Settings'}
                </button>
            </div>
        </div>
    );
}

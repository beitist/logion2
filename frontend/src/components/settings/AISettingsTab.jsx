import React, { useState, useEffect } from 'react';
import { updateProject } from '../../api/client';
import { Zap, Command, RefreshCw, Save, Terminal } from 'lucide-react';

export function AISettingsTab({ project, onUpdate }) {
    const [settings, setSettings] = useState({
        model: 'gemini-2.0-flash',
        custom_prompt: '',
        pre_translate_count: 0
    });

    const [availableModels, setAvailableModels] = useState([]);
    const [loadingModels, setLoadingModels] = useState(true);

    // Load Project Config
    useEffect(() => {
        if (project && project.config) {
            const ai = project.config.ai_settings || {};
            setSettings({
                model: ai.model || 'gemini-2.0-flash',
                custom_prompt: ai.custom_prompt || '',
                pre_translate_count: ai.pre_translate_count || 0
            });
        }
    }, [project]);

    // Load Available Models
    useEffect(() => {
        const fetchModels = async () => {
            try {
                // Fetch from the backend endpoint we created
                // Assuming client.js usually has the base URL, but here we might need to construct it or add a helper.
                // Since updateProject uses a client, let's just use fetch for now or add getModels to client.
                const res = await fetch('http://localhost:8000/config/models');
                const data = await res.json();
                if (data.models) {
                    setAvailableModels(data.models);
                }
            } catch (e) {
                console.error("Failed to load models", e);
                // Fallback
                setAvailableModels([{ id: 'gemini-2.0-flash', name: 'Gemini 2.0 Flash (Fallback)' }]);
            } finally {
                setLoadingModels(false);
            }
        };
        fetchModels();
    }, []);

    const handleSave = async () => {
        try {
            const currentConfig = project.config || {};
            const updatedProject = await updateProject(project.id, {
                config: {
                    ...currentConfig,
                    ai_settings: {
                        ...(currentConfig.ai_settings || {}),
                        ...settings
                    }
                }
            });
            onUpdate(updatedProject);
            alert("AI Settings saved!");
        } catch (e) {
            alert("Error saving settings: " + e.message);
        }
    };

    return (
        <div className="space-y-6 py-4 h-full flex flex-col">
            <div className="flex items-center gap-2 text-purple-800 bg-purple-50 p-3 rounded-lg border border-purple-100 mb-2">
                <Zap size={18} />
                <span className="font-semibold text-sm">AI Model & Prompting</span>
            </div>

            <div className="space-y-6 flex-1 overflow-y-auto pr-2">
                {/* 1. Model Selection */}
                <div>
                    <label className="block text-sm font-medium text-gray-700 mb-1">Generative Model</label>
                    {loadingModels ? (
                        <div className="text-gray-400 text-sm animate-pulse">Loading models...</div>
                    ) : (
                        <select
                            value={settings.model}
                            onChange={(e) => setSettings({ ...settings, model: e.target.value })}
                            className="w-full px-3 py-2 border border-gray-300 rounded-md bg-white focus:ring-indigo-500 focus:border-indigo-500 shadow-sm"
                        >
                            {availableModels.map(m => (
                                <option key={m.id} value={m.id}>
                                    {m.name}
                                </option>
                            ))}
                        </select>
                    )}
                    <p className="text-xs text-gray-500 mt-1">Select the underlying engine for drafts and translations.</p>
                </div>

                {/* 2. Custom Prompt */}
                <div>
                    <label className="block text-sm font-medium text-gray-700 mb-1 flex items-center justify-between">
                        <span>Custom Instructions (System Prompt)</span>
                        <span className="text-xs text-gray-400 font-normal">Optional</span>
                    </label>
                    <textarea
                        value={settings.custom_prompt}
                        onChange={(e) => setSettings({ ...settings, custom_prompt: e.target.value })}
                        placeholder="e.g. 'Use formal bureaucratic German. Do not use anglicisms. Address the audience as experts.'"
                        className="w-full h-32 px-3 py-2 border border-gray-300 rounded-lg focus:ring-purple-500 focus:border-purple-500 shadow-sm text-sm font-mono"
                    />
                    <p className="text-xs text-gray-500 mt-1">
                        These instructions are injected into the system prompt. Use this to define tone, style, or specific terminology rules.
                    </p>
                </div>

                {/* 3. Pre-Translate (Legacy/Helper) */}
                <div className="p-4 bg-gray-50 rounded-lg border border-gray-200">
                    <label className="block text-sm font-medium text-gray-700 mb-1">Auto-Drafting (Pre-Cache)</label>
                    <div className="flex items-center gap-4">
                        <input
                            type="number"
                            min="0"
                            max="20"
                            value={settings.pre_translate_count}
                            onChange={(e) => setSettings({ ...settings, pre_translate_count: parseInt(e.target.value) })}
                            className="w-24 px-3 py-2 border border-gray-300 rounded-md focus:ring-indigo-500 focus:border-indigo-500"
                        />
                        <span className="text-sm text-gray-600">segments on load</span>
                    </div>
                </div>
            </div>

            <div className="pt-4 border-t border-gray-100 flex justify-end">
                <button
                    onClick={handleSave}
                    className="flex items-center gap-2 px-6 py-2 bg-gray-900 text-white rounded hover:bg-black transition-colors shadow-sm font-medium"
                >
                    <Save size={16} /> Save AI Settings
                </button>
            </div>
        </div>
    );
}

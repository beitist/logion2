import React, { useState, useEffect } from 'react';
import { updateProject, getAiModels } from '../../api/client';
import { Zap, Command, Cpu, FileText, Sparkles, Eye, Save } from 'lucide-react';
import { SettingsCard, SettingsToggle, SettingsSection } from './shared';

/**
 * Default custom prompt for translation style / system instruction.
 * Sourced from ÜPrompt.txt – professional German translation guidance
 * for government/development cooperation documents (BMZ style).
 * Users can freely edit or replace this in the settings UI.
 */
const DEFAULT_CUSTOM_PROMPT = `Du bist ein erfahrener Fachübersetzer für Verwaltung und Projektmanagement. Deine Aufgabe: Überführe den englischen Sachverhalt in ein präzises, flüssiges Deutsch.

Regeln: Löse dich von der englischen Satzstruktur. Wenn das Englische ein Ding als handelndes Subjekt nutzt (z. B. 'The amendment approved'), formuliere im Deutschen passiv oder einleitend ('Mit der Änderung wurde...'). Fachbegriffe sind in angemessener Behördensprache wiederzugeben. Das Ziel ist maximale Lesbarkeit für deutsche Entscheider beim BMZ. Beachte auch die vorhergehenden Sätze und sorge für einen flüssigen Lesefluss. Achte auf sprachliche Kohärenz. Du darfst lange Sätze auf mehrere Sätze aufteilen, wenn das sinnvoll erscheint.

Bitte achte auf eine geschlechterneutrale Sprache oder benutze den Gender-* für die deutsche Übersetzung.

Beispiel für den gewünschten Stil: Source: "The report highlights the need for gender-sensitive budgeting, whereas previous versions focused on pure financial metrics." Target: "Während sich frühere Fassungen auf rein finanzielle Kennzahlen konzentrierten, unterstreicht der vorliegende Bericht die Notwendigkeit einer gendersensiblen Haushaltsplanung."

Beispiel 2 für den gewünschten Stil: Source: "The project implementation has been successful in most regions, whereas the reporting from the rural areas remains inconsistent." Target: "Während die Projektumsetzung in den meisten Regionen erfolgreich verlief, weist die Berichterstattung aus den ländlichen Gebieten nach wie vor Lücken auf."

Prüfe den Text auf typisches 'Übersetzungsdeutsch' und formuliere ihn so um, als wäre er ursprünglich in deutscher Sprache verfasst worden (z. B.: nicht: whereas -> wobei, sondern passend umformulieren).

Prüfe deine Übersetzung vor der Ausgabe: Würde dieser Satz so in einem offiziellen deutschen Regierungsdokument stehen? Falls er noch nach 'Übersetzung' klingt, strukturiere ihn radikal um.`;

/** Preferred default model ID for both editor and workflow translation */
const DEFAULT_MODEL_ID = 'gemini-3.1-pro-preview';

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
        glossary_model: '',
        auto_glossary_on_edit: false,
        custom_prompt: '',
        topic_description: '',
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
                glossary_model: ai.glossary_model || '',
                auto_glossary_on_edit: ai.auto_glossary_on_edit || false,
                // Fall back to the default translation prompt if none is configured yet
                custom_prompt: ai.custom_prompt !== undefined ? ai.custom_prompt : DEFAULT_CUSTOM_PROMPT,
                topic_description: ai.topic_description || '',
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

                    // Set defaults if not configured:
                    // Prefer Gemini 3 Pro Preview for quality; fall back to first available model
                    setSettings(s => {
                        const newS = { ...s };
                        const hasDefault = mtModels.some(m => m.id === DEFAULT_MODEL_ID);
                        const fallbackId = hasDefault ? DEFAULT_MODEL_ID : (mtModels[0]?.id || '');
                        if (!newS.model) newS.model = fallbackId;
                        if (!newS.workflow_model) newS.workflow_model = fallbackId;
                        // Default glossary model to cheapest Flash model
                        if (!newS.glossary_model) {
                            const flash = mtModels.find(m => m.id.includes('flash'));
                            newS.glossary_model = flash?.id || fallbackId;
                        }
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
            {/* Header Banner - Sleek */}
            <div className="flex items-center gap-3 px-1 pb-2 border-b border-gray-100">
                <div className="p-2 bg-gray-50 rounded-lg border border-gray-100 text-gray-400">
                    <Zap size={18} />
                </div>
                <div>
                    <h2 className="font-semibold text-gray-800 text-sm">AI Configuration</h2>
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
                        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                            {/* Editor Model */}
                            <div>
                                <label className="block text-xs font-medium text-gray-600 mb-1.5">
                                    Editor Model
                                    <span className="text-gray-400 font-normal ml-1">(Manual)</span>
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
                                    <span className="text-gray-400 font-normal ml-1">(Batch)</span>
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

                            {/* Glossary Model */}
                            <div>
                                <label className="block text-xs font-medium text-gray-600 mb-1.5">
                                    Glossary Model
                                    <span className="text-gray-400 font-normal ml-1">(Extraction)</span>
                                </label>
                                {loadingModels ? (
                                    <div className="h-10 bg-gray-100 rounded-lg animate-pulse" />
                                ) : (
                                    <select
                                        value={settings.glossary_model}
                                        onChange={(e) => setSettings({ ...settings, glossary_model: e.target.value })}
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

                {/* Topic Description */}
                <SettingsCard>
                    <SettingsSection
                        icon={Command}
                        title="Topic / Domain"
                        description="Describes the project domain for auto-glossary extraction"
                        accentColor="text-teal-500"
                    >
                        <textarea
                            value={settings.topic_description}
                            onChange={(e) => setSettings({ ...settings, topic_description: e.target.value })}
                            placeholder="e.g. 'Evaluation of GIZ projects in the area of climate adaptation in Sub-Saharan Africa.'"
                            rows={2}
                            className="w-full px-4 py-3 border border-gray-200 rounded-xl
                                       focus:ring-2 focus:ring-teal-500/20 focus:border-teal-400
                                       shadow-sm text-sm resize-none transition-all
                                       placeholder:text-gray-400"
                        />
                    </SettingsSection>
                </SettingsCard>

                {/* Automation Settings */}
                <SettingsCard>
                    <SettingsSection
                        icon={Sparkles}
                        title="Automation Behavior"
                        description="Control how and when MT drafts are generated"
                    >
                        <div className="space-y-2">
                            {/* Auto-fetch on Focus Toggle */}
                            <label className="flex items-center gap-3 px-3 py-2 bg-white rounded-lg border border-gray-100 cursor-pointer">
                                <SettingsToggle
                                    checked={guiSettings.auto_fetch_mt_on_focus}
                                    onChange={(val) => setGuiSettings({ ...guiSettings, auto_fetch_mt_on_focus: val })}
                                    accentColor="bg-indigo-500"
                                />
                                <div className="min-w-0">
                                    <span className="text-sm font-medium text-gray-800">Auto-fetch MT on focus</span>
                                    <span className="text-xs text-gray-400 ml-1.5">— generates draft when focusing empty segment</span>
                                </div>
                            </label>

                            {/* Auto-Glossary on Edit */}
                            <label className="flex items-center gap-3 px-3 py-2 bg-white rounded-lg border border-gray-100 cursor-pointer">
                                <SettingsToggle
                                    checked={settings.auto_glossary_on_edit}
                                    onChange={(val) => setSettings({ ...settings, auto_glossary_on_edit: val })}
                                    accentColor="bg-teal-500"
                                />
                                <div className="min-w-0">
                                    <span className="text-sm font-medium text-gray-800">Auto-Glossary on single MT</span>
                                    <span className="text-xs text-gray-400 ml-1.5">— extracts terms after each translation</span>
                                </div>
                            </label>

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
                    className="flex items-center gap-2 px-4 py-2 
                               bg-gray-900 hover:bg-black 
                               text-white text-xs font-semibold rounded-lg
                               transition-colors shadow-sm
                               disabled:opacity-50 disabled:cursor-not-allowed"
                >
                    <Save size={14} />
                    {saving ? 'Saving...' : 'Save AI Settings'}
                </button>
            </div>
        </div>
    );
}

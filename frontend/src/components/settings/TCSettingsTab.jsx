import React, { useState, useEffect } from 'react';
import { updateProject } from '../../api/client';
import { GitCompareArrows, UserPen, Save } from 'lucide-react';
import { SettingsCard, SettingsToggle, SettingsSection } from './shared';

/**
 * Track Changes Settings Tab
 *
 * Manages:
 * - TC mode (first_last vs step_by_step)
 * - Author replacement for export
 * - Translator display name
 */
export function TCSettingsTab({ project, onUpdate }) {
    const [settings, setSettings] = useState({
        tc_mode: 'first_last',
        tc_replace_authors: false,
        tc_translator_name: ''
    });
    const [saving, setSaving] = useState(false);

    useEffect(() => {
        if (project && project.config) {
            const tc = project.config.tc_settings || {};
            setSettings({
                tc_mode: tc.tc_mode || 'first_last',
                tc_replace_authors: tc.tc_replace_authors || false,
                tc_translator_name: tc.tc_translator_name || ''
            });
        }
    }, [project]);

    const handleSave = async () => {
        setSaving(true);
        try {
            const currentConfig = project.config || {};
            const updatedProject = await updateProject(project.id, {
                config: {
                    ...currentConfig,
                    tc_settings: settings
                }
            });
            onUpdate(updatedProject);
        } catch (e) {
            alert("Error saving TC settings: " + e.message);
        } finally {
            setSaving(false);
        }
    };

    const modes = [
        {
            value: 'first_last',
            label: 'Einfach (Original → Final)',
            desc: 'Source zeigt ein Diff zwischen Original und Final. Target wird normal übersetzt.'
        },
        {
            value: 'step_by_step',
            label: 'Schritt für Schritt',
            desc: 'Source-Slider navigiert Revisionen. Target-Editor trackt Änderungen des Übersetzers.'
        }
    ];

    return (
        <div className="space-y-6 py-2 h-full flex flex-col">
            {/* Header Banner */}
            <div className="flex items-center gap-3 px-1 pb-2 border-b border-gray-100">
                <div className="p-2 bg-gray-50 rounded-lg border border-gray-100 text-gray-400">
                    <GitCompareArrows size={18} />
                </div>
                <div>
                    <h2 className="font-semibold text-gray-800 text-sm">Track Changes</h2>
                    <p className="text-xs text-gray-500">Revision tracking and author settings</p>
                </div>
            </div>

            {/* Scrollable Content */}
            <div className="space-y-5 flex-1 overflow-y-auto pr-1">

                {/* Mode Selection */}
                <SettingsCard>
                    <SettingsSection
                        icon={GitCompareArrows}
                        title="TC-Modus"
                        description="Wie sollen Track Changes beim Übersetzen behandelt werden?"
                        accentColor="text-blue-500"
                    >
                        <div className="space-y-2">
                            {modes.map(mode => (
                                <label
                                    key={mode.value}
                                    className={`flex items-start gap-3 p-3 rounded-xl border cursor-pointer transition-all ${
                                        settings.tc_mode === mode.value
                                            ? 'border-blue-300 bg-blue-50/50'
                                            : 'border-gray-100 bg-white hover:border-gray-200'
                                    }`}
                                >
                                    <input
                                        type="radio"
                                        name="tc_mode"
                                        value={mode.value}
                                        checked={settings.tc_mode === mode.value}
                                        onChange={(e) => setSettings({ ...settings, tc_mode: e.target.value })}
                                        className="mt-0.5 accent-blue-600"
                                    />
                                    <div className="flex-1">
                                        <div className="text-sm font-medium text-gray-800">{mode.label}</div>
                                        <div className="text-xs text-gray-500 mt-0.5">{mode.desc}</div>
                                    </div>
                                </label>
                            ))}
                        </div>
                    </SettingsSection>
                </SettingsCard>

                {/* Author Settings */}
                <SettingsCard>
                    <SettingsSection
                        icon={UserPen}
                        title="Autoren-Einstellungen"
                        description="Steuert wie Revisionsautoren im Export erscheinen"
                        accentColor="text-amber-500"
                    >
                        <div className="space-y-4">
                            <div className="flex items-center justify-between p-3 bg-white rounded-xl border border-gray-100">
                                <div className="flex-1">
                                    <div className="text-sm font-medium text-gray-800">
                                        Revisionsautoren ersetzen
                                    </div>
                                    <div className="text-xs text-gray-500 mt-0.5">
                                        Verwendet den Übersetzer-Namen statt der Original-Autoren
                                    </div>
                                </div>
                                <SettingsToggle
                                    enabled={settings.tc_replace_authors}
                                    onChange={(val) => setSettings({ ...settings, tc_replace_authors: val })}
                                    accentColor="bg-amber-500"
                                />
                            </div>

                            {settings.tc_replace_authors && (
                                <div>
                                    <label className="block text-xs font-medium text-gray-600 mb-1.5">
                                        Übersetzer-Name
                                    </label>
                                    <input
                                        type="text"
                                        value={settings.tc_translator_name}
                                        onChange={(e) => setSettings({ ...settings, tc_translator_name: e.target.value })}
                                        placeholder="z.B. Max Mustermann"
                                        className="w-full px-3 py-2.5 border border-gray-200 rounded-xl
                                                   focus:ring-2 focus:ring-amber-500/20 focus:border-amber-400
                                                   shadow-sm text-sm transition-all"
                                    />
                                    <p className="text-xs text-gray-400 mt-1">
                                        Wird als Autor für alle Änderungen im Target-Editor und im DOCX-Export verwendet
                                    </p>
                                </div>
                            )}
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
                    {saving ? 'Saving...' : 'Save Changes'}
                </button>
            </div>
        </div>
    );
}

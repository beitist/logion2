import React, { useState, useEffect } from 'react';
import { updateProject, reingestProject } from '../../api/client';
import { Database, Sliders, Save, AlertTriangle } from 'lucide-react';
import { SettingsCard, SettingsSection } from './shared';

/**
 * RAG Settings Tab
 * 
 * Manages context match thresholds for different match types.
 * Controls minimum confidence scores for displaying matches.
 */
export function RAGSettingsTab({ project, onUpdate }) {
    const [settings, setSettings] = useState({
        threshold_mandatory: 60,
        threshold_optional: 40,
        threshold_tm: 60,
        threshold_internal_tm: 50
    });
    const [saving, setSaving] = useState(false);

    useEffect(() => {
        if (project && project.config) {
            const ai = project.config.ai_settings || {};
            setSettings({
                threshold_mandatory: ai.threshold_mandatory !== undefined ? ai.threshold_mandatory : 60,
                threshold_optional: ai.threshold_optional !== undefined ? ai.threshold_optional : 40,
                threshold_tm: ai.threshold_tm !== undefined ? ai.threshold_tm : 60,
                threshold_internal_tm: ai.threshold_internal_tm !== undefined ? ai.threshold_internal_tm : 50
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
                    ai_settings: {
                        ...(currentConfig.ai_settings || {}),
                        ...settings
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

    // Reusable slider component
    const ThresholdSlider = ({ label, emoji, value, field, color }) => {
        const colorClasses = {
            red: { bg: 'bg-red-500', light: 'bg-red-100', text: 'text-red-700', accent: 'accent-red-500' },
            blue: { bg: 'bg-blue-500', light: 'bg-blue-100', text: 'text-blue-700', accent: 'accent-blue-500' },
            green: { bg: 'bg-green-500', light: 'bg-green-100', text: 'text-green-700', accent: 'accent-green-500' }
        };
        const c = colorClasses[color] || colorClasses.blue;

        return (
            <div className="p-4 bg-white rounded-xl border border-gray-100">
                <div className="flex justify-between items-center mb-3">
                    <div className="flex items-center gap-2">
                        <span>{emoji}</span>
                        <span className="text-sm font-medium text-gray-700">{label}</span>
                    </div>
                    <div className={`text-xs font-bold px-2.5 py-1 rounded-lg ${c.light} ${c.text}`}>
                        {value}%
                    </div>
                </div>
                <input
                    type="range"
                    min="0"
                    max="100"
                    step="5"
                    value={value}
                    onChange={(e) => setSettings({ ...settings, [field]: parseInt(e.target.value) })}
                    className={`w-full h-2 bg-gray-200 rounded-lg appearance-none cursor-pointer ${c.accent}`}
                />
                <div className="flex justify-between text-[9px] text-gray-400 mt-1.5 uppercase tracking-wider font-mono">
                    <span>Show All</span>
                    <span>Strict</span>
                </div>
            </div>
        );
    };

    return (
        <div className="space-y-6 py-2 h-full flex flex-col">
            {/* Header Banner - Sleek */}
            <div className="flex items-center gap-3 px-1 pb-2 border-b border-gray-100">
                <div className="p-2 bg-gray-50 rounded-lg border border-gray-100 text-gray-400">
                    <Database size={18} />
                </div>
                <div>
                    <h2 className="font-semibold text-gray-800 text-sm">Context Match Thresholds</h2>
                    <p className="text-xs text-gray-500">Minimum scores for displaying matches</p>
                </div>
            </div>

            {/* Content */}
            <div className="space-y-5 flex-1 overflow-y-auto pr-1">
                <SettingsCard>
                    <SettingsSection
                        icon={Sliders}
                        title="Threshold Configuration"
                        description="Configure minimum confidence scores for different match types"
                        accentColor="text-indigo-500"
                    >
                        <div className="space-y-4">
                            <ThresholdSlider
                                label="Mandatory / Legal Matches"
                                emoji="⚖️"
                                value={settings.threshold_mandatory}
                                field="threshold_mandatory"
                                color="red"
                            />

                            <ThresholdSlider
                                label="Optional / Archive Matches"
                                emoji="💡"
                                value={settings.threshold_optional}
                                field="threshold_optional"
                                color="blue"
                            />

                            <ThresholdSlider
                                label="Project TM (Internal)"
                                emoji="🔄"
                                value={settings.threshold_internal_tm}
                                field="threshold_internal_tm"
                                color="green"
                            />
                        </div>
                    </SettingsSection>
                </SettingsCard>

                {/* Info Note */}
                <div className="flex items-start gap-3 p-4 bg-amber-50/50 rounded-xl border border-amber-200/50">
                    <AlertTriangle size={16} className="text-amber-500 mt-0.5 flex-shrink-0" />
                    <p className="text-xs text-amber-700">
                        Higher thresholds show only high-confidence matches. Lower values display more results but may include less relevant suggestions.
                    </p>
                </div>
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
                    {saving ? 'Saving...' : 'Save RAG Settings'}
                </button>
            </div>
        </div>
    );
}

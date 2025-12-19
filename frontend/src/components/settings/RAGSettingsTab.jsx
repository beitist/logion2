import React, { useState, useEffect } from 'react';
import { updateProject, reingestProject } from '../../api/client';
import { Database, Sliders, Save, RefreshCw } from 'lucide-react';

export function RAGSettingsTab({ project, onUpdate }) {
    const [settings, setSettings] = useState({
        threshold_mandatory: 60,
        threshold_optional: 40,
        threshold_tm: 60
    });
    const [isReingesting, setIsReingesting] = useState(false);

    useEffect(() => {
        if (project && project.config) {
            const ai = project.config.ai_settings || {};
            setSettings({
                threshold_mandatory: ai.threshold_mandatory !== undefined ? ai.threshold_mandatory : 60,
                threshold_optional: ai.threshold_optional !== undefined ? ai.threshold_optional : 40,
                threshold_tm: ai.threshold_tm !== undefined ? ai.threshold_tm : 60
            });
        }
    }, [project]);

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
            alert("RAG Settings saved!");
        } catch (e) {
            alert("Error saving settings: " + e.message);
        }
    };

    const handleReingest = async () => {
        if (!confirm("This will clear all existing context vectors and re-process all files. Continue?")) return;

        setIsReingesting(true);
        try {
            await reingestProject(project.id);
            alert("Re-ingestion started in background. Check logs or wait a few minutes.");
        } catch (e) {
            alert("Failed to trigger re-ingest: " + e.message);
        } finally {
            setIsReingesting(false);
        }
    };

    const Slider = ({ label, value, field, color = "indigo" }) => (
        <div className="bg-gray-50 border border-gray-200 rounded-lg p-4">
            <div className="flex justify-between items-end mb-2">
                <label className="text-sm font-medium text-gray-700">{label}</label>
                <div className={`text-xs font-bold px-2 py-1 rounded bg-${color}-100 text-${color}-700 min-w-[3rem] text-center`}>
                    {value}%
                </div>
            </div>
            <input
                type="range"
                min="0"
                max="100"
                step="1"
                value={value}
                onChange={(e) => setSettings({ ...settings, [field]: parseInt(e.target.value) })}
                className={`w-full h-2 bg-gray-200 rounded-lg appearance-none cursor-pointer accent-${color}-600`}
            />
            <div className="flex justify-between text-[10px] text-gray-400 mt-1 uppercase tracking-wide font-mono">
                <span>0% (Show All)</span>
                <span>100% (Strict)</span>
            </div>
        </div>
    );

    return (
        <div className="space-y-6 py-4 h-full flex flex-col">
            <div className="flex items-center gap-2 text-indigo-800 bg-indigo-50 p-3 rounded-lg border border-indigo-100 mb-2">
                <Database size={18} />
                <span className="font-semibold text-sm">Context Match Thresholds</span>
            </div>

            <p className="text-sm text-gray-600 px-1">
                Configure the minimum confidence score required to display context matches in the sidebar.
            </p>

            <div className="space-y-4 flex-1">
                <Slider
                    label="⚖️ Mandatory / Legal Matches"
                    value={settings.threshold_mandatory}
                    field="threshold_mandatory"
                    color="red"
                />

                <Slider
                    label="💡 Optional / Archive Matches"
                    value={settings.threshold_optional}
                    field="threshold_optional"
                    color="blue"
                />

                <div className="opacity-50 grayscale pointer-events-none relative">
                    <div className="absolute inset-0 flex items-center justify-center z-10">
                        <span className="bg-gray-800 text-white text-xs px-2 py-1 rounded shadow">Coming Soon</span>
                    </div>
                    <Slider
                        label="🧠 Translation Memory (TM)"
                        value={settings.threshold_tm}
                        field="threshold_tm"
                        color="green"
                    />
                </div>
            </div>

            <div className="pt-4 border-t border-gray-100 flex justify-end">
                <button
                    onClick={handleSave}
                    className="flex items-center gap-2 px-6 py-2 bg-gray-900 text-white rounded hover:bg-black transition-colors shadow-sm font-medium"
                >
                    <Save size={16} /> Save RAG Settings
                </button>
            </div>
        </div>
    );
}

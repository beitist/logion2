import React, { useState, useEffect } from 'react';
import { updateProject } from '../api/client';
import { Settings, RefreshCw, Zap, Sliders, Database, AlertCircle } from 'lucide-react';

export function AISettingsTab({ project, onUpdate }) {
    // Local state for form values
    const [settings, setSettings] = useState({
        pre_translate_count: 0,
        similarity_threshold: 0.4,
        model: 'gemini-1.5-flash',
        enable_shortcut: false,
        include_source_rag: true
    });

    // Status for re-ingestion
    const [reingesting, setReingesting] = useState(false);
    const [reingestMsg, setReingestMsg] = useState(null);

    // Initialize from project config
    useEffect(() => {
        if (project && project.config) {
            const ai = project.config.ai_settings || {};
            setSettings({
                pre_translate_count: ai.pre_translate_count || 0,
                similarity_threshold: ai.similarity_threshold !== undefined ? ai.similarity_threshold : 0.4,
                model: ai.model || 'gemini-1.5-flash',
                enable_shortcut: ai.enable_shortcut || false,
                include_source_rag: ai.include_source_rag !== undefined ? ai.include_source_rag : true
            });
        }
    }, [project]);

    const handleSave = async () => {
        try {
            // Update project config
            const currentConfig = project.config || {};
            const updatedProject = await updateProject(project.id, {
                config: {
                    ...currentConfig,
                    ai_settings: settings
                }
            });
            onUpdate(updatedProject);
            alert("Settings saved!");
        } catch (e) {
            alert("Error saving settings: " + e.message);
        }
    };

    const handleReingest = async () => {
        if (!confirm("This will clear all existing vectors and restart the ingestion process for this project. Continue?")) return;

        try {
            setReingesting(true);
            setReingestMsg("Triggering ingestion...");

            // Call API (we need to add this function to client.js)
            const API_BASE = "http://localhost:8000";
            await fetch(`${API_BASE}/project/${project.id}/reingest`, { method: "POST" });

            setReingestMsg("Ingestion started in background. Check the console or logs.");

            // Optionally reload project status
            setTimeout(() => {
                setReingesting(false);
            }, 2000);

        } catch (e) {
            setReingestMsg("Error: " + e.message);
            setReingesting(false);
        }
    };

    return (
        <div className="space-y-8 py-4">

            {/* Model & Behavior */}
            <div className="space-y-4">
                <h3 className="text-sm font-semibold text-gray-500 uppercase tracking-wider flex items-center gap-2">
                    <Zap size={16} /> Generation Model
                </h3>
                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                    <div>
                        <label className="block text-sm font-medium text-gray-700 mb-1">AI Model</label>
                        <select
                            value={settings.model}
                            onChange={(e) => setSettings({ ...settings, model: e.target.value })}
                            className="w-full px-3 py-2 border border-gray-300 rounded-md bg-white focus:ring-indigo-500 focus:border-indigo-500"
                        >
                            <option value="gemini-1.5-flash">Gemini 1.5 Flash (Recommended)</option>
                            <option value="gemini-1.5-pro">Gemini 1.5 Pro (Slower, Higher Quality)</option>
                        </select>
                    </div>

                    <div>
                        <label className="block text-sm font-medium text-gray-700 mb-1">Pre-translate Segments</label>
                        <input
                            type="number"
                            min="0"
                            max="50"
                            value={settings.pre_translate_count}
                            onChange={(e) => setSettings({ ...settings, pre_translate_count: parseInt(e.target.value) })}
                            className="w-full px-3 py-2 border border-gray-300 rounded-md focus:ring-indigo-500 focus:border-indigo-500"
                        />
                        <p className="text-xs text-gray-500 mt-1">Number of empty segments to auto-draft when opening (0 = disabled).</p>
                    </div>
                </div>
            </div>

            {/* RAG Settings */}
            <div className="space-y-4">
                <h3 className="text-sm font-semibold text-gray-500 uppercase tracking-wider flex items-center gap-2">
                    <Database size={16} /> Knowledge Base (RAG)
                </h3>

                {/* Threshold Slider */}
                <div>
                    <div className="flex justify-between mb-1">
                        <label className="block text-sm font-medium text-gray-700">Similarity Threshold</label>
                        <span className="text-xs font-mono bg-gray-100 px-2 rounded text-gray-600">{(settings.similarity_threshold * 100).toFixed(0)}%</span>
                    </div>
                    <input
                        type="range"
                        min="0"
                        max="1"
                        step="0.05"
                        value={settings.similarity_threshold}
                        onChange={(e) => setSettings({ ...settings, similarity_threshold: parseFloat(e.target.value) })}
                        className="w-full h-2 bg-gray-200 rounded-lg appearance-none cursor-pointer accent-indigo-600"
                    />
                    <div className="flex justify-between text-xs text-gray-400 mt-1">
                        <span>Everything (Loose)</span>
                        <span>Exact Match (Strict)</span>
                    </div>
                </div>

                {/* Source RAG Toggle */}
                <div className="flex items-start space-x-3 p-3 bg-gray-50 rounded border border-gray-200">
                    <div className="flex items-center h-5">
                        <input
                            id="source_rag"
                            type="checkbox"
                            checked={settings.include_source_rag}
                            onChange={(e) => setSettings({ ...settings, include_source_rag: e.target.checked })}
                            className="focus:ring-indigo-500 h-4 w-4 text-indigo-600 border-gray-300 rounded"
                        />
                    </div>
                    <div className="ml-3 text-sm">
                        <label htmlFor="source_rag" className="font-medium text-gray-700">Index Source File (Internal Consistency)</label>
                        <p className="text-gray-500">Allows the AI to find similar segments within the source text itself to ensure consistent terminology.</p>
                    </div>
                </div>

                {/* Re-Ingest Zone */}
                <div className="pt-4 border-t border-gray-100">
                    <div className="bg-yellow-50 border border-yellow-200 rounded-lg p-4 flex justify-between items-center">
                        <div className="text-sm text-yellow-800 flex items-center gap-2">
                            <AlertCircle size={16} />
                            <span>Database out of sync or stuck? </span>
                        </div>
                        <button
                            onClick={handleReingest}
                            disabled={reingesting}
                            className="flex items-center gap-2 px-4 py-2 bg-white border border-yellow-300 text-yellow-700 rounded hover:bg-yellow-100 transition-colors shadow-sm font-medium"
                        >
                            <RefreshCw size={16} className={reingesting ? "animate-spin" : ""} />
                            Re-Ingest Project
                        </button>
                    </div>
                    {reingestMsg && <p className="text-xs text-center text-gray-500 mt-2 font-mono">{reingestMsg}</p>}
                </div>

            </div>

            {/* Save Button */}
            <div className="pt-6 flex justify-end border-t border-gray-200">
                <button
                    onClick={handleSave}
                    className="px-6 py-2 bg-gray-900 text-white rounded hover:bg-black transition-colors flex items-center gap-2"
                >
                    <Settings size={16} /> Save Configuration
                </button>
            </div>
        </div>
    );
}

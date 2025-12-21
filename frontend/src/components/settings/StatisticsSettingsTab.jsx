import React, { useMemo, useState, useEffect } from 'react';
import { updateProject, getAiModels } from '../../api/client';

export function StatisticsSettingsTab({ project, onProjectUpdate }) {
    const [isResetting, setIsResetting] = useState(false);
    const [modelPricing, setModelPricing] = useState([]);

    // Fetch pricing from backend on mount
    useEffect(() => {
        getAiModels().then(data => {
            if (data && data.models) {
                setModelPricing(data.models);
            }
        }).catch(err => console.error("Failed to load model pricing", err));
    }, []);

    const stats = useMemo(() => {
        if (!project) return { chars: 0, words: 0, tokens: 0, usage: {} };

        let totalChars = 0;
        let totalWords = 0;

        // Calculate basic file stats
        const segments = project.segments || [];
        segments.forEach(seg => {
            const txt = seg.source_content || "";
            totalChars += txt.length;
            totalWords += txt.split(/\s+/).filter(w => w.length > 0).length;
        });

        // Backend AI Usage Stats
        const usageStats = project.config?.usage_stats || {};

        // Heuristic fallback for file size
        const estimatedTokens = Math.ceil(totalChars / 4);

        return { chars: totalChars, words: totalWords, tokens: estimatedTokens, usage: usageStats };
    }, [project]);

    // Calculate Costs
    const usageTable = useMemo(() => {
        const rows = [];
        let totalCost = 0;

        Object.entries(stats.usage).forEach(([modelId, data]) => {
            const modelInfo = modelPricing.find(m => m.id === modelId) || { name: modelId, cost_input_1k: 0, cost_output_1k: 0 };

            // Handle pricing format differences:
            // ai_models.json uses "input_cost_per_m" (per million)
            // Legacy/Fallback might use "cost_input_1k"

            let inputCost = 0;
            let outputCost = 0;

            if (modelInfo.input_cost_per_m !== undefined) {
                // Per Million logic
                inputCost = (data.input_tokens / 1000000) * modelInfo.input_cost_per_m;
                outputCost = (data.output_tokens / 1000000) * modelInfo.output_cost_per_m;
            } else {
                // Legacy per 1k logic (just in case)
                inputCost = (data.input_tokens / 1000) * (modelInfo.cost_input_1k || 0);
                outputCost = (data.output_tokens / 1000) * (modelInfo.cost_output_1k || 0);
            }

            const cost = inputCost + outputCost;
            totalCost += cost;

            rows.push({
                name: modelInfo.name,
                input: data.input_tokens,
                output: data.output_tokens,
                cost: cost
            });
        });

        return { rows, totalCost };
    }, [stats.usage, modelPricing]);

    const handleReset = async () => {
        if (!confirm("Are you sure you want to reset the AI Token Usage counter? This cannot be undone.")) return;
        setIsResetting(true);
        try {
            await updateProject(project.id, {
                config: {
                    ...project.config,
                    usage_stats: {}
                }
            });
            // Ideally trigger refresh, but updateProject returns updated project usually
            if (onProjectUpdate) onProjectUpdate();
            // Since we modified nested config, optimistic UI update might be hard, 
            // but SplitView should reload or we assume parent handles it.
            // Usually onProjectUpdate implies a fetch/refresh.
        } catch (e) {
            alert("Failed to reset stats: " + e.message);
        } finally {
            setIsResetting(false);
        }
    };

    return (
        <div className="space-y-8">
            {/* File Stats */}
            <div>
                <h3 className="text-sm font-bold text-gray-700 uppercase tracking-wider mb-2">Project Size</h3>
                <div className="grid grid-cols-3 gap-4">
                    <div className="p-4 bg-gray-50 rounded border border-gray-100 flex flex-col items-center">
                        <span className="text-2xl font-bold text-gray-800">{stats.chars.toLocaleString()}</span>
                        <span className="text-xs text-gray-500 uppercase tracking-widest mt-1">Characters</span>
                    </div>
                    <div className="p-4 bg-gray-50 rounded border border-gray-100 flex flex-col items-center">
                        <span className="text-2xl font-bold text-gray-800">{stats.words.toLocaleString()}</span>
                        <span className="text-xs text-gray-500 uppercase tracking-widest mt-1">Words</span>
                    </div>
                    <div className="p-4 bg-blue-50 rounded border border-blue-100 flex flex-col items-center">
                        <span className="text-2xl font-bold text-blue-800">~{stats.tokens.toLocaleString()}</span>
                        <span className="text-xs text-blue-600 uppercase tracking-widest mt-1">Est. Size (Tokens)</span>
                    </div>
                </div>
            </div>

            {/* AI Usage Stats */}
            <div>
                <div className="flex justify-between items-end mb-2">
                    <h3 className="text-sm font-bold text-gray-700 uppercase tracking-wider">AI Usage (Since Reset)</h3>
                    {usageTable.rows.length > 0 && (
                        <button
                            onClick={handleReset}
                            disabled={isResetting}
                            className="text-xs text-red-500 hover:text-red-700 underline"
                        >
                            {isResetting ? "Resetting..." : "Reset Counter"}
                        </button>
                    )}
                </div>

                {usageTable.rows.length === 0 ? (
                    <div className="p-6 bg-gray-50 rounded border border-gray-100 text-center text-gray-400 text-sm italic">
                        No AI usage recorded yet.
                    </div>
                ) : (
                    <div className="border border-gray-200 rounded overflow-hidden">
                        <table className="w-full text-sm">
                            <thead className="bg-gray-100 text-gray-600 font-medium border-b border-gray-200">
                                <tr>
                                    <th className="p-3 text-left">Model</th>
                                    <th className="p-3 text-right">Input Tokens</th>
                                    <th className="p-3 text-right">Output Tokens</th>
                                    <th className="p-3 text-right">Est. Cost</th>
                                </tr>
                            </thead>
                            <tbody className="divide-y divide-gray-100">
                                {usageTable.rows.map(row => (
                                    <tr key={row.name} className="bg-white">
                                        <td className="p-3 text-gray-800 font-medium">{row.name}</td>
                                        <td className="p-3 text-right text-gray-600">{row.input.toLocaleString()}</td>
                                        <td className="p-3 text-right text-gray-600">{row.output.toLocaleString()}</td>
                                        <td className="p-3 text-right text-green-700 font-bold">
                                            ${row.cost.toFixed(4)}
                                        </td>
                                    </tr>
                                ))}
                                <tr className="bg-gray-50 font-bold">
                                    <td className="p-3 text-gray-800">Total</td>
                                    <td className="p-3 text-right">
                                        {usageTable.rows.reduce((acc, r) => acc + r.input, 0).toLocaleString()}
                                    </td>
                                    <td className="p-3 text-right">
                                        {usageTable.rows.reduce((acc, r) => acc + r.output, 0).toLocaleString()}
                                    </td>
                                    <td className="p-3 text-right text-green-800">
                                        ${usageTable.totalCost.toFixed(4)}
                                    </td>
                                </tr>
                            </tbody>
                        </table>
                    </div>
                )}
                <div className="text-[10px] text-gray-400 italic mt-2">
                    * Costs are estimated based on configured rates. Actual API billing may vary.
                </div>
            </div>
        </div>
    );
}

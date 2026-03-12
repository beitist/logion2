import React, { useMemo, useState, useEffect } from 'react';
import { updateProject, getAiModels } from '../../api/client';
import { BarChart3, FileText, Zap, DollarSign, RotateCcw } from 'lucide-react';
import { SettingsCard, SettingsSection } from './shared';

/**
 * Statistics Settings Tab
 * 
 * Displays project statistics:
 * - File stats (characters, words, estimated tokens)
 * - AI usage tracking with cost estimation
 */
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
        if (!project) return { chars: 0, words: 0, usage: {} };
        return {
            chars: project.char_count || 0,
            words: project.word_count || 0,
            usage: project.config?.usage_stats || {},
        };
    }, [project]);

    // Calculate costs table
    const usageTable = useMemo(() => {
        const rows = [];
        let totalCost = 0;

        Object.entries(stats.usage).forEach(([modelId, data]) => {
            const modelInfo = modelPricing.find(m => m.id === modelId) || { name: modelId };

            let inputCost = 0;
            let outputCost = 0;

            if (modelInfo.input_cost_per_m !== undefined) {
                inputCost = (data.input_tokens / 1000000) * modelInfo.input_cost_per_m;
                outputCost = (data.output_tokens / 1000000) * modelInfo.output_cost_per_m;
            }

            const cost = inputCost + outputCost;
            totalCost += cost;

            rows.push({
                name: modelInfo.name || modelId,
                input: data.input_tokens,
                output: data.output_tokens,
                cost: cost
            });
        });

        return { rows, totalCost };
    }, [stats.usage, modelPricing]);

    const handleReset = async () => {
        if (!confirm("Reset the AI Token Usage counter? This cannot be undone.")) return;
        setIsResetting(true);
        try {
            await updateProject(project.id, {
                config: {
                    ...project.config,
                    usage_stats: {}
                }
            });
            if (onProjectUpdate) onProjectUpdate();
        } catch (e) {
            alert("Failed to reset stats: " + e.message);
        } finally {
            setIsResetting(false);
        }
    };

    // Stat card component
    const StatCard = ({ value, label, highlight = false }) => (
        <div className={`p-4 rounded-lg border flex flex-col items-center justify-center
                        ${highlight
                ? 'bg-gray-50 border-gray-200'
                : 'bg-white border-gray-200'}`}
        >
            <span className={`text-2xl font-bold ${highlight ? 'text-gray-900' : 'text-gray-800'}`}>
                {value}
            </span>
            <span className={`text-[10px] uppercase tracking-widest mt-1 ${highlight ? 'text-blue-600' : 'text-gray-500'}`}>
                {label}
            </span>
        </div>
    );

    return (
        <div className="space-y-6 py-2 h-full flex flex-col">
            {/* Header Banner - Sleek */}
            <div className="flex items-center gap-3 px-1 pb-2 border-b border-gray-100">
                <div className="p-2 bg-gray-50 rounded-lg border border-gray-100 text-gray-400">
                    <BarChart3 size={18} />
                </div>
                <div>
                    <h2 className="font-semibold text-gray-800 text-sm">Project Statistics</h2>
                    <p className="text-xs text-gray-500">Usage tracking and analytics</p>
                </div>
            </div>

            {/* Content */}
            <div className="space-y-5 flex-1 overflow-y-auto pr-1">

                {/* Project Size Stats */}
                <SettingsCard>
                    <SettingsSection
                        icon={FileText}
                        title="Project Size"
                        accentColor="text-gray-500"
                    >
                        <div className="grid grid-cols-2 gap-3">
                            <StatCard
                                value={stats.words.toLocaleString()}
                                label="Words"
                                highlight
                            />
                            <StatCard
                                value={stats.chars.toLocaleString()}
                                label="Characters"
                            />
                        </div>
                    </SettingsSection>
                </SettingsCard>

                {/* AI Usage Stats */}
                <SettingsCard>
                    <SettingsSection
                        icon={Zap}
                        title="AI Usage"
                        description="Token consumption since last reset"
                        accentColor="text-purple-500"
                    >
                        {usageTable.rows.length === 0 ? (
                            <div className="p-8 bg-gray-50 rounded-xl text-center text-gray-400 text-sm italic">
                                No AI usage recorded yet.
                            </div>
                        ) : (
                            <>
                                <div className="border border-gray-200 rounded-xl overflow-hidden bg-white">
                                    <table className="w-full text-sm">
                                        <thead className="bg-gray-50 text-gray-600 font-medium">
                                            <tr>
                                                <th className="px-4 py-2.5 text-left text-xs">Model</th>
                                                <th className="px-4 py-2.5 text-right text-xs">Input</th>
                                                <th className="px-4 py-2.5 text-right text-xs">Output</th>
                                                <th className="px-4 py-2.5 text-right text-xs">Kosten (ca.)</th>
                                            </tr>
                                        </thead>
                                        <tbody className="divide-y divide-gray-50">
                                            {usageTable.rows.map(row => (
                                                <tr key={row.name} className="hover:bg-gray-50/50">
                                                    <td className="px-4 py-2.5 text-gray-800 font-medium">{row.name}</td>
                                                    <td className="px-4 py-2.5 text-right text-gray-600 font-mono text-xs">
                                                        {row.input.toLocaleString()}
                                                    </td>
                                                    <td className="px-4 py-2.5 text-right text-gray-600 font-mono text-xs">
                                                        {row.output.toLocaleString()}
                                                    </td>
                                                    <td className="px-4 py-2.5 text-right text-emerald-600 font-bold">
                                                        {row.cost.toFixed(4)} €
                                                    </td>
                                                </tr>
                                            ))}
                                            <tr className="bg-gray-50 font-bold">
                                                <td className="px-4 py-2.5 text-gray-800">Total</td>
                                                <td className="px-4 py-2.5 text-right font-mono text-xs">
                                                    {usageTable.rows.reduce((acc, r) => acc + r.input, 0).toLocaleString()}
                                                </td>
                                                <td className="px-4 py-2.5 text-right font-mono text-xs">
                                                    {usageTable.rows.reduce((acc, r) => acc + r.output, 0).toLocaleString()}
                                                </td>
                                                <td className="px-4 py-2.5 text-right text-emerald-700">
                                                    {usageTable.totalCost.toFixed(4)} €
                                                </td>
                                            </tr>
                                        </tbody>
                                    </table>
                                </div>

                                <div className="flex justify-between items-center mt-4">
                                    <p className="text-[10px] text-gray-400 italic">
                                        * Kosten geschätzt auf Basis konfigurierter Preise
                                    </p>
                                    <button
                                        onClick={handleReset}
                                        disabled={isResetting}
                                        className="flex items-center gap-1.5 text-xs text-red-500 hover:text-red-700 
                                                   transition-colors disabled:opacity-50"
                                    >
                                        <RotateCcw size={12} />
                                        {isResetting ? "Resetting..." : "Reset Counter"}
                                    </button>
                                </div>
                            </>
                        )}
                    </SettingsSection>
                </SettingsCard>
            </div>
        </div>
    );
}

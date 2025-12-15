import React, { useMemo } from 'react';

export function StatisticsSettingsTab({ project }) {
    const stats = useMemo(() => {
        if (!project || !project.segments) return { chars: 0, words: 0, tokens: 0 };

        let totalChars = 0;
        let totalWords = 0;

        // Assuming project.segments is available. If not, we might need to rely on backend stats.
        // If project segments are not fully loaded in frontend project object, this might be partial.
        // Assuming 'parts' or 'segments' property. 
        // Based on SplitView, 'segments' seems to be the state name.
        // But the 'project' prop usually comes from API.

        // Fallback: If project object has 'statistics' field from backend
        if (project.statistics) {
            return project.statistics;
        }

        // Calculate if we have segments array
        const segments = project.segments || [];
        segments.forEach(seg => {
            const txt = seg.source_content || "";
            totalChars += txt.length;
            totalWords += txt.split(/\s+/).filter(w => w.length > 0).length;
        });

        // Heuristic: 1 token ~ 4 chars for English/Latin. 
        // For accurate count, backend tokenizer is needed.
        const estimatedTokens = Math.ceil(totalChars / 4);

        return { chars: totalChars, words: totalWords, tokens: estimatedTokens };
    }, [project]);

    return (
        <div className="space-y-4">
            <h3 className="text-sm font-bold text-gray-700 uppercase tracking-wider mb-2">Project Statistics</h3>

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
                    <span className="text-xs text-blue-600 uppercase tracking-widest mt-1">Est. Tokens</span>
                </div>
            </div>

            <div className="text-[10px] text-gray-400 italic text-center mt-2">
                * Token count is an estimate (Chart/4). Actual usage may vary by model.
            </div>
        </div>
    );
}

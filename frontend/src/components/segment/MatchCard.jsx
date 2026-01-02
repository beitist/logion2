import React from 'react';
import { formatSourceContent } from '../../utils/editorTransforms';

/**
 * Displays a single TM/MT/User match card.
 * 
 * Match Types and their styling:
 * - mandatory: Red border, legal/required translation
 * - mt: Purple, Machine Translation result
 * - user: Indigo, User-created memory entry
 * - glossary: (handled separately in GlossaryCard)
 * - default: Blue, optional/suggested match
 * 
 * @param {Object} match - The match object { type, content, score, filename, note }
 * @param {string} shortcutLabel - Keyboard shortcut hint (e.g., "Cmd+Opt+9")
 * @param {boolean} isFlashing - Whether to show flash animation (new MT result)
 * @param {Object} project - Project object for AI model display
 */
export function MatchCard({ match, shortcutLabel, isFlashing, project }) {
    const isMandatory = match.type === 'mandatory';
    const isMT = match.type === 'mt';
    const isUser = match.type === 'user';

    // Determine styling based on match type
    let borderClass = isMandatory ? 'border-l-red-500' : 'border-l-blue-400';
    let bgClass = 'bg-white';
    let textClass = isMandatory ? 'text-red-700' : 'text-blue-700';
    let label = isMandatory ? '⚖️ Vorgabe' : '💡 Vorschlag aus Archiv';

    if (isMT) {
        borderClass = 'border-l-purple-500';
        bgClass = isFlashing ? 'animate-flash-purple' : 'bg-purple-50';
        textClass = 'text-purple-700';
        label = '🤖 Machine Translation';
    } else if (isUser) {
        borderClass = 'border-l-indigo-500';
        bgClass = 'bg-indigo-50';
        textClass = 'text-indigo-700';
        label = '👤 User Memory';
    }

    return (
        <div className={`p-2.5 rounded border transition-all hover:shadow-sm ${bgClass} ${borderClass} border-gray-200`}>
            {/* Header: Label, Score, Shortcut */}
            <div className="flex justify-between items-start mb-1">
                <div className="flex items-center gap-2">
                    <span className={`text-[10px] font-bold uppercase tracking-wider flex items-center gap-1 ${textClass}`}>
                        {label}
                    </span>

                    {/* Score badge (not shown for MT which has no score) */}
                    {match.score !== undefined && !isMT && (
                        <span className={`text-[9px] font-bold px-1.5 rounded-full ${match.score > 85 ? 'bg-green-100 text-green-700' : 'bg-gray-100 text-gray-600'}`}>
                            {match.score}%
                        </span>
                    )}

                    {/* Keyboard shortcut hint (visible on hover) */}
                    <span className="text-[9px] font-mono text-gray-400 bg-white/50 px-1 rounded border border-gray-100 opacity-0 group-hover:opacity-100 transition-opacity">
                        {shortcutLabel}
                    </span>
                </div>

                {/* Source filename / model name */}
                <div className="flex items-center gap-1 text-[9px] text-gray-400 font-mono" title={match.filename}>
                    <span className="truncate max-w-[100px]">
                        {isMT ? (project?.config?.ai_settings?.model || match.filename) : match.filename}
                    </span>
                </div>
            </div>

            {/* Match content (rendered with tag formatting) */}
            <div
                className="text-gray-800 text-[13px] leading-snug font-source selection:bg-yellow-100"
                dangerouslySetInnerHTML={{ __html: formatSourceContent(match.content, null, false) }}
            />

            {/* Optional note */}
            {match.note && (
                <div className="mt-1 text-[10px] text-gray-500 italic border-t border-gray-200/50 pt-1">
                    Note: {match.note}
                </div>
            )}
        </div>
    );
}

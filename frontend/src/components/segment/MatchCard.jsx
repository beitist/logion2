import React from 'react';
import { formatSourceContent } from '../../utils/editorTransforms';

/**
 * Displays a single TM/MT/User match card.
 * 
 * Match Types and their styling:
 * - mandatory: Red border, legal/required translation (⚖️)
 * - mt: Orange, Machine Translation result (🤖)
 * - user: Indigo, User-created memory entry (👤)
 * - glossary: (handled separately in GlossaryCard)
 * - default: Blue, optional/suggested match (💡)
 * 
 * Features:
 * - Score badge with color coding
 * - Always-visible keyboard shortcut hints
 * - Match quality penalty explanations (when enabled)
 * - Expandable filename display
 * 
 * @param {Object} match - The match object { type, content, score, filename, note, metadata }
 * @param {string} shortcutLabel - Keyboard shortcut hint (e.g., "Cmd+Opt+9")
 * @param {boolean} isFlashing - Whether to show flash animation (new MT result)
 * @param {Object} project - Project object for AI model display and settings
 */
export function MatchCard({ match, shortcutLabel, isFlashing, project }) {
    const isMandatory = match.type === 'mandatory';
    const isMT = match.type === 'mt';
    const isUser = match.type === 'user';
    const isInternal = match.type === 'internal';

    // Check if penalty display is enabled in GUI settings
    const showPenalties = project?.config?.gui_settings?.show_match_penalties || false;
    const penalties = match.metadata?.penalties || [];

    // Determine styling based on match type
    // MT uses ORANGE (changed from purple)
    let borderClass = isMandatory ? 'border-l-red-500' : 'border-l-blue-400';
    let bgClass = 'bg-white';
    let textClass = isMandatory ? 'text-red-700' : 'text-blue-700';
    let label = isMandatory ? '⚖️ Vorgabe' : '💡 Vorschlag aus Archiv';

    if (isMT) {
        borderClass = 'border-l-orange-500';
        bgClass = isFlashing ? 'animate-flash-orange' : 'bg-orange-50';
        textClass = 'text-orange-700';
        label = '🤖 Machine Translation';
    } else if (isInternal) {
        borderClass = 'border-l-violet-400';
        bgClass = 'bg-violet-50';
        textClass = 'text-violet-700';
        label = '🔄 Project TM';
    } else if (isUser) {
        borderClass = 'border-l-indigo-500';
        bgClass = 'bg-indigo-50';
        textClass = 'text-indigo-700';
        label = '👤 User Memory';
    }

    // Format penalty display for user-friendly messages
    const formatPenalty = (penalty) => {
        if (penalty === 'number_mismatch') return '⚠️ Numbers differ';
        if (penalty.startsWith('length_ratio_')) return '⚠️ Length differs';
        if (penalty.startsWith('fragment_')) return '⚠️ Fragment detected';
        return `⚠️ ${penalty}`;
    };

    return (
        <div className={`p-2.5 rounded-lg border-l-4 transition-all hover:shadow-sm ${bgClass} ${borderClass} border border-gray-200/50`}>
            {/* Header: Label, Score, Shortcut */}
            <div className="flex justify-between items-start mb-1.5">
                <div className="flex items-center gap-2 flex-wrap">
                    <span className={`text-[10px] font-bold uppercase tracking-wider flex items-center gap-1 ${textClass}`}>
                        {label}
                    </span>

                    {/* Score badge (not shown for MT which has no score) */}
                    {match.score !== undefined && !isMT && (
                        <span className={`text-[9px] font-bold px-1.5 py-0.5 rounded-full 
                            ${match.score > 85
                                ? 'bg-green-100 text-green-700'
                                : match.score > 60
                                    ? 'bg-yellow-100 text-yellow-700'
                                    : 'bg-gray-100 text-gray-600'}`}
                        >
                            {match.score}%
                        </span>
                    )}

                    {/* Keyboard shortcut hint - ALWAYS VISIBLE */}
                    {shortcutLabel && (
                        <span className="text-[9px] font-mono text-gray-500 bg-gray-100 px-1.5 py-0.5 rounded border border-gray-200">
                            {shortcutLabel}
                        </span>
                    )}
                </div>

                {/* Source filename / model name - LONGER display */}
                <div className="flex items-center gap-1 text-[9px] text-gray-400 font-mono" title={match.filename}>
                    <span className="truncate max-w-[200px]">
                        {isMT ? (project?.config?.ai_settings?.model || match.filename) : match.filename}
                    </span>
                </div>
            </div>

            {/* Source text preview for internal TM (shows the similar source) */}
            {isInternal && match.source_text && (
                <div
                    className="text-[11px] text-violet-500/70 leading-snug mb-1 italic"
                    dangerouslySetInnerHTML={{ __html: formatSourceContent(match.source_text, null, false) }}
                />
            )}

            {/* Match content (rendered with tag formatting) */}
            <div
                className="text-gray-800 text-[13px] leading-snug font-source selection:bg-yellow-100"
                dangerouslySetInnerHTML={{ __html: formatSourceContent(match.content, null, false) }}
            />

            {/* Match Quality Explanations (Penalties) - shown when enabled */}
            {showPenalties && penalties.length > 0 && (
                <div className="mt-2 pt-2 border-t border-gray-200/50 flex flex-wrap gap-1.5">
                    {penalties.map((penalty, idx) => (
                        <span
                            key={idx}
                            className="text-[9px] text-amber-700 bg-amber-50 px-1.5 py-0.5 rounded border border-amber-200"
                        >
                            {formatPenalty(penalty)}
                        </span>
                    ))}
                </div>
            )}

            {/* Optional note */}
            {match.note && (
                <div className="mt-1.5 text-[10px] text-gray-500 italic border-t border-gray-200/50 pt-1.5">
                    Note: {match.note}
                </div>
            )}
        </div>
    );
}

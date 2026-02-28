import React from 'react';
import { formatSourceContent } from '../../utils/editorTransforms';

/**
 * Displays a glossary term match.
 * 
 * Glossary entries are shown in the Target column (right side)
 * to provide quick reference for required terminology.
 * 
 * @param {Object} match - Glossary match { content, source_term, note }
 */
export function GlossaryCard({ match }) {
    const isAuto = match.metadata?.origin === 'auto';

    // Auto-glossary: emerald tones, Manual: teal tones
    const colors = isAuto
        ? {
            border: 'border-emerald-100',
            bg: 'bg-emerald-50/50',
            hover: 'hover:bg-emerald-50',
            label: 'text-emerald-700',
            tag: 'text-emerald-600 border-emerald-100',
            selection: 'selection:bg-emerald-100',
            noteBorder: 'border-emerald-100/50',
        }
        : {
            border: 'border-teal-100',
            bg: 'bg-teal-50/50',
            hover: 'hover:bg-teal-50',
            label: 'text-teal-700',
            tag: 'text-teal-600 border-teal-100',
            selection: 'selection:bg-teal-100',
            noteBorder: 'border-teal-100/50',
        };

    return (
        <div className={`p-2.5 rounded border ${colors.border} ${colors.bg} ${colors.hover} transition-colors`}>
            {/* Header with source term */}
            <div className="flex justify-between items-start mb-1">
                <div className="flex items-center gap-2">
                    <span className={`text-[10px] font-bold uppercase tracking-wider ${colors.label}`}>
                        {isAuto ? '🤖 Auto-Glossary' : '📚 Glossary'}
                    </span>
                    {match.source_term && (
                        <span className={`text-[10px] font-medium bg-white/50 px-1 rounded border ${colors.tag}`}>
                            {match.source_term}
                        </span>
                    )}
                </div>
            </div>

            {/* Target term content */}
            <div
                className={`text-gray-800 text-sm leading-snug font-source ${colors.selection}`}
                dangerouslySetInnerHTML={{ __html: formatSourceContent(match.content, null, false) }}
            />

            {/* Optional context note */}
            {match.note && (
                <div className={`mt-1 text-[10px] text-gray-500 italic border-t ${colors.noteBorder} pt-1`}>
                    {match.note}
                </div>
            )}
        </div>
    );
}

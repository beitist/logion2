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
    return (
        <div className="p-2.5 rounded border border-teal-100 bg-teal-50/50 hover:bg-teal-50 transition-colors">
            {/* Header with source term */}
            <div className="flex justify-between items-start mb-1">
                <div className="flex items-center gap-2">
                    <span className="text-[10px] font-bold uppercase tracking-wider text-teal-700">
                        📚 Glossary
                    </span>
                    {match.source_term && (
                        <span className="text-[10px] text-teal-600 font-medium bg-white/50 px-1 rounded border border-teal-100">
                            {match.source_term}
                        </span>
                    )}
                </div>
            </div>

            {/* Target term content */}
            <div
                className="text-gray-800 text-sm leading-snug font-source selection:bg-teal-100"
                dangerouslySetInnerHTML={{ __html: formatSourceContent(match.content, null, false) }}
            />

            {/* Optional context note */}
            {match.note && (
                <div className="mt-1 text-[10px] text-gray-500 italic border-t border-teal-100/50 pt-1">
                    {match.note}
                </div>
            )}
        </div>
    );
}

import React from 'react';
import { Copy, Search } from 'lucide-react';
import { TiptapEditor } from '../TiptapEditor';
import { formatSourceContent, getSegmentComments } from '../../utils/editorTransforms';
import { MatchCard } from './MatchCard';

/**
 * Source column of the SegmentRow - displays source text and TM matches.
 * 
 * Contains:
 * - Copy button and segment index
 * - Source text (read-only TiptapEditor)
 * - Comments section (if any)
 * - Context matches panel (TM, MT, User matches)
 * - Debug info (if showDebug enabled)
 * 
 * @param {Object} segment - The segment data
 * @param {Object} project - Project configuration
 * @param {Array} sortedMatches - Pre-sorted and filtered matches
 * @param {Array} tmMatches - TM-only matches for shortcut key assignment
 * @param {boolean} hasContext - Whether context panel should be shown
 * @param {Object} generatingSegments - Map of segment IDs currently generating
 * @param {Object} flashingSegments - Map of segment IDs with flash animation
 * @param {boolean} showDebug - Whether to show debug info
 * @param {Function} onAiDraft - Callback for AI draft generation
 */
export function SourceColumn({
    segment,
    project,
    sortedMatches,
    tmMatches,
    hasContext,
    generatingSegments,
    flashingSegments,
    showDebug,
    onAiDraft
}) {
    const comments = getSegmentComments(segment.tags);
    const aiSettings = project?.config?.ai_settings || {};

    // Threshold values for filtering matches
    const tMandatory = aiSettings.threshold_mandatory ?? 60;
    const tOptional = aiSettings.threshold_optional ?? 40;

    /**
     * Determines keyboard shortcut label for a match.
     * MT = Cmd+Opt+0, TM matches = Cmd+Opt+9, 8, 7...
     */
    const getShortcutLabel = (match, tmMatches) => {
        if (match.type === 'mt') return 'Cmd+Opt+0';
        if (match.type === 'glossary') return '';

        const tmIdx = tmMatches.indexOf(match);
        if (tmIdx === 0) return 'Cmd+Opt+9';
        if (tmIdx === 1) return 'Cmd+Opt+8';
        if (tmIdx === 2) return 'Cmd+Opt+7';
        return '';
    };

    /**
     * Filters matches based on score thresholds.
     * Glossary matches are shown in target column, not here.
     */
    const shouldShowMatch = (match) => {
        if (match.type === 'glossary') return false;
        if (match.type === 'mt') return true;
        if (match.type === 'mandatory') return match.score >= tMandatory;
        return match.score >= tOptional;
    };

    return (
        <div className="p-5 bg-gray-50/80 rounded-l-xl text-sm leading-relaxed border-r border-gray-100 flex flex-col relative">
            {/* Copy button and segment index (shown on hover) */}
            <div className="absolute top-2 right-2 flex items-center gap-2">
                <button
                    onClick={() => navigator.clipboard.writeText(segment.source_content)}
                    className="opacity-0 group-hover:opacity-100 transition-opacity p-1 text-gray-300 hover:text-gray-500 rounded"
                    title="Copy Source Text"
                >
                    <Copy size={12} />
                </button>
                <span className="opacity-0 group-hover:opacity-100 transition-opacity text-xs text-gray-300 font-mono pointer-events-none">
                    #{segment.index + 1}
                </span>
            </div>

            {/* Source Text (read-only Tiptap with invisible character display) */}
            <div className="flex-grow">
                <TiptapEditor
                    content={formatSourceContent(segment.source_content, segment.tags, true)}
                    isReadOnly={true}
                    chromeless={true}
                    availableTags={segment.tags}
                    segmentId={`source-${segment.id}`}
                />
            </div>

            {/* Comments Section (from Word document comments) */}
            {comments.length > 0 && (
                <div className="mt-4 pt-3 border-t border-gray-200 text-xs text-gray-600 bg-yellow-50 -mx-5 -mb-5 p-4">
                    <div className="font-semibold mb-1 flex items-center gap-2 text-yellow-700">
                        <span>💬 Comments ({comments.length})</span>
                    </div>
                    <ul className="space-y-1 list-disc list-inside">
                        {comments.map((c, i) => (
                            <li key={i}>{c}</li>
                        ))}
                    </ul>
                </div>
            )}

            {/* DEBUG: Show raw source content */}
            {showDebug && (
                <div className="mt-4 p-1 bg-red-50 text-[10px] font-mono text-red-500 border border-red-200 rounded break-all opacity-50 hover:opacity-100 transition-opacity">
                    DEBUG Source-DB: {segment.tags ? "HAS TAGS" : "NO TAGS"}
                </div>
            )}

            {/* Context Panel (Translation Memory / AI Matches) */}
            {hasContext && (
                <div className="mt-6 border-t border-gray-200 pt-4">
                    {/* Header with refresh buttons */}
                    <div className="flex justify-between items-center mb-3">
                        <h4 className="text-[10px] font-bold text-gray-400 uppercase tracking-widest flex items-center gap-2">
                            <span className="w-1 h-1 bg-gray-400 rounded-full"></span>
                            Translation Memory / Context
                        </h4>
                        <div className="flex gap-1">
                            {/* Search/Refresh matches (cheap) */}
                            <button
                                onClick={() => onAiDraft(segment.id, false, "analyze", false, true)}
                                className={`text-gray-400 hover:text-blue-600 transition-colors ${generatingSegments[segment.id] ? 'opacity-50 cursor-not-allowed' : ''}`}
                                title="Search Matches (Refresh) - Cheap"
                                disabled={generatingSegments[segment.id]}
                            >
                                <Search size={14} />
                            </button>
                            {/* Regenerate translation (uses tokens) */}
                            <button
                                onClick={() => onAiDraft(segment.id, false, "translate", false, true)}
                                className={`text-gray-400 hover:text-indigo-600 transition-colors ${generatingSegments[segment.id] ? 'animate-spin text-indigo-500' : ''}`}
                                title="Regenerate Translation (Force Refresh) - Uses Tokens"
                                disabled={generatingSegments[segment.id]}
                            >
                                <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15"></path>
                                </svg>
                            </button>
                        </div>
                    </div>

                    {/* Match cards */}
                    <div className="space-y-2">
                        {sortedMatches.filter(shouldShowMatch).map((match, idx) => (
                            <MatchCard
                                key={idx}
                                match={match}
                                shortcutLabel={getShortcutLabel(match, tmMatches)}
                                isFlashing={match.type === 'mt' && flashingSegments[segment.id]}
                                project={project}
                            />
                        ))}
                    </div>
                </div>
            )}
        </div>
    );
}

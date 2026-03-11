import React, { useMemo } from 'react';
import { Copy, Search } from 'lucide-react';
import { TiptapEditor } from '../TiptapEditor';
import { formatSourceContent, getSegmentComments, highlightGlossaryTerms } from '../../utils/editorTransforms';
import { createInlineDiff } from '../../utils/diffUtils';
import { RevisionSlider } from './RevisionSlider';
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
 * @param {Function} onContextMenu - Callback for right-click context menu (glossary add)
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
    showSourceTC,
    tcMode,
    isSimpleInsert = false,
    isDeletedFinal = false,
    initialStage = 0,
    onAiDraft,
    onContextMenu,
    onStageChange
}) {
    const comments = getSegmentComments(segment.tags);
    const aiSettings = project?.config?.ai_settings || {};
    const hasTC = segment.metadata?.has_track_changes;

    // Threshold values for filtering matches
    const tMandatory = aiSettings.threshold_mandatory ?? 60;
    const tOptional = aiSettings.threshold_optional ?? 40;
    const tInternalTm = aiSettings.threshold_internal_tm ?? 50;

    // Extract glossary matches for inline highlighting
    const glossaryMatches = useMemo(() => {
        return sortedMatches
            .filter(m => m.type === 'glossary')
            .map(m => ({ source: m.source_text || m.source, target: m.content || m.target, note: m.note }));
    }, [sortedMatches]);

    // Track changes display: mode-dependent
    // step_by_step → slider (if >= 2 stages), first_last → simple diff
    const revisionStages = segment.metadata?.revision_stages;
    const hasSlider = showSourceTC && tcMode === 'step_by_step' && revisionStages && revisionStages.length >= 2;

    // Simple diff HTML: used in first_last mode OR as fallback when no slider stages
    const diffHtml = useMemo(() => {
        if (!showSourceTC) return null;
        if (hasSlider) return null; // slider takes priority
        // Show diff for first_last mode or step_by_step without stages
        return createInlineDiff(
            segment.metadata?.original_text,
            segment.metadata?.final_text
        );
    }, [showSourceTC, hasSlider, segment.metadata?.original_text, segment.metadata?.final_text]);

    // Format source content with glossary term highlighting
    const formattedSourceContent = useMemo(() => {
        const baseContent = formatSourceContent(segment.source_content, segment.tags, true);
        // Apply glossary highlighting if matches exist
        if (glossaryMatches.length > 0) {
            return highlightGlossaryTerms(baseContent, glossaryMatches);
        }
        return baseContent;
    }, [segment.source_content, segment.tags, glossaryMatches]);

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
        if (match.type === 'internal') return match.score >= tInternalTm;
        return match.score >= tOptional;
    };

    return (
        <div className="p-5 bg-gray-50/80 rounded-l-xl text-sm leading-relaxed border-r border-gray-100 flex flex-col relative">
            {/* Copy button, TC badge, and segment index (shown on hover) */}
            <div className="absolute top-2 right-2 flex items-center gap-2">
                <button
                    onClick={() => navigator.clipboard.writeText(segment.source_content)}
                    className="opacity-0 group-hover:opacity-100 transition-opacity p-1 text-gray-300 hover:text-gray-500 rounded"
                    title="Copy Source Text"
                >
                    <Copy size={12} />
                </button>
                {hasTC && (
                    <span
                        className={`text-[9px] font-bold px-1.5 py-0.5 rounded cursor-default select-none ${
                            showSourceTC
                                ? 'bg-blue-200 text-blue-800'
                                : 'bg-blue-100 text-blue-600'
                        }`}
                        title={`${revisionStages ? revisionStages.length - 1 : 1} revision(s) — ${tcMode || 'not configured'}`}
                    >
                        TC{revisionStages && revisionStages.length >= 2 ? ` ${revisionStages.length - 1}` : ''}
                    </span>
                )}
                {isSimpleInsert && (
                    <span className="text-[9px] font-bold px-1.5 py-0.5 rounded bg-green-100 text-green-700 cursor-default select-none">
                        NEW
                    </span>
                )}
                {isDeletedFinal && (
                    <span className="text-[9px] font-bold px-1.5 py-0.5 rounded bg-red-100 text-red-600 cursor-default select-none">
                        DEL
                    </span>
                )}
                <span className="opacity-0 group-hover:opacity-100 transition-opacity text-xs text-gray-300 font-mono pointer-events-none">
                    #{segment.index + 1}
                </span>
            </div>

            {/* Source Text with inline glossary highlights */}
            {/* If glossary matches exist, use raw HTML to render highlights correctly */}
            {/* TipTap sanitizes unknown HTML elements, so we bypass it for highlighted content */}
            <div className="flex-grow">
                {isSimpleInsert && revisionStages?.[1] ? (
                    // Simple insert: show the new content with author info
                    <div className="text-sm leading-relaxed">
                        <div className="flex items-center gap-1.5 mb-1.5">
                            <span className="text-[10px] text-gray-500">
                                {revisionStages[1].author || 'Author'}
                            </span>
                            {revisionStages[1].date && (
                                <span className="text-[10px] text-gray-400">
                                    {new Date(revisionStages[1].date).toLocaleDateString('de-DE', { day: '2-digit', month: '2-digit' })}
                                </span>
                            )}
                        </div>
                        <div className="text-green-800 bg-green-50/50 rounded px-2 py-1 border-l-2 border-green-300">
                            {revisionStages[1].text}
                        </div>
                    </div>
                ) : hasSlider ? (
                    // Git-Slider: navigate between revision stages with per-step diffs
                    <RevisionSlider stages={revisionStages} onStageChange={onStageChange} initialStage={initialStage} />
                ) : diffHtml ? (
                    // Simple diff view: shows original→final with red/green highlighting
                    <div
                        className="prose max-w-none text-sm leading-relaxed"
                        dangerouslySetInnerHTML={{ __html: diffHtml }}
                    />
                ) : glossaryMatches.length > 0 ? (
                    // Raw HTML with glossary highlights (TipTap would escape the <mark> tags)
                    // Bind onContextMenu for right-click glossary add functionality
                    <div
                        className="prose max-w-none text-sm leading-relaxed source-content-highlighted"
                        dangerouslySetInnerHTML={{ __html: formattedSourceContent }}
                        onContextMenu={onContextMenu}
                    />
                ) : (
                    // Standard TipTap for source without highlights
                    // Wrap in div for onContextMenu binding
                    <div onContextMenu={onContextMenu}>
                        <TiptapEditor
                            content={formatSourceContent(segment.source_content, segment.tags, true)}
                            isReadOnly={true}
                            chromeless={true}
                            availableTags={segment.tags}
                            segmentId={`source-${segment.id}`}
                        />
                    </div>
                )}
            </div>

            {/* Glossary Cards - Directly under source text for visibility */}
            {/* MOVED to TargetColumn per user request */}

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
            {/* Also show when generating so user sees loading feedback even with no existing matches */}
            {(hasContext || generatingSegments[segment.id]) && (
                <div className="mt-6 border-t border-gray-200 pt-4">
                    {/* Header with refresh buttons */}
                    <div className="flex justify-between items-center mb-3">
                        <h4 className="text-[10px] font-bold text-gray-400 uppercase tracking-widest flex items-center gap-2">
                            <span className="w-1 h-1 bg-gray-400 rounded-full"></span>
                            Translation Memory / Context
                        </h4>
                        <div className="flex gap-1">
                            {/* Search/Refresh matches (cheap - retrieval only, no LLM) */}
                            <button
                                onClick={() => onAiDraft(segment.id, false, "analyze", false, true)}
                                className={`text-gray-400 hover:text-blue-600 transition-colors ${generatingSegments[segment.id] === 'analyze' ? 'animate-pulse text-blue-500' : generatingSegments[segment.id] ? 'opacity-50 cursor-not-allowed' : ''}`}
                                title="Search Matches (Refresh) - Cheap"
                                disabled={!!generatingSegments[segment.id]}
                            >
                                <Search size={14} />
                            </button>
                            {/* Regenerate translation (uses tokens) */}
                            <button
                                onClick={() => onAiDraft(segment.id, false, "translate", false, true)}
                                className={`text-gray-400 hover:text-indigo-600 transition-colors ${generatingSegments[segment.id] && generatingSegments[segment.id] !== 'analyze' ? 'animate-spin text-indigo-500' : ''}`}
                                title="Regenerate Translation (Force Refresh) - Uses Tokens"
                                disabled={!!generatingSegments[segment.id]}
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

                        {/* Skeleton loader: shown while generating and no MT match exists yet.
                           Mimics the look of an MT MatchCard with pulsing placeholder lines. */}
                        {generatingSegments[segment.id] && generatingSegments[segment.id] !== 'analyze' && !sortedMatches.some(m => m.type === 'mt') && (
                            <div className="p-2.5 rounded-lg border-l-4 border-l-orange-500 border border-gray-200/50 bg-orange-50 animate-pulse">
                                <div className="flex justify-between items-center mb-2">
                                    <span className="text-[10px] font-bold uppercase tracking-wider text-orange-700 flex items-center gap-1">
                                        🤖 Machine Translation
                                    </span>
                                    <span className="text-[9px] font-mono text-gray-500 bg-gray-100 px-1.5 py-0.5 rounded border border-gray-200">
                                        Cmd+Opt+0
                                    </span>
                                </div>
                                {/* Pulsing text lines simulating incoming content */}
                                <div className="space-y-1.5">
                                    <div className="h-3 bg-orange-200/60 rounded w-full"></div>
                                    <div className="h-3 bg-orange-200/60 rounded w-4/5"></div>
                                    <div className="h-3 bg-orange-200/60 rounded w-3/5"></div>
                                </div>
                            </div>
                        )}
                    </div>
                </div>
            )}
        </div>
    );
}

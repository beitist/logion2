import React from 'react';
import { TiptapEditor } from '../TiptapEditor';
import { hydrateContent } from '../../utils/editorTransforms';
import { SegmentBadges, SegmentTypeBadges, SpacingWarning } from './SegmentBadges';
import { GlossaryCard } from './GlossaryCard';

/**
 * Target column of the SegmentRow - editable translation with glossary.
 * 
 * Contains:
 * - Header with status badges and flags
 * - Editable TiptapEditor for translation
 * - Glossary matches section
 * - Debug info (if enabled)
 * 
 * @param {Object} segment - The segment data
 * @param {Object} project - Project configuration
 * @param {Array} sortedMatches - Pre-sorted matches (for glossary filtering)
 * @param {boolean} isMandatoryContext - Whether segment has mandatory match
 * @param {Object} aiSettings - AI configuration for editor
 * @param {Function} onSave - Callback when content is saved
 * @param {Function} onAiDraft - Callback for AI draft generation
 * @param {Function} onFocus - Callback when editor receives focus
 * @param {Function} onNavigate - Callback for keyboard navigation
 * @param {Function} onToggleFlag - Callback to toggle flag
 * @param {Function} registerEditor - Callback to register editor instance
 * @param {boolean} showDebug - Whether to show debug info
 */
export function TargetColumn({
    segment,
    project,
    sortedMatches,
    isMandatoryContext,
    aiSettings,
    onSave,
    onAiDraft,
    onFocus,
    onNavigate,
    onToggleFlag,
    registerEditor,
    showDebug,
    tcMode = null,
    activeTCStage = 0,
    baseStage = 0,
    isSimpleInsert = false,
    isDeletedFinal = false,
    trackChangesEnabled = false,
    trackChangesUser = null
}) {
    const [localEditor, setLocalEditor] = React.useState(null);
    const isFlagged = segment.metadata?.flagged || false;
    const glossaryMatches = sortedMatches.filter(m => m.type === 'glossary');

    // TC base state: slider is at the base stage (translate original/base, TC off)
    const hasTC = segment.metadata?.has_track_changes;
    const stages = segment.metadata?.revision_stages || [];
    const isAtBase = hasTC && tcMode === 'step_by_step' && !isSimpleInsert && activeTCStage === baseStage;
    const needsBaseTranslation = isAtBase && !segment.target_content;

    // Detect if slider is at the deleted final stage
    const isAtDeletedStage = isDeletedFinal && activeTCStage === stages.length - 1;

    // Editor content: use precomputed TC markup from batch when available,
    // otherwise fall back to target_content (base translation or manual edit).
    const editorContent = React.useMemo(() => {
        if (hasTC && tcMode === 'step_by_step' && !isSimpleInsert && activeTCStage > baseStage) {
            const stageMarkup = segment.metadata?.tc_stage_markup?.[String(activeTCStage)];
            if (stageMarkup) {
                return hydrateContent(stageMarkup, segment.tags);
            }
        }
        return hydrateContent(segment.target_content, segment.tags);
    }, [segment.target_content, segment.metadata?.tc_stage_markup, activeTCStage, baseStage, tcMode, hasTC, isSimpleInsert, segment.tags]);

    // Lock editor: past base stage without base translation → must translate base first
    const editorLocked = hasTC && tcMode === 'step_by_step' && !isSimpleInsert
        && activeTCStage > baseStage && !segment.target_content;

    // Background color varies based on segment state
    const bgClass = isFlagged
        ? 'bg-yellow-50/50 border-l border-yellow-200'
        : isMandatoryContext
            ? 'bg-red-50/80 border-l border-red-200'
            : isAtDeletedStage
                ? 'bg-red-50/30 border-l border-red-200'
                : trackChangesEnabled
                    ? 'bg-blue-50/40 border-l border-blue-300'
                    : needsBaseTranslation
                        ? 'bg-blue-50/30 border-l border-blue-200'
                        : 'bg-white';

    // Target label reflects TC state and active stage
    const targetLabel = isMandatoryContext
        ? '⚠️ Mandatory Target'
        : isAtDeletedStage
            ? 'Target (DE) — Segment gelöscht'
            : trackChangesEnabled
                ? `Target (DE) — TC Stage ${activeTCStage} (${trackChangesUser?.nickname || 'Editor'})`
                : isSimpleInsert
                    ? 'Target (DE) — NEW'
                    : needsBaseTranslation
                        ? `Target (DE) — Stage ${baseStage} übersetzen`
                        : isAtBase
                            ? `Target (DE) — Stage ${baseStage}`
                            : 'Target (DE)';

    return (
        <div className={`p-5 rounded-r-xl flex flex-col relative group ${bgClass}`}>
            {/* Header row with labels and badges */}
            <div className="text-xs text-gray-400 font-mono mb-2 uppercase tracking-wider flex justify-between items-center select-none">
                <div className="flex items-center gap-2">
                    {/* Target label */}
                    <span className={`font-bold transition-colors ${
                        isMandatoryContext ? 'text-red-800'
                            : isAtDeletedStage ? 'text-red-500'
                                : trackChangesEnabled ? 'text-blue-700'
                                    : isAtBase ? 'text-blue-400'
                                        : 'text-gray-300 group-hover:text-indigo-400'
                    }`}>
                        {targetLabel}
                    </span>

                    {/* Spacing mismatch warning */}
                    <SpacingWarning segment={segment} />

                    {/* Type badges (H for header, Tb for table) */}
                    <SegmentTypeBadges metadata={segment.metadata} />
                </div>

                {/* Status badges and flag button */}
                <SegmentBadges
                    segment={segment}
                    isFlagged={isFlagged}
                    onToggleFlag={onToggleFlag}
                />
            </div>

            {/* Base stage hint: translate base first before TC tracking begins */}
            {needsBaseTranslation && (
                <div className="mb-2 px-3 py-2 bg-blue-50 border border-blue-200 rounded-lg text-xs text-blue-700">
                    <span className="font-bold">Stage {baseStage}:</span> Zuerst {baseStage === 0 ? 'das Original' : 'die Basis'} übersetzen (MT oder manuell).
                    Danach wird Track Changes für weitere Stufen aktiviert.
                </div>
            )}

            {/* Hint: slider past base but no base translation yet */}
            {hasTC && tcMode === 'step_by_step' && !isSimpleInsert && activeTCStage > baseStage && !segment.target_content && (
                <div className="mb-2 px-3 py-2 bg-amber-50 border border-amber-200 rounded-lg text-xs text-amber-700">
                    <span className="font-bold">Hinweis:</span> Zuerst Stage {baseStage} ({baseStage === 0 ? 'Original' : 'Basis'}) übersetzen.
                    Slider auf Stage {baseStage} bewegen und Übersetzung eingeben.
                </div>
            )}

            {/* Deleted segment hint */}
            {isAtDeletedStage && (
                <div className="mb-2 px-3 py-2 bg-red-50 border border-red-200 rounded-lg text-xs text-red-700">
                    <span className="font-bold">Gelöscht:</span> Dieses Segment wird in der finalen Version entfernt.
                    {!segment.target_content && ' Keine Übersetzung nötig.'}
                </div>
            )}

            {/* Editable TiptapEditor */}
            <div className="flex-grow">
                <TiptapEditor
                    content={editorContent}
                    segmentId={segment.id}
                    availableTags={segment.tags}
                    contextMatches={sortedMatches}
                    onSave={onSave}
                    isReadOnly={editorLocked}
                    aiSettings={aiSettings}
                    onAiDraft={(id) => onAiDraft(id)}
                    onFocus={() => onFocus(segment.id)}
                    onNavigate={(dir) => onNavigate(segment.id, dir)}
                    onEditorReady={(ed) => {
                        registerEditor(segment.id, ed);
                        setLocalEditor(ed);
                    }}
                    trackChangesEnabled={trackChangesEnabled}
                    trackChangesUser={trackChangesUser}
                />

                {/* Track Changes Action Bar */}
                {trackChangesEnabled && localEditor && (
                    <div className="flex items-center gap-2 mt-1.5 pt-1.5 border-t border-gray-100">
                        <span className="text-[9px] font-bold text-blue-600 uppercase tracking-wider">TC</span>
                        <button
                            onClick={() => localEditor.commands.acceptChange?.()}
                            className="text-[10px] px-2 py-0.5 rounded border border-green-200 bg-green-50 text-green-700 hover:bg-green-100 transition-colors"
                            title="Accept change at cursor (Cmd+Shift+A)"
                        >
                            Accept
                        </button>
                        <button
                            onClick={() => localEditor.commands.rejectChange?.()}
                            className="text-[10px] px-2 py-0.5 rounded border border-red-200 bg-red-50 text-red-700 hover:bg-red-100 transition-colors"
                            title="Reject change at cursor (Cmd+Shift+R)"
                        >
                            Reject
                        </button>
                        <div className="flex-1" />
                        <button
                            onClick={() => localEditor.commands.acceptAllChanges?.()}
                            className="text-[10px] px-2 py-0.5 rounded border border-gray-200 bg-gray-50 text-gray-600 hover:bg-gray-100 transition-colors"
                            title="Accept all changes"
                        >
                            Accept All
                        </button>
                        <button
                            onClick={() => localEditor.commands.rejectAllChanges?.()}
                            className="text-[10px] px-2 py-0.5 rounded border border-gray-200 bg-gray-50 text-gray-600 hover:bg-gray-100 transition-colors"
                            title="Reject all changes"
                        >
                            Reject All
                        </button>
                    </div>
                )}

                {/* Glossary Matches - Directly under editor for visibility */}
                {glossaryMatches.length > 0 && (
                    <div className="mt-2 pt-2 border-t border-gray-100/50">
                        <div className="text-[9px] font-bold text-teal-600/80 uppercase tracking-widest mb-1.5 flex items-center gap-1.5">
                            <span className="w-1 h-1 bg-teal-400 rounded-full"></span>
                            Glossary Suggestions
                        </div>
                        <div className="space-y-1">
                            {glossaryMatches.map((match, idx) => (
                                <GlossaryCard key={idx} match={match} />
                            ))}
                        </div>
                    </div>
                )}
            </div>

            {/* Note: Glossary matches moved to SourceColumn for better visibility */}

            {/* DEBUG: Show raw target content */}
            {showDebug && (
                <div className="mt-2 text-[9px] text-gray-300 font-mono break-all opacity-0 group-hover:opacity-50 transition-opacity">
                    DB: {segment.target_content || '(empty)'}
                </div>
            )}
        </div>
    );
}

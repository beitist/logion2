import React, { memo, useState, useCallback, useMemo } from 'react';
import { useSegmentMatches } from './hooks/useSegmentMatches';
import { SourceColumn } from './SourceColumn';
import { TargetColumn } from './TargetColumn';

/**
 * SegmentRow - A single translation segment in the editor.
 * 
 * Displays source text on the left and editable target on the right.
 * Acts as an orchestrator, delegating to specialized sub-components.
 * 
 * Props:
 * @param {Object} segment - The segment data (source_content, target_content, metadata, etc.)
 * @param {Object} project - Project configuration
 * @param {Object} generatingSegments - Map of segment IDs currently generating AI drafts
 * @param {Object} flashingSegments - Map of segment IDs with flash animation
 * @param {boolean} showDebug - Whether to show debug information
 * @param {Function} onAiDraft - Callback to trigger AI draft generation
 * @param {Function} onToggleFlag - Callback to toggle flag state
 * @param {Function} onSave - Callback when target content is saved
 * @param {Function} onFocus - Callback when editor receives focus
 * @param {Function} onNavigate - Callback for keyboard navigation between segments
 * @param {Function} onContextMenu - Callback for right-click context menu (glossary add)
 * @param {Function} registerEditor - Callback to register editor instance for external control
 */
export const SegmentRow = memo(({
    segment,
    project,
    generatingSegments,
    flashingSegments,
    showDebug,
    onAiDraft,
    onToggleFlag,
    onSave,
    onFocus,
    onNavigate,
    onContextMenu,
    registerEditor,
    onGlossaryUpdate
}) => {
    // Use custom hook to process and sort matches
    const {
        sortedMatches,
        tmMatches,
        isMandatoryContext,
        hasContext
    } = useSegmentMatches(segment);

    const aiSettings = project?.config?.ai_settings || {};

    // Derive Track Changes state from project config (no toolbar toggle needed)
    const tcSettings = project?.config?.tc_settings || {};
    const hasTC = segment.metadata?.has_track_changes;
    // TC mode: 'first_last' (simple diff), 'step_by_step' (slider + target TC), or undefined
    const tcMode = hasTC ? (tcSettings.tc_mode || 'first_last') : null;
    const showSourceTC = !!tcMode;

    // Revision stages & special segment type detection
    const stages = segment.metadata?.revision_stages || [];
    // Insert-only: stage 0 is empty (entirely new content in stage 1+)
    const isInsertOnly = stages.length >= 2 && !stages[0]?.text?.trim();
    // Deleted: final stage is empty (content removed in last revision)
    const isDeletedFinal = stages.length >= 2 && !stages[stages.length - 1]?.text?.trim();
    // Simple insert: insert-only with exactly 2 stages → no slider, no TC needed
    const isSimpleInsert = isInsertOnly && stages.length === 2;

    // Base stage: stage 1 for insert-only (stage 0 is empty), else 0
    const baseStage = isInsertOnly ? 1 : 0;

    // Slider stage tracking (starts at baseStage)
    const [activeTCStage, setActiveTCStage] = useState(baseStage);
    const handleStageChange = useCallback((stageIndex) => {
        setActiveTCStage(stageIndex);
    }, []);

    // Target TC: active past base stage, with content, in step_by_step, not simple insert
    const currentStage = stages[activeTCStage] || {};
    const targetTCEnabled = tcMode === 'step_by_step'
        && !isSimpleInsert
        && activeTCStage > baseStage
        && !!segment.target_content;

    // TC author: use translator name if tc_replace_authors is on, else original stage author
    const replaceAuthors = tcSettings.tc_replace_authors;
    const translatorName = tcSettings.tc_translator_name || 'Translator';

    // TC user from revision stage author (memoized for stable object reference)
    const trackChangesUser = useMemo(() => {
        if (!targetTCEnabled) return null;
        const name = replaceAuthors ? translatorName : (currentStage.author || 'Editor');
        return {
            id: name.toLowerCase().replace(/\s+/g, '_'),
            nickname: name
        };
    }, [targetTCEnabled, currentStage.author, replaceAuthors, translatorName]);

    // Wrap onAiDraft for TC segments.
    // TC 0 / first_last: simple MT with correct source stage text.
    // TC 1+ step_by_step: no manual shortcut — batch workflow only.
    const wrappedOnAiDraft = useCallback((segmentId) => {
        if (tcMode && !isSimpleInsert && stages.length >= 2) {
            // step_by_step TC1+: disabled — must use batch workflow
            if (tcMode === 'step_by_step' && activeTCStage > baseStage) {
                return Promise.resolve(null);
            }
            // first_last: translate the final source text
            // step_by_step TC0: translate the base stage (classic MT)
            const stageIdx = tcMode === 'first_last' ? stages.length - 1 : baseStage;
            const stageData = stages[stageIdx] || {};
            const tcParams = {
                tc_source_text: stageData.text || '',
                tc_base_translation: '',
                tc_author_id: 'mt',
                tc_author_name: 'MT',
                tc_date: stageData.date || '',
            };
            return onAiDraft(segmentId, false, 'translate', false, false, tcParams);
        } else {
            return onAiDraft(segmentId);
        }
    }, [onAiDraft, tcMode, isSimpleInsert, activeTCStage, stages, baseStage]);

    return (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4 bg-white rounded-xl shadow-sm border border-gray-200 overflow-hidden group hover:shadow-md transition-shadow">
            {/* Source Column (Left) */}
            <SourceColumn
                segment={segment}
                project={project}
                sortedMatches={sortedMatches}
                tmMatches={tmMatches}
                hasContext={hasContext}
                generatingSegments={generatingSegments}
                flashingSegments={flashingSegments}
                showDebug={showDebug}
                showSourceTC={showSourceTC}
                tcMode={tcMode}
                isSimpleInsert={isSimpleInsert}
                isDeletedFinal={isDeletedFinal}
                initialStage={baseStage}
                onAiDraft={wrappedOnAiDraft}
                onContextMenu={onContextMenu}
                onStageChange={handleStageChange}
            />

            {/* Target Column (Right) */}
            <TargetColumn
                segment={segment}
                project={project}
                sortedMatches={sortedMatches}
                isMandatoryContext={isMandatoryContext}
                aiSettings={aiSettings}
                onSave={onSave}
                onAiDraft={wrappedOnAiDraft}
                onFocus={onFocus}
                onNavigate={onNavigate}
                onToggleFlag={onToggleFlag}
                registerEditor={registerEditor}
                showDebug={showDebug}
                onGlossaryUpdate={onGlossaryUpdate}
                tcMode={tcMode}
                activeTCStage={activeTCStage}
                baseStage={baseStage}
                isSimpleInsert={isSimpleInsert}
                isDeletedFinal={isDeletedFinal}
                trackChangesEnabled={targetTCEnabled}
                trackChangesUser={trackChangesUser}
            />
        </div>
    );
});

import React, { memo } from 'react';
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
    registerEditor
}) => {
    // Use custom hook to process and sort matches
    const {
        sortedMatches,
        tmMatches,
        isMandatoryContext,
        hasContext
    } = useSegmentMatches(segment);

    const aiSettings = project?.config?.ai_settings || {};

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
                onAiDraft={onAiDraft}
            />

            {/* Target Column (Right) */}
            <TargetColumn
                segment={segment}
                project={project}
                sortedMatches={sortedMatches}
                isMandatoryContext={isMandatoryContext}
                aiSettings={aiSettings}
                onSave={onSave}
                onAiDraft={onAiDraft}
                onFocus={onFocus}
                onNavigate={onNavigate}
                onToggleFlag={onToggleFlag}
                registerEditor={registerEditor}
                showDebug={showDebug}
            />
        </div>
    );
});

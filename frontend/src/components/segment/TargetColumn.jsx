import React from 'react';
import { TiptapEditor } from '../TiptapEditor';
import { hydrateContent } from '../../utils/editorTransforms';
import { SegmentBadges, SegmentTypeBadges, SpacingWarning } from './SegmentBadges';

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
    showDebug
}) {
    const isFlagged = segment.metadata?.flagged || false;
    const glossaryMatches = sortedMatches.filter(m => m.type === 'glossary');

    // Background color varies based on segment state
    const bgClass = isFlagged
        ? 'bg-yellow-50/50 border-l border-yellow-200'
        : isMandatoryContext
            ? 'bg-red-50/80 border-l border-red-200'
            : 'bg-white';

    return (
        <div className={`p-5 rounded-r-xl flex flex-col relative group ${bgClass}`}>
            {/* Header row with labels and badges */}
            <div className="text-xs text-gray-400 font-mono mb-2 uppercase tracking-wider flex justify-between items-center select-none">
                <div className="flex items-center gap-2">
                    {/* Target label */}
                    <span className={`font-bold transition-colors ${isMandatoryContext ? 'text-red-800' : 'text-gray-300 group-hover:text-indigo-400'}`}>
                        {isMandatoryContext ? '⚠️ Mandatory Target' : 'Target (DE)'}
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

            {/* Editable TiptapEditor */}
            <div className="flex-grow">
                <TiptapEditor
                    content={hydrateContent(segment.target_content, segment.tags)}
                    segmentId={segment.id}
                    availableTags={segment.tags}
                    contextMatches={sortedMatches}
                    onSave={onSave}
                    aiSettings={aiSettings}
                    onAiDraft={(id) => onAiDraft(id)}
                    onFocus={() => onFocus(segment.id)}
                    onNavigate={(dir) => onNavigate(segment.id, dir)}
                    onEditorReady={(ed) => registerEditor(segment.id, ed)}
                />
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

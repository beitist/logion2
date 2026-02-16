import React, { useState, useEffect, useMemo } from 'react';
import { ChevronLeft, ChevronRight } from 'lucide-react';
import { createInlineDiff } from '../../utils/diffUtils';

/**
 * RevisionSlider — Stage-based revision navigator for track changes.
 *
 * Starts at stage 0 (original text, no diff). Moving to stage 1+ shows
 * the inline diff from the previous stage. The active stage index is
 * reported via onStageChange so the parent can control the target editor's
 * TC user/level accordingly.
 *
 * @param {Array} stages - Revision stages [{stage, author, date, text}, ...]
 * @param {Function} onStageChange - Called with (stageIndex) when active stage changes
 */
export function RevisionSlider({ stages, onStageChange, initialStage = 0 }) {
    const [activeStage, setActiveStage] = useState(initialStage);

    // Notify parent whenever active stage changes
    useEffect(() => {
        onStageChange?.(activeStage);
    }, [activeStage, onStageChange]);

    // Pre-compute diffs between consecutive stages (stage 1+)
    const diffs = useMemo(() => {
        if (!stages || stages.length < 2) return [];
        const d = [];
        for (let i = 1; i < stages.length; i++) {
            d.push(createInlineDiff(stages[i - 1].text, stages[i].text));
        }
        return d;
    }, [stages]);

    if (!stages || stages.length < 2) return null;

    const current = stages[activeStage];
    if (!current) return null;

    const canPrev = activeStage > 0;
    const canNext = activeStage < stages.length - 1;

    const formatDate = (dateStr) => {
        if (!dateStr) return '';
        try {
            const d = new Date(dateStr);
            return d.toLocaleDateString('de-DE', { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' });
        } catch {
            return dateStr;
        }
    };

    // Base stage shows plain text (TC off), stages past base show diffs (TC on)
    const isBase = activeStage === initialStage && activeStage < stages.length;
    const isOriginal = activeStage === 0;
    const diffHtml = (isOriginal || isBase) ? null : diffs[activeStage - 1];

    return (
        <div className="space-y-2">
            {/* Navigation header */}
            <div className="flex items-center justify-between text-xs">
                <button
                    onClick={() => canPrev && setActiveStage(activeStage - 1)}
                    disabled={!canPrev}
                    className={`flex items-center gap-0.5 px-1.5 py-0.5 rounded transition-colors ${
                        canPrev ? 'text-gray-600 hover:bg-gray-200 cursor-pointer' : 'text-gray-300 cursor-default'
                    }`}
                >
                    <ChevronLeft size={14} />
                    <span>Prev</span>
                </button>

                <div className="text-center">
                    {isOriginal ? (
                        <span className="font-medium text-gray-500">Original</span>
                    ) : (
                        <>
                            <span className="font-medium text-gray-700">
                                {current.author || `Revision ${activeStage}`}
                            </span>
                            {current.date && (
                                <span className="text-gray-400 ml-1.5">
                                    {formatDate(current.date)}
                                </span>
                            )}
                        </>
                    )}
                </div>

                <button
                    onClick={() => canNext && setActiveStage(activeStage + 1)}
                    disabled={!canNext}
                    className={`flex items-center gap-0.5 px-1.5 py-0.5 rounded transition-colors ${
                        canNext ? 'text-gray-600 hover:bg-gray-200 cursor-pointer' : 'text-gray-300 cursor-default'
                    }`}
                >
                    <span>Next</span>
                    <ChevronRight size={14} />
                </button>
            </div>

            {/* Content: plain text for base stage, diff for stages past base */}
            {isBase ? (
                <div className="text-sm leading-relaxed text-gray-700">
                    {current.text || <span className="italic text-gray-400">Empty (new segment)</span>}
                </div>
            ) : isOriginal && !current.text?.trim() ? (
                <div className="text-sm leading-relaxed text-gray-400 italic">
                    Empty (new segment)
                </div>
            ) : diffHtml ? (
                <div
                    className="text-sm leading-relaxed"
                    dangerouslySetInnerHTML={{ __html: diffHtml }}
                />
            ) : (
                <div className="text-sm text-gray-400 italic">No changes in this revision</div>
            )}

            {/* Stage dots */}
            <div className="flex items-center justify-center gap-1.5 pt-1">
                {stages.map((stage, i) => (
                    <button
                        key={i}
                        onClick={() => setActiveStage(i)}
                        className={`rounded-full transition-all ${
                            i === activeStage
                                ? 'w-2.5 h-2.5 bg-blue-500'
                                : 'w-1.5 h-1.5 bg-gray-300 hover:bg-gray-400'
                        }`}
                        title={`${i === 0 ? 'Original' : (stage.author || `Rev ${i}`)}${stage.date ? ` (${formatDate(stage.date)})` : ''}`}
                    />
                ))}
            </div>

            {/* Stage label */}
            <div className="text-center text-[10px] text-gray-400">
                {isBase ? (
                    <span>Stage {activeStage} — {isOriginal ? 'Original' : 'Base'} <span className="text-blue-500 font-medium">(TC off)</span></span>
                ) : (
                    <span>Stage {activeStage} of {stages.length - 1} <span className="text-blue-500 font-medium">(TC on)</span></span>
                )}
            </div>
        </div>
    );
}

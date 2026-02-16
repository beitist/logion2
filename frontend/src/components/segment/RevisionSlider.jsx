import React, { useState, useMemo } from 'react';
import { ChevronLeft, ChevronRight } from 'lucide-react';
import { createInlineDiff } from '../../utils/diffUtils';

/**
 * RevisionSlider — Git-style revision navigator for track changes.
 *
 * Shows the text at each revision stage with inline diff highlighting
 * between consecutive stages. Users can navigate with Prev/Next buttons
 * or click on stage dots.
 *
 * @param {Array} stages - Revision stages [{stage, author, date, text}, ...]
 */
export function RevisionSlider({ stages }) {
    // Start at the transition from stage 0 → 1 (first change)
    const [activeTransition, setActiveTransition] = useState(1);

    // Transitions: each is a diff between stage N-1 and stage N
    const transitions = useMemo(() => {
        if (!stages || stages.length < 2) return [];
        const t = [];
        for (let i = 1; i < stages.length; i++) {
            t.push({
                index: i,
                from: stages[i - 1],
                to: stages[i],
                diffHtml: createInlineDiff(stages[i - 1].text, stages[i].text),
            });
        }
        return t;
    }, [stages]);

    if (transitions.length === 0) return null;

    const current = transitions[activeTransition - 1];
    if (!current) return null;

    const canPrev = activeTransition > 1;
    const canNext = activeTransition < transitions.length;

    const formatDate = (dateStr) => {
        if (!dateStr) return '';
        try {
            const d = new Date(dateStr);
            return d.toLocaleDateString('de-DE', { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' });
        } catch {
            return dateStr;
        }
    };

    return (
        <div className="space-y-2">
            {/* Navigation header */}
            <div className="flex items-center justify-between text-xs">
                <button
                    onClick={() => canPrev && setActiveTransition(activeTransition - 1)}
                    disabled={!canPrev}
                    className={`flex items-center gap-0.5 px-1.5 py-0.5 rounded transition-colors ${
                        canPrev ? 'text-gray-600 hover:bg-gray-200 cursor-pointer' : 'text-gray-300 cursor-default'
                    }`}
                >
                    <ChevronLeft size={14} />
                    <span>Prev</span>
                </button>

                <div className="text-center">
                    <span className="font-medium text-gray-700">
                        {current.to.author || 'Change'}
                    </span>
                    {current.to.date && (
                        <span className="text-gray-400 ml-1.5">
                            {formatDate(current.to.date)}
                        </span>
                    )}
                </div>

                <button
                    onClick={() => canNext && setActiveTransition(activeTransition + 1)}
                    disabled={!canNext}
                    className={`flex items-center gap-0.5 px-1.5 py-0.5 rounded transition-colors ${
                        canNext ? 'text-gray-600 hover:bg-gray-200 cursor-pointer' : 'text-gray-300 cursor-default'
                    }`}
                >
                    <span>Next</span>
                    <ChevronRight size={14} />
                </button>
            </div>

            {/* Diff content */}
            {current.diffHtml ? (
                <div
                    className="text-sm leading-relaxed"
                    dangerouslySetInnerHTML={{ __html: current.diffHtml }}
                />
            ) : (
                <div className="text-sm text-gray-400 italic">No changes in this revision</div>
            )}

            {/* Stage dots */}
            <div className="flex items-center justify-center gap-1.5 pt-1">
                {stages.map((stage, i) => {
                    // Dot before transition i represents stage i
                    // Active range: from.stage and to.stage
                    const isFrom = i === activeTransition - 1;
                    const isTo = i === activeTransition;

                    return (
                        <button
                            key={i}
                            onClick={() => {
                                if (i > 0 && i <= transitions.length) setActiveTransition(i);
                                else if (i === 0 && transitions.length > 0) setActiveTransition(1);
                            }}
                            className={`rounded-full transition-all ${
                                isTo
                                    ? 'w-2.5 h-2.5 bg-blue-500'
                                    : isFrom
                                        ? 'w-2 h-2 bg-blue-300'
                                        : 'w-1.5 h-1.5 bg-gray-300 hover:bg-gray-400'
                            }`}
                            title={`${stage.author || 'Original'}${stage.date ? ` (${formatDate(stage.date)})` : ''}`}
                        />
                    );
                })}
            </div>

            {/* Stage label */}
            <div className="text-center text-[10px] text-gray-400">
                Step {activeTransition} of {transitions.length}
            </div>
        </div>
    );
}

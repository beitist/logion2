import React, { useState, useMemo, useRef, useEffect } from 'react';
import { ShieldCheck, AlertTriangle, ChevronRight, X } from 'lucide-react';

/**
 * QA Check dropdown in the toolbar.
 * Live-counts issues and provides "go to next" navigation.
 */
export function QACheck({ segments, activeSegmentId, onNavigateToSegment }) {
    const [open, setOpen] = useState(false);
    const dropdownRef = useRef(null);

    // Close on outside click
    useEffect(() => {
        if (!open) return;
        const handler = (e) => {
            if (dropdownRef.current && !dropdownRef.current.contains(e.target)) {
                setOpen(false);
            }
        };
        document.addEventListener('mousedown', handler);
        return () => document.removeEventListener('mousedown', handler);
    }, [open]);

    const checks = useMemo(() => {
        const empty = [];
        const drafts = [];
        const flagged = [];

        for (const seg of segments) {
            const meta = seg.metadata || {};
            // Skip comments, shapes, etc. — only check translatable segments
            if (meta.type === 'comment') continue;
            if (meta.skip) continue;

            const hasTarget = seg.target_content && seg.target_content.trim();

            if (!hasTarget && seg.status !== 'translated') {
                empty.push(seg);
            }

            if (seg.status === 'mt_draft' || seg.status === 'draft') {
                drafts.push(seg);
            }

            if (meta.flagged) {
                flagged.push(seg);
            }
        }

        return { empty, drafts, flagged };
    }, [segments]);

    const totalIssues = checks.empty.length + checks.drafts.length + checks.flagged.length;

    const findNext = (issueList) => {
        if (!issueList.length) return null;
        // Find the first issue AFTER the current active segment
        const activeIdx = segments.findIndex(s => s.id === activeSegmentId);
        const afterCurrent = issueList.find(s => {
            const idx = segments.findIndex(seg => seg.id === s.id);
            return idx > activeIdx;
        });
        return afterCurrent || issueList[0]; // wrap around
    };

    const goToNext = (issueList) => {
        const next = findNext(issueList);
        if (next) {
            onNavigateToSegment(next.id);
            setOpen(false);
        }
    };

    const categories = [
        {
            key: 'empty',
            label: 'Empty (no skip)',
            list: checks.empty,
            color: 'red',
            bgColor: 'bg-red-50',
            textColor: 'text-red-700',
            dotColor: 'bg-red-500',
        },
        {
            key: 'drafts',
            label: 'Unreviewed drafts',
            list: checks.drafts,
            color: 'amber',
            bgColor: 'bg-amber-50',
            textColor: 'text-amber-700',
            dotColor: 'bg-amber-500',
        },
        {
            key: 'flagged',
            label: 'Flagged for review',
            list: checks.flagged,
            color: 'blue',
            bgColor: 'bg-blue-50',
            textColor: 'text-blue-700',
            dotColor: 'bg-blue-500',
        },
    ];

    return (
        <div className="relative" ref={dropdownRef}>
            <button
                onClick={() => setOpen(!open)}
                className={`p-2 rounded-lg transition-colors relative ${
                    totalIssues > 0
                        ? 'text-amber-600 hover:bg-amber-50'
                        : 'text-green-600 hover:bg-green-50'
                }`}
                title={totalIssues > 0 ? `${totalIssues} QA issues` : 'No QA issues'}
            >
                {totalIssues > 0 ? <AlertTriangle size={18} /> : <ShieldCheck size={18} />}
                {totalIssues > 0 && (
                    <span className="absolute -top-0.5 -right-0.5 min-w-[18px] h-[18px] flex items-center justify-center bg-amber-500 text-white text-[10px] font-bold rounded-full px-1 leading-none">
                        {totalIssues > 99 ? '99+' : totalIssues}
                    </span>
                )}
            </button>

            {open && (
                <div className="absolute right-0 top-full mt-2 w-72 bg-white rounded-xl shadow-xl border border-gray-100 overflow-hidden z-30">
                    {/* Header */}
                    <div className="px-4 py-2.5 border-b border-gray-100 flex items-center justify-between">
                        <span className="text-xs font-semibold text-gray-500 uppercase tracking-wider">QA Check</span>
                        {totalIssues === 0 ? (
                            <span className="text-xs font-medium text-green-600 flex items-center gap-1">
                                <ShieldCheck size={13} /> All clear
                            </span>
                        ) : (
                            <span className="text-xs font-medium text-amber-600">
                                {totalIssues} issue{totalIssues !== 1 ? 's' : ''}
                            </span>
                        )}
                    </div>

                    {/* Categories */}
                    <div className="p-1.5">
                        {categories.map(cat => (
                            <div key={cat.key} className={`flex items-center justify-between px-3 py-2 rounded-lg ${cat.list.length > 0 ? cat.bgColor : 'bg-gray-50'} mb-1 last:mb-0`}>
                                <div className="flex items-center gap-2">
                                    <span className={`w-2 h-2 rounded-full ${cat.list.length > 0 ? cat.dotColor : 'bg-gray-300'}`} />
                                    <span className={`text-sm font-medium ${cat.list.length > 0 ? cat.textColor : 'text-gray-400'}`}>
                                        {cat.label}
                                    </span>
                                </div>
                                <div className="flex items-center gap-2">
                                    <span className={`text-sm font-semibold tabular-nums ${cat.list.length > 0 ? cat.textColor : 'text-gray-400'}`}>
                                        {cat.list.length}
                                    </span>
                                    {cat.list.length > 0 && (
                                        <button
                                            onClick={() => goToNext(cat.list)}
                                            className={`p-1 rounded-md hover:bg-white/60 transition-colors ${cat.textColor}`}
                                            title={`Go to next ${cat.label.toLowerCase()}`}
                                        >
                                            <ChevronRight size={14} />
                                        </button>
                                    )}
                                </div>
                            </div>
                        ))}
                    </div>
                </div>
            )}
        </div>
    );
}

/**
 * Export warning modal — shown before export if QA issues exist.
 */
export function QAExportWarning({ segments, onProceed, onCancel }) {
    const counts = useMemo(() => {
        let empty = 0, drafts = 0;
        for (const seg of segments) {
            const meta = seg.metadata || {};
            if (meta.type === 'comment' || meta.skip) continue;
            const hasTarget = seg.target_content && seg.target_content.trim();
            if (!hasTarget && seg.status !== 'translated') empty++;
            if (seg.status === 'mt_draft' || seg.status === 'draft') drafts++;
        }
        return { empty, drafts, total: empty + drafts };
    }, [segments]);

    if (counts.total === 0) return null;

    return (
        <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50" onClick={onCancel}>
            <div className="bg-white rounded-2xl shadow-2xl w-full max-w-sm mx-4 overflow-hidden" onClick={e => e.stopPropagation()}>
                <div className="p-5">
                    <div className="flex items-center gap-3 mb-3">
                        <div className="w-10 h-10 rounded-full bg-amber-100 flex items-center justify-center flex-shrink-0">
                            <AlertTriangle size={20} className="text-amber-600" />
                        </div>
                        <div>
                            <h3 className="text-base font-semibold text-gray-900">Export with QA issues?</h3>
                            <p className="text-xs text-gray-500 mt-0.5">Some segments need attention</p>
                        </div>
                    </div>
                    <div className="space-y-1.5 ml-[52px]">
                        {counts.empty > 0 && (
                            <div className="flex items-center gap-2 text-sm">
                                <span className="w-2 h-2 rounded-full bg-red-500" />
                                <span className="text-gray-700"><strong>{counts.empty}</strong> empty segment{counts.empty !== 1 ? 's' : ''}</span>
                            </div>
                        )}
                        {counts.drafts > 0 && (
                            <div className="flex items-center gap-2 text-sm">
                                <span className="w-2 h-2 rounded-full bg-amber-500" />
                                <span className="text-gray-700"><strong>{counts.drafts}</strong> unreviewed draft{counts.drafts !== 1 ? 's' : ''}</span>
                            </div>
                        )}
                    </div>
                </div>
                <div className="flex border-t border-gray-100">
                    <button
                        onClick={onCancel}
                        className="flex-1 py-3 text-sm font-medium text-gray-600 hover:bg-gray-50 transition-colors"
                    >
                        Cancel
                    </button>
                    <div className="w-px bg-gray-100" />
                    <button
                        onClick={onProceed}
                        className="flex-1 py-3 text-sm font-medium text-amber-600 hover:bg-amber-50 transition-colors"
                    >
                        Export anyway
                    </button>
                </div>
            </div>
        </div>
    );
}

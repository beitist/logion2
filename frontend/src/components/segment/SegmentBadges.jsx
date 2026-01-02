import React from 'react';
import { Bug } from 'lucide-react';

/**
 * Displays segment metadata badges and status indicators.
 * 
 * Badge Types:
 * - H: Header segment
 * - Tb: Table cell segment
 * - Status: draft/translated/error
 * 
 * @param {Object} segment - Segment with metadata and status
 * @param {boolean} isFlagged - Whether segment is flagged for review
 * @param {Function} onToggleFlag - Callback to toggle flag state
 */
export function SegmentBadges({ segment, isFlagged, onToggleFlag }) {
    return (
        <div className="flex items-center gap-2">
            {/* Flag button */}
            <button
                onClick={() => onToggleFlag(segment.id, isFlagged)}
                className={`p-1 rounded transition-colors ${isFlagged ? 'text-yellow-600 bg-yellow-100' : 'text-gray-300 hover:text-yellow-500'}`}
                title={isFlagged ? "Flagged for Review" : "Flag for Review"}
            >
                <Bug size={14} className={isFlagged ? "fill-yellow-500" : ""} />
            </button>

            {/* Status badge */}
            <span className={`px-2 py-0.5 rounded-full text-[9px] font-bold border ${segment.status === 'draft' ? 'bg-yellow-50 text-yellow-600 border-yellow-100' :
                    segment.status === 'mt_draft' ? 'bg-purple-50 text-purple-600 border-purple-100' :
                        segment.status === 'translated' ? 'bg-green-50 text-green-600 border-green-100' :
                            'bg-gray-50 border-gray-100'
                }`}>
                {segment.status}
            </span>
        </div>
    );
}

/**
 * Displays segment type badges (Header, Table).
 * 
 * @param {Object} metadata - Segment metadata containing type info
 */
export function SegmentTypeBadges({ metadata }) {
    if (!metadata) return null;

    return (
        <div className="flex gap-1">
            {metadata.type === 'header' && (
                <span className="bg-purple-50 text-purple-600 px-1.5 py-0.5 rounded text-[9px] font-bold border border-purple-100">
                    H
                </span>
            )}
            {(metadata.type === 'table' || metadata.child_type === 'table_cell') && (
                <span className="bg-blue-50 text-blue-600 px-1.5 py-0.5 rounded text-[9px] font-bold border border-blue-100">
                    Tb
                </span>
            )}
        </div>
    );
}

/**
 * Warning indicator for whitespace mismatches between source and target.
 * 
 * Checks if target starts/ends with expected whitespace from source.
 * Important for document reassembly where spacing must be preserved.
 * 
 * @param {Object} segment - Segment with metadata.whitespaces and target_content
 */
export function SpacingWarning({ segment }) {
    const ws = segment.metadata?.whitespaces;
    if (!ws) return null;

    const target = segment.target_content || "";
    const expectedLead = ws.leading || "";
    const expectedTrail = ws.trailing || "";

    let mismatchParts = [];
    if (!target.startsWith(expectedLead)) mismatchParts.push("Leading Space");
    if (!target.endsWith(expectedTrail)) mismatchParts.push("Trailing Space");

    if (mismatchParts.length === 0) return null;

    return (
        <div
            className="ml-2 flex items-center gap-1 text-[10px] text-red-500 bg-red-50 px-1.5 py-0.5 rounded border border-red-100"
            title={`Mismatch: ${mismatchParts.join(", ")}`}
        >
            <span className="font-bold font-mono">␣!</span>
            <span className="hidden group-hover:inline">Spacing</span>
        </div>
    );
}

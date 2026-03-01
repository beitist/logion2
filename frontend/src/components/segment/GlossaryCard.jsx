import React, { useState, useRef, useEffect } from 'react';
import { Pencil, Check, X } from 'lucide-react';
import { formatSourceContent } from '../../utils/editorTransforms';

export function GlossaryCard({ match, onUpdate }) {
    const [isEditing, setIsEditing] = useState(false);
    const [targetValue, setTargetValue] = useState(match.content || '');
    const [noteValue, setNoteValue] = useState(match.note || '');
    const targetRef = useRef(null);

    const isAuto = match.metadata?.origin === 'auto';
    const entryId = match.metadata?.entry_id;
    const canEdit = !!entryId && !!onUpdate;

    // Focus target input when entering edit mode
    useEffect(() => {
        if (isEditing) targetRef.current?.focus();
    }, [isEditing]);

    const handleSave = async () => {
        if (!canEdit) return;
        const trimmedTarget = targetValue.trim();
        if (!trimmedTarget) return; // Don't save empty target
        await onUpdate(entryId, {
            target_term: trimmedTarget,
            context_note: noteValue.trim() || null,
        });
        setIsEditing(false);
    };

    const handleCancel = () => {
        setTargetValue(match.content || '');
        setNoteValue(match.note || '');
        setIsEditing(false);
    };

    const handleKeyDown = (e) => {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            handleSave();
        } else if (e.key === 'Escape') {
            handleCancel();
        }
    };

    const colors = isAuto
        ? {
            border: 'border-emerald-100',
            bg: 'bg-emerald-50/50',
            hover: 'hover:bg-emerald-50',
            label: 'text-emerald-700',
            tag: 'text-emerald-600 border-emerald-100',
            selection: 'selection:bg-emerald-100',
            noteBorder: 'border-emerald-100/50',
        }
        : {
            border: 'border-teal-100',
            bg: 'bg-teal-50/50',
            hover: 'hover:bg-teal-50',
            label: 'text-teal-700',
            tag: 'text-teal-600 border-teal-100',
            selection: 'selection:bg-teal-100',
            noteBorder: 'border-teal-100/50',
        };

    return (
        <div className={`p-2.5 rounded border ${colors.border} ${colors.bg} ${colors.hover} transition-colors group/card`}>
            {/* Header with source term */}
            <div className="flex justify-between items-start mb-1">
                <div className="flex items-center gap-2 flex-1 min-w-0">
                    <span className={`text-[10px] font-bold uppercase tracking-wider ${colors.label} flex-shrink-0`}>
                        {isAuto ? '🤖 Auto' : '📚 Glossary'}
                    </span>
                    {match.source_text && (
                        <span className={`text-[10px] font-medium bg-white/50 px-1 rounded border ${colors.tag} truncate`}>
                            {match.source_text}
                        </span>
                    )}
                </div>
                {canEdit && !isEditing && (
                    <button
                        onClick={() => setIsEditing(true)}
                        className="p-0.5 rounded text-gray-300 hover:text-gray-500 opacity-0 group-hover/card:opacity-100 transition-opacity flex-shrink-0"
                        title="Edit glossary entry"
                    >
                        <Pencil size={11} />
                    </button>
                )}
            </div>

            {isEditing ? (
                /* Edit Mode */
                <div className="space-y-1.5">
                    <input
                        ref={targetRef}
                        value={targetValue}
                        onChange={(e) => setTargetValue(e.target.value)}
                        onKeyDown={handleKeyDown}
                        className="w-full text-sm px-2 py-1 border border-gray-300 rounded focus:outline-none focus:ring-1 focus:ring-indigo-300 focus:border-indigo-400"
                        placeholder="Target term"
                    />
                    <input
                        value={noteValue}
                        onChange={(e) => setNoteValue(e.target.value)}
                        onKeyDown={handleKeyDown}
                        className="w-full text-[11px] px-2 py-0.5 border border-gray-200 rounded focus:outline-none focus:ring-1 focus:ring-indigo-200 text-gray-500"
                        placeholder="Note (optional)"
                    />
                    <div className="flex items-center gap-1 justify-end">
                        <button
                            onClick={handleCancel}
                            className="p-1 rounded hover:bg-gray-200 text-gray-400 hover:text-gray-600 transition-colors"
                            title="Cancel (Esc)"
                        >
                            <X size={13} />
                        </button>
                        <button
                            onClick={handleSave}
                            className="p-1 rounded hover:bg-green-100 text-green-500 hover:text-green-700 transition-colors"
                            title="Save (Enter)"
                        >
                            <Check size={13} />
                        </button>
                    </div>
                </div>
            ) : (
                /* Display Mode */
                <>
                    <div
                        className={`text-gray-800 text-sm leading-snug font-source ${colors.selection}`}
                        dangerouslySetInnerHTML={{ __html: formatSourceContent(match.content, null, false) }}
                    />
                    {match.note && (
                        <div className={`mt-1 text-[10px] text-gray-500 italic border-t ${colors.noteBorder} pt-1`}>
                            {match.note}
                        </div>
                    )}
                </>
            )}
        </div>
    );
}

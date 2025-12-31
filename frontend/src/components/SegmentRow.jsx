import React, { memo } from 'react';
import { Copy, Bug, Search } from 'lucide-react';
import { TiptapEditor } from './TiptapEditor';
import { formatSourceContent, hydrateContent, getSegmentComments } from '../utils/editorTransforms';

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
    const comments = getSegmentComments(segment.tags);
    const hasContext = (segment.context_matches?.length > 0 || segment.metadata?.context_matches?.length > 0) || !!segment.metadata?.ai_draft;

    // Logic for UI Highlight
    const allMatches = segment.context_matches || segment.metadata?.context_matches || [];
    const mandatoryMatch = allMatches.find(m => m.type === 'mandatory' && m.score >= 98);
    const isMandatoryContext = !!mandatoryMatch;
    const isFlagged = segment.metadata?.flagged || false;
    const aiSettings = project?.config?.ai_settings || {};

    // --- Matches Calculation (Lifted for TiptapEditor Shortcut) ---
    let rawMatches = (segment.context_matches || segment.metadata?.context_matches || []);

    // INJECT AI DRAFT AS A MATCH
    const aiDraft = segment.metadata?.ai_draft;
    if (aiDraft) {
        const existingMT = rawMatches.find(m => m.type === 'mt');
        if (!existingMT) {
            rawMatches = [...rawMatches, {
                type: 'mt',
                content: aiDraft,
                score: 0,
                filename: segment.metadata.ai_model || 'AI',
                model: segment.metadata.ai_model || 'AI'
            }];
        }
    }

    const sortedMatches = rawMatches.sort((a, b) => {
        if (a.type === 'mt') return -1;
        if (b.type === 'mt') return 1;
        return (b.score || 0) - (a.score || 0);
    });
    const tmMatches = sortedMatches.filter(m => m.type !== 'mt');
    // ----------------------------------------------------------------

    return (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4 bg-white rounded-xl shadow-sm border border-gray-200 overflow-hidden group hover:shadow-md transition-shadow">
            {/* Source Column */}
            <div className="p-5 bg-gray-50/80 rounded-l-xl text-sm leading-relaxed border-r border-gray-100 flex flex-col relative">
                <div className="absolute top-2 right-2 flex items-center gap-2">
                    <button
                        onClick={() => navigator.clipboard.writeText(segment.source_content)}
                        className="opacity-0 group-hover:opacity-100 transition-opacity p-1 text-gray-300 hover:text-gray-500 rounded"
                        title="Copy Source Text"
                    >
                        <Copy size={12} />
                    </button>
                    <span className="opacity-0 group-hover:opacity-100 transition-opacity text-xs text-gray-300 font-mono pointer-events-none">#{segment.index + 1}</span>
                </div>

                {/* Source Text (Tiptap ReadOnly with Invisible Chars) */}
                <div className="flex-grow">
                    <TiptapEditor
                        content={formatSourceContent(segment.source_content, segment.tags, true)}
                        isReadOnly={true}
                        chromeless={true}
                        availableTags={segment.tags}
                        segmentId={`source-${segment.id}`}
                    />
                </div>

                {/* Comments Section */}
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

                {/* Context Panel (Matches) */}
                {hasContext && (
                    <div className="mt-6 border-t border-gray-200 pt-4">
                        <div className="flex justify-between items-center mb-3">
                            <h4 className="text-[10px] font-bold text-gray-400 uppercase tracking-widest flex items-center gap-2">
                                <span className="w-1 h-1 bg-gray-400 rounded-full"></span> Translation Memory / Context
                            </h4>
                            <div className="flex gap-1">
                                <button
                                    onClick={() => onAiDraft(segment.id, false, "analyze", false, true)}
                                    className={`text-gray-400 hover:text-blue-600 transition-colors ${generatingSegments[segment.id] ? 'opacity-50 cursor-not-allowed' : ''}`}
                                    title="Search Matches (Refresh) - Cheap"
                                    disabled={generatingSegments[segment.id]}
                                >
                                    <Search size={14} />
                                </button>
                                <button
                                    onClick={() => onAiDraft(segment.id, false, "translate", false, true)}
                                    className={`text-gray-400 hover:text-indigo-600 transition-colors ${generatingSegments[segment.id] ? 'animate-spin text-indigo-500' : ''}`}
                                    title="Regenerate Translation (Force Refresh) - Uses Tokens"
                                    disabled={generatingSegments[segment.id]}
                                >
                                    <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15"></path></svg>
                                </button>
                            </div>
                        </div>
                        <div className="space-y-2">
                            {sortedMatches.map((match, idx) => {
                                const isMandatory = match.type === 'mandatory';
                                const isMT = match.type === 'mt';
                                const isGlossary = match.type === 'glossary';

                                const aiConfig = project?.config?.ai_settings || {};
                                const tMandatory = aiConfig.threshold_mandatory !== undefined ? aiConfig.threshold_mandatory : 60;
                                const tOptional = aiConfig.threshold_optional !== undefined ? aiConfig.threshold_optional : 40;
                                const score = match.score || 0;

                                if (isGlossary) return null; // Show in Target Column instead!
                                else if (isMandatory) { if (score < tMandatory) return null; }
                                else if (!isMT) { if (score < tOptional) return null; }

                                let shortcutLabel = '';
                                if (isMT) shortcutLabel = 'Cmd+Opt+0';
                                else if (!isGlossary) {
                                    const tmIdx = tmMatches.indexOf(match);
                                    if (tmIdx === 0) shortcutLabel = 'Cmd+Opt+9';
                                    else if (tmIdx === 1) shortcutLabel = 'Cmd+Opt+8';
                                    else if (tmIdx === 2) shortcutLabel = 'Cmd+Opt+7';
                                }

                                let borderClass = isMandatory ? 'border-l-red-500' : 'border-l-blue-400';
                                let bgClass = 'bg-white';
                                let textClass = isMandatory ? 'text-red-700' : 'text-blue-700';
                                let label = isMandatory ? '⚖️ Vorgabe' : '💡 Vorschlag aus Archiv';

                                if (isMT) {
                                    borderClass = 'border-l-purple-500';
                                    bgClass = 'bg-purple-50';
                                    textClass = 'text-purple-700';
                                    label = '🤖 Machine Translation';
                                    if (flashingSegments[segment.id]) bgClass = 'animate-flash-purple';
                                } else if (isGlossary) {
                                    borderClass = 'border-l-teal-500';
                                    bgClass = 'bg-teal-50';
                                    textClass = 'text-teal-700';
                                    label = '📚 Glossary Term';
                                }

                                return (
                                    <div key={idx} className={`p-2.5 rounded border transition-all hover:shadow-sm ${bgClass} ${borderClass} border-gray-200`}>
                                        <div className="flex justify-between items-start mb-1">
                                            <div className="flex items-center gap-2">
                                                <span className={`text-[10px] font-bold uppercase tracking-wider flex items-center gap-1 ${textClass}`}>
                                                    {label}
                                                </span>
                                                {match.score !== undefined && !isMT && (
                                                    <span className={`text-[9px] font-bold px-1.5 rounded-full ${match.score > 85 ? 'bg-green-100 text-green-700' : 'bg-gray-100 text-gray-600'}`}>
                                                        {match.score}%
                                                    </span>
                                                )}
                                                <span className="text-[9px] font-mono text-gray-400 bg-white/50 px-1 rounded border border-gray-100 opacity-0 group-hover:opacity-100 transition-opacity">
                                                    {shortcutLabel}
                                                </span>
                                            </div>
                                            <div className="flex items-center gap-1 text-[9px] text-gray-400 font-mono" title={match.filename}>
                                                <span className="truncate max-w-[100px]">
                                                    {isMT ? (project?.config?.ai_settings?.model || match.filename) : match.filename}
                                                </span>
                                            </div>
                                        </div>
                                        <div
                                            className="text-gray-800 text-[13px] leading-snug font-source selection:bg-yellow-100"
                                            dangerouslySetInnerHTML={{ __html: formatSourceContent(match.content, null, false) }}
                                        />
                                        {match.note && (
                                            <div className="mt-1 text-[10px] text-gray-500 italic border-t border-gray-200/50 pt-1">
                                                Note: {match.note}
                                            </div>
                                        )}
                                    </div>
                                )
                            })}
                        </div>
                    </div>
                )}
            </div>

            {/* Target Column */}
            <div className={`p-5 rounded-r-xl flex flex-col relative group ${isFlagged ? 'bg-yellow-50/50 border-l border-yellow-200' : isMandatoryContext ? 'bg-red-50/80 border-l border-red-200' : 'bg-white'}`}>
                <div className="text-xs text-gray-400 font-mono mb-2 uppercase tracking-wider flex justify-between items-center select-none">
                    <div className="flex items-center gap-2">
                        <span className={`font-bold transition-colors ${isMandatoryContext ? 'text-red-800' : 'text-gray-300 group-hover:text-indigo-400'}`}>
                            {isMandatoryContext ? '⚠️ Mandatory Target' : 'Target (DE)'}
                        </span>
                        {/* Spacing Warning */}
                        {(() => {
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
                                <div className="ml-2 flex items-center gap-1 text-[10px] text-red-500 bg-red-50 px-1.5 py-0.5 rounded border border-red-100" title={`Mismatch: ${mismatchParts.join(", ")}`}>
                                    <span className="font-bold font-mono">␣!</span>
                                    <span className="hidden group-hover:inline">Spacing</span>
                                </div>
                            );
                        })()}

                        {segment.metadata && (
                            <div className="flex gap-1">
                                {segment.metadata.type === 'header' && (
                                    <span className="bg-purple-50 text-purple-600 px-1.5 py-0.5 rounded text-[9px] font-bold border border-purple-100">H</span>
                                )}
                                {(segment.metadata.type === 'table' || segment.metadata.child_type === 'table_cell') && (
                                    <span className="bg-blue-50 text-blue-600 px-1.5 py-0.5 rounded text-[9px] font-bold border border-blue-100">Tb</span>
                                )}
                            </div>
                        )}
                    </div>
                    <div className="flex items-center gap-2">
                        <button
                            onClick={() => onToggleFlag(segment.id, isFlagged)}
                            className={`p-1 rounded transition-colors ${isFlagged ? 'text-yellow-600 bg-yellow-100' : 'text-gray-300 hover:text-yellow-500'}`}
                            title={isFlagged ? "Flagged for Review" : "Flag for Review"}
                        >
                            <Bug size={14} className={isFlagged ? "fill-yellow-500" : ""} />
                        </button>
                        <span className={`px-2 py-0.5 rounded-full text-[9px] font-bold border ${segment.status === 'draft' ? 'bg-yellow-50 text-yellow-600 border-yellow-100' :
                            segment.status === 'translated' ? 'bg-green-50 text-green-600 border-green-100' : 'bg-gray-50 border-gray-100'
                            }`}>
                            {segment.status}
                        </span>
                    </div>
                </div>

                <div className="flex-grow">
                    <TiptapEditor
                        content={hydrateContent(segment.target_content, segment.tags)}
                        segmentId={segment.id}
                        availableTags={segment.tags}
                        contextMatches={sortedMatches} // Use injected matches
                        onSave={onSave}
                        aiSettings={aiSettings}
                        onAiDraft={(id) => onAiDraft(id)}
                        onFocus={() => onFocus(segment.id)}
                        onNavigate={(dir) => onNavigate(segment.id, dir)}
                        onEditorReady={(ed) => registerEditor(segment.id, ed)}
                    />
                </div>

                {/* Glossary Matches (Right Column) */}
                {sortedMatches.filter(m => m.type === 'glossary').length > 0 && (
                    <div className="mt-3 pt-3 border-t border-gray-100">
                        <div className="text-[10px] font-bold text-gray-400 uppercase tracking-widest mb-2 flex items-center gap-2">
                            <span className="w-1 h-1 bg-teal-400 rounded-full"></span> Glossary terms
                        </div>
                        <div className="space-y-2">
                            {sortedMatches.filter(m => m.type === 'glossary').map((match, idx) => (
                                <div key={idx} className="p-2.5 rounded border border-teal-100 bg-teal-50/50 hover:bg-teal-50 transition-colors">
                                    <div className="flex justify-between items-start mb-1">
                                        <div className="flex items-center gap-2">
                                            <span className="text-[10px] font-bold uppercase tracking-wider text-teal-700">
                                                📚 Glossary
                                            </span>
                                            {match.source_term && (
                                                <span className="text-[10px] text-teal-600 font-medium bg-white/50 px-1 rounded border border-teal-100">
                                                    {match.source_term}
                                                </span>
                                            )}
                                        </div>
                                    </div>
                                    <div
                                        className="text-gray-800 text-sm leading-snug font-source selection:bg-teal-100"
                                        dangerouslySetInnerHTML={{ __html: formatSourceContent(match.content, null, false) }}
                                    />
                                    {match.note && (
                                        <div className="mt-1 text-[10px] text-gray-500 italic border-t border-teal-100/50 pt-1">
                                            {match.note}
                                        </div>
                                    )}
                                </div>
                            ))}
                        </div>
                    </div>
                )}

                {/* DEBUG: Show raw target content sent to backend */}
                {showDebug && (
                    <div className="mt-2 text-[9px] text-gray-300 font-mono break-all opacity-0 group-hover:opacity-50 transition-opacity">
                        DB: {segment.target_content || '(empty)'}
                    </div>
                )}
            </div>
        </div >
    );
});

import React, { useState, useEffect, useRef, useCallback } from 'react';
import { useProjectData } from '../hooks/useProjectData';
import { useSegmentChat } from '../hooks/useSegmentChat';
import { SegmentRow } from './segment';
import { ChatPanel } from './ChatPanel';
import { ArrowLeft, Check, ChevronsRight, Lock, SkipForward, X } from 'lucide-react';
import { updateSegment } from '../api/client';
import './TiptapStyles.css';

const stripTags = (content) =>
    (content || '').replace(/<[^>]*>/g, '').replace(/\[TAB\]/g, ' ').trim();

export function ReviewView({ projectId, onBack }) {
    const [activeIndex, setActiveIndex] = useState(0);
    const [editModalOpen, setEditModalOpen] = useState(false);
    const [showChat, setShowChat] = useState(false);
    const scrollRef = useRef(null);
    const segmentRefs = useRef({});
    const modalEditorRef = useRef(null);

    const noop = useCallback(() => {}, []);
    const log = useCallback((msg, level) => console.log(`[Review] ${level}: ${msg}`), []);

    const {
        segments, project, loading, setSegments,
        handleSave, handleToggleFlag, handleToggleLock, handleToggleSkip, handlePropagate,
    } = useProjectData(projectId, { log, setActiveSegmentId: noop, queueSegments: null });

    const chat = useSegmentChat(projectId);

    const activeSegment = segments[activeIndex] || null;

    // Auto-scroll to first non-reviewed segment on initial load
    const initialScrollDone = useRef(false);
    useEffect(() => {
        if (initialScrollDone.current || segments.length === 0) return;
        initialScrollDone.current = true;
        const firstUnreviewed = segments.findIndex(s => !s.metadata?.reviewed && !s.metadata?.propagation_lock && !s.metadata?.skip);
        if (firstUnreviewed > 0) setActiveIndex(firstUnreviewed);
    }, [segments.length]);

    // Scroll active segment into view
    useEffect(() => {
        if (!activeSegment) return;
        const el = segmentRefs.current[activeIndex];
        if (el) el.scrollIntoView({ behavior: 'smooth', block: 'center' });
    }, [activeIndex, activeSegment?.id]);

    // Auto-focus editor when modal opens
    useEffect(() => {
        if (editModalOpen && modalEditorRef.current) {
            setTimeout(() => modalEditorRef.current.commands?.focus('end'), 100);
        }
    }, [editModalOpen]);

    // Move active index
    const moveActive = useCallback((delta) => {
        setActiveIndex(prev => {
            const next = prev + delta;
            if (next < 0 || next >= segments.length) return prev;
            return next;
        });
    }, [segments.length]);

    // Find next segment that needs review (skip propagation_lock)
    const findNextReviewable = useCallback((fromIndex) => {
        for (let i = fromIndex + 1; i < segments.length; i++) {
            const m = segments[i].metadata;
            if (!m?.propagation_lock && !m?.skip) return i;
        }
        return Math.min(fromIndex + 1, segments.length - 1);
    }, [segments]);

    // Mark current segment as reviewed and advance to next reviewable
    const markReviewedAndAdvance = useCallback(async () => {
        const seg = segments[activeIndex];
        if (!seg) return;
        // Optimistic update
        setSegments(prev => prev.map(s =>
            s.id === seg.id ? { ...s, metadata: { ...(s.metadata || {}), reviewed: true } } : s
        ));
        // Persist
        try {
            await updateSegment(seg.id, undefined, undefined, { reviewed: true });
        } catch (err) {
            console.error('Failed to mark reviewed', err);
        }
        // Advance to next reviewable segment
        const next = findNextReviewable(activeIndex);
        setActiveIndex(next);
    }, [activeIndex, segments, setSegments, findNextReviewable]);

    // Keyboard navigation
    useEffect(() => {
        const handler = (e) => {
            if (editModalOpen) {
                if (e.key === 'Escape') {
                    e.preventDefault();
                    setEditModalOpen(false);
                }
                return;
            }
            // Cmd+Option+ArrowDown = mark reviewed + advance
            if (e.key === 'ArrowDown' && e.metaKey && e.altKey) {
                e.preventDefault();
                markReviewedAndAdvance();
                return;
            }
            if (e.key === 'ArrowDown') { e.preventDefault(); moveActive(1); }
            if (e.key === 'ArrowUp') { e.preventDefault(); moveActive(-1); }
            if (e.key === 'ArrowRight') { e.preventDefault(); setEditModalOpen(true); }
        };
        document.addEventListener('keydown', handler);
        return () => document.removeEventListener('keydown', handler);
    }, [editModalOpen, moveActive, markReviewedAndAdvance]);

    // Progress calculation — based on reviewed count
    const reviewedCount = segments.filter(s => s.metadata?.reviewed).length;
    const progress = segments.length > 0
        ? Math.round(reviewedCount / segments.length * 100)
        : 0;

    if (loading) {
        return <div className="h-screen flex items-center justify-center text-gray-400">Loading...</div>;
    }

    return (
        <div className="h-screen flex flex-col bg-gray-50">
            {/* Top Bar */}
            <div className="bg-white border-b border-gray-200 px-6 py-3 flex items-center justify-between flex-shrink-0">
                <div className="flex items-center gap-4">
                    <button onClick={onBack} className="text-gray-400 hover:text-gray-700 transition-colors">
                        <ArrowLeft size={20} />
                    </button>
                    <h1 className="text-sm font-medium text-gray-700">{project?.name || project?.filename || 'Project'}</h1>
                    <span className="px-2 py-0.5 text-xs font-semibold rounded-full bg-blue-100 text-blue-800">review</span>
                </div>
                <div className="flex items-center gap-3">
                    <div className="w-32 bg-gray-200 rounded-full h-2">
                        <div className="bg-indigo-500 h-2 rounded-full transition-all" style={{ width: `${progress}%` }} />
                    </div>
                    <span className="text-xs text-gray-500">{reviewedCount}/{segments.length}</span>
                </div>
            </div>

            {/* Segment Reading View */}
            <div ref={scrollRef} className="flex-1 overflow-y-auto py-12">
                <div className="max-w-2xl mx-auto px-4">
                    {segments.map((seg, idx) => {
                        const isActive = idx === activeIndex;
                        const target = stripTags(seg.target_content);
                        const source = stripTags(seg.source_content);
                        const isEmpty = !target;
                        const isManualLocked = seg.metadata?.locked;
                        const isPropLocked = seg.metadata?.propagation_lock;
                        const isLocked = isManualLocked || isPropLocked;
                        const isSkipped = seg.metadata?.skip;
                        const isReviewed = seg.metadata?.reviewed;

                        if (isActive) {
                            return (
                                <div
                                    key={seg.id}
                                    ref={el => segmentRefs.current[idx] = el}
                                    className="flex items-center gap-3 my-4"
                                >
                                    {/* Lock/Skip/Reviewed indicator */}
                                    <div className="w-5 flex-shrink-0 flex flex-col items-center gap-1">
                                        {isReviewed && <Check size={12} className="text-green-400" />}
                                        {isManualLocked && <Lock size={12} className="text-gray-300" />}
                                        {isPropLocked && !isManualLocked && <Lock size={12} className="text-blue-300" />}
                                        {isSkipped && !isLocked && <SkipForward size={12} className="text-orange-300" />}
                                    </div>

                                    {/* Active Card */}
                                    <div
                                        className="flex-1 border border-indigo-200 rounded-lg shadow-sm bg-white p-5 cursor-pointer"
                                        onClick={() => setEditModalOpen(true)}
                                    >
                                        <div className="text-gray-400 text-sm leading-relaxed">{source || '(no source)'}</div>
                                        <hr className="my-3 border-gray-200" />
                                        <div className={`text-base leading-relaxed ${isEmpty ? 'text-gray-300 italic' : 'text-gray-800'}`}>
                                            {target || '(empty)'}
                                        </div>
                                    </div>

                                    {/* Edit button */}
                                    <button
                                        onClick={() => setEditModalOpen(true)}
                                        className="flex-shrink-0 text-indigo-300 hover:text-indigo-600 transition-colors p-1"
                                        title="Edit segment (Arrow Right)"
                                    >
                                        <ChevronsRight size={20} />
                                    </button>
                                </div>
                            );
                        }

                        return (
                            <div
                                key={seg.id}
                                ref={el => segmentRefs.current[idx] = el}
                                className="flex items-center gap-3"
                            >
                                {/* Lock/Skip/Reviewed indicator */}
                                <div className="w-5 flex-shrink-0 flex flex-col items-center gap-1">
                                    {isReviewed && <Check size={12} className="text-green-400" />}
                                    {isLocked && <Lock size={12} className="text-gray-300" />}
                                    {isSkipped && !isLocked && <SkipForward size={12} className="text-orange-300" />}
                                </div>

                                <div
                                    onClick={() => setActiveIndex(idx)}
                                    className={`flex-1 py-2 cursor-pointer text-base leading-relaxed transition-colors hover:text-gray-900 ${
                                        isEmpty ? 'text-gray-300 italic' : 'text-gray-600'
                                    }`}
                                >
                                    {target || '(empty)'}
                                </div>

                                {/* Spacer to align with active card's edit button */}
                                <div className="w-7 flex-shrink-0" />
                            </div>
                        );
                    })}
                </div>
            </div>

            {/* Edit Modal */}
            {editModalOpen && activeSegment && (
                <div className="fixed inset-0 z-50 bg-black/40 flex items-center justify-center" onClick={() => setEditModalOpen(false)}>
                    <div
                        className="bg-white rounded-2xl shadow-2xl w-[92vw] max-w-5xl max-h-[85vh] flex flex-col overflow-hidden"
                        onClick={e => e.stopPropagation()}
                    >
                        {/* Modal Header */}
                        <div className="flex items-center justify-between px-5 py-3 border-b border-gray-100 flex-shrink-0">
                            <button
                                onClick={() => setEditModalOpen(false)}
                                className="text-gray-400 hover:text-gray-700 transition-colors"
                                title="Close (Escape)"
                            >
                                <X size={20} />
                            </button>
                            <span className="text-xs text-gray-400 font-mono">
                                Segment #{activeSegment.index + 1}
                            </span>
                            <button
                                onClick={() => setShowChat(!showChat)}
                                className={`text-xs px-2 py-1 rounded transition-colors ${
                                    showChat ? 'bg-indigo-100 text-indigo-700' : 'bg-gray-100 text-gray-500 hover:bg-gray-200'
                                }`}
                            >
                                Chat
                            </button>
                        </div>

                        {/* Modal Body */}
                        <div className="flex-1 flex overflow-hidden">
                            {/* Segment Editor */}
                            <div className="flex-1 overflow-y-auto p-4">
                                <SegmentRow
                                    segment={activeSegment}
                                    project={project}
                                    generatingSegments={{}}
                                    flashingSegments={{}}
                                    showDebug={false}
                                    onAiDraft={noop}
                                    onToggleFlag={handleToggleFlag}
                                    onToggleLock={handleToggleLock}
                                    onToggleSkip={handleToggleSkip}
                                    onPropagate={handlePropagate}
                                    onSave={handleSave}
                                    onFocus={noop}
                                    onNavigate={(id, dir) => {
                                        setEditModalOpen(false);
                                        moveActive(dir === 'next' ? 1 : -1);
                                    }}
                                    onContextMenu={noop}
                                    registerEditor={(id, ed) => { modalEditorRef.current = ed; }}
                                    onGlossaryUpdate={noop}
                                />
                            </div>

                            {/* Chat Panel */}
                            {showChat && (
                                <div className="w-80 border-l border-gray-200 flex-shrink-0">
                                    <ChatPanel
                                        segment={activeSegment}
                                        messages={chat.getMessages(activeSegment.id)}
                                        isLoading={chat.isLoading}
                                        onSendMessage={(segId, msg) => chat.sendMessage(segId, msg)}
                                        onClearChat={() => chat.clearChat(activeSegment.id)}
                                        onClose={() => setShowChat(false)}
                                    />
                                </div>
                            )}
                        </div>
                    </div>
                </div>
            )}
        </div>
    );
}

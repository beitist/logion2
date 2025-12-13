import React, { useEffect } from 'react'
import { useEditor, EditorContent } from '@tiptap/react'
import StarterKit from '@tiptap/starter-kit'
import Link from '@tiptap/extension-link'
import Underline from '@tiptap/extension-underline'
import { Node, Extension, mergeAttributes } from '@tiptap/core'

import './TiptapStyles.css';

// Custom Node for Tags (Atom/Inline)
// This represents a single tag marker (Start OR End is determined by context)
const TagNode = Node.create({
    name: 'tag',
    group: 'inline',
    inline: true,
    atom: true, // It is a single unit

    addAttributes() {
        return {
            id: {
                default: null,
                parseHTML: element => element.getAttribute('data-id'),
                renderHTML: attributes => {
                    return {
                        'data-id': attributes.id,
                        'data-type': 'tag-node', // marker for parsing
                        'class': `tag-node tag-node-${attributes.id}`,
                    }
                },
            },
            label: {
                default: '?',
                parseHTML: element => element.getAttribute('data-label'),
                renderHTML: attributes => {
                    return {
                        'data-label': attributes.label,
                        // CSS var for content
                        'style': `--tag-label: "${attributes.label}"`
                    }
                },
            }
        }
    },

    parseHTML() {
        return [
            {
                tag: 'span[data-type="tag-node"]',
            },
        ]
    },

    renderHTML({ HTMLAttributes }) {
        return ['span', mergeAttributes(this.options.HTMLAttributes, HTMLAttributes)]
    },
})

const MenuBar = ({ editor, availableTags, onAiDraft }) => {
    if (!editor) {
        return null
    }

    return (
        <div className="flex flex-wrap items-center gap-1 p-2 border-b border-gray-200 bg-gray-50 rounded-t-md">
            {/* AI Action Button */}
            {onAiDraft && (
                <>
                    <button
                        onClick={onAiDraft}
                        className="px-3 py-1 text-xs font-bold rounded border bg-indigo-50 text-indigo-700 border-indigo-200 hover:bg-indigo-100 flex items-center gap-1 mr-2"
                        title="Generate AI Draft (Ctrl+Space)"
                    >
                        <span>🪄</span>
                        <span>AI Draft</span>
                    </button>
                    <div className="w-px h-4 bg-gray-300 mx-1"></div>
                </>
            )}

            {/* Tag Buttons: INSERT NODE */}
            {/* 1. Generic Tab Button (if any available) */}
            {availableTags && Object.values(availableTags).some(t => t.type === 'tab') && (
                <button
                    onClick={() => editor.chain().focus().insertContent({ type: 'tag', attrs: { id: 'TAB', label: 'TAB' } }).run()}
                    onMouseDown={(e) => e.preventDefault()}
                    className="px-2 py-1 text-xs font-mono rounded border bg-gray-100 text-gray-700 border-gray-300 hover:bg-gray-200 active:bg-gray-300 min-w-[24px] font-bold"
                    title="Insert Tab (Auto-mapped)"
                >
                    ⇥
                </button>
            )}

            {/* 2. Specific ID Buttons (excluding Tabs and Comments) */}
            {availableTags && Object.keys(availableTags).map(tid => {
                const tag = availableTags[tid];
                if (!tag) return null;

                // Only skip 'tab' (generic button) and 'comment' (not needed as button)
                // We SHOW bold/italic/underline as chips because the user expects them as numbered tags.
                if (['tab', 'comment'].includes(tag.type)) return null;

                // Determine Label
                let label = tid;
                let display = tid;
                let title = `Tag ${tid}`;

                return (
                    <button
                        key={tid}
                        onClick={() => editor.chain().focus().insertContent({ type: 'tag', attrs: { id: tid, label: label } }).run()}
                        onMouseDown={(e) => e.preventDefault()}
                        className="px-2 py-1 text-xs font-mono rounded border bg-white text-gray-600 border-gray-300 hover:bg-blue-50 active:bg-blue-100 min-w-[24px]"
                        title={title}
                    >
                        {display}
                    </button>
                )
            })}

            {!availableTags && <span className="text-xs text-gray-400">No tags</span>}
        </div>
    )
}

export function TiptapEditor({ content, onUpdate, segmentId, onSave, isReadOnly, availableTags, contextMatches, aiSettings, onAiDraft }) {
    const aiSettingsRef = React.useRef(aiSettings);
    const onAiDraftRef = React.useRef(onAiDraft);
    const contextMatchesRef = React.useRef(contextMatches);

    useEffect(() => {
        aiSettingsRef.current = aiSettings;
        onAiDraftRef.current = onAiDraft;
        contextMatchesRef.current = contextMatches;
    }, [aiSettings, onAiDraft, contextMatches]);

    const editor = useEditor({
        extensions: [
            StarterKit,
            Underline,
            Link.configure({
                openOnClick: false,
                HTMLAttributes: {
                    class: 'text-blue-500 underline cursor-pointer',
                },
            }),
            TagNode,
            Extension.create({
                addKeyboardShortcuts() {
                    return {
                        'Mod-Alt-0': () => {
                            const matches = contextMatchesRef.current;
                            const mtMatch = matches?.find(m => m.type === 'mt');
                            if (mtMatch) {
                                return this.editor.commands.setContent(mtMatch.content)
                            }
                            return false;
                        },
                        'Mod-Alt-9': () => {
                            const matches = contextMatchesRef.current;
                            // Filter out MT for numeric shortcuts to keep 0 distinct
                            const refs = matches?.filter(m => m.type !== 'mt') || [];
                            if (refs[0]) {
                                return this.editor.commands.setContent(refs[0].content)
                            }
                            return false
                        },
                        'Mod-Alt-8': () => {
                            const matches = contextMatchesRef.current;
                            const refs = matches?.filter(m => m.type !== 'mt') || [];
                            if (refs[1]) {
                                return this.editor.commands.setContent(refs[1].content)
                            }
                            return false
                        },
                        'Mod-Alt-7': () => {
                            const matches = contextMatchesRef.current;
                            const refs = matches?.filter(m => m.type !== 'mt') || [];
                            if (refs[2]) {
                                return this.editor.commands.setContent(refs[2].content)
                            }
                            return false
                        },
                        'Mod-Alt-ü': () => {
                            // Explicit MT shortcut "Get AI Translation"
                            if (onAiDraftRef.current && segmentId) {
                                onAiDraftRef.current(segmentId).then((newContent) => {
                                    if (newContent) {
                                        this.editor.commands.setContent(newContent);
                                    }
                                });
                                return true;
                            }
                            return false;
                        },
                        'Control-Space': () => {
                            // Easier shortcut for AI Draft
                            if (onAiDraftRef.current && segmentId) {
                                onAiDraftRef.current(segmentId).then((newContent) => {
                                    if (newContent) {
                                        this.editor.commands.setContent(newContent);
                                    }
                                });
                                return true;
                            }
                            return false;
                        },
                        'Mod-Enter': () => {
                            if (onSave && segmentId) {
                                onSave(segmentId, this.editor.getHTML())
                                return true
                            }
                            return false
                        }
                    }
                }
            })
        ],
        content: content || "",
        editable: !isReadOnly,
        onUpdate: ({ editor }) => {
            if (onUpdate) onUpdate(editor.getHTML());
        },
        onFocus: ({ editor }) => {
            // Auto-Trigger AI Draft if empty (User Request)
            if (editor.isEmpty && onAiDraftRef.current && segmentId) {
                console.log("Auto-triggering AI Draft on focus...");
                // Visual feedback? The Magic Wand button handles it nicely.
                onAiDraftRef.current(segmentId).then((newContent) => {
                    if (newContent && editor.isEmpty) { // Check empty again to be safe
                        editor.commands.setContent(newContent);
                    }
                });
            }
        },
        onBlur: ({ editor }) => {
            if (onSave && segmentId) {
                onSave(segmentId, editor.getHTML())
            }
        },
    })


    // Update content if it changes externally
    // Note: 'content' passed here MUST be hydrated HTML with <span data-type="tag-node"> already!
    useEffect(() => {
        if (editor && content && content !== editor.getHTML()) {
            editor.commands.setContent(content)
        }
    }, [content, editor])

    if (!editor) {
        return null
    }

    return (
        <div className={`prose max-w-none border rounded-md transition-shadow relative group/editor ${isReadOnly
            ? 'bg-gray-50 text-gray-700 border-gray-200'
            : 'bg-white border-gray-300 focus-within:border-blue-500 focus-within:ring-2 focus-within:ring-blue-100 shadow-sm'
            }`}>
            {!isReadOnly && <MenuBar editor={editor} availableTags={availableTags} onAiDraft={() => onAiDraft && segmentId ? onAiDraft(segmentId) : null} />}
            <EditorContent editor={editor} className="min-h-[100px] outline-none p-4" />
        </div>
    )
}

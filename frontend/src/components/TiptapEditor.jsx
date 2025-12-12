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

const MenuBar = ({ editor, availableTags }) => {
    if (!editor) {
        return null
    }

    return (
        <div className="flex flex-wrap items-center gap-1 p-2 border-b border-gray-200 bg-gray-50 rounded-t-md">
            {console.log("MenuBar Tags:", availableTags)}
            {/* Standard Formatting Buttons Removed per User Request ("Lieber Chips") */}

            {/* Tag Buttons: INSERT NODE */}

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

    useEffect(() => {
        aiSettingsRef.current = aiSettings;
        onAiDraftRef.current = onAiDraft;
    }, [aiSettings, onAiDraft]);

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
                        'Alt-1': () => {
                            if (contextMatches && contextMatches[0]) {
                                return this.editor.commands.insertContent(contextMatches[0].content + " ")
                            }
                            return false
                        },
                        'Alt-2': () => {
                            if (contextMatches && contextMatches[1]) {
                                return this.editor.commands.insertContent(contextMatches[1].content + " ")
                            }
                            return false
                        },
                        'Alt-3': () => {
                            if (contextMatches && contextMatches[2]) {
                                return this.editor.commands.insertContent(contextMatches[2].content + " ")
                            }
                            return false
                        },
                        'Mod-j': () => {
                            const enabled = aiSettingsRef.current?.enable_shortcut;
                            // console.log("Mod-J triggered. Enabled:", enabled);
                            if (enabled && onAiDraftRef.current && segmentId) {
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
        onBlur: ({ editor }) => {
            // Optional: Save on blur
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
            {!isReadOnly && <MenuBar editor={editor} availableTags={availableTags} />}
            <EditorContent editor={editor} className="min-h-[100px] outline-none p-4" />
        </div>
    )
}

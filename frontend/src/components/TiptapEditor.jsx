import React, { useEffect } from 'react'
import { useEditor, EditorContent } from '@tiptap/react'
import StarterKit from '@tiptap/starter-kit'
import Link from '@tiptap/extension-link'
import Underline from '@tiptap/extension-underline'
import { Node, mergeAttributes } from '@tiptap/core'

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
            <button
                onClick={() => editor.chain().focus().toggleBold().run()}
                className={`px-2 py-1 text-sm rounded hover:bg-gray-200 ${editor.isActive('bold') ? 'bg-gray-200 font-bold' : ''}`}
                title="Bold"
            >
                B
            </button>
            <button
                onClick={() => editor.chain().focus().toggleItalic().run()}
                className={`px-2 py-1 text-sm italic rounded hover:bg-gray-200 ${editor.isActive('italic') ? 'bg-gray-200' : ''}`}
                title="Italic"
            >
                i
            </button>
            <button
                onClick={() => editor.chain().focus().toggleUnderline().run()}
                className={`px-2 py-1 text-sm underline rounded hover:bg-gray-200 ${editor.isActive('underline') ? 'bg-gray-200' : ''}`}
                title="Underline"
            >
                U
            </button>

            <div className="w-px h-4 bg-gray-300 mx-2"></div>

            {/* Tag Buttons: INSERT NODE */}
            {/* 1. Generic Tab Button (if any available) */}
            {availableTags && Object.values(availableTags).some(t => t.type === 'tab') && (
                <button
                    onClick={() => editor.chain().focus().insertContent({ type: 'tag', attrs: { id: 'TAB', label: 'TAB' } }).run()}
                    className="px-2 py-1 text-xs font-mono rounded border bg-gray-100 text-gray-700 border-gray-300 hover:bg-gray-200 active:bg-gray-300 min-w-[24px] font-bold"
                    title="Insert Tab (Auto-mapped)"
                >
                    ⇥
                </button>
            )}

            {/* 2. Specific ID Buttons (excluding Tabs and Formatters) */}
            {availableTags && Object.keys(availableTags).map(tid => {
                const tag = availableTags[tid];

                // Skip formatting tags (handled by B/I/U buttons)
                if (tag.type === 'bold' || tag.type === 'italic' || tag.type === 'underline') return null;
                // Skip Tabs (handled by generic button)
                if (tag.type === 'tab') return null;

                // Determine Label
                let label = tid;
                let display = tid;
                let title = `Tag ${tid}`;

                if (tag.type === 'comment') {
                    label = '💬'; // Or 'C'
                    display = '💬';
                    title = 'Insert Comment Tag';
                }

                return (
                    <button
                        key={tid}
                        onClick={() => editor.chain().focus().insertContent({ type: 'tag', attrs: { id: tid, label: label } }).run()}
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

export function TiptapEditor({ content, onUpdate, segmentId, onSave, isReadOnly, availableTags }) {
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
        ],
        content: content || "",
        editable: !isReadOnly,
        onUpdate: ({ editor }) => {
            if (onUpdate) onUpdate(editor.getHTML());
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
            {!isReadOnly && <MenuBar editor={editor} availableTags={availableTags} />}
            <EditorContent editor={editor} className="min-h-[100px] outline-none p-4" />
        </div>
    )
}

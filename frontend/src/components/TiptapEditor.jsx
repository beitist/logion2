import React, { useEffect } from 'react'
import { useEditor, EditorContent, BubbleMenu } from '@tiptap/react'
import StarterKit from '@tiptap/starter-kit'
import Link from '@tiptap/extension-link'
import Underline from '@tiptap/extension-underline'
import { Mark, mergeAttributes } from '@tiptap/core'

import './TiptapStyles.css'; // We'll create this for the pseudo-elements

// Custom Mark for Tags
const TagMark = Mark.create({
    name: 'tagMark',

    addOptions() {
        return {
            HTMLAttributes: {},
        }
    },

    addAttributes() {
        return {
            tagId: {
                default: null,
                parseHTML: element => element.getAttribute('data-tag-id'),
                renderHTML: attributes => {
                    return {
                        'data-tag-id': attributes.tagId,
                        // Add class for styling
                        'class': `tag-mark tag-mark-${attributes.tagId}`,
                        'style': `--tag-label: "${attributes.tagId}"`
                        // We use CSS variable to pass content to pseudo-element!
                    }
                },
            },
        }
    },

    parseHTML() {
        return [
            {
                tag: 'span[data-tag-id]',
            },
        ]
    },

    renderHTML({ HTMLAttributes }) {
        return ['span', mergeAttributes(this.options.HTMLAttributes, HTMLAttributes), 0]
    },
})

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
            TagMark,
        ],
        content: content || "", // We might need to parse initial content to apply marks if passing raw <1>... strings? 
        // Logic Gap: If content comes as "Text <1>Bold</1>", Tiptap sees text.
        // We need a Deserializer to convert "<N>...</N>" string into TagMark?
        // OR rely on User to re-tag.
        // For MVP, existing chips are text <1>. 
        // Improving Deserialization is a "Nice to Have" but user is asking for INPUT.
        // Assuming user types fresh or we implement hydration later.

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
    useEffect(() => {
        if (editor && content && content !== editor.getHTML()) {
            // TODO: If we want to support showing existing tags as marks, we need to PARSE 'content' 
            // and replace <1>...</1> patterns with <span data-tag-id="1">...</span> BEFORE setting content.
            // Let's do a quick regex replacement here to "Hydrate" existing tags into Marks!

            // Regex to match <N>content</N>
            // Note: Nested tags might break with simple regex.
            // But basic ones work.
            let hydrated = content;
            // Loop to replace <(\d+)>(.*?)</\1> with <span data-tag-id="$1">$2</span>
            // We need a loop for nesting logic or just simple replace for non-nested.
            // Let's rely on standard HTML behavior? No, <1> is invalid HTML, Tiptap strips it or keeps as text.
            // Tiptap StarterKit likely treats <1> as text.

            // Replace <N>...</N> with <span data-tag-id="N">...</span>
            // We do this responsibly.
            // Actually, we must be careful not to break HTML.
            // Let's skip hydration complexity in this step to avoid breaking existing workflow 
            // unless user explicitly asked to "see" existing tags as chips in input.
            // User asked for INPUT support. 
            // existing content is displayed as text <1>.

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
            {/* Bubble Menu */}
            {editor && !isReadOnly && (
                <BubbleMenu editor={editor} tippyOptions={{ duration: 100 }} className="flex bg-white shadow-lg border border-gray-200 rounded divide-x divide-gray-200 overflow-hidden">
                    <button
                        onClick={() => editor.chain().focus().toggleBold().run()}
                        className={`px-3 py-1 text-sm hover:bg-gray-100 ${editor.isActive('bold') ? 'bg-gray-100 font-bold' : ''}`}
                    >
                        B
                    </button>
                    <button
                        onClick={() => editor.chain().focus().toggleItalic().run()}
                        className={`px-3 py-1 text-sm italic hover:bg-gray-100 ${editor.isActive('italic') ? 'bg-gray-100' : ''}`}
                    >
                        i
                    </button>
                    <button
                        onClick={() => editor.chain().focus().toggleUnderline().run()}
                        className={`px-3 py-1 text-sm underline hover:bg-gray-100 ${editor.isActive('underline') ? 'bg-gray-100' : ''}`}
                    >
                        U
                    </button>

                    {/* Tag Buttons */}
                    {availableTags && Object.keys(availableTags).map(tid => (
                        <button
                            key={tid}
                            onClick={() => editor.chain().focus().toggleMark('tagMark', { tagId: tid }).run()}
                            className={`px-3 py-1 text-sm font-mono hover:bg-blue-50 text-blue-600 ${editor.isActive('tagMark', { tagId: tid }) ? 'bg-blue-100 ring-inset ring-1 ring-blue-200' : ''}`}
                            title={`Tag ${tid}`}
                        >
                            {tid}
                        </button>
                    ))}
                </BubbleMenu>
            )}

            <EditorContent editor={editor} className="min-h-[120px] outline-none p-4" />
        </div>
    )
}

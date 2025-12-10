import React, { useEffect } from 'react'
import { useEditor, EditorContent } from '@tiptap/react'
import StarterKit from '@tiptap/starter-kit'
import Link from '@tiptap/extension-link'
import Underline from '@tiptap/extension-underline'

// Placeholder for Tag Extension - for now we just let text render, 
// but we want to visualize <1> as chips later.
// For skeleton MVP, we allow editing text.

export function TiptapEditor({ content, onUpdate, segmentId, onSave, isReadOnly }) {
    const editor = useEditor({
        extensions: [
            StarterKit,
            Underline,
            Link,
        ],
        content: content || "",
        editable: !isReadOnly,
        onUpdate: ({ editor }) => {
            // Local state update if needed
            if (onUpdate) onUpdate(editor.getHTML());
        },
        onBlur: ({ editor }) => {
            if (onSave && segmentId) {
                onSave(segmentId, editor.getHTML())
            }
        },
    })

    // Update content if it changes externally (e.g. initial load)
    useEffect(() => {
        if (editor && content && content !== editor.getHTML()) {
            editor.commands.setContent(content)
        }
    }, [content, editor])

    if (!editor) {
        return null
    }

    return (
        <div className={`prose max-w-none ${isReadOnly ? 'bg-gray-50 text-gray-700' : 'bg-white'}`}>
            <EditorContent editor={editor} className="min-h-[100px] outline-none p-2" />
        </div>
    )
}

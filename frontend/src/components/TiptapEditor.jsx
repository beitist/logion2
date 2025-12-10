import React, { useEffect } from 'react'
import { useEditor, EditorContent } from '@tiptap/react'
import StarterKit from '@tiptap/starter-kit'
import Link from '@tiptap/extension-link'
import Underline from '@tiptap/extension-underline'

// Placeholder for Tag Extension - for now we just let text render, 
// but we want to visualize <1> as chips later.
// For skeleton MVP, we allow editing text.

export function TiptapEditor({ content, onUpdate, isReadOnly }) {
    const editor = useEditor({
        extensions: [
            StarterKit,
            Underline,
            Link,
        ],
        content: content || "",
        editable: !isReadOnly,
        onUpdate: ({ editor }) => {
            // In a real app we'd debounce this
            // and sanitize back to tag format? 
            // Current architecture: "Review" updates status, save happens separately?
            // Spec says: PATCH /segment/{id} updates translation.
        },
    })

    // Update content if it changes externally (e.g. initial load)
    useEffect(() => {
        if (editor && content !== editor.getHTML()) {
            // Simple string comparison is dangerous with HTML but ok for init
            // editor.commands.setContent(content) 
            // Careful with loops.
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

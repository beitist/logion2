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
                        tabIndex="-1"
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
                    tabIndex="-1"
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
                        tabIndex="-1"
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
    const availableTagsRef = React.useRef(availableTags);

    useEffect(() => {
        aiSettingsRef.current = aiSettings;
        onAiDraftRef.current = onAiDraft;
        contextMatchesRef.current = contextMatches;
        availableTagsRef.current = availableTags;
    }, [aiSettings, onAiDraft, contextMatches, availableTags]);

    // Internal Helper: Hydrate raw XML tags <1> into Tiptap TagNodes
    // Duplicated simplified logic from SplitView to ensure self-contained editor behavior
    const hydrateContent = (content, tags) => {
        if (!content) return "";
        let hydrated = content;

        // 1. Pre-Pass: Handle Self-Contained Tabs <N>[TAB]</N>
        hydrated = hydrated.replace(/<(\d+)>\[TAB\]<\/\1>/g, (match, id) => {
            const tagInfo = tags ? tags[id] : null;
            if (tagInfo && tagInfo.type === 'tab') {
                return `<span data-type="tag-node" data-id="TAB" data-label="TAB"></span>`;
            }
            return match;
        });

        // 2. Standard Match <(\d+)> OR </(\d+)>
        hydrated = hydrated.replace(/<(\d+)>|<\/(\d+)>/g, (match, openId, closeId) => {
            const id = openId || closeId;
            const tagInfo = tags ? tags[id] : null;
            let label = id;
            let finalId = id;

            if (tagInfo) {
                if (tagInfo.type === 'tab') {
                    label = 'TAB';
                    finalId = 'TAB';
                }
                else if (tagInfo.type === 'comment') label = '💬';
            }
            return `<span data-type="tag-node" data-id="${finalId}" data-label="${label}"></span>`;
        });

        // 3. Handle [TAB] (Legacy/Fallback)
        hydrated = hydrated.replace(/\[TAB\]/g, `<span data-type="tag-node" data-id="TAB" data-label="TAB"></span>`);

        return hydrated;
    };

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
                                const hydrated = hydrateContent(mtMatch.content, availableTagsRef.current);
                                return this.editor.commands.setContent(hydrated)
                            }
                            return false;
                        },
                        'Mod-Alt-9': () => {
                            const matches = contextMatchesRef.current;
                            const refs = matches?.filter(m => m.type !== 'mt') || [];
                            if (refs[0]) {
                                const hydrated = hydrateContent(refs[0].content, availableTagsRef.current);
                                return this.editor.commands.setContent(hydrated)
                            }
                            return false
                        },
                        'Mod-Alt-8': () => {
                            const matches = contextMatchesRef.current;
                            const refs = matches?.filter(m => m.type !== 'mt') || [];
                            if (refs[1]) {
                                const hydrated = hydrateContent(refs[1].content, availableTagsRef.current);
                                return this.editor.commands.setContent(hydrated)
                            }
                            return false
                        },
                        'Mod-Alt-7': () => {
                            const matches = contextMatchesRef.current;
                            const refs = matches?.filter(m => m.type !== 'mt') || [];
                            if (refs[2]) {
                                const hydrated = hydrateContent(refs[2].content, availableTagsRef.current);
                                return this.editor.commands.setContent(hydrated)
                            }
                            return false
                        },
                        'Mod-Alt-ü': () => {
                            if (onAiDraftRef.current && segmentId) {
                                onAiDraftRef.current(segmentId).then((newContent) => {
                                    if (newContent) {
                                        const hydrated = hydrateContent(newContent, availableTagsRef.current);
                                        this.editor.commands.setContent(hydrated);
                                    }
                                });
                                return true;
                            }
                            return false;
                        },
                        // Context Refresh: Try multiple bindings for 'ß' to handle Mac/ISO behaviors
                        // Mac German: Option+ß often produces '¿' or '\' depending on layout versions.
                        'Mod-Alt-ß': () => {
                            console.log("Shortcut triggered: Mod-Alt-ß");
                            if (onAiDraftRef.current && segmentId) {
                                onAiDraftRef.current(segmentId);
                                return true;
                            }
                            return false;
                        },
                        'Mod-Alt-¿': () => {
                            console.log("Shortcut triggered: Mod-Alt-¿");
                            if (onAiDraftRef.current && segmentId) {
                                onAiDraftRef.current(segmentId);
                                return true;
                            }
                            return false;
                        },
                        'Mod-Alt-\\': () => {
                            console.log("Shortcut triggered: Mod-Alt-\\");
                            if (onAiDraftRef.current && segmentId) {
                                onAiDraftRef.current(segmentId);
                                return true;
                            }
                            return false;
                        },
                        // Case: User holds Shift (Cmd+Alt+Shift+ß -> ?)
                        'Mod-Alt-?': () => {
                            console.log("Shortcut triggered: Mod-Alt-?");
                            if (onAiDraftRef.current && segmentId) {
                                onAiDraftRef.current(segmentId);
                                return true;
                            }
                            return false;
                        },
                        'Mod-Alt-Shift-ß': () => {
                            console.log("Shortcut triggered: Mod-Alt-Shift-ß");
                            if (onAiDraftRef.current && segmentId) {
                                onAiDraftRef.current(segmentId);
                                return true;
                            }
                            return false;
                        },
                        'Control-Space': () => {
                            if (onAiDraftRef.current && segmentId) {
                                onAiDraftRef.current(segmentId).then((newContent) => {
                                    if (newContent) {
                                        const hydrated = hydrateContent(newContent, availableTagsRef.current);
                                        this.editor.commands.setContent(hydrated);
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
            }),
        ],
        content: content || "",
        editable: !isReadOnly,
        onUpdate: ({ editor }) => {
            if (onUpdate) onUpdate(editor.getHTML());
        },
        onFocus: ({ editor }) => {
            // Auto-Trigger AI Retrieval if empty (Fetcher only, no Insert)
            if (editor.isEmpty && segmentId) {
                // 1. Check if we already have data
                const existingMatches = contextMatchesRef.current;

                if (existingMatches && existingMatches.length > 0) {
                    // Already have matches, do nothing
                    // console.log("Matches already loaded.");
                }
                // 2. Otherwise trigger retrieval (SplitView handles the state update)
                else if (onAiDraftRef.current) {
                    console.log("Fetching context on focus...");
                    onAiDraftRef.current(segmentId);
                }
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

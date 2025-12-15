import React, { useEffect } from 'react'
import { useEditor, EditorContent } from '@tiptap/react'
import StarterKit from '@tiptap/starter-kit'
import Link from '@tiptap/extension-link'
import Underline from '@tiptap/extension-underline'
import InvisibleCharacters, { InvisibleCharacter, SpaceCharacter, HardBreakNode, ParagraphNode } from '@tiptap/extension-invisible-characters'
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


// Custom Invisible Character for Tabs
class TabCharacter extends InvisibleCharacter {
    constructor() {
        super({
            type: 'tab',
            predicate: char => char === '\t',
        })
    }

    render() {
        const span = document.createElement('span')
        span.classList.add('Tiptap-invisible-character', 'Tiptap-invisible-character--tab')
        // Allow selection/cursor interaction quirks if needed
        return span
    }
}

export function TiptapEditor({ content, onUpdate, segmentId, onSave, isReadOnly, availableTags, contextMatches, aiSettings, onAiDraft, onFocus, onNavigate, chromeless = false }) {
    const aiSettingsRef = React.useRef(aiSettings);
    const onAiDraftRef = React.useRef(onAiDraft);
    const contextMatchesRef = React.useRef(contextMatches);
    const availableTagsRef = React.useRef(availableTags);
    const onNavigateRef = React.useRef(onNavigate);

    useEffect(() => {
        aiSettingsRef.current = aiSettings;
        onAiDraftRef.current = onAiDraft;
        contextMatchesRef.current = contextMatches;
        availableTagsRef.current = availableTags;
        onNavigateRef.current = onNavigate;
    }, [aiSettings, onAiDraft, contextMatches, availableTags, onNavigate]);

    // ... hydrateContent ... (same)
    const hydrateContent = (content, tags) => { // ... (same)
        if (!content) return "";
        let hydrated = content;
        // 1. Pre-Pass: Handle Self-Contained Tabs <N>[TAB]</N>
        hydrated = hydrated.replace(/<(\d+)>\[TAB\]<\/\1>/g, (match, id) => {
            const tagInfo = tags ? tags[id] : null;
            if (tagInfo && tagInfo.type === 'tab') {
                return "\t";
            }
            return match;
        });
        // 2. Standard Match
        hydrated = hydrated.replace(/<(\d+)>|<\/(\d+)>/g, (match, openId, closeId) => {
            const id = openId || closeId;
            const tagInfo = tags ? tags[id] : null;
            let label = id;
            let finalId = id;
            if (tagInfo) {
                if (tagInfo.type === 'tab') {
                    // Suppress tab tags that weren't caught by pre-pass
                    return "";
                }
                else if (tagInfo.type === 'comment') label = '💬';
            }
            return `<span data-type="tag-node" data-id="${finalId}" data-label="${label}"></span>`;
        });
        // 3. Fallback
        hydrated = hydrated.replace(/\[TAB\]/g, "\t");
        return hydrated;
    };

    const editor = useEditor({
        parseOptions: {
            preserveWhitespace: 'full',
        },
        extensions: [
            StarterKit,
            Underline,
            Link.configure({
                openOnClick: false,
                HTMLAttributes: {
                    class: 'text-blue-500 underline cursor-pointer',
                },
            }),
            InvisibleCharacters.configure({
                injectCSS: true,
                builders: [
                    new SpaceCharacter(),
                    new HardBreakNode(),
                    new ParagraphNode(),
                    new TabCharacter(),
                ]
            }),
            TagNode,
            Extension.create({
                addKeyboardShortcuts() {
                    return {
                        // Navigation
                        'Mod-Alt-ArrowDown': () => {
                            if (onNavigateRef.current) {
                                onNavigateRef.current('next');
                                return true;
                            }
                            return false;
                        },
                        'Mod-Alt-ArrowUp': () => {
                            if (onNavigateRef.current) {
                                onNavigateRef.current('prev');
                                return true;
                            }
                            return false;
                        },
                        // Real Tab
                        'Tab': () => {
                            this.editor.commands.insertContent('\t');
                            return true;
                        },
                        'Mod-Alt-0': () => {
                            const matches = contextMatchesRef.current;
                            const mtMatch = matches?.find(m => m.type === 'mt');
                            if (mtMatch) {
                                const hydrated = hydrateContent(mtMatch.content, availableTagsRef.current);
                                return this.editor.commands.setContent(hydrated)
                            }
                            return false;
                        },
                        // ... (rest of shortcuts same) ...
                        'Mod-Alt-9': () => {
                            // ...
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
                        'Mod-Alt-ß': () => { if (onAiDraftRef.current && segmentId) { onAiDraftRef.current(segmentId); return true; } return false; },
                        'Mod-Alt-¿': () => { if (onAiDraftRef.current && segmentId) { onAiDraftRef.current(segmentId); return true; } return false; },
                        'Mod-Alt-\\': () => { if (onAiDraftRef.current && segmentId) { onAiDraftRef.current(segmentId); return true; } return false; },
                        'Mod-Alt-?': () => { if (onAiDraftRef.current && segmentId) { onAiDraftRef.current(segmentId); return true; } return false; },
                        'Mod-Alt-Shift-ß': () => { if (onAiDraftRef.current && segmentId) { onAiDraftRef.current(segmentId); return true; } return false; },
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
        editorProps: {
            attributes: {
                // Ensure chromeless editor has no min-height using Tailwind !min-h-0
                class: chromeless ? '!min-h-0' : '',
            }
        },
        onUpdate: ({ editor }) => {
            if (onUpdate) onUpdate(editor.getHTML());
        },
        onFocus: ({ editor }) => {
            if (onFocus) onFocus();
            if (editor.isEmpty && segmentId) {
                const existingMatches = contextMatchesRef.current;
                if (existingMatches && existingMatches.length > 0) { }
                else if (onAiDraftRef.current) {
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

    useEffect(() => {
        if (editor && content && content !== editor.getHTML()) {
            editor.commands.setContent(content)
        }
    }, [content, editor])

    if (!editor) {
        return null
    }

    // Styles for Chromeless Mode
    // If chromeless, we strip: border, shadow, background (inherit), padding
    const containerClasses = chromeless
        ? `prose max-w-none relative group/editor`
        : `prose max-w-none border rounded-md transition-shadow relative group/editor ${isReadOnly
            ? 'bg-gray-50 text-gray-700 border-gray-200'
            : 'bg-white border-gray-300 focus-within:border-blue-500 focus-within:ring-2 focus-within:ring-blue-100 shadow-sm'
        }`;

    const editorContentClasses = chromeless
        ? `outline-none` // No padding, no min-height (handled by editorProps !min-h-0)
        : `min-h-[100px] outline-none p-4`;

    return (
        <div id={`editor-${segmentId}`} className={containerClasses}>
            {!isReadOnly && !chromeless && <MenuBar editor={editor} availableTags={availableTags} onAiDraft={() => onAiDraft && segmentId ? onAiDraft(segmentId) : null} />}
            <EditorContent editor={editor} className={editorContentClasses} />
        </div>
    )
}

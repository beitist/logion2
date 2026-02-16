import React, { useEffect } from 'react'
import { useEditor, EditorContent } from '@tiptap/react'
import StarterKit from '@tiptap/starter-kit'
import Link from '@tiptap/extension-link'
import Underline from '@tiptap/extension-underline'
import InvisibleCharacters, { InvisibleCharacter, SpaceCharacter, HardBreakNode, ParagraphNode } from '@tiptap/extension-invisible-characters'
import { Node, Extension, mergeAttributes } from '@tiptap/core'

import './TiptapStyles.css';
import { getTagLabel, mergeAdjacentTags } from '../utils/tagUtils';

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
                    const lbl = getTagLabel(attributes.label);
                    return {
                        'data-label': lbl,
                        // CSS var for content
                        'style': `--tag-label: "${lbl}"`
                    }
                },
            },
            tagType: {
                default: 'unknown',
                parseHTML: element => element.getAttribute('data-tag-type'),
                renderHTML: attributes => ({
                    'data-tag-type': attributes.tagType,
                }),
            },
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
            {/* 1. Generic Tab Button REMOVED (User Request) */}
            {/* But we replace it with NBSP button? Or just add NBSP button next to it? */}
            {/* User requested to remove TAB button. Let's add NBSP instead. */}

            <button
                tabIndex="-1"
                onClick={() => editor.chain().focus().insertContent('\u00A0').run()}
                onMouseDown={(e) => e.preventDefault()}
                className="px-2 py-1 text-xs font-mono rounded border bg-gray-50 text-gray-500 border-gray-300 hover:bg-gray-100 active:bg-gray-200 min-w-[24px]"
                title="Insert Non-Breaking Space (Cmd+Opt+Ctrl+Space)"
            >
                ␣
            </button>

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

// Custom Invisible Character for NBSP
class NbspCharacter extends InvisibleCharacter {
    constructor() {
        super({
            type: 'nbsp',
            predicate: char => char === '\u00A0',
        })
    }

    render() {
        const span = document.createElement('span')
        span.classList.add('Tiptap-invisible-character', 'Tiptap-invisible-character--nbsp')
        span.innerHTML = '&nbsp;' // Render actual nbsp or visual? CSS usually handles visual.
        // Actually for visuals we might want a distinct marker like a small dot or circle.
        // But the extension usually uses CSS `::before` content.
        // We just need the class.
        return span
    }
}

export function TiptapEditor({ content, onUpdate, segmentId, onSave, isReadOnly, availableTags, contextMatches, aiSettings, onAiDraft, onFocus, onNavigate, onEditorReady, chromeless = false }) {
    const aiSettingsRef = React.useRef(aiSettings);
    const onAiDraftRef = React.useRef(onAiDraft);
    const contextMatchesRef = React.useRef(contextMatches);
    const availableTagsRef = React.useRef(availableTags);
    const onNavigateRef = React.useRef(onNavigate);
    const isSavingRef = React.useRef(false);
    const lastEmittedContent = React.useRef(content);

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
                // REMOVED: Speechbubble override for comments (User Request 1)
                // else if (tagInfo.type === 'comment') label = '💬';
            }
            return `<span data-type="tag-node" data-id="${finalId}" data-label="${label}" class="tag-node tag-node-${finalId}" style="--tag-label: '${label}'"></span>`;
        });

        // 3. Post-Pass: Merge Adjacent Tags (Combo Tags) (User Request 2)
        // We look for adjacent spans and merge them into one.
        // Example: <span id="1"></span><span id="2"></span> -> <span id="1,2"></span>
        // We do this loop until no more merges occur to handle N tags.
        // 3. Post-Pass: Merge Adjacent Tags (Combo Tags) (User Request 2)
        // Refactored to Utils
        hydrated = mergeAdjacentTags(hydrated);

        // 4. Fallback
        hydrated = hydrated.replace(/\[TAB\]/g, "\t");
        return hydrated;
    };

    const editor = useEditor({
        extensions: [
            StarterKit.configure({
                history: false, // We handle history manually or it conflicts with external state updates sometimes
            }),
            Link.configure({
                openOnClick: false,
                HTMLAttributes: {
                    class: 'text-blue-500 underline cursor-pointer',
                },
            }),
            Underline,
            // Custom Invisible Characters
            InvisibleCharacters.configure({
                injectCSS: false, // We use our own CSS
                builders: [
                    new SpaceCharacter(),
                    new HardBreakNode(),
                    new ParagraphNode(),
                    new TabCharacter(), // <--- Our custom tab
                    new NbspCharacter(), // <--- Our custom NBSP
                ]
            }),
            // Custom Tag Node
            TagNode,
            Extension.create({
                addKeyboardShortcuts() {
                    return {
                        // Navigation: Next Segment
                        'Mod-Alt-ArrowDown': () => { if (onNavigateRef.current) { onNavigateRef.current('next'); return true; } return false; },
                        'Mod-Control-Alt-ArrowDown': () => { if (onNavigateRef.current) { onNavigateRef.current('next'); return true; } return false; },
                        'Mod-Shift-ArrowDown': () => { if (onNavigateRef.current) { onNavigateRef.current('next'); return true; } return false; },

                        // Navigation: Prev Segment
                        'Mod-Alt-ArrowUp': () => { if (onNavigateRef.current) { onNavigateRef.current('prev'); return true; } return false; },
                        'Mod-Control-Alt-ArrowUp': () => { if (onNavigateRef.current) { onNavigateRef.current('prev'); return true; } return false; },
                        'Mod-Shift-ArrowUp': () => { if (onNavigateRef.current) { onNavigateRef.current('prev'); return true; } return false; },

                        // Real Tab
                        'Tab': () => {
                            this.editor.commands.insertContent('\t');
                            return true;
                        },

                        // NBSP Shortcut
                        'Mod-Control-Alt-Space': () => {
                            this.editor.commands.insertContent('\u00A0');
                            return true;
                        },

                        // --- INSERT MATCHES (Legacy: 0=MT, 9,8,7=Refs) ---
                        // 0. Mandatory / MT
                        'Mod-Alt-0': () => {
                            const matches = contextMatchesRef.current;
                            const mtMatch = matches?.find(m => m.type === 'mt');
                            const bestMatch = mtMatch || matches?.[0];

                            if (bestMatch) {
                                const hydrated = hydrateContent(bestMatch.content, availableTagsRef.current);
                                return this.editor.commands.setContent(hydrated, false, { preserveWhitespace: 'full' })
                            }
                            return false;
                        },

                        // 9. Match 1 (Ref)
                        'Mod-Alt-9': () => {
                            const matches = contextMatchesRef.current;
                            const refs = matches?.filter(m => m.type !== 'mt') || [];
                            if (refs[0]) {
                                const hydrated = hydrateContent(refs[0].content, availableTagsRef.current);
                                return this.editor.commands.setContent(hydrated, false, { preserveWhitespace: 'full' })
                            }
                            return false
                        },

                        // 8. Match 2 (Ref)
                        'Mod-Alt-8': () => {
                            const matches = contextMatchesRef.current;
                            const refs = matches?.filter(m => m.type !== 'mt') || [];
                            if (refs[1]) {
                                const hydrated = hydrateContent(refs[1].content, availableTagsRef.current);
                                return this.editor.commands.setContent(hydrated, false, { preserveWhitespace: 'full' })
                            }
                            return false
                        },

                        // 7. Match 3 (Ref)
                        'Mod-Alt-7': () => {
                            const matches = contextMatchesRef.current;
                            const refs = matches?.filter(m => m.type !== 'mt') || [];
                            if (refs[2]) {
                                const hydrated = hydrateContent(refs[2].content, availableTagsRef.current);
                                return this.editor.commands.setContent(hydrated, false, { preserveWhitespace: 'full' })
                            }
                            return false
                        },
                        'Mod-Alt-ü': () => {
                            if (onAiDraftRef.current && segmentId) {
                                onAiDraftRef.current(segmentId).then((newContent) => {
                                    if (newContent) {
                                        const hydrated = hydrateContent(newContent, availableTagsRef.current);
                                        this.editor.commands.setContent(hydrated, false, { preserveWhitespace: 'full' });
                                    }
                                });
                                return true;
                            }
                            return false;
                        },
                        'Mod-Alt-ß': () => {
                            if (onAiDraftRef.current && segmentId) {
                                const hasMT = contextMatchesRef.current?.some(m => m.type === 'mt');
                                const mode = hasMT ? "draft" : "translate";
                                onAiDraftRef.current(segmentId, false, mode);
                                return true;
                            }
                            return false;
                        },
                        'Mod-Alt-¿': () => { if (onAiDraftRef.current && segmentId) { onAiDraftRef.current(segmentId); return true; } return false; },
                        'Mod-Alt-\\': () => { if (onAiDraftRef.current && segmentId) { onAiDraftRef.current(segmentId); return true; } return false; },
                        'Mod-Alt-?': () => { if (onAiDraftRef.current && segmentId) { onAiDraftRef.current(segmentId); return true; } return false; },
                        'Mod-Alt-Shift-ß': () => { if (onAiDraftRef.current && segmentId) { onAiDraftRef.current(segmentId); return true; } return false; },
                        'Control-Space': () => {
                            if (onAiDraftRef.current && segmentId) {
                                onAiDraftRef.current(segmentId).then((newContent) => {
                                    if (newContent) {
                                        const hydrated = hydrateContent(newContent, availableTagsRef.current);
                                        this.editor.commands.setContent(hydrated, false, { preserveWhitespace: 'full' });
                                    }
                                });
                                return true;
                            }
                            return false;
                        },
                        'Mod-Alt-Enter': () => {
                            if (onSave && segmentId) {
                                // Block onBlur from firing a second save immediately
                                isSavingRef.current = true;
                                setTimeout(() => { isSavingRef.current = false; }, 500);

                                onSave(segmentId, this.editor.getHTML());

                                // User requested "Confirm & Next" behavior
                                if (onNavigateRef.current) {
                                    onNavigateRef.current('next');
                                }
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
        parseOptions: {
            preserveWhitespace: 'full', // Preserves \t characters
        },
        editorProps: {
            attributes: {
                // Ensure chromeless editor has no min-height using Tailwind !min-h-0
                class: chromeless ? '!min-h-0' : '',
            }
        },
        onUpdate: ({ editor }) => {
            const html = editor.getHTML();
            lastEmittedContent.current = html;
            if (onUpdate) onUpdate(html);
        },
        onFocus: ({ editor }) => {
            if (onFocus) onFocus();
            if (editor.isEmpty && segmentId) {
                const existingMatches = contextMatchesRef.current;
                if (existingMatches && existingMatches.length > 0) { }
                else if (onAiDraftRef.current) {
                    onAiDraftRef.current(segmentId).then(updated => {
                        // Explicitly apply draft if editor is still empty and focused
                        // This bypasses the useEffect Focus Guard.
                        if (updated && updated.target_content && editor.isEmpty) {
                            const hydrated = hydrateContent(updated.target_content, availableTagsRef.current);
                            editor.commands.setContent(hydrated, false, { preserveWhitespace: 'full' });
                        }
                    });
                }
            }
        },
        onBlur: ({ editor }) => {
            if (isSavingRef.current) return;
            if (onSave && segmentId) {
                onSave(segmentId, editor.getHTML())
            }
        },
    })

    useEffect(() => {
        if (editor) {
            if (onEditorReady) onEditorReady(editor);

            if (content && content !== editor.getHTML() && content !== lastEmittedContent.current) {
                // Focus Guard: Prevent external updates (e.g. from backend poller or MT refresh)
                // from overwriting the editor while the user is working.
                // EXCEPTION: If the editor is empty, we allow the update (Auto-Draft / Pre-Translate)
                if (!editor.isFocused || editor.isEmpty) {
                    editor.commands.setContent(content, false, { preserveWhitespace: 'full' });
                    lastEmittedContent.current = content;
                }
            }
        }
    }, [content, editor, onEditorReady])

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

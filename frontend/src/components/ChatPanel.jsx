import React, { useRef, useEffect, useState } from 'react';
import { X, Send, Trash2, MessageSquare, Loader2 } from 'lucide-react';

export function ChatPanel({ segment, messages, isLoading, onSendMessage, onClearChat, onClose }) {
    const [input, setInput] = useState('');
    const messagesEndRef = useRef(null);
    const textareaRef = useRef(null);

    // Auto-scroll to bottom on new messages
    useEffect(() => {
        messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
    }, [messages, isLoading]);

    // Focus textarea when segment changes (only if panel is visible)
    useEffect(() => {
        if (segment?.id) {
            setTimeout(() => textareaRef.current?.focus(), 100);
        }
    }, [segment?.id]);

    const handleSend = () => {
        if (!input.trim() || isLoading || !segment) return;
        onSendMessage(segment.id, input);
        setInput('');
    };

    const handleKeyDown = (e) => {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            handleSend();
        }
    };

    if (!segment) {
        return (
            <div className="h-full flex items-center justify-center text-gray-400 text-sm p-6 text-center">
                <div>
                    <MessageSquare size={24} className="mx-auto mb-2 text-gray-300" />
                    <p>Select a segment to start chatting.</p>
                </div>
            </div>
        );
    }

    const sourcePreview = (segment.source_content || '').replace(/<[^>]*>/g, '');
    const truncated = sourcePreview.length > 80 ? sourcePreview.substring(0, 80) + '...' : sourcePreview;

    return (
        <div className="h-full flex flex-col bg-white">
            {/* Header */}
            <div className="px-4 py-3 border-b border-gray-200 bg-gray-50 flex items-center justify-between flex-shrink-0">
                <div className="flex-1 min-w-0 mr-2">
                    <div className="flex items-center gap-2">
                        <MessageSquare size={14} className="text-indigo-500 flex-shrink-0" />
                        <span className="text-xs font-bold text-gray-700">
                            Segment #{(segment.index ?? 0) + 1}
                        </span>
                    </div>
                    <p className="text-[10px] text-gray-400 mt-0.5 truncate" title={sourcePreview}>
                        {truncated}
                    </p>
                </div>
                <div className="flex items-center gap-1 flex-shrink-0">
                    {messages.length > 0 && (
                        <button
                            onClick={() => onClearChat(segment.id)}
                            className="p-1.5 hover:bg-gray-200 rounded text-gray-400 hover:text-gray-600 transition-colors"
                            title="Clear chat"
                        >
                            <Trash2 size={14} />
                        </button>
                    )}
                    <button
                        onClick={onClose}
                        className="p-1.5 hover:bg-gray-200 rounded text-gray-400 hover:text-gray-600 transition-colors"
                        title="Close chat"
                    >
                        <X size={14} />
                    </button>
                </div>
            </div>

            {/* Messages */}
            <div className="flex-1 overflow-y-auto p-4 space-y-3">
                {messages.length === 0 && (
                    <div className="text-center text-gray-400 text-xs mt-8 space-y-2">
                        <MessageSquare size={24} className="mx-auto text-gray-300" />
                        <p>Ask about this segment's translation.</p>
                        <div className="text-[10px] text-gray-300 space-y-1">
                            <p>"Give me a more formal version"</p>
                            <p>"Why did you translate X as Y?"</p>
                            <p>"What does this term mean here?"</p>
                        </div>
                    </div>
                )}
                {messages.map((msg, idx) => (
                    <div
                        key={idx}
                        className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}
                    >
                        <div
                            className={`max-w-[85%] px-3 py-2 rounded-lg text-sm whitespace-pre-wrap ${
                                msg.role === 'user'
                                    ? 'bg-indigo-500 text-white rounded-br-sm'
                                    : msg.isError
                                        ? 'bg-red-50 text-red-700 border border-red-200 rounded-bl-sm'
                                        : 'bg-gray-100 text-gray-800 rounded-bl-sm'
                            }`}
                        >
                            {msg.content}
                            {msg.usage && (
                                <div className="text-[9px] mt-1 opacity-50">
                                    {msg.usage.input_tokens + msg.usage.output_tokens} tokens
                                </div>
                            )}
                        </div>
                    </div>
                ))}
                {isLoading && (
                    <div className="flex justify-start">
                        <div className="bg-gray-100 text-gray-500 px-3 py-2 rounded-lg rounded-bl-sm text-sm flex items-center gap-2">
                            <Loader2 size={14} className="animate-spin" />
                            Thinking...
                        </div>
                    </div>
                )}
                <div ref={messagesEndRef} />
            </div>

            {/* Input */}
            <div className="p-3 border-t border-gray-200 bg-gray-50 flex-shrink-0">
                <div className="flex items-end gap-2">
                    <textarea
                        ref={textareaRef}
                        value={input}
                        onChange={(e) => setInput(e.target.value)}
                        onKeyDown={handleKeyDown}
                        placeholder="Ask about this segment..."
                        rows={1}
                        className="flex-1 resize-none border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-200 focus:border-indigo-400 max-h-24 overflow-y-auto"
                        style={{ minHeight: '38px' }}
                        disabled={isLoading}
                    />
                    <button
                        onClick={handleSend}
                        disabled={!input.trim() || isLoading}
                        className="p-2 bg-indigo-500 text-white rounded-lg hover:bg-indigo-600 disabled:opacity-40 disabled:cursor-not-allowed transition-colors flex-shrink-0"
                        title="Send (Enter)"
                    >
                        <Send size={16} />
                    </button>
                </div>
            </div>
        </div>
    );
}

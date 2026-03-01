import { useState, useCallback, useRef } from 'react';
import { sendSegmentChat } from '../api/client';

export function useSegmentChat(projectId) {
    const [chatHistories, setChatHistories] = useState({});
    const [isLoading, setIsLoading] = useState(false);
    const historiesRef = useRef(chatHistories);
    historiesRef.current = chatHistories;

    const getMessages = useCallback((segmentId) => {
        return chatHistories[segmentId] || [];
    }, [chatHistories]);

    const sendMessage = useCallback(async (segmentId, userMessage) => {
        if (!userMessage.trim() || isLoading) return;

        const userMsg = { role: 'user', content: userMessage.trim(), timestamp: Date.now() };

        setChatHistories(prev => {
            const updated = { ...prev, [segmentId]: [...(prev[segmentId] || []), userMsg] };
            historiesRef.current = updated;
            return updated;
        });

        setIsLoading(true);

        try {
            const apiMessages = [...(historiesRef.current[segmentId] || [])].map(m => ({
                role: m.role,
                content: m.content,
            }));

            const response = await sendSegmentChat(projectId, segmentId, apiMessages);

            const assistantMsg = {
                role: 'assistant',
                content: response.reply,
                timestamp: Date.now(),
                usage: response.usage,
            };

            setChatHistories(prev => ({
                ...prev,
                [segmentId]: [...(prev[segmentId] || []), assistantMsg],
            }));
        } catch (err) {
            const errorMsg = {
                role: 'assistant',
                content: `Error: ${err.message}`,
                timestamp: Date.now(),
                isError: true,
            };
            setChatHistories(prev => ({
                ...prev,
                [segmentId]: [...(prev[segmentId] || []), errorMsg],
            }));
        } finally {
            setIsLoading(false);
        }
    }, [projectId, isLoading]);

    const clearChat = useCallback((segmentId) => {
        setChatHistories(prev => {
            const next = { ...prev };
            delete next[segmentId];
            return next;
        });
    }, []);

    return { getMessages, sendMessage, clearChat, isLoading };
}

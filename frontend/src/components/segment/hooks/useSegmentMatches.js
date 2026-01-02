import { useMemo } from 'react';

/**
 * Processes segment context matches for display.
 * 
 * Responsibilities:
 * 1. Extracts raw matches from segment (context_matches or metadata.context_matches)
 * 2. Injects AI draft as a synthetic 'mt' match if available
 * 3. Sorts matches: MT first, then by score descending
 * 4. Identifies mandatory match for UI highlighting
 * 
 * @param {Object} segment - The segment object containing context_matches and metadata
 * @returns {Object} { sortedMatches, tmMatches, mandatoryMatch, hasContext }
 */
export function useSegmentMatches(segment) {
    return useMemo(() => {
        // Extract raw matches from either location
        let rawMatches = segment.context_matches || segment.metadata?.context_matches || [];

        // Inject AI draft as a synthetic 'mt' (Machine Translation) match
        // This allows it to be displayed alongside TM matches in the UI
        const aiDraft = segment.metadata?.ai_draft;
        if (aiDraft) {
            const existingMT = rawMatches.find(m => m.type === 'mt');
            if (!existingMT) {
                rawMatches = [...rawMatches, {
                    type: 'mt',
                    content: aiDraft,
                    score: 0,  // MT doesn't have a similarity score
                    filename: segment.metadata.ai_model || 'AI',
                    model: segment.metadata.ai_model || 'AI'
                }];
            }
        }

        // Sort: MT first (always shown at top), then by score descending
        const sortedMatches = rawMatches.sort((a, b) => {
            if (a.type === 'mt') return -1;
            if (b.type === 'mt') return 1;
            return (b.score || 0) - (a.score || 0);
        });

        // Filter to only TM matches (non-MT) for shortcut key assignment
        const tmMatches = sortedMatches.filter(m => m.type !== 'mt');

        // Check for mandatory match with high score (98%+) for prominent UI indication
        const mandatoryMatch = sortedMatches.find(m => m.type === 'mandatory' && m.score >= 98);

        // Determine if context panel should be shown
        const hasContext = sortedMatches.length > 0 || !!segment.metadata?.ai_draft;

        return {
            sortedMatches,
            tmMatches,
            mandatoryMatch,
            isMandatoryContext: !!mandatoryMatch,
            hasContext
        };
    }, [segment.context_matches, segment.metadata?.context_matches, segment.metadata?.ai_draft, segment.metadata?.ai_model]);
}

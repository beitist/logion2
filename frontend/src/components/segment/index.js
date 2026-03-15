/**
 * Segment Components Module
 * 
 * Feature-based module for the translation segment row display.
 * Contains the main SegmentRow component and its sub-components.
 */

// Main component (orchestrator)
export { SegmentRow } from './SegmentRow';

// Sub-components (can be imported individually if needed)
export { SourceColumn } from './SourceColumn';
export { TargetColumn } from './TargetColumn';
export { MatchCard } from './MatchCard';
export { GlossaryCard } from './GlossaryCard';
export { SegmentBadges, SegmentTypeBadges } from './SegmentBadges';

// Hooks
export { useSegmentMatches } from './hooks/useSegmentMatches';

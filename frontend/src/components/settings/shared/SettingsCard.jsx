import React from 'react';

/**
 * Modern glassmorphism-style card wrapper for settings sections.
 * Features: Subtle gradient border, light backdrop blur, smooth hover shadow.
 * 
 * @param {React.ReactNode} children - Card content
 * @param {string} className - Additional CSS classes
 * @param {boolean} highlight - If true, uses accent color gradient
 */
export function SettingsCard({ children, className = '', highlight = false }) {
    // Gradient border effect achieved via a wrapper with gradient background
    // and inner div with solid background inset by 1px
    const gradientClass = highlight
        ? 'bg-gradient-to-br from-purple-500/20 via-indigo-500/20 to-blue-500/20'
        : 'bg-gradient-to-br from-gray-200/50 to-gray-300/30';

    return (
        <div className={`p-[1px] rounded-2xl ${gradientClass} shadow-sm hover:shadow-md transition-shadow duration-300`}>
            <div className={`bg-white/90 backdrop-blur-sm rounded-2xl p-5 ${className}`}>
                {children}
            </div>
        </div>
    );
}

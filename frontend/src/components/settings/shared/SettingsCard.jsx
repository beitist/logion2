import React from 'react';

/**
 * A sleek, high-density card component for settings.
 * Removes heavy gradients and large padding in favor of a clean, technical look.
 */
export const SettingsCard = ({ children, highlight = false, className = '' }) => {
    return (
        <div
            className={`
                bg-white rounded-lg border 
                ${highlight ? 'border-indigo-200' : 'border-gray-200'} 
                ${className}
            `}
        >
            {children}
        </div>
    );
};

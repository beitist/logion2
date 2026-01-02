import React from 'react';

/**
 * Modern animated toggle switch component (iOS-style).
 * Replaces boring checkboxes with a sleek sliding toggle.
 * 
 * @param {boolean} checked - Current toggle state
 * @param {function} onChange - Callback when toggled: (newValue) => void
 * @param {boolean} disabled - If true, toggle is non-interactive
 * @param {string} size - Toggle size: 'sm' | 'md' | 'lg' (default: 'md')
 * @param {string} accentColor - Tailwind color class for active state (default: 'bg-indigo-500')
 */
export function SettingsToggle({
    checked,
    onChange,
    disabled = false,
    size = 'md',
    accentColor = 'bg-indigo-500'
}) {
    // Size variants for the toggle track and knob
    const sizes = {
        sm: { track: 'w-8 h-4', knob: 'w-3 h-3', translate: 'translate-x-4' },
        md: { track: 'w-11 h-6', knob: 'w-5 h-5', translate: 'translate-x-5' },
        lg: { track: 'w-14 h-7', knob: 'w-6 h-6', translate: 'translate-x-7' }
    };

    const sizeConfig = sizes[size] || sizes.md;

    const handleClick = () => {
        if (!disabled) {
            onChange(!checked);
        }
    };

    return (
        <button
            type="button"
            role="switch"
            aria-checked={checked}
            disabled={disabled}
            onClick={handleClick}
            className={`
                relative inline-flex items-center rounded-full 
                transition-colors duration-200 ease-in-out
                focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-indigo-500
                ${sizeConfig.track}
                ${checked ? accentColor : 'bg-gray-200'}
                ${disabled ? 'opacity-50 cursor-not-allowed' : 'cursor-pointer'}
            `}
        >
            {/* Sliding knob */}
            <span
                className={`
                    inline-block rounded-full bg-white shadow-md
                    transform transition-transform duration-200 ease-in-out
                    ${sizeConfig.knob}
                    ${checked ? sizeConfig.translate : 'translate-x-0.5'}
                `}
            />
        </button>
    );
}

import React from 'react';

/**
 * Section header component for settings panels.
 * Provides consistent icon + title + description pattern.
 * 
 * @param {React.ComponentType} icon - Lucide icon component
 * @param {string} title - Section title
 * @param {string} description - Optional description text
 * @param {string} accentColor - Tailwind text color for icon (default: 'text-indigo-500')
 * @param {React.ReactNode} children - Section content
 */
export function SettingsSection({
    icon: Icon,
    title,
    description,
    accentColor = 'text-indigo-500',
    children
}) {
    return (
        <div className="space-y-4">
            {/* Header */}
            <div className="flex items-start gap-3">
                {Icon && (
                    <div className={`p-2 rounded-lg bg-gray-50 ${accentColor}`}>
                        <Icon size={18} />
                    </div>
                )}
                <div className="flex-1">
                    <h3 className="text-sm font-semibold text-gray-800">{title}</h3>
                    {description && (
                        <p className="text-xs text-gray-500 mt-0.5">{description}</p>
                    )}
                </div>
            </div>

            {/* Content */}
            <div className="pl-0 md:pl-11">
                {children}
            </div>
        </div>
    );
}

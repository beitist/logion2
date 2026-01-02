import React from 'react';

/**
 * A compact section header for settings.
 * Optimized for information density and speed.
 */
export const SettingsSection = ({ icon: Icon, title, description, accentColor = "text-gray-400", children, rightContent }) => {
    return (
        <div className="flex flex-col">
            <div className="flex items-start gap-3 p-3 border-b border-gray-100 bg-gray-50/50 rounded-t-lg">
                {Icon && (
                    <div className={`mt-0.5 ${accentColor}`}>
                        <Icon size={16} strokeWidth={2} />
                    </div>
                )}
                <div className="flex-1 min-w-0">
                    <h3 className="text-sm font-semibold text-gray-900 leading-tight flex items-center gap-2">
                        {title}
                        {rightContent}
                    </h3>
                    {description && (
                        <p className="text-xs text-gray-500 mt-0.5 leading-snug">{description}</p>
                    )}
                </div>
            </div>

            <div className="p-3">
                {children}
            </div>
        </div>
    );
};

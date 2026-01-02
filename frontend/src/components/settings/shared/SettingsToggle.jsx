import React from 'react';

/**
 * A compact, professional toggle switch.
 * Less "bouncy", more "functional".
 */
export const SettingsToggle = ({ enabled, onChange, label, description, size = "md", accentColor = "bg-indigo-600" }) => {

    // Size variants
    const sizes = {
        sm: { w: "w-7", h: "h-4", ball: "w-3 h-3", trans: "translate-x-3" },
        md: { w: "w-9", h: "h-5", ball: "w-3.5 h-3.5", trans: "translate-x-4" }
    };
    const s = sizes[size] || sizes.md;

    return (
        <div
            className="flex items-center justify-between gap-4 w-full cursor-pointer group"
            onClick={() => onChange(!enabled)}
        >
            <div className="flex-1">
                <div className="text-sm font-medium text-gray-700 group-hover:text-gray-900 transition-colors">
                    {label}
                </div>
                {description && (
                    <div className="text-xs text-gray-500 mt-0.5">
                        {description}
                    </div>
                )}
            </div>

            {/* Toggle Track */}
            <div
                className={`
                    relative rounded-full transition-colors duration-200 ease-in-out flex-shrink-0
                    ${s.w} ${s.h}
                    ${enabled ? accentColor : 'bg-gray-200'}
                `}
            >
                {/* Toggle Ball */}
                <div
                    className={`
                        absolute top-0.5 left-0.5 bg-white rounded-full shadow-sm transition-transform duration-200 ease-in-out
                        ${s.ball}
                        ${enabled ? s.trans : 'translate-x-0'}
                    `}
                />
            </div>
        </div>
    );
};

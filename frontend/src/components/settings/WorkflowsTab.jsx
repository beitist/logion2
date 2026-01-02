import React, { useState } from 'react';
import { RefreshCw, Search, Sparkles, Database, Copy, RotateCcw } from 'lucide-react';
import { ReinitializeModal } from '../ReinitializeModal';
import { copySourceToTarget } from '../../api/client';
import { SettingsCard, SettingsSection } from './shared';

/**
 * Workflows Tab
 * 
 * Provides batch operations and automation tools:
 * - Pre-analysis (context retrieval only)
 * - Pre-translate (generate AI drafts)
 * - Machine translation (fill targets)
 * - Copy source to target
 * - Reinitialize source file
 * - Re-ingest vectors
 */
export function WorkflowsTab({ project, segments, onQueueAll, onReingest, onRefresh, onBatchProcess, onFullReinit }) {
    const [copyLoading, setCopyLoading] = useState(false);
    const [isReinitModalOpen, setIsReinitModalOpen] = useState(false);

    const handleRun = (mode) => {
        if (!segments) return;

        // Blocking Batch Workflows
        if (onBatchProcess && (mode === 'draft' || mode === 'translate')) {
            if (confirm(`Start Blocking Workflow: ${mode.toUpperCase()} for ${segments.length} segments?`)) {
                onBatchProcess(mode);
            }
            return;
        }

        // Background Queue for analyze
        const ids = segments.map(s => s.id);
        if (confirm(`Queue ${ids.length} segments for ${mode} (Background)?`)) {
            onQueueAll(ids, mode, true);
        }
    };

    const handleCopySource = async () => {
        if (!project) return;
        if (!confirm("This will overwrite target content for ALL segments with source content. Continue?")) return;

        try {
            setCopyLoading(true);
            await copySourceToTarget(project.id);
            if (onRefresh) onRefresh();
        } catch (err) {
            alert("Failed to copy source: " + err.message);
        } finally {
            setCopyLoading(false);
        }
    };

    const handleReinitConfirm = (file) => {
        setIsReinitModalOpen(false);
        if (onFullReinit) {
            onFullReinit(file);
        }
    };

    // Workflow card component for consistent styling
    const WorkflowCard = ({ icon: Icon, iconBg, title, description, buttonText, buttonStyle, onClick, disabled }) => (
        <div className="p-4 bg-white rounded-xl border border-gray-100 shadow-sm hover:shadow-md hover:border-gray-200 transition-all">
            <div className="flex items-start gap-3 mb-3">
                <div className={`p-2.5 rounded-xl ${iconBg}`}>
                    <Icon size={18} />
                </div>
                <div className="flex-1">
                    <h3 className="text-sm font-semibold text-gray-800">{title}</h3>
                    <p className="text-xs text-gray-500 mt-0.5">{description}</p>
                </div>
            </div>
            <button
                onClick={onClick}
                disabled={disabled}
                className={`w-full flex items-center justify-center gap-2 px-4 py-2.5 
                           rounded-xl text-xs font-medium transition-all
                           disabled:opacity-50 disabled:cursor-not-allowed ${buttonStyle}`}
            >
                {buttonText}
            </button>
        </div>
    );

    return (
        <div className="space-y-6 py-2 h-full flex flex-col">
            {/* Header Banner */}
            <div className="flex items-center gap-3 bg-gradient-to-r from-cyan-500/10 via-teal-500/10 to-emerald-500/10 p-4 rounded-xl border border-teal-200/50">
                <div className="p-2 bg-white rounded-lg shadow-sm">
                    <RefreshCw size={20} className="text-teal-600" />
                </div>
                <div>
                    <h2 className="font-semibold text-gray-800">Workflows & Automation</h2>
                    <p className="text-xs text-gray-500">Batch operations for the entire project</p>
                </div>
            </div>

            {/* Scrollable Content */}
            <div className="space-y-4 flex-1 overflow-y-auto pr-1">

                {/* Main Workflows Grid */}
                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                    <WorkflowCard
                        icon={Search}
                        iconBg="bg-blue-50 text-blue-600"
                        title="Pre-Analysis"
                        description="Retrieve TM/Glossary matches without AI drafting"
                        buttonText="Analyze Context"
                        buttonStyle="bg-blue-50 border border-blue-200 text-blue-700 hover:bg-blue-100"
                        onClick={() => handleRun("analyze")}
                    />

                    <WorkflowCard
                        icon={Sparkles}
                        iconBg="bg-purple-50 text-purple-600"
                        title="Pre-Translate (Suggestions)"
                        description="Generate AI drafts for instant availability"
                        buttonText="Generate Suggestions"
                        buttonStyle="bg-purple-50 border border-purple-200 text-purple-700 hover:bg-purple-100"
                        onClick={() => handleRun("draft")}
                    />

                    <WorkflowCard
                        icon={Database}
                        iconBg="bg-emerald-50 text-emerald-600"
                        title="Machine Translation"
                        description="Translate and fill all empty segments"
                        buttonText="Translate All Empty"
                        buttonStyle="bg-emerald-500 text-white hover:bg-emerald-600 shadow-sm"
                        onClick={() => handleRun("translate")}
                    />

                    <WorkflowCard
                        icon={Copy}
                        iconBg="bg-orange-50 text-orange-600"
                        title="Copy Source to Target"
                        description="Verification: Copy source text to all targets"
                        buttonText={copyLoading ? "Copying..." : "Copy All Sources"}
                        buttonStyle="bg-orange-50 border border-orange-200 text-orange-700 hover:bg-orange-100"
                        onClick={handleCopySource}
                        disabled={copyLoading}
                    />
                </div>

                {/* Maintenance Section */}
                <SettingsCard>
                    <SettingsSection
                        icon={RotateCcw}
                        title="Maintenance"
                        description="Reset and reprocessing options"
                        accentColor="text-gray-500"
                    >
                        <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                            <button
                                onClick={() => setIsReinitModalOpen(true)}
                                className="flex items-center justify-center gap-2 px-4 py-2.5 
                                           bg-gray-50 border border-gray-200 text-gray-700 
                                           rounded-xl text-xs font-medium hover:bg-gray-100 transition-colors"
                            >
                                <RefreshCw size={14} />
                                Reinitialize Source
                            </button>

                            <button
                                onClick={onReingest}
                                className="flex items-center justify-center gap-2 px-4 py-2.5 
                                           bg-gray-50 border border-gray-200 text-gray-700 
                                           rounded-xl text-xs font-medium hover:bg-gray-100 transition-colors"
                            >
                                <Database size={14} />
                                Re-Ingest Vectors
                            </button>
                        </div>
                    </SettingsSection>
                </SettingsCard>
            </div>

            <ReinitializeModal
                isOpen={isReinitModalOpen}
                onClose={() => setIsReinitModalOpen(false)}
                onConfirm={handleReinitConfirm}
                projectFilename={project?.filename}
            />
        </div>
    );
}

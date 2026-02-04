import React, { useState, useRef } from 'react';
import { Upload, FileText, Trash2, RefreshCw, ChevronDown, ChevronUp, AlertCircle, CheckCircle, FolderOpen } from 'lucide-react';
import { SettingsCard, SettingsSection } from './shared';
import { getProjectFiles, addProjectFile, replaceProjectFile, deleteProjectFile } from '../../api/client';

/**
 * FilesSettingsTab - Manages project files across all categories.
 * Allows adding, replacing, and deleting source, legal, and background files.
 * 
 * Props:
 * - project: The project object with files array
 * - files: Array of ProjectFile objects from API
 * - onRefresh: Callback to refresh project data after file operations
 */
export const FilesSettingsTab = ({ project, files, onRefresh }) => {
    const [isLoading, setIsLoading] = useState(false);
    const [actionStatus, setActionStatus] = useState(null); // {type: 'success'|'error', message: string}

    // Group files by category for display
    const groupedFiles = {
        source: files?.filter(f => f.category === 'source') || [],
        legal: files?.filter(f => f.category === 'legal') || [],
        background: files?.filter(f => f.category === 'background') || [],
    };

    // Category configuration with icons and descriptions
    const categories = [
        {
            id: 'source',
            label: 'Source Files',
            icon: FileText,
            description: 'DOCX/XLSX files to translate',
            accept: '.docx,.xlsx',
            accentColor: 'text-blue-500'
        },
        {
            id: 'legal',
            label: 'Legal Reference (TM)',
            icon: FolderOpen,
            description: 'TMX, DOCX, XLSX, or PDF for translation memory',
            accept: '.tmx,.docx,.xlsx,.pdf',
            accentColor: 'text-amber-500'
        },
        {
            id: 'background',
            label: 'Background Context',
            icon: FolderOpen,
            description: 'Reference documents for RAG context',
            accept: '.docx,.xlsx,.pdf,.txt',
            accentColor: 'text-purple-500'
        }
    ];

    // Show temporary status message
    const showStatus = (type, message) => {
        setActionStatus({ type, message });
        setTimeout(() => setActionStatus(null), 3000);
    };

    // Handle file upload (add new file)
    const handleAddFile = async (category, file) => {
        if (!file) return;
        setIsLoading(true);
        try {
            await addProjectFile(project.id, category, file);
            showStatus('success', `Added ${file.name}`);
            onRefresh?.();
        } catch (err) {
            showStatus('error', err.message);
        } finally {
            setIsLoading(false);
        }
    };

    // Handle file replacement
    const handleReplaceFile = async (fileId, file) => {
        if (!file) return;
        setIsLoading(true);
        try {
            await replaceProjectFile(project.id, fileId, file);
            showStatus('success', `Replaced with ${file.name}`);
            onRefresh?.();
        } catch (err) {
            showStatus('error', err.message);
        } finally {
            setIsLoading(false);
        }
    };

    // Handle file deletion
    const handleDeleteFile = async (fileId, filename) => {
        if (!confirm(`Delete "${filename}"? This will remove all linked segments.`)) return;
        setIsLoading(true);
        try {
            await deleteProjectFile(project.id, fileId);
            showStatus('success', `Deleted ${filename}`);
            onRefresh?.();
        } catch (err) {
            showStatus('error', err.message);
        } finally {
            setIsLoading(false);
        }
    };

    return (
        <div className="space-y-4">
            {/* Status Toast */}
            {actionStatus && (
                <div className={`flex items-center gap-2 px-3 py-2 rounded-lg text-sm ${actionStatus.type === 'success'
                        ? 'bg-green-50 text-green-700 border border-green-200'
                        : 'bg-red-50 text-red-700 border border-red-200'
                    }`}>
                    {actionStatus.type === 'success' ? <CheckCircle size={16} /> : <AlertCircle size={16} />}
                    {actionStatus.message}
                </div>
            )}

            {/* Category Sections */}
            {categories.map(cat => (
                <SettingsCard key={cat.id}>
                    <SettingsSection
                        icon={cat.icon}
                        title={cat.label}
                        description={cat.description}
                        accentColor={cat.accentColor}
                    >
                        <div className="space-y-2">
                            {/* File List */}
                            {groupedFiles[cat.id].length > 0 ? (
                                groupedFiles[cat.id].map(file => (
                                    <FileRow
                                        key={file.id}
                                        file={file}
                                        accept={cat.accept}
                                        onReplace={(newFile) => handleReplaceFile(file.id, newFile)}
                                        onDelete={() => handleDeleteFile(file.id, file.filename)}
                                        disabled={isLoading}
                                    />
                                ))
                            ) : (
                                <p className="text-sm text-gray-400 italic">No files yet</p>
                            )}

                            {/* Add File Button */}
                            <AddFileButton
                                category={cat.id}
                                accept={cat.accept}
                                onAdd={(file) => handleAddFile(cat.id, file)}
                                disabled={isLoading}
                            />
                        </div>
                    </SettingsSection>
                </SettingsCard>
            ))}
        </div>
    );
};

/**
 * FileRow - Displays a single file with Replace/Delete actions.
 */
const FileRow = ({ file, accept, onReplace, onDelete, disabled }) => {
    const replaceInputRef = useRef(null);

    return (
        <div className="flex items-center justify-between py-2 px-3 bg-gray-50 rounded-lg hover:bg-gray-100 transition-colors">
            <div className="flex items-center gap-2 min-w-0 flex-1">
                <FileText size={16} className="text-gray-400 flex-shrink-0" />
                <span className="text-sm font-medium text-gray-700 truncate">{file.filename}</span>
                {file.segment_count > 0 && (
                    <span className="text-xs text-gray-400 flex-shrink-0">
                        ({file.segment_count} segments)
                    </span>
                )}
            </div>

            <div className="flex items-center gap-1 flex-shrink-0">
                {/* Replace Button */}
                <input
                    ref={replaceInputRef}
                    type="file"
                    accept={accept}
                    className="hidden"
                    onChange={(e) => onReplace(e.target.files[0])}
                />
                <button
                    onClick={() => replaceInputRef.current?.click()}
                    disabled={disabled}
                    className="p-1.5 text-gray-500 hover:text-blue-600 hover:bg-blue-50 rounded transition-colors disabled:opacity-50"
                    title="Replace file"
                >
                    <RefreshCw size={14} />
                </button>

                {/* Delete Button */}
                <button
                    onClick={onDelete}
                    disabled={disabled}
                    className="p-1.5 text-gray-500 hover:text-red-600 hover:bg-red-50 rounded transition-colors disabled:opacity-50"
                    title="Delete file"
                >
                    <Trash2 size={14} />
                </button>
            </div>
        </div>
    );
};

/**
 * AddFileButton - File picker button for adding new files.
 */
const AddFileButton = ({ category, accept, onAdd, disabled }) => {
    const inputRef = useRef(null);

    return (
        <>
            <input
                ref={inputRef}
                type="file"
                accept={accept}
                className="hidden"
                onChange={(e) => {
                    onAdd(e.target.files[0]);
                    e.target.value = ''; // Reset for re-selecting same file
                }}
            />
            <button
                onClick={() => inputRef.current?.click()}
                disabled={disabled}
                className="flex items-center gap-2 w-full py-2 px-3 text-sm text-gray-500 hover:text-gray-700 hover:bg-gray-50 border border-dashed border-gray-200 rounded-lg transition-colors disabled:opacity-50"
            >
                <Upload size={14} />
                <span>Add {category === 'source' ? 'Source' : category === 'legal' ? 'Legal' : 'Background'} File</span>
            </button>
        </>
    );
};

export default FilesSettingsTab;

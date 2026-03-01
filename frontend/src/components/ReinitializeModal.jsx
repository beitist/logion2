import React, { useState } from 'react';
import { Upload, X, RefreshCw, FileText, AlertTriangle } from 'lucide-react';

export function ReinitializeModal({ isOpen, onClose, onConfirm, projectFilename }) {
    const [file, setFile] = useState(null);

    if (!isOpen) return null;

    const handleFileChange = (e) => {
        if (e.target.files && e.target.files[0]) {
            setFile(e.target.files[0]);
        }
    };

    const handleSubmit = () => {
        onConfirm(file);
    };

    return (
        <div className="fixed inset-0 bg-black/50 backdrop-blur-sm flex items-center justify-center z-[100] p-4">
            <div className="bg-white rounded-xl shadow-2xl w-full max-w-lg border border-gray-100 overflow-hidden">
                {/* Header */}
                <div className="flex items-center justify-between p-6 border-b border-gray-100">
                    <div className="flex items-center gap-3 text-gray-900">
                        <div className="p-2 bg-indigo-50 text-indigo-600 rounded-lg">
                            <RefreshCw size={20} />
                        </div>
                        <h3 className="text-lg font-bold">Reinitialize Source</h3>
                    </div>
                    <button onClick={onClose} className="text-gray-400 hover:text-gray-600 transition-colors">
                        <X size={20} />
                    </button>
                </div>

                {/* Body */}
                <div className="p-6 space-y-6">
                    {/* Warning */}
                    <div className="flex gap-3 bg-yellow-50 p-4 rounded-lg border border-yellow-100 text-yellow-800 text-sm">
                        <AlertTriangle className="shrink-0 mt-0.5" size={16} />
                        <div>
                            <span className="font-semibold block mb-1">Warning:</span>
                            Reinitializing re-parses the source file. Existing translations are preserved ONLY if the source text matches exactly.
                        </div>
                    </div>

                    {/* Current File Info */}
                    <div>
                        <label className="block text-xs font-semibold text-gray-500 uppercase tracking-wider mb-2">Current Source File</label>
                        <div className="flex items-center gap-3 p-3 bg-gray-50 rounded-lg border border-gray-200 text-gray-700 text-sm">
                            <FileText size={16} className="text-gray-400" />
                            <span className="font-medium truncate">{projectFilename || "Unknown.docx"}</span>
                        </div>
                    </div>

                    {/* New File Upload */}
                    <div>
                        <label className="block text-xs font-semibold text-gray-500 uppercase tracking-wider mb-2">Replace Source File (Optional)</label>

                        {!file ? (
                            <label className="flex flex-col items-center justify-center w-full h-32 border-2 border-dashed border-gray-300 rounded-lg cursor-pointer bg-gray-50 hover:bg-white hover:border-indigo-400 transition-all group">
                                <div className="flex flex-col items-center justify-center pt-5 pb-6">
                                    <div className="p-3 bg-white rounded-full shadow-sm mb-3 group-hover:scale-110 transition-transform">
                                        <Upload size={20} className="text-indigo-500" />
                                    </div>
                                    <p className="mb-1 text-sm text-gray-600 font-medium">Click to upload new version</p>
                                    <p className="text-xs text-gray-400">DOCX files only</p>
                                </div>
                                <input type="file" className="hidden" accept=".docx" onChange={handleFileChange} />
                            </label>
                        ) : (
                            <div className="relative group">
                                <div className="flex items-center gap-3 p-3 bg-indigo-50 rounded-lg border border-indigo-100 text-indigo-900 text-sm">
                                    <FileText size={16} className="text-indigo-500" />
                                    <span className="font-semibold truncate flex-1">{file.name}</span>
                                    <span className="text-xs text-indigo-400">{(file.size / 1024).toFixed(1)} KB</span>
                                </div>
                                <button
                                    onClick={() => setFile(null)}
                                    className="absolute -top-2 -right-2 bg-white text-gray-400 hover:text-red-500 rounded-full p-1 shadow-md border border-gray-100 opacity-0 group-hover:opacity-100 transition-opacity"
                                >
                                    <X size={14} />
                                </button>
                            </div>
                        )}
                        <p className="text-xs text-gray-400 mt-2">
                            If uploaded, this file will overwrite the existing source file permanently.
                        </p>
                    </div>
                </div>

                {/* Footer */}
                <div className="p-6 bg-gray-50 border-t border-gray-100 flex justify-end gap-3">
                    <button
                        onClick={onClose}
                        className="px-4 py-2 text-gray-600 hover:bg-gray-200 rounded-lg text-sm font-medium transition-colors"
                    >
                        Cancel
                    </button>
                    <button
                        onClick={handleSubmit}
                        className="px-4 py-2 bg-indigo-600 hover:bg-indigo-700 text-white rounded-lg text-sm font-medium shadow-sm transition-colors flex items-center gap-2"
                    >
                        <RefreshCw size={16} />
                        {file ? "Replace & Reinitialize" : "Reinitialize"}
                    </button>
                </div>
            </div>
        </div>
    );
}

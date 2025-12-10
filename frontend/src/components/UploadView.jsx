import React, { useState } from 'react';
import { uploadProject } from '../api/client';

export function UploadView({ onUploadSuccess }) {
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState(null);

    const handleFileChange = async (e) => {
        const file = e.target.files[0];
        if (!file) return;

        setLoading(true);
        setError(null);

        try {
            const data = await uploadProject(file);
            onUploadSuccess(data.id);
        } catch (err) {
            console.error(err);
            setError(err.message);
        } finally {
            setLoading(false);
        }
    };

    return (
        <div className="flex flex-col items-center justify-center min-h-screen bg-gray-100">
            <div className="bg-white p-8 rounded-lg shadow-md w-full max-w-md text-center">
                <h1 className="text-2xl font-bold mb-6 text-gray-800">Logion 2 Workbench</h1>
                <p className="text-gray-600 mb-8">Upload a DOCX file to start translating.</p>

                <label className="cursor-pointer bg-blue-600 hover:bg-blue-700 text-white font-semibold py-3 px-6 rounded-lg transition-colors">
                    <span>{loading ? "Uploading..." : "Select Document"}</span>
                    <input
                        type="file"
                        accept=".docx"
                        className="hidden"
                        onChange={handleFileChange}
                        disabled={loading}
                    />
                </label>

                {error && (
                    <div className="mt-6 p-4 bg-red-50 text-red-600 rounded-md border border-red-200">
                        {error}
                    </div>
                )}
            </div>
        </div>
    );
}

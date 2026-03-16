import React, { useState, useEffect, useRef } from 'react';
import { X, Save, HardDrive, Database, FolderArchive, Upload, Download, FolderOpen, ChevronRight, ArrowUp } from 'lucide-react';
import { getAppSettings, updateAppSettings, triggerBackup, listBackups, restoreBackup, getProjects, browseDirs } from '../api/client';

const INTERVAL_OPTIONS = [
    { value: 5, label: '5 min' },
    { value: 10, label: '10 min' },
    { value: 15, label: '15 min' },
    { value: 30, label: '30 min' },
];

function DirectoryPicker({ value, onChange, onClose }) {
    const [currentPath, setCurrentPath] = useState('');
    const [parentPath, setParentPath] = useState('');
    const [dirs, setDirs] = useState([]);
    const [cloudShortcuts, setCloudShortcuts] = useState([]);
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState(null);

    const loadDir = async (path) => {
        setLoading(true);
        setError(null);
        try {
            const data = await browseDirs(path);
            setCurrentPath(data.current);
            setParentPath(data.parent);
            setDirs(data.directories);
            setCloudShortcuts(data.cloud_shortcuts || []);
        } catch (err) {
            setError(err.message);
        } finally {
            setLoading(false);
        }
    };

    useEffect(() => {
        loadDir(value || '');
    }, []);

    return (
        <div className="border border-indigo-200 rounded-lg bg-white shadow-sm mt-2">
            {/* Current path + select button */}
            <div className="flex items-center gap-2 px-3 py-2 bg-indigo-50 border-b border-indigo-100 rounded-t-lg">
                <button
                    onClick={() => loadDir(parentPath)}
                    disabled={currentPath === parentPath}
                    className="p-1 text-gray-400 hover:text-gray-600 disabled:opacity-30 transition-colors"
                    title="Go up"
                >
                    <ArrowUp size={14} />
                </button>
                <span className="text-xs font-mono text-gray-600 truncate flex-1" title={currentPath}>
                    {currentPath}
                </span>
                <button
                    onClick={() => { onChange(currentPath); onClose(); }}
                    className="px-2.5 py-1 text-xs font-medium bg-indigo-600 text-white rounded hover:bg-indigo-700 transition-colors"
                >
                    Select
                </button>
                <button
                    onClick={onClose}
                    className="p-1 text-gray-400 hover:text-gray-600 transition-colors"
                >
                    <X size={14} />
                </button>
            </div>

            {/* Directory list */}
            <div className="max-h-48 overflow-y-auto">
                {loading && <div className="px-3 py-4 text-xs text-gray-400 text-center">Loading...</div>}
                {error && <div className="px-3 py-2 text-xs text-red-500">{error}</div>}
                {/* Cloud storage shortcuts */}
                {!loading && cloudShortcuts.length > 0 && (
                    <>
                        {cloudShortcuts.map(cs => (
                            <button
                                key={cs.path}
                                onClick={() => loadDir(cs.path)}
                                className="w-full flex items-center gap-2 px-3 py-1.5 text-xs text-blue-700 hover:bg-blue-50 text-left transition-colors"
                            >
                                <span className="flex-shrink-0">☁️</span>
                                <span className="truncate">{cs.name.replace('☁ ', '')}</span>
                                <ChevronRight size={12} className="text-blue-300 ml-auto flex-shrink-0" />
                            </button>
                        ))}
                        <div className="border-t border-gray-100" />
                    </>
                )}
                {!loading && dirs.length === 0 && cloudShortcuts.length === 0 && !error && (
                    <div className="px-3 py-4 text-xs text-gray-400 text-center">No subdirectories</div>
                )}
                {!loading && dirs.map(dir => (
                    <button
                        key={dir}
                        onClick={() => loadDir(currentPath + '/' + dir)}
                        className="w-full flex items-center gap-2 px-3 py-1.5 text-xs text-gray-700 hover:bg-gray-50 text-left transition-colors"
                    >
                        <FolderOpen size={13} className="text-gray-400 flex-shrink-0" />
                        <span className="truncate">{dir}</span>
                        <ChevronRight size={12} className="text-gray-300 ml-auto flex-shrink-0" />
                    </button>
                ))}
            </div>
        </div>
    );
}

export function GlobalSettingsModal({ open, onClose, onProjectRestored }) {
    const [settings, setSettings] = useState({});
    const [env, setEnv] = useState({});
    const [version, setVersion] = useState('');
    const [backups, setBackups] = useState([]);
    const [projects, setProjects] = useState([]);
    const [loading, setLoading] = useState(true);
    const [saving, setSaving] = useState(false);
    const [backingUp, setBackingUp] = useState(null);
    const [restoring, setRestoring] = useState(false);
    const [message, setMessage] = useState(null);
    const [showDirPicker, setShowDirPicker] = useState(false);
    const fileInputRef = useRef(null);

    const fetchAll = async () => {
        try {
            setLoading(true);
            const [settingsData, backupData, projectData] = await Promise.all([
                getAppSettings(),
                listBackups().catch(() => ({ backups: [] })),
                getProjects().catch(() => []),
            ]);
            setSettings(settingsData.settings || {});
            setEnv(settingsData.env || {});
            setVersion(settingsData.version || '?');
            setBackups(backupData.backups || []);
            setProjects(projectData.filter(p => !p.archived));
        } catch (err) {
            setMessage({ type: 'error', text: 'Failed to load settings: ' + err.message });
        } finally {
            setLoading(false);
        }
    };

    useEffect(() => {
        if (open) { fetchAll(); setShowDirPicker(false); }
    }, [open]);

    useEffect(() => {
        if (message) {
            const t = setTimeout(() => setMessage(null), 4000);
            return () => clearTimeout(t);
        }
    }, [message]);

    const handleSave = async () => {
        setSaving(true);
        try {
            const res = await updateAppSettings(settings);
            setSettings(res.settings || settings);
            setMessage({ type: 'success', text: 'Settings saved' });
            const backupData = await listBackups().catch(() => ({ backups: [] }));
            setBackups(backupData.backups || []);
        } catch (err) {
            setMessage({ type: 'error', text: err.message });
        } finally {
            setSaving(false);
        }
    };

    const handleBackupAll = async () => {
        if (projects.length === 0) return;
        setBackingUp('all');
        let ok = 0, fail = 0;
        for (const p of projects) {
            try {
                await triggerBackup(p.id);
                ok++;
            } catch {
                fail++;
            }
        }
        setBackingUp(null);
        setMessage({ type: fail > 0 ? 'error' : 'success', text: `Backup: ${ok} succeeded, ${fail} failed` });
        const backupData = await listBackups().catch(() => ({ backups: [] }));
        setBackups(backupData.backups || []);
    };

    const handleRestore = async (e) => {
        const file = e.target.files?.[0];
        if (!file) return;
        setRestoring(true);
        try {
            const result = await restoreBackup(file);
            setMessage({ type: 'success', text: `Restored: ${result.name}` });
            onProjectRestored?.();
        } catch (err) {
            setMessage({ type: 'error', text: err.message });
        } finally {
            setRestoring(false);
            if (fileInputRef.current) fileInputRef.current.value = '';
        }
    };

    const formatBytes = (bytes) => {
        if (!bytes) return '0 B';
        if (bytes < 1024) return bytes + ' B';
        if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB';
        return (bytes / (1024 * 1024)).toFixed(1) + ' MB';
    };

    if (!open) return null;

    return (
        <div className="fixed inset-0 z-50 bg-black/40 flex items-center justify-center" onClick={onClose}>
            <div
                className="bg-gray-50 rounded-2xl shadow-2xl w-[90vw] max-w-3xl max-h-[85vh] flex flex-col overflow-hidden"
                onClick={e => e.stopPropagation()}
            >
                {/* Header */}
                <div className="flex items-center justify-between px-6 py-4 bg-white border-b border-gray-200">
                    <h2 className="text-lg font-semibold text-gray-800">Settings</h2>
                    <div className="flex items-center gap-3">
                        {version && (
                            <span className="text-xs text-gray-400 font-mono">v{version}</span>
                        )}
                        <button onClick={onClose} className="text-gray-400 hover:text-gray-600 transition-colors">
                            <X size={20} />
                        </button>
                    </div>
                </div>

                {/* Message Toast */}
                {message && (
                    <div className={`mx-6 mt-4 px-4 py-2 rounded-lg text-sm ${
                        message.type === 'success' ? 'bg-green-50 text-green-700 border border-green-200' : 'bg-red-50 text-red-700 border border-red-200'
                    }`}>
                        {message.text}
                    </div>
                )}

                {/* Content */}
                <div className="flex-1 overflow-y-auto p-6 space-y-6">
                    {loading ? (
                        <div className="text-center py-12 text-gray-400">Loading...</div>
                    ) : (
                        <>
                            {/* Card 1: Paths */}
                            <div className="bg-white rounded-xl border border-gray-200 shadow-sm">
                                <div className="px-5 py-3 border-b border-gray-100 flex items-center gap-2">
                                    <HardDrive size={16} className="text-gray-400" />
                                    <h3 className="text-sm font-semibold text-gray-700">Paths</h3>
                                </div>
                                <div className="p-5 space-y-4">
                                    <div>
                                        <label className="block text-xs text-gray-500 mb-1">Backup Directory</label>
                                        <div className="flex gap-2">
                                            <input
                                                type="text"
                                                value={settings.backup_dir || ''}
                                                onChange={e => setSettings(s => ({ ...s, backup_dir: e.target.value }))}
                                                className="flex-1 px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-indigo-300 focus:border-indigo-400"
                                                placeholder="/path/to/backups (leave empty to disable)"
                                            />
                                            <button
                                                onClick={() => setShowDirPicker(v => !v)}
                                                className={`px-3 py-2 border rounded-lg text-sm transition-colors flex items-center gap-1.5 ${
                                                    showDirPicker
                                                        ? 'border-indigo-300 bg-indigo-50 text-indigo-700'
                                                        : 'border-gray-300 text-gray-500 hover:bg-gray-50 hover:text-gray-700'
                                                }`}
                                                title="Browse directories"
                                            >
                                                <FolderOpen size={14} />
                                            </button>
                                        </div>
                                        {showDirPicker && (
                                            <DirectoryPicker
                                                value={settings.backup_dir || ''}
                                                onChange={(path) => setSettings(s => ({ ...s, backup_dir: path }))}
                                                onClose={() => setShowDirPicker(false)}
                                            />
                                        )}
                                    </div>
                                    <div>
                                        <label className="block text-xs text-gray-500 mb-1">File Storage Root</label>
                                        <input
                                            type="text"
                                            value={env.storage_root || ''}
                                            disabled
                                            className="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm bg-gray-50 text-gray-400 cursor-not-allowed"
                                        />
                                        <p className="text-[10px] text-gray-400 mt-1">Set via STORAGE_ROOT environment variable</p>
                                    </div>
                                </div>
                            </div>

                            {/* Card 2: Backup Settings */}
                            <div className="bg-white rounded-xl border border-gray-200 shadow-sm">
                                <div className="px-5 py-3 border-b border-gray-100 flex items-center gap-2">
                                    <FolderArchive size={16} className="text-gray-400" />
                                    <h3 className="text-sm font-semibold text-gray-700">Backup</h3>
                                </div>
                                <div className="p-5 space-y-5">
                                    {/* Settings Row */}
                                    <div className="grid grid-cols-3 gap-4">
                                        <div>
                                            <label className="block text-xs text-gray-500 mb-1">Max Backups per Project</label>
                                            <input
                                                type="number"
                                                min={1}
                                                max={20}
                                                value={settings.backup_max_count || 3}
                                                onChange={e => setSettings(s => ({ ...s, backup_max_count: Math.max(1, Math.min(20, parseInt(e.target.value) || 3)) }))}
                                                className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-indigo-300"
                                            />
                                        </div>
                                        <div>
                                            <label className="block text-xs text-gray-500 mb-1">Auto-Backup Interval</label>
                                            <select
                                                value={settings.backup_interval_minutes || 10}
                                                onChange={e => setSettings(s => ({ ...s, backup_interval_minutes: parseInt(e.target.value) }))}
                                                className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-indigo-300 bg-white"
                                            >
                                                {INTERVAL_OPTIONS.map(o => (
                                                    <option key={o.value} value={o.value}>{o.label}</option>
                                                ))}
                                            </select>
                                        </div>
                                        <div className="flex items-end">
                                            <label className="flex items-center gap-2 cursor-pointer">
                                                <input
                                                    type="checkbox"
                                                    checked={settings.backup_include_files !== false}
                                                    onChange={e => setSettings(s => ({ ...s, backup_include_files: e.target.checked }))}
                                                    className="rounded border-gray-300 text-indigo-600 focus:ring-indigo-500"
                                                />
                                                <span className="text-xs text-gray-600">Include source files</span>
                                            </label>
                                        </div>
                                    </div>

                                    {/* Actions */}
                                    <div className="flex items-center gap-3 pt-2 border-t border-gray-100">
                                        <button
                                            onClick={handleBackupAll}
                                            disabled={backingUp || !settings.backup_dir}
                                            className="flex items-center gap-2 px-3 py-1.5 text-sm bg-indigo-50 text-indigo-700 rounded-lg hover:bg-indigo-100 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
                                        >
                                            <Download size={14} className={backingUp === 'all' ? 'animate-spin' : ''} />
                                            {backingUp === 'all' ? 'Backing up...' : 'Backup All Projects'}
                                        </button>

                                        <button
                                            onClick={() => fileInputRef.current?.click()}
                                            disabled={restoring}
                                            className="flex items-center gap-2 px-3 py-1.5 text-sm bg-emerald-50 text-emerald-700 rounded-lg hover:bg-emerald-100 disabled:opacity-40 transition-colors"
                                        >
                                            <Upload size={14} />
                                            {restoring ? 'Restoring...' : 'Restore from Backup'}
                                        </button>
                                        <input
                                            ref={fileInputRef}
                                            type="file"
                                            accept=".zip"
                                            onChange={handleRestore}
                                            className="hidden"
                                        />
                                    </div>

                                    {/* Backup History */}
                                    {backups.length > 0 && (
                                        <div className="pt-2">
                                            <h4 className="text-xs font-medium text-gray-500 mb-2">Backup History</h4>
                                            <div className="max-h-48 overflow-y-auto border border-gray-200 rounded-lg">
                                                <table className="w-full text-xs">
                                                    <thead className="bg-gray-50 sticky top-0">
                                                        <tr>
                                                            <th className="text-left px-3 py-2 text-gray-500 font-medium">Project</th>
                                                            <th className="text-left px-3 py-2 text-gray-500 font-medium">Date</th>
                                                            <th className="text-right px-3 py-2 text-gray-500 font-medium">Size</th>
                                                        </tr>
                                                    </thead>
                                                    <tbody className="divide-y divide-gray-100">
                                                        {backups.map((b, i) => (
                                                            <tr key={i} className="hover:bg-gray-50">
                                                                <td className="px-3 py-2 text-gray-700">{b.project_name}</td>
                                                                <td className="px-3 py-2 text-gray-500">
                                                                    {new Date(b.modified_at).toLocaleString()}
                                                                </td>
                                                                <td className="px-3 py-2 text-gray-500 text-right">{formatBytes(b.size_bytes)}</td>
                                                            </tr>
                                                        ))}
                                                    </tbody>
                                                </table>
                                            </div>
                                        </div>
                                    )}
                                </div>
                            </div>

                            {/* Card 3: Database (placeholder) */}
                            <div className="bg-white rounded-xl border border-gray-200 shadow-sm">
                                <div className="px-5 py-3 border-b border-gray-100 flex items-center gap-2">
                                    <Database size={16} className="text-gray-400" />
                                    <h3 className="text-sm font-semibold text-gray-700">Database</h3>
                                    <span className="text-[9px] text-gray-400 bg-gray-100 px-1.5 py-0.5 rounded">read-only</span>
                                </div>
                                <div className="p-5">
                                    <div className="grid grid-cols-2 gap-3 text-xs">
                                        <div>
                                            <span className="text-gray-400">Host:</span>
                                            <span className="ml-2 text-gray-600 font-mono">{env.db_host || '?'}</span>
                                        </div>
                                        <div>
                                            <span className="text-gray-400">Port:</span>
                                            <span className="ml-2 text-gray-600 font-mono">{env.db_port || '?'}</span>
                                        </div>
                                        <div>
                                            <span className="text-gray-400">User:</span>
                                            <span className="ml-2 text-gray-600 font-mono">{env.db_user || '?'}</span>
                                        </div>
                                        <div>
                                            <span className="text-gray-400">Database:</span>
                                            <span className="ml-2 text-gray-600 font-mono">{env.db_name || '?'}</span>
                                        </div>
                                    </div>
                                </div>
                            </div>
                        </>
                    )}
                </div>

                {/* Footer */}
                <div className="px-6 py-4 bg-white border-t border-gray-200 flex justify-end">
                    <button
                        onClick={handleSave}
                        disabled={saving || loading}
                        className="flex items-center gap-2 px-4 py-2 bg-indigo-600 hover:bg-indigo-700 text-white text-sm rounded-lg disabled:opacity-50 transition-colors"
                    >
                        <Save size={14} />
                        {saving ? 'Saving...' : 'Save Settings'}
                    </button>
                </div>
            </div>
        </div>
    );
}

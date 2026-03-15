import React, { useEffect, useState, useMemo } from 'react';
import { getProjects, deleteProject, duplicateProject, updateProject } from '../api/client';
import { Trash2, FilePlus, Copy, FileText, FileSpreadsheet, Archive, ArchiveRestore, ChevronDown, ChevronRight, FolderOpen, Folder, X, Settings } from 'lucide-react';
import { GlobalSettingsModal } from './GlobalSettingsModal';

export function ProjectList({ onSelectProject, onNewProject }) {
    const [projects, setProjects] = useState([]);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState(null);
    const [archiveOpen, setArchiveOpen] = useState(false);
    const [archiveDialog, setArchiveDialog] = useState(null); // { projectId, folderName }
    const [settingsOpen, setSettingsOpen] = useState(false);

    const fetchList = async () => {
        try {
            setLoading(true);
            const data = await getProjects();
            setProjects(data);
            setError(null);
        } catch (err) {
            setError("Failed to load projects: " + err.message);
        } finally {
            setLoading(false);
        }
    };

    useEffect(() => { fetchList(); }, []);

    const activeProjects = useMemo(() => projects.filter(p => !p.archived), [projects]);
    const archivedProjects = useMemo(() => projects.filter(p => p.archived), [projects]);

    // Group archived by folder
    const archivedFolders = useMemo(() => {
        const groups = {};
        archivedProjects.forEach(p => {
            const folder = p.archive_folder || '(Unsorted)';
            if (!groups[folder]) groups[folder] = [];
            groups[folder].push(p);
        });
        // Sort folders alphabetically, but (Unsorted) last
        return Object.entries(groups).sort(([a], [b]) => {
            if (a === '(Unsorted)') return 1;
            if (b === '(Unsorted)') return -1;
            return a.localeCompare(b);
        });
    }, [archivedProjects]);

    // Collect existing folder names for suggestions
    const existingFolders = useMemo(() => {
        const set = new Set();
        archivedProjects.forEach(p => { if (p.archive_folder) set.add(p.archive_folder); });
        return [...set].sort();
    }, [archivedProjects]);

    const handleDelete = async (e, id) => {
        e.stopPropagation();
        if (!confirm("Delete this project?")) return;
        try {
            await deleteProject(id);
            setProjects(prev => prev.filter(p => p.id !== id));
        } catch (err) { alert(err.message); }
    };

    const handleDuplicate = async (e, id) => {
        e.stopPropagation();
        if (!confirm("Duplicate this project?")) return;
        try {
            const newProject = await duplicateProject(id);
            setProjects(prev => [newProject, ...prev]);
        } catch (err) { alert(err.message); }
    };

    const handleArchive = (e, projectId) => {
        e.stopPropagation();
        setArchiveDialog({ projectId, folderName: '' });
    };

    const handleArchiveConfirm = async () => {
        if (!archiveDialog) return;
        const { projectId, folderName } = archiveDialog;
        try {
            await updateProject(projectId, {
                archived: true,
                archive_folder: folderName.trim() || null,
            });
            setProjects(prev => prev.map(p =>
                p.id === projectId ? { ...p, archived: true, archive_folder: folderName.trim() || null } : p
            ));
        } catch (err) { alert(err.message); }
        setArchiveDialog(null);
    };

    const handleUnarchive = async (e, projectId) => {
        e.stopPropagation();
        try {
            await updateProject(projectId, { archived: false, archive_folder: null });
            setProjects(prev => prev.map(p =>
                p.id === projectId ? { ...p, archived: false, archive_folder: null } : p
            ));
        } catch (err) { alert(err.message); }
    };

    const STATUS_CYCLE = { processing: 'review', review: 'completed', completed: 'processing' };
    const handleCycleStatus = async (e, projectId, currentStatus) => {
        e.stopPropagation();
        const next = STATUS_CYCLE[currentStatus] || 'processing';
        try {
            await updateProject(projectId, { status: next });
            setProjects(prev => prev.map(p => p.id === projectId ? { ...p, status: next } : p));
        } catch (err) { console.error(err); }
    };

    const getFileIcon = (filename) => {
        if (!filename) return <FileText size={18} className="text-blue-500" />;
        const ext = filename.split('.').pop().toLowerCase();
        if (ext === 'xlsx' || ext === 'xls') return <FileSpreadsheet size={18} className="text-green-600" />;
        return <FileText size={18} className="text-blue-600" />;
    };

    if (loading) return <div className="p-8 text-center text-gray-400">Loading projects...</div>;

    const ProjectRow = ({ project, isArchived = false }) => (
        <tr
            key={project.id}
            onClick={() => onSelectProject(project.id, project.status)}
            className="hover:bg-gray-50 cursor-pointer transition-colors"
        >
            <td className="px-6 py-4 whitespace-nowrap">
                <div className="flex items-center gap-3">
                    {getFileIcon(project.filename)}
                    <div className="text-sm font-medium text-gray-900">{project.name || "Untitled"}</div>
                </div>
            </td>
            <td className="px-6 py-4 whitespace-nowrap">
                <div className="flex items-center gap-2">
                    <div className="w-24 bg-gray-200 rounded-full h-2.5">
                        <div
                            className="bg-indigo-600 h-2.5 rounded-full transition-all duration-500"
                            style={{ width: `${project.progress || 0}%` }}
                        />
                    </div>
                    <span className="text-xs text-gray-500">{project.progress || 0}%</span>
                </div>
            </td>
            <td className="px-6 py-4 whitespace-nowrap">
                <div className="text-sm text-gray-500 uppercase">{project.source_lang} &rarr; {project.target_lang}</div>
            </td>
            <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-500">
                {new Date(project.created_at).toLocaleDateString()}
            </td>
            <td className="px-6 py-4 whitespace-nowrap">
                <button
                    onClick={(e) => handleCycleStatus(e, project.id, project.status)}
                    className={`px-2 inline-flex text-xs leading-5 font-semibold rounded-full cursor-pointer hover:opacity-80 transition-opacity ${
                        project.status === 'completed' ? 'bg-green-100 text-green-800' :
                        project.status === 'review' ? 'bg-blue-100 text-blue-800' :
                        'bg-yellow-100 text-yellow-800'
                    }`}
                    title="Click to change status"
                >
                    {project.status}
                </button>
            </td>
            <td className="px-6 py-4 whitespace-nowrap text-right text-sm font-medium flex justify-end gap-1">
                {isArchived ? (
                    <button
                        onClick={(e) => handleUnarchive(e, project.id)}
                        className="text-emerald-400 hover:text-emerald-600 p-2 hover:bg-emerald-50 rounded-full transition-colors"
                        title="Restore from archive"
                    >
                        <ArchiveRestore size={16} />
                    </button>
                ) : (
                    <>
                        <button
                            onClick={(e) => handleArchive(e, project.id)}
                            className="text-gray-300 hover:text-amber-500 p-2 hover:bg-amber-50 rounded-full transition-colors"
                            title="Archive project"
                        >
                            <Archive size={16} />
                        </button>
                        <button
                            onClick={(e) => handleDuplicate(e, project.id)}
                            className="text-indigo-400 hover:text-indigo-600 p-2 hover:bg-indigo-50 rounded-full transition-colors"
                            title="Duplicate Project"
                        >
                            <Copy size={16} />
                        </button>
                    </>
                )}
                <button
                    onClick={(e) => handleDelete(e, project.id)}
                    className="text-red-400 hover:text-red-600 p-2 hover:bg-red-50 rounded-full transition-colors"
                    title="Delete Project"
                >
                    <Trash2 size={16} />
                </button>
            </td>
        </tr>
    );

    const TableHead = () => (
        <thead className="bg-gray-50">
            <tr>
                <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Project Name</th>
                <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Progress</th>
                <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Language</th>
                <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Created</th>
                <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Status</th>
                <th className="relative px-6 py-3"><span className="sr-only">Actions</span></th>
            </tr>
        </thead>
    );

    return (
        <div className="max-w-6xl mx-auto py-8 px-4">
            <div className="flex justify-between items-center mb-8">
                <h1 className="text-2xl font-bold text-gray-800 dark:text-gray-100">My Projects</h1>
                <div className="flex items-center gap-2">
                    <button
                        onClick={() => setSettingsOpen(true)}
                        className="p-2 text-gray-400 hover:text-gray-600 hover:bg-gray-100 rounded-lg transition-colors"
                        title="Settings"
                    >
                        <Settings size={20} />
                    </button>
                    <button
                        onClick={onNewProject}
                        className="flex items-center gap-2 px-4 py-2 bg-indigo-600 hover:bg-indigo-700 text-white rounded-md transition-colors"
                    >
                        <FilePlus size={18} />
                        <span>New Project</span>
                    </button>
                </div>
            </div>

            {error && (
                <div className="p-4 mb-6 bg-red-50 text-red-700 rounded-md border border-red-200">{error}</div>
            )}

            {/* Active Projects */}
            {activeProjects.length === 0 && archivedProjects.length === 0 ? (
                <div className="text-center py-20 bg-gray-50 border-2 border-dashed border-gray-200 rounded-xl">
                    <p className="text-gray-500 mb-4">No projects found.</p>
                    <button onClick={onNewProject} className="text-indigo-600 hover:underline">Create your first project</button>
                </div>
            ) : (
                <>
                    {activeProjects.length > 0 && (
                        <div className="bg-white shadow-sm ring-1 ring-gray-200 rounded-lg overflow-hidden">
                            <table className="min-w-full divide-y divide-gray-200">
                                <TableHead />
                                <tbody className="bg-white divide-y divide-gray-200">
                                    {activeProjects.map(p => <ProjectRow key={p.id} project={p} />)}
                                </tbody>
                            </table>
                        </div>
                    )}

                    {activeProjects.length === 0 && (
                        <div className="text-center py-12 bg-gray-50 border-2 border-dashed border-gray-200 rounded-xl mb-6">
                            <p className="text-gray-400 text-sm">All projects are archived.</p>
                        </div>
                    )}
                </>
            )}

            {/* Archive Section */}
            {archivedProjects.length > 0 && (
                <div className="mt-6">
                    <button
                        onClick={() => setArchiveOpen(!archiveOpen)}
                        className="flex items-center gap-2 text-sm text-gray-500 hover:text-gray-700 transition-colors mb-3"
                    >
                        {archiveOpen ? <ChevronDown size={16} /> : <ChevronRight size={16} />}
                        <Archive size={14} />
                        <span>Archive ({archivedProjects.length})</span>
                    </button>

                    {archiveOpen && (
                        <div className="space-y-4">
                            {archivedFolders.map(([folder, folderProjects]) => (
                                <ArchiveFolder
                                    key={folder}
                                    folder={folder}
                                    projects={folderProjects}
                                    onSelectProject={onSelectProject}
                                    renderRow={(p) => <ProjectRow key={p.id} project={p} isArchived />}
                                    TableHead={TableHead}
                                />
                            ))}
                        </div>
                    )}
                </div>
            )}

            {/* Archive Dialog */}
            {archiveDialog && (
                <ArchiveDialogModal
                    archiveDialog={archiveDialog}
                    setArchiveDialog={setArchiveDialog}
                    existingFolders={existingFolders}
                    onConfirm={handleArchiveConfirm}
                />
            )}

            {/* Global Settings Modal */}
            <GlobalSettingsModal
                open={settingsOpen}
                onClose={() => setSettingsOpen(false)}
                onProjectRestored={fetchList}
            />
        </div>
    );
}

function ArchiveFolder({ folder, projects, renderRow, TableHead }) {
    const [open, setOpen] = useState(false);
    const isUnsorted = folder === '(Unsorted)';

    return (
        <div>
            <button
                onClick={() => setOpen(!open)}
                className="flex items-center gap-2 text-xs text-gray-400 hover:text-gray-600 transition-colors mb-2 ml-2"
            >
                {open ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
                {open ? <FolderOpen size={13} /> : <Folder size={13} />}
                <span className={isUnsorted ? 'italic' : 'font-medium'}>{folder}</span>
                <span className="text-gray-300">({projects.length})</span>
            </button>
            {open && (
                <div className="bg-white shadow-sm ring-1 ring-gray-200 rounded-lg overflow-hidden ml-4 opacity-80">
                    <table className="min-w-full divide-y divide-gray-200">
                        <TableHead />
                        <tbody className="bg-white divide-y divide-gray-200">
                            {projects.map(p => renderRow(p))}
                        </tbody>
                    </table>
                </div>
            )}
        </div>
    );
}

function ArchiveDialogModal({ archiveDialog, setArchiveDialog, existingFolders, onConfirm }) {
    const [folderName, setFolderName] = useState(archiveDialog.folderName);

    const handleKeyDown = (e) => {
        if (e.key === 'Enter') {
            archiveDialog.folderName = folderName;
            onConfirm();
        } else if (e.key === 'Escape') {
            setArchiveDialog(null);
        }
    };

    const handleConfirm = () => {
        archiveDialog.folderName = folderName;
        onConfirm();
    };

    return (
        <div className="fixed inset-0 bg-black/30 flex items-center justify-center z-50" onClick={() => setArchiveDialog(null)}>
            <div className="bg-white rounded-xl shadow-xl p-6 w-96 space-y-4" onClick={e => e.stopPropagation()}>
                <div className="flex justify-between items-center">
                    <h3 className="font-semibold text-gray-800">Archive Project</h3>
                    <button onClick={() => setArchiveDialog(null)} className="text-gray-400 hover:text-gray-600">
                        <X size={18} />
                    </button>
                </div>

                <div>
                    <label className="block text-xs text-gray-500 mb-1.5">Folder (optional)</label>
                    <input
                        autoFocus
                        value={folderName}
                        onChange={(e) => setFolderName(e.target.value)}
                        onKeyDown={handleKeyDown}
                        className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-indigo-300 focus:border-indigo-400"
                        placeholder="e.g. Client Name, 2024, Project X..."
                    />
                    {existingFolders.length > 0 && (
                        <div className="flex flex-wrap gap-1.5 mt-2">
                            {existingFolders.map(f => (
                                <button
                                    key={f}
                                    onClick={() => setFolderName(f)}
                                    className={`px-2 py-0.5 text-xs rounded-full border transition-colors ${
                                        folderName === f
                                            ? 'bg-indigo-50 border-indigo-300 text-indigo-700'
                                            : 'bg-gray-50 border-gray-200 text-gray-500 hover:border-gray-300'
                                    }`}
                                >
                                    {f}
                                </button>
                            ))}
                        </div>
                    )}
                </div>

                <div className="flex justify-end gap-2 pt-2">
                    <button
                        onClick={() => setArchiveDialog(null)}
                        className="px-3 py-1.5 text-sm text-gray-500 hover:text-gray-700 transition-colors"
                    >
                        Cancel
                    </button>
                    <button
                        onClick={handleConfirm}
                        className="px-4 py-1.5 text-sm bg-amber-500 hover:bg-amber-600 text-white rounded-lg transition-colors"
                    >
                        Archive
                    </button>
                </div>
            </div>
        </div>
    );
}

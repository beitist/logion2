import React, { useEffect, useState } from 'react';
import { getProjects, deleteProject, duplicateProject } from '../api/client';
import { Trash2, FilePlus, ExternalLink, Copy } from 'lucide-react';

export function ProjectList({ onSelectProject, onNewProject }) {
    const [projects, setProjects] = useState([]);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState(null);

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

    useEffect(() => {
        fetchList();
    }, []);

    const handleDelete = async (e, id) => {
        e.stopPropagation(); // Prevent row click
        if (!confirm("Delete this project?")) return;
        try {
            await deleteProject(id);
            setProjects(projects.filter(p => p.id !== id));
        } catch (err) {
            alert(err.message);
        }
    };

    const handleDuplicate = async (e, id) => {
        e.stopPropagation();
        if (!confirm("Duplicate this project?")) return;
        try {
            const newProject = await duplicateProject(id);
            // Refresh list or append
            setProjects([newProject, ...projects]);
        } catch (err) {
            alert(err.message);
        }
    };

    if (loading) return <div className="p-8 text-center text-gray-400">Loading projects...</div>;

    return (
        <div className="max-w-5xl mx-auto py-8 px-4">
            <div className="flex justify-between items-center mb-8">
                <h1 className="text-2xl font-bold text-gray-800 dark:text-gray-100">My Projects</h1>
                <button
                    onClick={onNewProject}
                    className="flex items-center gap-2 px-4 py-2 bg-indigo-600 hover:bg-indigo-700 text-white rounded-md transition-colors"
                >
                    <FilePlus size={18} />
                    <span>New Project</span>
                </button>
            </div>

            {error && (
                <div className="p-4 mb-6 bg-red-50 text-red-700 rounded-md border border-red-200">
                    {error}
                </div>
            )}

            {projects.length === 0 ? (
                <div className="text-center py-20 bg-gray-50 border-2 border-dashed border-gray-200 rounded-xl">
                    <p className="text-gray-500 mb-4">No projects found.</p>
                    <button onClick={onNewProject} className="text-indigo-600 hover:underline">Create your first project</button>
                </div>
            ) : (
                <div className="bg-white shadow-sm ring-1 ring-gray-200 rounded-lg overflow-hidden">
                    <table className="min-w-full divide-y divide-gray-200">
                        <thead className="bg-gray-50">
                            <tr>
                                <th scope="col" className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Project Name</th>
                                <th scope="col" className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">File</th>
                                <th scope="col" className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Language</th>
                                <th scope="col" className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Created</th>
                                <th scope="col" className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Status</th>
                                <th scope="col" className="relative px-6 py-3"><span className="sr-only">Actions</span></th>
                            </tr>
                        </thead>
                        <tbody className="bg-white divide-y divide-gray-200">
                            {projects.map((project) => (
                                <tr
                                    key={project.id}
                                    onClick={() => onSelectProject(project.id)}
                                    className="hover:bg-gray-50 cursor-pointer transition-colors"
                                >
                                    <td className="px-6 py-4 whitespace-nowrap">
                                        <div className="text-sm font-medium text-gray-900">{project.name || "Untitled"}</div>
                                    </td>
                                    <td className="px-6 py-4 whitespace-nowrap">
                                        <div className="text-sm text-gray-500 flex items-center gap-2">
                                            {project.filename}
                                        </div>
                                    </td>
                                    <td className="px-6 py-4 whitespace-nowrap">
                                        <div className="text-sm text-gray-500 uppercase">{project.source_lang} &rarr; {project.target_lang}</div>
                                    </td>
                                    <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-500">
                                        {new Date(project.created_at).toLocaleDateString()}
                                    </td>
                                    <td className="px-6 py-4 whitespace-nowrap">
                                        <span className={`px-2 inline-flex text-xs leading-5 font-semibold rounded-full ${project.status === 'completed' ? 'bg-green-100 text-green-800' :
                                            project.status === 'processing' ? 'bg-yellow-100 text-yellow-800' :
                                                'bg-blue-100 text-blue-800'
                                            }`}>
                                            {project.status}
                                        </span>
                                    </td>
                                    <td className="px-6 py-4 whitespace-nowrap text-right text-sm font-medium flex justify-end gap-2">
                                        <button
                                            onClick={(e) => handleDuplicate(e, project.id)}
                                            className="text-indigo-400 hover:text-indigo-600 p-2 hover:bg-indigo-50 rounded-full transition-colors"
                                            title="Duplicate Project"
                                        >
                                            <Copy size={16} />
                                        </button>
                                        <button
                                            onClick={(e) => handleDelete(e, project.id)}
                                            className="text-red-400 hover:text-red-600 p-2 hover:bg-red-50 rounded-full transition-colors"
                                            title="Delete Project"
                                        >
                                            <Trash2 size={16} />
                                        </button>
                                    </td>
                                </tr>
                            ))}
                        </tbody>
                    </table>
                </div>
            )}
        </div>
    );
}

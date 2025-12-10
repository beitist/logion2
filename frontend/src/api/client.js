const API_BASE = "http://localhost:8000";

export async function uploadProject(file) {
    const formData = new FormData();
    formData.append("file", file);

    const res = await fetch(`${API_BASE}/project/upload`, {
        method: "POST",
        body: formData,
    });

    if (!res.ok) {
        const err = await res.json();
        throw new Error(err.detail || "Upload failed");
    }

    return res.json();
}

export async function getProject(id) {
    const res = await fetch(`${API_BASE}/project/${id}`);
    if (!res.ok) throw new Error("Failed to fetch project");
    return res.json();
}

export async function getSegments(projectId) {
    const res = await fetch(`${API_BASE}/project/${projectId}/segments`);
    if (!res.ok) throw new Error("Failed to fetch segments");
    return res.json();
}

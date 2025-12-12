const API_BASE = "http://localhost:8000";

export async function getProjects() {
    const res = await fetch(`${API_BASE}/project/`);
    if (!res.ok) throw new Error("Failed to fetch projects");
    return res.json();
}

export async function createProject(formData) {
    const res = await fetch(`${API_BASE}/project/create`, {
        method: "POST",
        body: formData,
    });

    if (!res.ok) {
        const err = await res.json();
        throw new Error(err.detail || "Creation failed");
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

export async function updateSegment(segmentId, content, status) {
    const body = { target_content: content };
    if (status) body.status = status;

    const res = await fetch(`${API_BASE}/segment/${segmentId}`, {
        method: "PATCH",
        headers: {
            "Content-Type": "application/json",
        },
        body: JSON.stringify(body),
    });
    if (!res.ok) throw new Error("Failed to update segment");
    return res.json();
}

export async function downloadProject(projectId) {
    const res = await fetch(`${API_BASE}/project/${projectId}/export`);
    if (!res.ok) throw new Error("Failed to export project");
    return res.blob();
}

export async function updateProject(projectId, data) {
    const res = await fetch(`${API_BASE}/project/${projectId}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(data),
    });
    if (!res.ok) throw new Error("Failed to update project");
    return res.json();
}

export async function deleteProject(projectId) {
    const res = await fetch(`${API_BASE}/project/${projectId}`, {
        method: "DELETE",
    });
    if (!res.ok) throw new Error("Failed to delete project");
    return res.json();
}

export async function generateDraft(segmentId) {
    const res = await fetch(`${API_BASE}/project/segment/${segmentId}/generate-draft`, {
        method: "POST",
    });
    if (!res.ok) throw new Error("Failed to generate draft");
    return res.json();
}

export async function reingestProject(projectId) {
    const res = await fetch(`${API_BASE}/project/${projectId}/reingest`, {
        method: "POST",
    });
    if (!res.ok) throw new Error("Failed to re-ingest project");
    return res.json();
}

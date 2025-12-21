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

export async function updateSegment(segmentId, content, status, metadata) {
    const body = {};
    if (content !== undefined) body.target_content = content;
    if (status) body.status = status;
    if (metadata) body.metadata = metadata;

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

export async function downloadProjectTMX(projectId) {
    const res = await fetch(`${API_BASE}/project/${projectId}/export/tmx`);
    if (!res.ok) throw new Error("Failed to export project TMX");
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

export async function duplicateProject(projectId) {
    const res = await fetch(`${API_BASE}/project/${projectId}/duplicate`, {
        method: "POST",
    });
    if (!res.ok) throw new Error("Failed to duplicate project");
    return res.json();
}

// Generate AI Draft for a single segment
export async function generateDraft(segmentId, mode = "translate", isWorkflow = false, forceRefresh = false) {
    // Mode: 'translate' (rewrite target), 'draft' (suggestion only), 'analyze' (retrieval only)
    const response = await fetch(`${API_BASE}/project/segment/${segmentId}/generate-draft?mode=${mode}&is_workflow=${isWorkflow}&force_refresh=${forceRefresh}`, {
        method: 'POST',
    });
    if (!response.ok) {
        const errorText = await response.text();
        console.error(`Generate Draft Failed [${response.status}]:`, errorText);
        throw new Error(`Failed to generate draft: ${response.status}`);
    }
    return response.json();
}

export async function generateProjectDrafts(projectId) {
    const res = await fetch(`${API_BASE}/project/${projectId}/generate-drafts`, {
        method: "POST",
    });
    if (!res.ok) throw new Error("Failed to start batch generation");
    return res.json();
}

export async function reingestProject(projectId) {
    const res = await fetch(`${API_BASE}/project/${projectId}/reingest`, {
        method: "POST",
    });
    if (!res.ok) throw new Error("Failed to re-ingest project");
    return res.json();
}

export async function reinitializeProject(projectId) {
    const res = await fetch(`${API_BASE}/project/${projectId}/reinitialize`, {
        method: "POST",
    });
    if (!res.ok) throw new Error("Failed to reinitialize project");
    return res.json();
}

// Glossary API

export async function addGlossaryTerm(projectId, source, target, note) {
    const res = await fetch(`${API_BASE}/project/${projectId}/glossary`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ source_term: source, target_term: target, context_note: note }),
    });
    if (!res.ok) throw new Error("Failed to add glossary term");
    return res.json();
}

export async function getGlossaryTerms(projectId) {
    const res = await fetch(`${API_BASE}/project/${projectId}/glossary`);
    if (!res.ok) throw new Error("Failed to fetch glossary");
    return res.json();
}

export async function uploadGlossary(projectId, file) {
    const formData = new FormData();
    formData.append("file", file);
    const res = await fetch(`${API_BASE}/project/${projectId}/glossary/upload`, {
        method: "POST",
        body: formData,
    });
    if (!res.ok) throw new Error("Failed to upload glossary");
    return res.json();
}

export async function getAiModels() {
    const res = await fetch(`${API_BASE}/config/models`);
    if (!res.ok) throw new Error("Failed to fetch models");
    return res.json();
}

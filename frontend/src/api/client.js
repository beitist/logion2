const API_BASE = "http://127.0.0.1:8000";

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
export async function generateDraft(segmentId, mode = "translate", isWorkflow = false, forceRefresh = false, tcParams = null) {
    // Mode: 'translate' (rewrite target), 'draft' (suggestion only), 'analyze' (retrieval only)
    const options = { method: 'POST' };
    if (tcParams) {
        options.headers = { 'Content-Type': 'application/json' };
        options.body = JSON.stringify(tcParams);
    }
    const response = await fetch(`${API_BASE}/project/segment/${segmentId}/generate-draft?mode=${mode}&is_workflow=${isWorkflow}&force_refresh=${forceRefresh}`, options);
    if (!response.ok) {
        const errorText = await response.text();
        console.error(`Generate Draft Failed [${response.status}]:`, errorText);
        throw new Error(`Failed to generate draft: ${response.status}`);
    }
    return response.json();
}

export async function copySourceToTarget(projectId) {
    const res = await fetch(`${API_BASE}/project/${projectId}/workflow/copy-source`, {
        method: "POST",
    });
    if (!res.ok) throw new Error("Failed to copy source");
    return res.json();
}

export async function clearDraftTargets(projectId) {
    const res = await fetch(`${API_BASE}/project/${projectId}/workflow/clear-drafts`, {
        method: "POST",
    });
    if (!res.ok) throw new Error("Failed to clear drafts");
    return res.json();
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

export async function reinitializeProject(projectId, fileData = null) {
    const url = `${API_BASE}/project/${projectId}/reinitialize`;

    let options = {
        method: "POST",
    };

    const formData = new FormData();
    if (fileData && fileData instanceof File) {
        formData.append('file', fileData);
    }
    options.body = formData;
    // If no body, empty POST is fine.

    const res = await fetch(url, options);
    if (!res.ok) throw new Error("Failed to reinitialize project");
    return await res.json();
}

export async function batchTranslate(projectId, segmentIds, mode = "draft") {
    const res = await fetch(`${API_BASE}/project/${projectId}/batch-translate`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ segment_ids: segmentIds, mode }),
    });
    if (!res.ok) throw new Error("Batch translation failed");
    return res.json();
}

export async function tcBatchTranslate(projectId) {
    const res = await fetch(`${API_BASE}/project/${projectId}/tc-batch-translate`, {
        method: "POST",
    });
    if (!res.ok) throw new Error("TC batch translation failed");
    return res.json();
}

export async function sequentialTranslate(projectId, segmentIds = null) {
    const body = segmentIds ? { segment_ids: segmentIds } : {};
    const res = await fetch(`${API_BASE}/project/${projectId}/sequential-translate`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
    });
    if (!res.ok) throw new Error("Sequential translation failed");
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

export async function updateGlossaryTerm(projectId, entryId, { source_term, target_term, context_note }) {
    const res = await fetch(`${API_BASE}/project/${projectId}/glossary/${entryId}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ source_term, target_term, context_note }),
    });
    if (!res.ok) throw new Error("Failed to update glossary term");
    return res.json();
}

export async function deleteGlossaryTerm(projectId, entryId) {
    const res = await fetch(`${API_BASE}/project/${projectId}/glossary/${entryId}`, {
        method: "DELETE",
    });
    if (!res.ok) throw new Error("Failed to delete glossary term");
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

// =========================================================================
// File Management API (Multi-File Support)
// =========================================================================

/**
 * Get all files for a project with their metadata and segment counts.
 */
export async function getProjectFiles(projectId) {
    const res = await fetch(`${API_BASE}/project/${projectId}/files`);
    if (!res.ok) throw new Error("Failed to fetch project files");
    return res.json();
}

/**
 * Add a new file to an existing project.
 * @param {string} projectId - Project UUID
 * @param {string} category - 'source', 'legal', or 'background'
 * @param {File} file - The file to upload
 */
export async function addProjectFile(projectId, category, file) {
    const formData = new FormData();
    formData.append("category", category);
    formData.append("file", file);

    const res = await fetch(`${API_BASE}/project/${projectId}/files`, {
        method: "POST",
        body: formData,
    });
    if (!res.ok) {
        const err = await res.json();
        throw new Error(err.detail || "Failed to add file");
    }
    return res.json();
}

/**
 * Replace an existing file with a new version.
 * @param {string} projectId - Project UUID
 * @param {string} fileId - File UUID to replace
 * @param {File} file - The new file
 */
export async function replaceProjectFile(projectId, fileId, file) {
    const formData = new FormData();
    formData.append("file", file);

    const res = await fetch(`${API_BASE}/project/${projectId}/files/${fileId}`, {
        method: "PUT",
        body: formData,
    });
    if (!res.ok) {
        const err = await res.json();
        throw new Error(err.detail || "Failed to replace file");
    }
    return res.json();
}

/**
 * Delete a file and all its linked segments.
 * @param {string} projectId - Project UUID
 * @param {string} fileId - File UUID to delete
 */
export async function deleteProjectFile(projectId, fileId) {
    const res = await fetch(`${API_BASE}/project/${projectId}/files/${fileId}`, {
        method: "DELETE",
    });
    if (!res.ok) throw new Error("Failed to delete file");
    return res.json();
}


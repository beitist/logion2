import React, { useState } from 'react'
import { ProjectList } from './components/ProjectList'
import { NewProjectModal } from './components/NewProjectModal'
import { SplitView } from './components/SplitView'

function App() {
  const [projectId, setProjectId] = useState(null)
  const [showNewProjectModal, setShowNewProjectModal] = useState(false)

  // Navigate to Project
  const handleSelectProject = (id) => {
    setProjectId(id)
  }

  // Handle Project Creation
  const handleProjectCreated = (newProject) => {
    setShowNewProjectModal(false)
    setProjectId(newProject.id) // Auto-open the new project
  }

  // Back to Dashboard
  const handleBack = () => {
    setProjectId(null)
  }

  if (projectId) {
    // Editor View
    return (
      <div className="h-screen flex flex-col">
        <div className="flex-1 overflow-hidden">
          <SplitView projectId={projectId} onBack={handleBack} />
        </div>
      </div>
    )
  }

  // Dashboard View
  return (
    <>
      <ProjectList
        onSelectProject={handleSelectProject}
        onNewProject={() => setShowNewProjectModal(true)}
      />

      {showNewProjectModal && (
        <NewProjectModal
          onClose={() => setShowNewProjectModal(false)}
          onCreated={handleProjectCreated}
        />
      )}
    </>
  )
}

export default App

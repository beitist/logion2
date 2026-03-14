import React, { useState } from 'react'
import { ProjectList } from './components/ProjectList'
import { NewProjectModal } from './components/NewProjectModal'
import { SplitView } from './components/SplitView'
import { ReviewView } from './components/ReviewView'

function App() {
  const [projectId, setProjectId] = useState(null)
  const [projectStatus, setProjectStatus] = useState(null)
  const [showNewProjectModal, setShowNewProjectModal] = useState(false)

  // Navigate to Project
  const handleSelectProject = (id, status) => {
    setProjectId(id)
    setProjectStatus(status || null)
  }

  // Handle Project Creation
  const handleProjectCreated = (newProject) => {
    setShowNewProjectModal(false)
    setProjectId(newProject.id) // Auto-open the new project
    setProjectStatus(newProject.status)
  }

  // Back to Dashboard
  const handleBack = () => {
    setProjectId(null)
    setProjectStatus(null)
  }

  if (projectId) {
    if (projectStatus === 'review') {
      return <ReviewView projectId={projectId} onBack={handleBack} />
    }
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

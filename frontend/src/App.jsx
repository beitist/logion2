import React, { useState } from 'react'
import { UploadView } from './components/UploadView'
import { SplitView } from './components/SplitView'

function App() {
  const [projectId, setProjectId] = useState(null)

  if (!projectId) {
    return <UploadView onUploadSuccess={setProjectId} />
  }

  return <SplitView projectId={projectId} />
}

export default App

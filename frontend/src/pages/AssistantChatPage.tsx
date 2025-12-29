import { useParams } from 'react-router-dom'
import { Box } from '@mui/material'
import { AssistantUIChat } from '../components/Chat/AssistantUIChat'

const AssistantChatPage = () => {
  const { caseId } = useParams<{ caseId: string }>()

  if (!caseId) {
    return (
      <Box sx={{ height: '100vh', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
        Дело не найдено
      </Box>
    )
  }

  return (
    <Box 
      sx={{ 
        height: '100vh', 
        display: 'flex', 
        flexDirection: 'column', 
        width: '100%',
        margin: 0,
        padding: 0,
        bgcolor: 'background.default',
      }}
    >
      <AssistantUIChat caseId={caseId} className="h-full" />
    </Box>
  )
}

export default AssistantChatPage



import { useParams } from 'react-router-dom'
import MainLayout from '../components/Layout/MainLayout'
import { AssistantUIChat } from '../components/Chat/AssistantUIChat'
import { Box, Typography, Alert } from '@mui/material'

const AssistantChatPage = () => {
  const { caseId } = useParams<{ caseId: string }>()

  if (!caseId) {
    return (
      <MainLayout>
        <Box p={3}>
          <Alert severity="error">Дело не найдено</Alert>
        </Box>
      </MainLayout>
    )
  }

  return (
    <MainLayout>
      <Box 
        sx={{ 
          height: 'calc(100vh - 64px)', 
          display: 'flex', 
          flexDirection: 'column', 
          width: '100%',
          margin: 0,
          padding: 0,
        }}
      >
        <Box sx={{ p: 1.5, borderBottom: 1, borderColor: 'divider' }}>
          <Typography variant="h5" component="h1">
            AI Ассистент
          </Typography>
          <Typography variant="body2" color="text.secondary">
            Задайте вопросы о документах дела
          </Typography>
        </Box>
        <Box sx={{ flex: 1, overflow: 'hidden', width: '100%' }}>
          <AssistantUIChat caseId={caseId} className="h-full" />
        </Box>
      </Box>
    </MainLayout>
  )
}

export default AssistantChatPage



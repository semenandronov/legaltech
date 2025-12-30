import { useParams } from 'react-router-dom'
import { AssistantUIChat } from '../components/Chat/AssistantUIChat'

const AssistantChatPage = () => {
  const { caseId } = useParams<{ caseId: string }>()

  if (!caseId) {
    return (
      <div className="h-full flex items-center justify-center">
        <p className="text-body text-[#6B7280]">Дело не найдено</p>
      </div>
    )
  }

  return (
    <div className="h-full w-full flex flex-col fade-in-up">
      <AssistantUIChat caseId={caseId} className="h-full" />
    </div>
  )
}

export default AssistantChatPage



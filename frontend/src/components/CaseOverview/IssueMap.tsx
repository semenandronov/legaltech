import Card from '../UI/Card'
import Badge from '../UI/Badge'

interface Issue {
  tag: string
  count: number
}

interface IssueMapProps {
  issues: Issue[]
}

const IssueMap = ({ issues }: IssueMapProps) => {
  if (issues.length === 0) {
    return (
      <Card>
        <p className="text-body text-secondary text-center py-4">Вопросы не найдены</p>
      </Card>
    )
  }
  
  return (
    <Card>
      <div className="flex flex-wrap gap-2">
        {issues.map((issue) => (
          <button
            key={issue.tag}
            className="px-3 py-1.5 bg-tertiary hover:bg-primary hover:text-white text-primary rounded-md transition-colors text-small font-medium"
          >
            {issue.tag}: {issue.count}
          </button>
        ))}
      </div>
    </Card>
  )
}

export default IssueMap

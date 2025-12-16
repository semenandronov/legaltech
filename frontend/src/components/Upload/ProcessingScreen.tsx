import { useEffect, useState } from 'react'
import './Upload.css'

interface ProcessingScreenProps {
  caseId?: string  // Optional, not currently used
  onComplete: () => void
}

const ProcessingScreen = ({ onComplete }: ProcessingScreenProps) => {
  const [currentStep, setCurrentStep] = useState(0)
  const [progress, setProgress] = useState(0)

  const steps = [
    { name: 'Парсинг документов', completed: false },
    { name: 'OCR обработка', completed: false },
    { name: 'Семантический анализ', completed: false },
    { name: 'Извлечение фактов', completed: false },
    { name: 'Построение таймлайна', completed: false },
    { name: 'Поиск противоречий', completed: false },
    { name: 'Генерация отчета', completed: false },
  ]

  useEffect(() => {
    // Simulate processing steps
    const interval = setInterval(() => {
      setCurrentStep((prev) => {
        if (prev < steps.length - 1) {
          return prev + 1
        }
        return prev
      })
      setProgress((prev) => {
        if (prev < 100) {
          return Math.min(prev + 15, 100)
        }
        return prev
      })
    }, 2000)

    if (progress >= 100) {
      clearInterval(interval)
      setTimeout(() => {
        onComplete()
      }, 1000)
    }

    return () => clearInterval(interval)
  }, [progress, steps.length, onComplete])

  return (
    <div className="processing-screen">
      <div className="processing-screen-content">
        <h2 className="processing-title">⏳ Анализ в процессе</h2>
        <p className="processing-subtitle">
          Это может занять несколько минут...
          <br />
          Вы можете оставить эту страницу, мы отправим email
        </p>

        <div className="processing-steps">
          {steps.map((step, index) => (
            <div
              key={index}
              className={`processing-step ${index < currentStep ? 'completed' : ''} ${
                index === currentStep ? 'active' : ''
              }`}
            >
              <div className="processing-step-icon">
                {index < currentStep ? '✅' : index === currentStep ? '⏳' : '⏹️'}
              </div>
              <div className="processing-step-name">{step.name}</div>
            </div>
          ))}
        </div>

        <div className="processing-progress">
          <div className="processing-progress-bar">
            <div
              className="processing-progress-fill"
              style={{ width: `${progress}%` }}
            />
          </div>
          <div className="processing-progress-text">{progress}% готово</div>
        </div>

        <p className="processing-estimate">
          Приблизительно: {Math.max(1, Math.ceil((100 - progress) / 15))} минут(ы) осталось
        </p>
      </div>
    </div>
  )
}

export default ProcessingScreen


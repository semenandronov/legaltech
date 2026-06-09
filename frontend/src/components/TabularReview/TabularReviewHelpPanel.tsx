import { X, HelpCircle, MessageSquare } from 'lucide-react'

interface TabularReviewHelpPanelProps {
  open: boolean
  onClose: () => void
}

const STEPS = [
  {
    title: 'Добавьте документы',
    text: 'Строка таблицы — один файл из дела. Сначала выберите, какие документы анализировать.',
  },
  {
    title: 'Создайте колонку',
    text: 'Колонка — один вопрос ко всем документам. Например: «Дата подписания» или «Краткое содержание».',
  },
  {
    title: 'Нажмите ▶ у колонки',
    text: 'ИИ пройдёт по каждому файлу и заполнит ячейки. Это может занять 1–2 минуты на десяток документов.',
  },
  {
    title: 'Проверьте источник',
    text: 'Клик по ячейке откроет документ на нужном фрагменте.',
  },
]

const CHAT_EXAMPLES = [
  'Какие документы без даты в таблице?',
  'Покажи только договоры',
  'Какие суммы требований самые крупные?',
  'Есть ли противоречия между документами?',
]

export function TabularReviewHelpPanel({ open, onClose }: TabularReviewHelpPanelProps) {
  if (!open) return null

  return (
    <>
      <button
        type="button"
        className="fixed inset-0 z-40 bg-black/20"
        aria-label="Закрыть справку"
        onClick={onClose}
      />
      <aside
        className="fixed top-0 right-0 z-50 h-full w-full max-w-md border-l shadow-xl overflow-y-auto"
        style={{
          backgroundColor: 'var(--color-bg-elevated)',
          borderColor: 'var(--color-border)',
        }}
      >
        <div
          className="sticky top-0 flex items-center justify-between px-5 py-4 border-b"
          style={{ borderColor: 'var(--color-border)', backgroundColor: 'var(--color-bg-elevated)' }}
        >
          <div className="flex items-center gap-2">
            <HelpCircle className="w-5 h-5" style={{ color: 'var(--color-accent)' }} />
            <h2 className="text-base font-semibold" style={{ color: 'var(--color-text-primary)' }}>
              Как пользоваться таблицей
            </h2>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="p-1.5 rounded-lg hover:bg-[var(--color-bg-hover)]"
            style={{ color: 'var(--color-text-muted)' }}
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        <div className="px-5 py-5 space-y-6">
          <p className="text-sm leading-relaxed" style={{ color: 'var(--color-text-secondary)' }}>
            Таблица — это массовый опрос документов дела: один и тот же вопрос задаётся каждому файлу,
            ответы удобно сравнивать и выгружать. В отличие от чата, здесь структура «файл × вопрос».
          </p>

          <ol className="space-y-4">
            {STEPS.map((step, index) => (
              <li key={step.title} className="flex gap-3">
                <span
                  className="flex-shrink-0 w-7 h-7 rounded-full flex items-center justify-center text-xs font-semibold"
                  style={{
                    backgroundColor: 'var(--color-accent-subtle, rgba(99,102,241,0.12))',
                    color: 'var(--color-accent)',
                  }}
                >
                  {index + 1}
                </span>
                <div>
                  <p className="text-sm font-medium mb-0.5" style={{ color: 'var(--color-text-primary)' }}>
                    {step.title}
                  </p>
                  <p className="text-sm leading-relaxed" style={{ color: 'var(--color-text-muted)' }}>
                    {step.text}
                  </p>
                </div>
              </li>
            ))}
          </ol>

          <section
            className="rounded-xl border p-4 space-y-3"
            style={{
              borderColor: 'var(--color-border)',
              backgroundColor: 'var(--color-bg-subtle, var(--color-bg-hover))',
            }}
          >
            <div className="flex items-center gap-2">
              <MessageSquare className="w-4 h-4 flex-shrink-0" style={{ color: 'var(--color-accent)' }} />
              <h3 className="text-sm font-semibold" style={{ color: 'var(--color-text-primary)' }}>
                Зачем чат рядом с таблицей
              </h3>
            </div>
            <p className="text-sm leading-relaxed" style={{ color: 'var(--color-text-secondary)' }}>
              Колонки заполняют ячейки по одному вопросу на каждый файл. Чат смотрит на{' '}
              <strong>всю уже собранную таблицу</strong> и отвечает на обобщающие вопросы —
              как аналитик, который видит все строки и колонки сразу.
            </p>
            <ul className="text-sm space-y-1.5 list-disc pl-4" style={{ color: 'var(--color-text-muted)' }}>
              <li>найти пробелы: пустые даты, прочерки, документы без ответа;</li>
              <li>сравнить документы и заметить расхождения в суммах, датах, сторонах;</li>
              <li>быстро получить сводку по делу без новой колонки;</li>
              <li>сформулировать идею для следующей колонки («что ещё стоит извлечь?»).</li>
            </ul>
            <p className="text-xs leading-relaxed" style={{ color: 'var(--color-text-muted)' }}>
              Чат <strong>не заменяет</strong> кнопку ▶ у колонки: он не извлекает данные в ячейки
              заново, а разбирает то, что уже есть в таблице. Для нового поля по всем файлам —
              добавьте колонку и запустите заполнение.
            </p>
            <div>
              <p className="text-xs font-medium mb-2" style={{ color: 'var(--color-text-secondary)' }}>
                Примеры вопросов в чат:
              </p>
              <ul className="space-y-1.5">
                {CHAT_EXAMPLES.map((example) => (
                  <li
                    key={example}
                    className="text-xs px-2.5 py-1.5 rounded-lg border"
                    style={{
                      color: 'var(--color-text-muted)',
                      borderColor: 'var(--color-border)',
                      backgroundColor: 'var(--color-bg-elevated)',
                    }}
                  >
                    {example}
                  </li>
                ))}
              </ul>
            </div>
          </section>
        </div>
      </aside>
    </>
  )
}

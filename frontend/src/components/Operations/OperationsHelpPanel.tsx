interface OperationsHelpPanelProps {
  open: boolean
  onClose: () => void
}

export function OperationsHelpPanel({ open, onClose }: OperationsHelpPanelProps) {
  if (!open) return null

  return (
    <>
      <button type="button" className="fixed inset-0 z-[110] bg-black/20" onClick={onClose} aria-label="Закрыть" />
      <div className="fixed right-0 top-0 bottom-0 z-[111] w-full max-w-md bg-white shadow-xl border-l border-gray-100 p-6 overflow-y-auto">
        <h2 className="text-lg font-semibold mb-4">Реестр операций</h2>
        <div className="space-y-4 text-sm text-gray-600">
          <p>Выберите одну банковскую выписку — таблица повторит её колонки из PDF.</p>
          <p>Фильтры и поиск работают как в Tabular Review. Клик по строке откроет выписку с подсветкой.</p>
          <p>Чат справа отвечает на вопросы по этой выписке: суммы, периоды, контрагенты.</p>
          <p>Чтобы открыть другую выписку, вернитесь к делу и снова зайдите в раздел операций.</p>
        </div>
      </div>
    </>
  )
}

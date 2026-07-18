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
          <p>Поиск и фильтры помогают сузить список операций. Экспорт выгружает текущий отфильтрованный набор в Excel.</p>
          <p>Клик по строке откроет выписку с подсветкой выбранной операции.</p>
        </div>
      </div>
    </>
  )
}

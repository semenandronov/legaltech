import React from "react"
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
} from "@/components/UI/dialog"
import { Card, CardContent } from "@/components/UI/Card"
import { Button } from "@/components/UI/Button"
import { PenTool } from "lucide-react"

interface CreateTableModeDialogProps {
  isOpen: boolean
  onClose: () => void
  onSelectManual: () => void
  onSelectAutomatic: () => void
}

export const CreateTableModeDialog: React.FC<CreateTableModeDialogProps> = ({
  isOpen,
  onClose,
  onSelectManual,
  onSelectAutomatic: _onSelectAutomatic,
}) => {
  const handleManual = () => {
    onClose()
    onSelectManual()
  }

  return (
    <Dialog open={isOpen} onOpenChange={onClose}>
      <DialogContent className="max-w-2xl">
        <DialogHeader>
          <DialogTitle>Создание таблицы</DialogTitle>
          <DialogDescription>
            Вы сами выбираете документы, создаете колонки и редактируете ячейки. 
            Полный контроль над структурой и содержимым таблицы.
          </DialogDescription>
        </DialogHeader>

        <div className="py-4">
          {/* Ручной режим */}
          <Card
            className="cursor-pointer transition-all duration-200 hover:border-border-strong hover:shadow-md"
            onClick={handleManual}
          >
            <CardContent className="p-6 flex flex-col h-full">
              <div className="flex items-center gap-3 mb-4">
                <div className="p-3 rounded-lg bg-bg-secondary">
                  <PenTool className="w-6 h-6 text-text-primary" />
                </div>
                <h3 className="font-display text-h3 text-text-primary">Ручной режим</h3>
              </div>
              <p className="text-body text-text-secondary mb-6 flex-1">
                Вы сами выбираете документы, создаете колонки и редактируете ячейки. 
                Полный контроль над структурой и содержимым таблицы.
              </p>
              <Button 
                variant="default" 
                className="w-full"
                onClick={(e) => {
                  e.stopPropagation()
                  handleManual()
                }}
              >
                Выбрать
              </Button>
            </CardContent>
          </Card>
        </div>

        <div className="flex justify-end pt-4 border-t border-border">
          <Button variant="outline" onClick={onClose}>
            Отмена
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  )
}


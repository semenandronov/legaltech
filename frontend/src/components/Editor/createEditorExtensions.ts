import StarterKit from '@tiptap/starter-kit'
import Placeholder from '@tiptap/extension-placeholder'
import Link from '@tiptap/extension-link'
import Table from '@tiptap/extension-table'
import TableRow from '@tiptap/extension-table-row'
import TableCell from '@tiptap/extension-table-cell'
import TableHeader from '@tiptap/extension-table-header'
import Typography from '@tiptap/extension-typography'
import Highlight from '@tiptap/extension-highlight'
import Underline from '@tiptap/extension-underline'
import TextAlign from '@tiptap/extension-text-align'
import TextStyle from '@tiptap/extension-text-style'
import UniqueID from '@tiptap/extension-unique-id'
import type { Extensions } from '@tiptap/core'
import { FontFamily } from './extensions/FontFamily'
import { FontSize } from './extensions/FontSize'
import { SlashCommands } from './SlashCommands'
import { TrackChanges } from './extensions/TrackChanges'
import { Comment } from './extensions/Comment'
import { RiskHighlight } from './extensions/RiskHighlight'
import { AIKeyboardShortcuts } from './extensions/AIKeyboardShortcuts'
import { SearchHighlight } from './extensions/SearchHighlight'
import type { RiskItem } from '../../services/documentEditorApi'

export interface CreateEditorExtensionsOptions {
  caseId?: string
  documentId?: string
  onInsertText?: (text: string) => void
  onSetRisks?: (risks: RiskItem[]) => void
  onImproveText?: () => void
  onOpenFindReplace?: () => void
  onOpenClauseLibrary?: () => void
}

export function createEditorExtensions(options: CreateEditorExtensionsOptions): Extensions {
  const {
    caseId,
    documentId,
    onInsertText,
    onSetRisks,
    onImproveText,
    onOpenFindReplace,
    onOpenClauseLibrary,
  } = options

  return [
    StarterKit.configure({
      heading: { levels: [1, 2, 3, 4, 5, 6] },
    }),
    UniqueID.configure({
      attributeName: 'id',
      types: ['paragraph', 'heading', 'listItem', 'tableCell'],
    }),
    TextStyle,
    FontFamily,
    FontSize,
    Placeholder.configure({
      placeholder: 'Начните писать или введите / для команд...',
    }),
    Link.configure({
      openOnClick: false,
      HTMLAttributes: { class: 'editor-link' },
    }),
    Table.configure({
      resizable: true,
      HTMLAttributes: { class: 'editor-table' },
    }),
    TableRow,
    TableHeader,
    TableCell,
    Typography,
    Highlight.configure({ multicolor: true }),
    Underline,
    TextAlign.configure({
      types: ['heading', 'paragraph'],
      defaultAlignment: 'left',
    }),
    SlashCommands.configure({
      caseId,
      documentId,
      onInsertText,
      onSetRisks,
    }),
    TrackChanges.configure({
      enabled: false,
      pendingChanges: [],
    }),
    Comment.configure({ comments: [] }),
    RiskHighlight.configure({ risks: [] }),
    AIKeyboardShortcuts.configure({
      documentId,
      onImproveText,
      onSetRisks,
      onOpenFindReplace,
      onOpenClauseLibrary,
    }),
    SearchHighlight,
  ]
}
